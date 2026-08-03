from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.overview import OverviewResponse
from app.services.overview import OverviewQueryService

router = APIRouter(prefix="/overview", tags=["overview"])


@router.get("", response_model=OverviewResponse)
async def get_overview(
    session: SessionDep,
    _: CurrentUserDep,
) -> OverviewResponse:
    return await OverviewQueryService(session).get(datetime.now(UTC))
