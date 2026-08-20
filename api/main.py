import uuid
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .auth import get_current_org
from .models import Org, Job, Batch
from .pricing import price_for_tier, QC_ONLY_PRICE_USD
from .schemas import (
    JobCreateRequest, JobCreateResponse, JobStatusResponse,
    BatchCreateRequest, BatchCreateResponse, QCOnlyRequest, QCOnlyResponse,
)
from .tasks import generate_job_task, qc_only_task

app = FastAPI(title="Motion Artwork API", version="1.0")


@app.get("/v1/health")
def health():
    return {"status": "ok"}


@app.post("/v1/motion-artwork/jobs", response_model=JobCreateResponse, status_code=202)
def create_job(req: JobCreateRequest, org: Org = Depends(get_current_org), db: Session = Depends(get_db)):
    price = price_for_tier(req.tier)
    job = Job(
        org_id=org.id, kind="generate", release_id=req.release_id, artist_id=req.artist_id,
        cover_art_url=str(req.cover_art_url), tier=req.tier, duration_seconds=req.duration_seconds,
        style_preset=req.style_preset, callback_url=str(req.callback_url),
        metadata_json=req.metadata, status="queued", price_usd=price,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    generate_job_task.delay(str(job.id))

    return JobCreateResponse(
        job_id=str(job.id), status="queued",
        estimated_completion_seconds=45, tier=req.tier, price_usd=price,
    )


@app.get("/v1/motion-artwork/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str, org: Org = Depends(get_current_org), db: Session = Depends(get_db)):
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="job not found")

    job = db.query(Job).filter(Job.id == job_uuid, Job.org_id == org.id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    qc_report = None
    if job.qc_reports:
        latest = sorted(job.qc_reports, key=lambda r: r.created_at)[-1]
        qc_report = {"passed": latest.passed, "checks": latest.checks, "apple_ready": latest.apple_ready}

    assets = None
    if job.status == "complete" and job.square_asset_url:
        assets = {
            "square_1x1": {"url": job.square_asset_url},
            "vertical_3x4": {"url": job.vertical_asset_url},
        }

    return JobStatusResponse(job_id=str(job.id), status=job.status, qc_report=qc_report, assets=assets)


@app.post("/v1/motion-artwork/jobs/batch", response_model=BatchCreateResponse, status_code=202)
def create_batch(req: BatchCreateRequest, org: Org = Depends(get_current_org), db: Session = Depends(get_db)):
    if not req.jobs:
        raise HTTPException(status_code=400, detail="jobs must be non-empty")
    if len(req.jobs) > 5000:
        raise HTTPException(status_code=400, detail="max 5000 jobs per batch — split into multiple batches")

    batch = Batch(org_id=org.id, job_count=len(req.jobs))
    db.add(batch)
    db.commit()
    db.refresh(batch)

    job_ids = []
    for item in req.jobs:
        price = price_for_tier(item.tier)
        job = Job(
            org_id=org.id, batch_id=batch.id, kind="generate", release_id=item.release_id,
            artist_id=item.artist_id, cover_art_url=str(item.cover_art_url), tier=item.tier,
            duration_seconds=item.duration_seconds, style_preset=item.style_preset,
            callback_url=str(item.callback_url), metadata_json=item.metadata,
            status="queued", price_usd=price,
        )
        db.add(job)
        db.flush()  # get job.id without committing yet
        job_ids.append(str(job.id))

    db.commit()

    for jid in job_ids:
        generate_job_task.delay(jid)

    return BatchCreateResponse(batch_id=str(batch.id), job_ids=job_ids)


@app.post("/v1/motion-artwork/qc", response_model=QCOnlyResponse, status_code=202)
def qc_only(req: QCOnlyRequest, org: Org = Depends(get_current_org), db: Session = Depends(get_db)):
    """The standalone 'Trojan Horse' endpoint — QC's a file this system did
    not render. No generation tier, flat per-check price."""
    job = Job(
        org_id=org.id, kind="qc_only", release_id=req.release_id,
        cover_art_url=str(req.source_cover_url),
        callback_url=str(req.callback_url) if req.callback_url else None,
        status="queued", price_usd=QC_ONLY_PRICE_USD,
    )
    # square/vertical asset URLs are inputs here, not outputs — stash on the
    # same columns since this job never produces its own assets.
    job.square_asset_url = str(req.square_asset_url)
    job.vertical_asset_url = str(req.vertical_asset_url)
    db.add(job)
    db.commit()
    db.refresh(job)

    qc_only_task.delay(str(job.id))

    return QCOnlyResponse(job_id=str(job.id), status="queued", price_usd=QC_ONLY_PRICE_USD)
