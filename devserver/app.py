"""
Runnable reference implementation of the API contract, for environments
without network access to install fastapi/celery/postgres/redis (like this
sandbox). Same request/response shapes as api/main.py. Run standalone:

    python3 devserver/app.py [port]

This is a same-CONTRACT stand-in, not a production server: Flask's dev
server and a Python thread pool are fine for proving the logic works, not
for real traffic. api/ (FastAPI + Celery + Postgres) remains the documented
production path — swap to it once you have network access to install those
packages and run real Postgres/Redis.
"""
import os
import sys
import json
import hashlib
import uuid
import threading
import queue
import datetime
import shutil

from flask import Flask, request, jsonify, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "generation"))
sys.path.insert(0, os.path.join(ROOT, "qc"))
sys.path.insert(0, ROOT)

import requests
from depth_estimator import ClassicalDepthEstimator
from parallax_render import render_pair, DEMO_SQUARE, DEMO_VERTICAL, PRODUCTION_SQUARE, PRODUCTION_VERTICAL
from qc_suite import run_qc_suite, CONFIG as QC_CONFIG
from api.pricing import price_for_tier, QC_ONLY_PRICE_USD

import db
from webhook_utils import sign_payload

# --- config -----------------------------------------------------------
USE_FULL_RES = os.environ.get("MOTION_ARTWORK_FULL_RES", "0") == "1"
DIMS = (PRODUCTION_SQUARE, PRODUCTION_VERTICAL) if USE_FULL_RES else (DEMO_SQUARE, DEMO_VERTICAL)
RENDER_DURATION_S = 12.0 if USE_FULL_RES else 3.0
RENDER_FPS = 24 if USE_FULL_RES else 12
RENDER_BITRATE_MBPS = 60.0 if USE_FULL_RES else 6.0

ASSETS_DIR = os.path.join(HERE, "storage")
os.makedirs(ASSETS_DIR, exist_ok=True)

app = Flask(__name__)
work_queue: "queue.Queue[tuple[str,str,str]]" = queue.Queue()

# QC bounds that match whichever DIMS/bitrate this run is actually using —
# in production this is just QC_CONFIG (the real Apple numbers) unmodified.
RUNTIME_QC_CONFIG = dict(QC_CONFIG)
if not USE_FULL_RES:
    RUNTIME_QC_CONFIG["square_resolution"] = DEMO_SQUARE
    RUNTIME_QC_CONFIG["vertical_resolution"] = DEMO_VERTICAL
    RUNTIME_QC_CONFIG["bitrate_range_mbps"] = (RENDER_BITRATE_MBPS * 0.85, RENDER_BITRATE_MBPS * 1.15)
    RUNTIME_QC_CONFIG["duration_range_s"] = (2, 35)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def require_org():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, (jsonify({"detail": "expected 'Bearer <api_key>'"}), 401)
    org = db.get_org_by_key_hash(hash_key(auth[len("Bearer "):].strip()))
    if org is None:
        return None, (jsonify({"detail": "invalid or revoked API key"}), 401)
    return org, None


# --- root -------------------------------------------------------------

@app.get("/")
def index():
    """Codespaces/Replit's 'Open in Browser' button opens this exact path —
    without a route here it 404s and looks like the whole server is broken,
    when actually every OTHER route was fine. This is that missing route."""
    return """
    <html><head><title>Motion Artwork API — dev server</title>
    <style>body{font-family:sans-serif;background:#111;color:#eee;padding:2rem;line-height:1.6}
    code{background:#222;padding:2px 6px;border-radius:4px}</style></head><body>
    <h2>It's running.</h2>
    <p>This page itself isn't an endpoint — the API lives under
    <code>/v1/motion-artwork/...</code>, and you talk to it with real HTTP
    requests (curl, or your own code), not by browsing to it directly.</p>
    <p>Two links that DO work directly in a browser:</p>
    <ul>
      <li><a href="/v1/health">/v1/health</a> — should show <code>{"status":"ok"}</code></li>
      <li><code>/v1/motion-artwork/preview/&lt;job_id&gt;</code> — once you've created
      a job and it's complete, this plays the result right here in the browser.</li>
    </ul>
    </body></html>
    """


