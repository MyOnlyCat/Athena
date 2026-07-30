from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.mark.asyncio
async def test_bootstrap_admin_can_login_read_profile_and_logout(
    client: AsyncClient,
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassword123"},
    )

    assert login.status_code == 200
    body = login.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "admin"
    assert body["user"]["is_active"] is True
    assert "password" not in str(body).lower()

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    profile = await client.get("/api/v1/auth/me", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["username"] == "admin"

    logout = await client.post("/api/v1/auth/logout", headers=headers)
    assert logout.status_code == 204
    revoked = await client.get("/api/v1/auth/me", headers=headers)
    assert revoked.status_code == 401
    assert revoked.json() == {
        "code": "TOKEN_REVOKED",
        "message": "登录凭证已失效",
    }


@pytest.mark.asyncio
async def test_existing_admin_is_not_overwritten_on_restart(
    settings: Settings,
) -> None:
    first_app = create_app(settings)
    async with first_app.router.lifespan_context(first_app):
        async with AsyncClient(
            transport=ASGITransport(app=first_app),
            base_url="http://test",
        ) as first_client:
            first_login = await first_client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "AdminPassword123"},
            )
            assert first_login.status_code == 200

    changed = settings.model_copy(update={"bootstrap_password": "ChangedPassword456"})
    second_app = create_app(changed)
    async with second_app.router.lifespan_context(second_app):
        async with AsyncClient(
            transport=ASGITransport(app=second_app),
            base_url="http://test",
        ) as second_client:
            original = await second_client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "AdminPassword123"},
            )
            changed_login = await second_client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "ChangedPassword456"},
            )

    assert original.status_code == 200
    assert changed_login.status_code == 401


@pytest.mark.asyncio
async def test_login_locks_only_the_username_and_source_ip_pair(
    client: AsyncClient,
) -> None:
    for _ in range(5):
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert response.status_code == 401
        assert response.json()["message"] == "用户名或密码错误"

    locked = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassword123"},
    )
    other_username = await client.post(
        "/api/v1/auth/login",
        json={"username": "other", "password": "wrong-password"},
    )

    assert locked.status_code == 429
    assert locked.json() == {
        "code": "LOGIN_LOCKED",
        "message": "登录失败次数过多，请稍后重试",
    }
    assert other_username.status_code == 401


@pytest.mark.asyncio
async def test_common_api_errors_use_chinese_messages(client: AsyncClient) -> None:
    missing = await client.get("/api/v1/does-not-exist")
    invalid = await client.post("/api/v1/auth/login", json={"username": "admin"})

    assert missing.status_code == 404
    assert missing.json() == {
        "code": "NOT_FOUND",
        "message": "请求的资源不存在",
    }
    assert invalid.status_code == 422
    assert invalid.json() == {
        "code": "INVALID_REQUEST",
        "message": "请求参数无效",
    }


def test_access_token_defaults_to_thirty_minutes(settings: Settings) -> None:
    assert settings.access_token_minutes == 30


def test_production_rejects_missing_required_configuration(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="生产环境缺少必要配置"):
        Settings(
            environment="production",
            jwt_secret="",
            credential_key="",
            bootstrap_username="admin",
            bootstrap_password="",
            data_dir=None,
            database_url="",
        )


def test_production_does_not_treat_development_paths_as_explicit_configuration() -> None:
    with pytest.raises(ValueError) as error:
        Settings(environment="production")

    message = str(error.value)
    assert "数据目录" in message
    assert "数据库配置" in message
