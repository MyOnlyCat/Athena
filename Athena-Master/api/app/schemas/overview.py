from pydantic import BaseModel


class OverviewNodeCounts(BaseModel):
    total: int
    pending: int
    active: int
    disabled: int
    rejected: int
    online: int
    stale: int
    offline: int


class OverviewAssetCounts(BaseModel):
    active: int
    abnormal: int
    unknown: int


class OverviewResponse(BaseModel):
    nodes: OverviewNodeCounts
    assets: OverviewAssetCounts
