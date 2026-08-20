from typing import Optional, Literal
from pydantic import BaseModel, Field, HttpUrl


class JobCreateRequest(BaseModel):
    release_id: str
    artist_id: Optional[str] = None
    cover_art_url: HttpUrl
    tier: Literal["parametric", "stylized", "cinematic"] = "parametric"
    duration_seconds: float = Field(12.0, ge=8.0, le=35.0)
    style_preset: str = "subtle_parallax"
    callback_url: HttpUrl
    metadata: dict = Field(default_factory=dict)


class JobCreateResponse(BaseModel):
    job_id: str
    status: str
    estimated_completion_seconds: int
    tier: str
    price_usd: float


class AssetInfo(BaseModel):
    url: str
    resolution: str
    codec: str
    bitrate_mbps: float
    duration_seconds: float
    checksum_sha256: str


class QCCheckResult(BaseModel):
    passed: bool
    checks: dict
    apple_ready: bool


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    qc_report: Optional[QCCheckResult] = None
    assets: Optional[dict] = None


class WebhookPayload(BaseModel):
    event: Literal["motion_artwork.completed", "motion_artwork.rejected", "motion_artwork.failed"]
    job_id: str
    release_id: Optional[str] = None
    status: str
    assets: Optional[dict] = None
    qc_report: Optional[QCCheckResult] = None
    billing: Optional[dict] = None


class BatchJobItem(JobCreateRequest):
    pass


class BatchCreateRequest(BaseModel):
    jobs: list[BatchJobItem]


class BatchCreateResponse(BaseModel):
    batch_id: str
    job_ids: list[str]


class QCOnlyRequest(BaseModel):
    release_id: str
    square_asset_url: HttpUrl
    vertical_asset_url: HttpUrl
    source_cover_url: HttpUrl
    callback_url: Optional[HttpUrl] = None


class QCOnlyResponse(BaseModel):
    job_id: str
    status: str
    price_usd: float = 0.10