# --- static / asset serving -------------------------------------------

@app.get("/test-assets/cover.png")
def test_cover():
    """Serves the synthetic test cover over real HTTP, so job submission
    exercises a genuine URL download rather than a local-path shortcut."""
    return send_from_directory(os.path.join(ROOT, "test_assets"), "cover_test.png")


@app.get("/v1/motion-artwork/assets/<job_id>/<filename>")
def get_asset(job_id, filename):
    return send_from_directory(os.path.join(ASSETS_DIR, job_id), filename)


@app.get("/v1/motion-artwork/preview/<job_id>")
def preview(job_id):
    """A plain HTML page that plays both deliverables inline in the browser.
    Exists specifically so you never need to trigger a file download to see
    whether a render worked — just open this URL."""
    job = db.get_job(job_id)
    if job is None or job["status"] != "complete":
        return f"<p>Job {job_id} isn't complete yet — status: {job['status'] if job else 'not found'}</p>", 404
    return f"""
    <html><head><title>Motion artwork preview — {job_id}</title>
    <style>body{{font-family:sans-serif;background:#111;color:#eee;padding:2rem}}
    video{{max-width:45%;margin:1rem;border-radius:8px}} .row{{display:flex;flex-wrap:wrap}}</style>
    </head><body>
    <h2>Job {job_id} — no download needed, just watch below</h2>
    <div class="row">
      <div><p>Square (1:1)</p><video controls autoplay loop muted
        src="/v1/motion-artwork/assets/{job_id}/{os.path.basename(job['square_asset_url'])}"></video></div>
      <div><p>Vertical (3:4)</p><video controls autoplay loop muted
        src="/v1/motion-artwork/assets/{job_id}/{os.path.basename(job['vertical_asset_url'])}"></video></div>
    </div>
    </body></html>
    """


@app.get("/v1/health")
def health():
    return jsonify({"status": "ok", "full_res": USE_FULL_RES})


# --- endpoints ----------------------------------------------------------

@app.post("/v1/motion-artwork/jobs")
def create_job():
    org, err = require_org()
    if err:
        return err
    body = request.get_json(force=True)
    for required in ("release_id", "cover_art_url", "callback_url"):
        if required not in body:
            return jsonify({"detail": f"missing field: {required}"}), 422

    tier = body.get("tier", "parametric")
    try:
        price = price_for_tier(tier)
    except ValueError as e:
        return jsonify({"detail": str(e)}), 422

    job_id = db.insert_job(
        org_id=org["id"], kind="generate", release_id=body["release_id"],
        artist_id=body.get("artist_id"), cover_art_url=body["cover_art_url"], tier=tier,
        duration_seconds=body.get("duration_seconds", RENDER_DURATION_S),
        style_preset=body.get("style_preset", "subtle_parallax"),
        callback_url=body["callback_url"], metadata=body.get("metadata", {}),
        status="queued", price_usd=price,
    )
    # Captured from THIS request, not a startup-time constant — so the asset
    # URLs the worker builds later match whatever host you actually used to
    # reach the server (127.0.0.1 directly, or a Codespaces/Replit forwarded
    # https://... domain), not always 127.0.0.1 regardless of context.
    work_queue.put((job_id, "generate", request.host_url.rstrip("/")))
    return jsonify({
        "job_id": job_id, "status": "queued",
        "estimated_completion_seconds": 20, "tier": tier, "price_usd": price,
    }), 202


@app.get("/v1/motion-artwork/jobs/<job_id>")
def get_job(job_id):
    org, err = require_org()
    if err:
        return err
    job = db.get_job(job_id)
    if job is None or job["org_id"] != org["id"]:
        return jsonify({"detail": "job not found"}), 404

    qc_report = db.get_latest_qc_report(job_id)
    assets = None
    if job["status"] == "complete" and job["square_asset_url"]:
        assets = {
            "square_1x1": {"url": job["square_asset_url"]},
            "vertical_3x4": {"url": job["vertical_asset_url"]},
            "preview_url": f"{request.host_url.rstrip('/')}/v1/motion-artwork/preview/{job_id}",
        }
    return jsonify({
        "job_id": job_id, "status": job["status"],
        "qc_report": qc_report, "assets": assets,
        "error_message": job.get("error_message"),
    })


