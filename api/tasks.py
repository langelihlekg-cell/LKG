import os
import sys
import tempfile
import datetime
from celery import Celery

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generation"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qc"))

from depth_estimator import ClassicalDepthEstimator  # swap for DepthAnythingV2Estimator in prod
from parallax_render import render_pair, PRODUCTION_SQUARE, PRODUCTION_VERTICAL
from qc_suite import run_qc_suite, CONFIG as QC_CONFIG

from .db import SessionLocal
from .models import Job, QCReport, Org
from .storage import upload_asset
from .webhooks import send_webhook
from .pricing import price_for_tier

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
PUBLIC_ASSET_BASE_URL = os.environ.get("PUBLIC_ASSET_BASE_URL", "https://cdn.example.com")

celery_app = Celery("motion_artwork", broker=REDIS_URL, backend=REDIS_URL)

# Production defaults. duration/fps trade render time for smoothness —
# tune per the cost model, not just for looks.
DEFAULT_FPS = 24
DEFAULT_CODEC = "h264"
DEFAULT_BITRATE_MBPS = 60  # mid-point of the 45-100 Mbps window; verify against
                           # Apple's current published spec before locking this in


def _download_to_tmp(url: str, dest_path: str) -> None:
    import httpx
    with httpx.stream("GET", url, timeout=60.0) as resp:
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1 << 20):
                f.write(chunk)


@celery_app.task(bind=True, max_retries=3)
def generate_job_task(self, job_id: str):
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            return
        job.status = "processing"
        db.commit()

        with tempfile.TemporaryDirectory() as tmp:
            cover_path = os.path.join(tmp, "cover.png")
            _download_to_tmp(job.cover_art_url, cover_path)

            estimator = ClassicalDepthEstimator()  # -> DepthAnythingV2Estimator() in production
            out_dir = os.path.join(tmp, "out")
            assets = render_pair(
                cover_path, out_dir, estimator,
                duration_s=float(job.duration_seconds or 12.0),
                fps=DEFAULT_FPS, codec=DEFAULT_CODEC, bitrate_mbps=DEFAULT_BITRATE_MBPS,
                dims=(PRODUCTION_SQUARE, PRODUCTION_VERTICAL),
            )

            job.status = "qc_review"
            db.commit()

            report = run_qc_suite(assets["square_1x1"], assets["vertical_3x4"], cover_path, QC_CONFIG)

            qc_row = QCReport(job_id=job.id, passed=report["passed"],
                               checks=report["checks"], apple_ready=report["apple_ready"])
            db.add(qc_row)

            if not report["passed"]:
                job.status = "rejected"
                db.commit()
                _fire_webhook(db, job, event="motion_artwork.rejected", qc_report=report, assets=None)
                return

            org = db.query(Org).filter(Org.id == job.org_id).first()
            square_meta = upload_asset(assets["square_1x1"], f"{job.id}/square.mov", PUBLIC_ASSET_BASE_URL)
            vertical_meta = upload_asset(assets["vertical_3x4"], f"{job.id}/vertical.mov", PUBLIC_ASSET_BASE_URL)

            job.square_asset_url = square_meta["url"]
            job.vertical_asset_url = vertical_meta["url"]
            job.status = "complete"
            job.completed_at = datetime.datetime.utcnow()
            db.commit()

            asset_block = {
                "square_1x1": {**square_meta, "resolution": "3840x3840"},
                "vertical_3x4": {**vertical_meta, "resolution": "2048x2732"},
            }
            _fire_webhook(db, job, event="motion_artwork.completed", qc_report=report, assets=asset_block)

    except Exception as e:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_message = str(e)[:2000]
            db.commit()
            _fire_webhook(db, job, event="motion_artwork.failed", qc_report=None, assets=None)
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def qc_only_task(self, job_id: str):
    """The Phase 4 wedge product: QC a file we did not render."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            return
        job.status = "processing"
        db.commit()

        with tempfile.TemporaryDirectory() as tmp:
            sq = os.path.join(tmp, "square.mov")
            v = os.path.join(tmp, "vertical.mov")
            cover = os.path.join(tmp, "cover.png")
            _download_to_tmp(job.square_asset_url, sq)
            _download_to_tmp(job.vertical_asset_url, v)
            _download_to_tmp(job.cover_art_url, cover)

            report = run_qc_suite(sq, v, cover, QC_CONFIG)
            db.add(QCReport(job_id=job.id, passed=report["passed"],
                             checks=report["checks"], apple_ready=report["apple_ready"]))
            job.status = "complete" if report["passed"] else "rejected"
            job.completed_at = datetime.datetime.utcnow()
            db.commit()

            event = "motion_artwork.completed" if report["passed"] else "motion_artwork.rejected"
            _fire_webhook(db, job, event=event, qc_report=report, assets=None)

    except Exception as e:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_message = str(e)[:2000]
            db.commit()
        raise
    finally:
        db.close()


def _fire_webhook(db, job, event: str, qc_report: dict | None, assets: dict | None):
    if not job.callback_url:
        return
    org = db.query(Org).filter(Org.id == job.org_id).first()
    payload = {
        "event": event,
        "job_id": str(job.id),
        "release_id": job.release_id,
        "status": job.status,
        "assets": assets,
        "qc_report": qc_report,
        "billing": {"price_usd": float(job.price_usd or 0)},
    }
    # First attempt inline; on failure a scheduled retry (via webhook_deliveries +
    # a periodic Celery beat task, not shown here) picks it up on RETRY_SCHEDULE_SECONDS.
    send_webhook(job.callback_url, payload, org.webhook_secret)
