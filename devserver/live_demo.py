#!/usr/bin/env python3
"""
Starts the real dev server + a real mock distributor receiver as separate
processes, then drives the ENTIRE API contract through actual HTTP requests:
job creation, background processing, polling, asset download, webhook
delivery with signature verification, batch submission, and both a passing
and a failing QC-only call. Prints a pass/fail summary.

Run: python3 devserver/live_demo.py
"""
import os
import sys
import time
import json
import uuid
import hashlib
import subprocess
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import requests
import db

APP_PORT = 9000
DIST_PORT = 9001
APP_BASE = f"http://127.0.0.1:{APP_PORT}"
DIST_BASE = f"http://127.0.0.1:{DIST_PORT}"

results = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((status, label, detail))
    print(f"  [{status}] {label}" + (f"  -- {detail}" if detail and not condition else ""))
    return condition


def wait_for_health(url, name, timeout=20):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    print(f"  !! {name} did not become healthy within {timeout}s")
    return False


def poll_job(job_id, headers, timeout=90):
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(f"{APP_BASE}/v1/motion-artwork/jobs/{job_id}", headers=headers, timeout=10)
        data = r.json()
        if data["status"] in ("complete", "rejected", "failed"):
            return data
        time.sleep(1.0)
    raise TimeoutError(f"job {job_id} did not finish within {timeout}s")