@app.post("/v1/motion-artwork/jobs/batch")
def create_batch():
    org, err = require_org()
    if err:
        return err
    body = request.get_json(force=True)
    jobs = body.get("jobs", [])
    if not jobs:
        return jsonify({"detail": "jobs must be non-empty"}), 400
    if len(jobs) > 5000:
        return jsonify({"detail": "max 5000 jobs per batch"}), 400

    batch_id = db.create_batch(org["id"], len(jobs))
    job_ids = []
    for item in jobs:
        tier = item.get("tier", "parametric")
        price = price_for_tier(tier)
        job_id = db.insert_job(
            org_id=org["id"], batch_id=batch_id, kind="generate",
            release_id=item["release_id"], artist_id=item.get("artist_id"),
            cover_art_url=item["cover_art_url"], tier=tier,
            duration_seconds=item.get("duration_seconds", RENDER_DURATION_S),
            style_preset=item.get("style_preset", "subtle_parallax"),
            callback_url=item["callback_url"], metadata=item.get("metadata", {}),
            status="queued", price_usd=price,
        )
        job_ids.append(job_id)
        work_queue.put((job_id, "generate", request.host_url.rstrip("/")))

    return jsonify({"batch_id": batch_id, "job_ids": job_ids}), 202


@app.post("/v1/motion-artwork/qc")
def qc_only():
    org, err = require_org()
    if err:
        return err
    body = request.get_json(force=True)
    for required in ("release_id", "square_asset_url", "vertical_asset_url", "source_cover_url"):
        if required not in body:
            return jsonify({"detail": f"missing field: {required}"}), 422

    job_id = db.insert_job(
        org_id=org["id"], kind="qc_only", release_id=body["release_id"],
        cover_art_url=body["source_cover_url"], callback_url=body.get("callback_url"),
        status="queued", price_usd=QC_ONLY_PRICE_USD,
    )
    db.update_job(job_id, square_asset_url=body["square_asset_url"], vertical_asset_url=body["vertical_asset_url"])
    work_queue.put((job_id, "qc_only", request.host_url.rstrip("/")))
    return jsonify({"job_id": job_id, "status": "queued", "price_usd": QC_ONLY_PRICE_USD}), 202


# --- background worker ---------------------------------------------------

def _download(url: str, dest: str):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    with open(dest, "wb") as f:
        f.write(r.content)


def _fire_webhook(job: dict, event: str, qc_report: dict | None, assets: dict | None):
    if not job.get("callback_url"):
        return
    org_row = None
    conn = db.get_conn()
    org_row = conn.execute("SELECT * FROM orgs WHERE id = ?", (job["org_id"],)).fetchone()
    conn.close()
    secret = org_row["webhook_secret"] if org_row else ""

    payload = {
        "event": event, "job_id": job["id"], "release_id": job.get("release_id"),
        "status": job["status"], "assets": assets, "qc_report": qc_report,
        "billing": {"price_usd": job.get("price_usd")},
    }
    body = json.dumps(payload).encode("utf-8")
    sig = sign_payload(body, secret)
    try:
        requests.post(
            job["callback_url"], data=body,
            headers={"Content-Type": "application/json", "X-Motion-Artwork-Signature": f"sha256={sig}"},
            timeout=10,
        )
    except requests.RequestException as e:
        print(f"[worker] webhook delivery failed for job {job['id']}: {e}", flush=True)


