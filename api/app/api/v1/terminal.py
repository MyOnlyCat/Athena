from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, status

from app.api.deps import CurrentUserDep, SessionDep
from app.core.errors import AppError
from app.models.host import Host
from app.schemas.terminal import TerminalTicketRequest, TerminalTicketResponse
from app.services.crypto import CredentialCipher
from app.services.ssh import HostConnection
from app.services.terminal import bridge_terminal

router = APIRouter(prefix="/terminal", tags=["terminal"])


@router.post(
    "/tickets",
    response_model=TerminalTicketResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_ticket(
    data: TerminalTicketRequest,
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
) -> TerminalTicketResponse:
    host = await session.get(Host, data.host_id)
    if host is None:
        raise AppError("HOST_NOT_FOUND", "主机不存在", status_code=404)
    if not host.host_key_fingerprint:
        raise AppError("SSH_HOST_UNTRUSTED", "请先确认 SSH 主机指纹", status_code=409)
    ticket = request.app.state.terminal_tickets.issue(user.id, host.id)
    return TerminalTicketResponse(ticket=ticket.value, expires_at=ticket.expires_at)


@router.websocket("/ws/{host_id}")
async def terminal_websocket(websocket: WebSocket, host_id: str) -> None:
    await websocket.accept()
    ticket = None
    try:
        first = await websocket.receive_json()
        ticket = websocket.app.state.terminal_tickets.consume(first.get("ticket", ""), host_id)
        if ticket is None:
            await websocket.send_json({"type": "error", "code": "INVALID_TERMINAL_TICKET"})
            await websocket.close(code=4401)
            return
        websocket.app.state.terminal_tickets.opened(ticket.user_id)
        async with websocket.app.state.session_factory() as session:
            host = await session.get(Host, host_id)
            if host is None or not host.host_key_fingerprint:
                await websocket.close(code=4404)
                return
            password = CredentialCipher(
                websocket.app.state.settings.credential_key
            ).decrypt(host.encrypted_password)
            terminal = await websocket.app.state.terminal_gateway.open(
                HostConnection(host.address, host.port, host.username, password),
                int(first.get("cols", 120)),
                int(first.get("rows", 36)),
            )
        await websocket.send_json({"type": "connected"})
        await bridge_terminal(websocket, terminal)
    except WebSocketDisconnect:
        pass
    finally:
        if ticket is not None:
            websocket.app.state.terminal_tickets.closed(ticket.user_id)

