from datetime import datetime

from pydantic import BaseModel


class TerminalTicketRequest(BaseModel):
    host_id: str


class TerminalTicketResponse(BaseModel):
    ticket: str
    expires_at: datetime

