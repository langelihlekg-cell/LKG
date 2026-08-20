# Motion Artwork API — Implementation

**New to coding or APIs?** Start with `GETTING_STARTED.md` instead — it's a
hand-holding, zero-assumed-experience walkthrough. This file is the denser
technical reference.

Implements the 5-phase plan: a depth-based parallax renderer, a standalone
Apple-compliance QC suite, and the distributor-facing API layer that wraps
both. Now includes a **real, running reference server** — not just written
code — that proves the entire API contract works end to end.

## The honest constraint, stated once

This sandbox has no internet access and no GPU. That means: no installing
FastAPI/Celery/Postgres/Redis/PyTorch, no real Depth Anything V2 weights, no
reaching Apple or a real distributor, and no exposing a public URL — none of
that is possible from here regardless of effort, and nothing below pretends
otherwise. What *is* possible: loopback networking (127.0.0.1) works fine,
and Flask + requests + sqlite3 are already installed. So `devserver/` is a
same-contract, dependency-free (beyond what's already here) implementation
that actually runs, as real servers, hit with real HTTP requests — closing
almost every "written but not executed" gap from the first pass. `api/`
(FastAPI + Celery + Postgres) remains the documented production path for
when you do have network access.

## What's real vs. what's a stand-in

**Actually running, proven with real HTTP traffic (`python3 devserver/live_demo.py`):**
- Two real server processes (the API + a mock distributor webhook receiver)
  talking over real loopback HTTP.
- Job creation → background worker picks it up → downloads the cover over
  HTTP → renders both deliverables → runs the full QC suite → serves the
  files back over HTTP → fires a webhook.
- The webhook is independently verified: received by a separate process,
  HMAC signature checked, event type checked.
- The downloaded asset is independently re-verified with `ffprobe` after
  fetching it over HTTP — not just trusted from the job status.
- Batch endpoint with multiple concurrent jobs.
- QC-only endpoint tested both ways: a genuinely compliant file passes, and
  a file with an injected audio track is correctly rejected, with the
  rejection isolated to the specific failing check.
- Invalid API keys are actually rejected with 401.
- **Last run: 18/18 checks passed.** Logs from that run are committed at
  `devserver/app.log` and `devserver/distributor.log` — read them, they're
  unedited.

**Still a stand-in for the real thing (physically can't be otherwise here):**
- `devserver` uses sqlite + Python threads instead of Postgres + Celery/Redis,
  and Flask's dev server instead of a production WSGI server. Fine for
  proving logic, not for real traffic — `api/` is the documented path for that.
- `ClassicalDepthEstimator` (classical CPU saliency, not a neural depth
  model) is what's running. Swapping in `DepthAnythingV2Estimator` needs
  `pip install torch transformers` and a weights download — one line of
  code, but needs network this sandbox doesn't have.
- Nothing here has touched Apple or a real distributor account — that's
  inherently something only you can do, not a gap I can close by trying
  harder.

## A real bug this testing caught

Initial FFmpeg encode settings used `-b:v` with a `±10–15%` `-minrate`/
`-maxrate` band. Testing against actual rendered output showed the real
bitrate landing at ~0.7 Mbps against a 6 Mbps target — libx264 logs
`CBR HRD requires constant bitrate` and silently falls back to
content-driven ABR when min/max aren't *exactly* equal to the target. Fixed
by setting `-minrate == -maxrate == -b:v` exactly. Not obvious from the
ffmpeg docs, and it fails silently rather than erroring — worth knowing
before you tune bitrate for real 4K delivery.

## Run it yourself

```bash
pip install flask requests opencv-python-headless numpy scipy pillow --break-system-packages
python3 devserver/live_demo.py
```
Starts both servers, runs all 8 test scenarios against real HTTP endpoints,
tears down, prints a pass/fail summary. Takes about 40 seconds. To run the
server standalone instead (e.g. to poke it with curl yourself):
```bash
python3 devserver/app.py 9000 &
python3 devserver/mock_distributor.py 9001 &
# then create a dev org + key — see devserver/live_demo.py's "Setup" section
# for the 3 lines that do this, or lift them into a small script
```
Set `MOTION_ARTWORK_FULL_RES=1` before starting `app.py` to render at real
Apple dimensions (3840×3840 / 2048×2732) instead of demo scale — much
slower on CPU, same code path.

## Repo structure

```
generation/     depth estimation + parallax renderer + Dockerfile (GPU worker)
qc/             standalone compliance suite (also the Phase 4 wedge product)
api/            production path: FastAPI, SQLAlchemy, Celery, webhooks, storage, pricing
devserver/      RUNS NOW: Flask + sqlite reference server, mock distributor, live_demo.py
migrations/     Postgres schema (production)
scripts/        week1_prototype.py — standalone CLI, no API needed
tests/          end-to-end pipeline test (generation + QC, no pytest dependency)
docker-compose.yml   local dev stack for api/ (postgres + redis + api + worker)
```

## Phase mapping

| Phase | What it needed | Status |
|---|---|---|
| 1. Manual pipeline validation | depth + parallax script | Built & tested. Submitting real output through your distributor account to a live Apple test release is the one step nothing here can do for you. |
| 2. Core engine + QC suite | containerized worker, compliance engine | Logic built & tested; `generation/Dockerfile` written, not build-tested (no Docker/network here). |
| 3. API gateway, webhooks, sandbox | HTTP API, DB, async jobs, webhook retries | **Running now** via `devserver/`, proven with real HTTP traffic. `api/` is the same contract on production infra, written and syntax-checked, not boot-tested (needs Postgres/Redis you'd run yourself). |
| 4. Distributor pilot, QC-only wedge | `/v1/motion-artwork/qc` at $0.10/check | Implemented and tested both pass and fail paths, live. |
| 5. Enterprise scaling, batch backfills | `/jobs/batch`, serverless GPU | Batch endpoint implemented and tested (5,000 job cap per call); `generation/Dockerfile` is what you'd point RunPod Serverless / Modal at. |

## Pricing

Wholesale tiers (what you bill the distributor) live in `api/pricing.py`
(reused directly by `devserver/app.py`): parametric $4, stylized $14,
cinematic $25 — mid-points of the $2–8 / $10–18 / $20–30 bands — plus the
$0.10 QC-only price and volume discount breakpoints at 1K/10K/40K jobs per
month. The distributor's own artist-facing retail price (e.g. the $9.99
add-on from the plan) is their markup decision, not something this service sets.

## To run the production stack (`api/`) once you have network access

1. `cp .env.example .env` and fill in R2 + a real `DATABASE_URL`/`REDIS_URL`.
2. `docker-compose up --build` — Postgres (auto-runs `migrations/001_init.sql`),
   Redis, the API on `:8000`, and the GPU worker.
3. Insert a row into `orgs` and `api_keys` (or adapt `devserver/live_demo.py`'s
   seeding logic — same shape, real tables) to get a working Bearer token.
4. `POST /v1/motion-artwork/jobs` with a real `cover_art_url` and `callback_url`.

## Immediate next actions

1. Swap `ClassicalDepthEstimator` for `DepthAnythingV2Estimator` (one line,
   in `api/tasks.py` or `devserver/app.py`) once you have GPU + network.
2. Run with `--full-res --real-depth` against a real album cover, then push
   the output through your own distributor account to a real Apple test
   release — the one validation step nothing here can substitute for.
3. Tune the bitrate target against Apple's *current* published spec — the
   45–100 Mbps figure in `qc/qc_suite.py`'s `CONFIG` is carried over from
   the doc you supplied, not independently re-verified against Apple's
   official page in this session.
4. When you're ready for real traffic, move `devserver`'s logic onto `api/`
   (same functions, already shared via `api/pricing.py`) rather than
   scaling Flask's dev server — it says so itself in the startup warning.