def process_generate_job(job_id: str, base_url: str):
    db.update_job(job_id, status="processing")
    job = db.get_job(job_id)
    work_dir = os.path.join(ASSETS_DIR, job_id)
    os.makedirs(work_dir, exist_ok=True)
    try:
        cover_path = os.path.join(work_dir, "source_cover.png")
        _download(job["cover_art_url"], cover_path)

        estimator = ClassicalDepthEstimator()
        assets = render_pair(
            cover_path, work_dir, estimator,
            duration_s=float(job["duration_seconds"] or RENDER_DURATION_S),
            fps=RENDER_FPS, codec="h264", bitrate_mbps=RENDER_BITRATE_MBPS, dims=DIMS,
        )
        db.update_job(job_id, status="qc_review")

        report = run_qc_suite(assets["square_1x1"], assets["vertical_3x4"], cover_path, RUNTIME_QC_CONFIG)
        db.insert_qc_report(job_id, report["passed"], report["checks"], report["apple_ready"])

        if not report["passed"]:
            db.update_job(job_id, status="rejected", completed_at=db.now())
            job = db.get_job(job_id)
            _fire_webhook(job, "motion_artwork.rejected", report, None)
            return

        sq_name = os.path.basename(assets["square_1x1"])
        v_name = os.path.basename(assets["vertical_3x4"])
        sq_url = f"{base_url}/v1/motion-artwork/assets/{job_id}/{sq_name}"
        v_url = f"{base_url}/v1/motion-artwork/assets/{job_id}/{v_name}"
        preview_url = f"{base_url}/v1/motion-artwork/preview/{job_id}"
        db.update_job(job_id, status="complete", square_asset_url=sq_url,
                       vertical_asset_url=v_url, completed_at=db.now())
        job = db.get_job(job_id)
        asset_block = {"square_1x1": {"url": sq_url}, "vertical_3x4": {"url": v_url}, "preview_url": preview_url}
        _fire_webhook(job, "motion_artwork.completed", report, asset_block)

    except Exception as e:
        db.update_job(job_id, status="failed", error_message=str(e)[:2000])
        job = db.get_job(job_id)
        _fire_webhook(job, "motion_artwork.failed", None, None)
        raise


def process_qc_only_job(job_id: str, base_url: str):
    db.update_job(job_id, status="processing")
    job = db.get_job(job_id)
    work_dir = os.path.join(ASSETS_DIR, job_id)
    os.makedirs(work_dir, exist_ok=True)
    try:
        sq = os.path.join(work_dir, "square.mov")
        v = os.path.join(work_dir, "vertical.mov")
        cover = os.path.join(work_dir, "cover.png")
        _download(job["square_asset_url"], sq)
        _download(job["vertical_asset_url"], v)
        _download(job["cover_art_url"], cover)

        report = run_qc_suite(sq, v, cover, RUNTIME_QC_CONFIG)
        db.insert_qc_report(job_id, report["passed"], report["checks"], report["apple_ready"])
        status = "complete" if report["passed"] else "rejected"
        db.update_job(job_id, status=status, completed_at=db.now())
        job = db.get_job(job_id)
        event = "motion_artwork.completed" if report["passed"] else "motion_artwork.rejected"
        _fire_webhook(job, event, report, None)
    except Exception as e:
        db.update_job(job_id, status="failed", error_message=str(e)[:2000])
        job = db.get_job(job_id)
        _fire_webhook(job, "motion_artwork.failed", None, None)
        raise


def worker_loop():
    while True:
        job_id, kind, base_url = work_queue.get()
        try:
            if kind == "generate":
                process_generate_job(job_id, base_url)
            else:
                process_qc_only_job(job_id, base_url)
        except Exception as e:
            print(f"[worker] job {job_id} failed: {e}", flush=True)
        finally:
            work_queue.task_done()


def start_workers(n: int = 2):
    for _ in range(n):
        t = threading.Thread(target=worker_loop, daemon=True)
        t.start()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    fresh = os.environ.get("MOTION_ARTWORK_FRESH_DB", "1") == "1"
    db.init_db(fresh=fresh)
    start_workers(n=2)
    print(f"[devserver] full_res={USE_FULL_RES} dims={DIMS} listening on 127.0.0.1:{port} "
          f"(asset URLs are built per-request now, not from this address)", flush=True)
    app.run(host="127.0.0.1", port=port, threaded=True)