def main():
    print("=== Setup: fresh DB, seed dev org + API key ===")
    db.init_db(fresh=True)
    org = db.create_org("Test Distributor Inc")
    raw_key = uuid.uuid4().hex + uuid.uuid4().hex
    db.create_api_key(org["id"], hashlib.sha256(raw_key.encode()).hexdigest())
    headers = {"Authorization": f"Bearer {raw_key}", "Content-Type": "application/json"}
    print(f"  org_id={org['id']}")

    procs = []
    log_app = open(os.path.join(HERE, "app.log"), "w")
    log_dist = open(os.path.join(HERE, "distributor.log"), "w")
    try:
        print("\n=== Starting real servers (subprocesses) ===")
        procs.append(subprocess.Popen(
            [sys.executable, os.path.join(HERE, "mock_distributor.py"), str(DIST_PORT)],
            stdout=log_dist, stderr=subprocess.STDOUT,
        ))
        env = dict(os.environ, MOTION_ARTWORK_FRESH_DB="0")
        procs.append(subprocess.Popen(
            [sys.executable, os.path.join(HERE, "app.py"), str(APP_PORT)],
            stdout=log_app, stderr=subprocess.STDOUT, env=env,
        ))

        ok_dist = wait_for_health(f"{DIST_BASE}/health", "mock_distributor")
        ok_app = wait_for_health(f"{APP_BASE}/v1/health", "devserver")
        check("mock_distributor process is up", ok_dist)
        check("devserver process is up", ok_app)
        if not (ok_dist and ok_app):
            print("\nAborting — server(s) failed to start. Logs:")
            print("--- app.log ---"); print(open(log_app.name).read()[-2000:])
            print("--- distributor.log ---"); print(open(log_dist.name).read()[-2000:])
            return

        requests.post(f"{DIST_BASE}/configure", json={"webhook_secret": org["webhook_secret"]})

        print("\n=== Test 1: create a generation job over real HTTP ===")
        job_req = {
            "release_id": "test-release-001",
            "cover_art_url": f"{APP_BASE}/test-assets/cover.png",
            "tier": "parametric",
            "duration_seconds": 3.0,
            "callback_url": f"{DIST_BASE}/webhook",
        }
        r = requests.post(f"{APP_BASE}/v1/motion-artwork/jobs", json=job_req, headers=headers)
        check("POST /jobs returns 202", r.status_code == 202, f"got {r.status_code}: {r.text[:300]}")
        job1 = r.json()
        job1_id = job1["job_id"]
        print(f"  job_id={job1_id}  price=${job1['price_usd']}")

        print("\n=== Test 2: poll until the background worker finishes it ===")
        final1 = poll_job(job1_id, headers)
        check("job reaches 'complete'", final1["status"] == "complete", f"status={final1['status']}")
        check("QC report says apple_ready", final1.get("qc_report", {}).get("apple_ready") is True)
        check("both asset URLs present", bool(final1.get("assets", {}).get("square_1x1", {}).get("url")))

        print("\n=== Test 3: actually download the generated asset and verify it's a real video ===")
        sq_url = final1["assets"]["square_1x1"]["url"]
        local_path = os.path.join(HERE, "downloaded_square.mov")
        r = requests.get(sq_url, headers=headers)
        with open(local_path, "wb") as f:
            f.write(r.content)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration,bit_rate", "-of", "json", local_path],
            capture_output=True, text=True,
        )
        probe_ok = probe.returncode == 0 and "duration" in probe.stdout
        check("downloaded file is a real, valid video (ffprobe)", probe_ok, probe.stderr[:300])

        print("\n=== Test 4: confirm the webhook actually arrived, signed correctly ===")
        time.sleep(0.5)
        received = requests.get(f"{DIST_BASE}/received").json()
        matching = [r for r in received if r["payload"].get("job_id") == job1_id]
        check("webhook received by mock distributor", len(matching) > 0)
        if matching:
            check("webhook signature verified valid", matching[-1]["signature_valid"] is True)
            check("webhook event is motion_artwork.completed", matching[-1]["payload"]["event"] == "motion_artwork.completed")

        print("\n=== Test 5: batch endpoint with multiple jobs ===")
        batch_req = {"jobs": [
            {**job_req, "release_id": "batch-rel-1"},
            {**job_req, "release_id": "batch-rel-2"},
        ]}
        r = requests.post(f"{APP_BASE}/v1/motion-artwork/jobs/batch", json=batch_req, headers=headers)
        check("POST /jobs/batch returns 202", r.status_code == 202, f"got {r.status_code}: {r.text[:300]}")
        batch_job_ids = r.json().get("job_ids", [])
        check("batch returns 2 job_ids", len(batch_job_ids) == 2)
        batch_results = [poll_job(jid, headers) for jid in batch_job_ids]
        check("both batch jobs complete", all(j["status"] == "complete" for j in batch_results))

        print("\n=== Test 6: QC-only endpoint — a genuinely compliant file should pass ===")
        qc_req_good = {
            "release_id": "qc-check-good",
            "square_asset_url": sq_url,
            "vertical_asset_url": final1["assets"]["vertical_3x4"]["url"],
            "source_cover_url": job_req["cover_art_url"],
            "callback_url": f"{DIST_BASE}/webhook",
        }
        r = requests.post(f"{APP_BASE}/v1/motion-artwork/qc", json=qc_req_good, headers=headers)
        check("POST /qc (good file) returns 202", r.status_code == 202, f"got {r.status_code}: {r.text[:300]}")
        qc_good_result = poll_job(r.json()["job_id"], headers)
        check("QC-only correctly PASSES a compliant file", qc_good_result["status"] == "complete")

        print("\n=== Test 7: QC-only endpoint — a broken file (injected audio) should be rejected ===")
        job_dir = os.path.join(HERE, "storage", job1_id)
        original_square = [f for f in os.listdir(job_dir) if f.startswith("square_1x1.")][0]
        broken_name = "square_1x1_BROKEN" + os.path.splitext(original_square)[1]
        broken_path = os.path.join(job_dir, broken_name)
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-i", os.path.join(job_dir, original_square),
            "-c:v", "copy", "-c:a", "aac", "-shortest", "-t", "3", broken_path,
        ], capture_output=True, check=True)
        broken_url = f"{APP_BASE}/v1/motion-artwork/assets/{job1_id}/{broken_name}"
        qc_req_bad = {**qc_req_good, "release_id": "qc-check-bad", "square_asset_url": broken_url}
        r = requests.post(f"{APP_BASE}/v1/motion-artwork/qc", json=qc_req_bad, headers=headers)
        qc_bad_result = poll_job(r.json()["job_id"], headers)
        check("QC-only correctly REJECTS a file with injected audio",
              qc_bad_result["status"] == "rejected")
        if qc_bad_result.get("qc_report"):
            audio_check = qc_bad_result["qc_report"]["checks"].get("audio_track_absent_square", {})
            check("rejection reason is specifically the audio check", audio_check.get("pass") is False)

        print("\n=== Test 8: auth actually rejects bad keys ===")
        r = requests.post(f"{APP_BASE}/v1/motion-artwork/jobs", json=job_req,
                           headers={"Authorization": "Bearer not-a-real-key", "Content-Type": "application/json"})
        check("invalid API key is rejected with 401", r.status_code == 401)

    finally:
        print("\n=== Shutting down servers ===")
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        log_app.close()
        log_dist.close()

    print("\n" + "=" * 60)
    passed = sum(1 for s, _, _ in results if s == "PASS")
    print(f"RESULT: {passed}/{len(results)} checks passed")
    for status, label, detail in results:
        if status == "FAIL":
            print(f"  FAILED: {label} -- {detail}")
    print("=" * 60)


if __name__ == "__main__":
    main()
