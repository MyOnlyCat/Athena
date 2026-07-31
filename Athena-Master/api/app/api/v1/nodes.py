from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Request

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.heartbeat import (
    AccessNodeListItem,
    AccessNodePage,
    ConnectivityStatus,
    HeartbeatAccepted,
)
from app.services.heartbeats import HeartbeatService
from app.services.node_status import connectivity_status
from app.services.nodes import AccessNodeQueryService

node_router = APIRouter(tags=["node-heartbeats"])
admin_router = APIRouter(prefix="/nodes", tags=["nodes"])


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
    body = await request.body()
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
                hostname=node.hostname,
                software_version=node.software_version,
                management_status=node.management_status,
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
