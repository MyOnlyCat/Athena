import json
import time
from secrets import token_hex
from typing import Any

import httpx

from app.services.signing import sign_request


class MasterClient:
    def __init__(
        self,
        base_url: str,
        node_id: str,
        token: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.node_id = node_id
        self.token = token
        self.http = http_client or httpx.AsyncClient(base_url=self.base_url, timeout=15)
        self._owns_client = http_client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.http.aclose()

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        timestamp = str(int(time.time()))
        nonce = token_hex(16)
        signature = sign_request(
            secret=self.token,
            method="POST",
            path_with_query=path,
            timestamp=timestamp,
            nonce=nonce,
            body=body,
        )
        response = await self.http.post(
            path,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Node-Id": self.node_id,
                "X-Timestamp": timestamp,
                "X-Nonce": nonce,
                "X-Signature": signature,
            },
        )
        response.raise_for_status()
        if not response.content:
            return {}
        return dict(response.json())

    async def test_connection(
        self,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self.heartbeat(
            payload
            or {
                "node": {
                    "id": self.node_id,
                    "name": self.node_id,
                    "version": "unknown",
                    "hostname": self.node_id,
                    "reported_at": "connection-test",
                },
                "hosts": [],
            }
        )

    async def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/api/node/v1/nodes/heartbeat", payload)

    async def submit_registration(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/api/node/v1/registration-applications", payload)

    async def claim_tasks(self, running_tasks: int, limit: int = 4) -> list[dict[str, Any]]:
        result = await self._post(
            f"/api/node/v1/nodes/{self.node_id}/tasks/claim",
            {"running_tasks": running_tasks, "limit": limit},
        )
        return list(result.get("tasks", []))

    async def send_events(
        self,
        task_id: str,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self._post(
            f"/api/node/v1/tasks/{task_id}/events",
            {"events": events},
        )
