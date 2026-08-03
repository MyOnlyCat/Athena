from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Request

from app.api.deps import CurrentUserDep, SessionDep
from app.core.errors import AppError
from app.models.registration import AccessNode
from app.schemas.asset import (
    AssetLifecycleStatus,
    HostAssetItem,
    HostAssetPage,
    HostDetectionFilter,
)
from app.schemas.heartbeat import (
    AccessNodeListItem,
    AccessNodePage,
    ConnectivityStatus,
    HeartbeatAccepted,
)
from app.schemas.node import (
    ManagedAccessNodeResponse,
    NodeManagementInfoUpdate,
    NodeStatusUpdate,
    NodeTokenRotation,
)
from app.services.assets import HostAssetQueryService
from app.services.heartbeats import MAX_HEARTBEAT_BODY_BYTES, HeartbeatService
from app.services.node_status import connectivity_status
from app.services.nodes import AccessNodeManagementService, AccessNodeQueryService

node_router = APIRouter(tags=["node-heartbeats"])
admin_router = APIRouter(prefix="/nodes", tags=["nodes"])


def managed_node_response(node: AccessNode) -> ManagedAccessNodeResponse:
    return ManagedAccessNodeResponse(
        node_id=node.node_id,
        reported_name=node.reported_name,
        display_name=node.display_name,
        effective_name=node.display_name or node.reported_name,
        hostname=node.hostname,
        software_version=node.software_version,
        management_status=node.management_status,
        notes=node.notes,
        management_tags=node.management_tags,
        disable_reason=node.disable_reason,
    )


def path_with_query(request: Request) -> str:
    query = request.url.query
    return request.url.path if not query else f"{request.url.path}?{query}"


@node_router.post("/nodes/heartbeat", response_model=HeartbeatAccepted)
async def accept_heartbeat(
    request: Request,
    session: SessionDep,
    node_id: Annotated[str, Header(alias="X-Node-Id")],
    timestamp_value: Annotated[str, Header(alias="X-Timestamp")],
    nonce: Annotated[str, Header(alias="X-Nonce")],
    signature: Annotated[str, Header(alias="X-Signature")],
) -> HeartbeatAccepted:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_HEARTBEAT_BODY_BYTES:
                raise AppError(
                    "NODE_PAYLOAD_TOO_LARGE",
                    "心跳正文超过 5 MiB 限制",
                    status_code=413,
                )
        except ValueError:
            raise AppError(
                "NODE_AUTH_INVALID",
                "节点认证头无效",
                status_code=422,
            ) from None
    body = await request.body()
    if len(body) > MAX_HEARTBEAT_BODY_BYTES:
        raise AppError(
            "NODE_PAYLOAD_TOO_LARGE",
            "心跳正文超过 5 MiB 限制",
            status_code=413,
        )
    received_at = datetime.now(UTC)
    async with request.app.state.node_write_lock:
        accepted_at = await HeartbeatService(
            session,
            request.app.state.settings.credential_key,
            request.app.state.node_request_throttle,
        ).accept(
            body=body,
            path_with_query=path_with_query(request),
            node_id=node_id,
            timestamp=timestamp_value,
            nonce=nonce,
            signature=signature,
            received_at=received_at,
        )
    return HeartbeatAccepted(accepted_at=accepted_at)


@admin_router.get("", response_model=AccessNodePage)
async def list_nodes(
    session: SessionDep,
    _: CurrentUserDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(max_length=255)] = None,
    management_status: Annotated[
        Literal["active", "disabled", "rejected", "pending"] | None,
        Query(),
    ] = None,
    connectivity_status_filter: Annotated[
        ConnectivityStatus | None,
        Query(alias="connectivity_status"),
    ] = None,
    sort_by: Annotated[
        Literal[
            "reported_name",
            "hostname",
            "software_version",
            "approved_at",
            "last_heartbeat_at",
        ],
        Query(),
    ] = "last_heartbeat_at",
    sort_order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> AccessNodePage:
    now = datetime.now(UTC)
    nodes, total = await AccessNodeQueryService(session).list_page(
        page=page,
        page_size=page_size,
        search=search,
        management_status=management_status,
        requested_connectivity=connectivity_status_filter,
        sort_by=sort_by,
        sort_order=sort_order,
        now=now,
    )
    return AccessNodePage(
        items=[
            AccessNodeListItem(
                node_id=node.node_id,
                reported_name=node.reported_name,
                display_name=node.display_name,
                effective_name=node.display_name or node.reported_name,
                hostname=node.hostname,
                software_version=node.software_version,
                management_status=node.management_status,
                notes=node.notes,
                management_tags=node.management_tags,
                disable_reason=node.disable_reason,
                connectivity_status=connectivity_status(
                    node.last_heartbeat_at,
                    now,
                ),
                approved_at=node.approved_at,
                last_heartbeat_at=node.last_heartbeat_at,
            )
            for node in nodes
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@admin_router.patch(
    "/{node_id}/management-info",
    response_model=ManagedAccessNodeResponse,
)
async def update_node_management_info(
    node_id: str,
    data: NodeManagementInfoUpdate,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> ManagedAccessNodeResponse:
    async with request.app.state.node_write_lock:
        node = await AccessNodeManagementService(
            session,
            request.app.state.settings.credential_key,
        ).update_info(
            node_id,
            display_name=data.display_name,
            notes=data.notes,
            management_tags=data.management_tags,
        )
    return managed_node_response(node)


@admin_router.patch("/{node_id}/status", response_model=ManagedAccessNodeResponse)
async def update_node_status(
    node_id: str,
    data: NodeStatusUpdate,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> ManagedAccessNodeResponse:
    async with request.app.state.node_write_lock:
        node = await AccessNodeManagementService(
            session,
            request.app.state.settings.credential_key,
        ).set_status(
            node_id,
            management_status=data.management_status,
            reason=data.reason,
        )
    return managed_node_response(node)


@admin_router.post("/{node_id}/token", response_model=ManagedAccessNodeResponse)
async def rotate_node_token(
    node_id: str,
    data: NodeTokenRotation,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> ManagedAccessNodeResponse:
    async with request.app.state.node_write_lock:
        node = await AccessNodeManagementService(
            session,
            request.app.state.settings.credential_key,
        ).rotate_token(node_id, data.token)
    return managed_node_response(node)


@admin_router.get("/{node_id}/assets", response_model=HostAssetPage)
async def list_node_assets(
    node_id: str,
    session: SessionDep,
    _: CurrentUserDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(max_length=255)] = None,
    lifecycle_status: Annotated[AssetLifecycleStatus | None, Query()] = None,
    detection_status: Annotated[HostDetectionFilter | None, Query()] = None,
    tag: Annotated[str | None, Query(max_length=32)] = None,
) -> HostAssetPage:
    assets, total = await HostAssetQueryService(session).list_page(
        node_id=node_id,
        page=page,
        page_size=page_size,
        search=search,
        lifecycle_status=lifecycle_status,
        detection_status=detection_status,
        tag=tag,
    )
    return HostAssetPage(
        items=[
            HostAssetItem(
                node_id=asset.node_id,
                host_id=asset.host_id,
                name=asset.name,
                address=asset.address,
                port=asset.port,
                username=asset.username,
                tags=asset.tags,
                is_local=asset.is_local,
                last_test_status=asset.last_test_status,
                last_test_code=asset.last_test_code,
                last_tested_at=asset.last_tested_at,
                lifecycle_status="retired" if asset.retired_at else "active",
                retired_at=asset.retired_at,
            )
            for asset in assets
        ],
        page=page,
        page_size=page_size,
        total=total,
    )
