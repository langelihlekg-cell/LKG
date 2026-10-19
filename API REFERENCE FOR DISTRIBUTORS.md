# Motion Canvas API Reference

For distributors, labels, and platforms integrating motion artwork generation
directly into a release workflow.

**Building a music, podcast, or audio app instead of a distributor?** The
same API and the same two deliverables (1:1 and 3:4) now also power iOS
26's `MPMediaItemAnimatedArtwork` — animated Now Playing/lock-screen art
for *any* app, not just Apple Music. See
`IOS26_ANIMATED_ARTWORK_OPPORTUNITY.md` for the exact spec and a working
integration example.

**Base URL:** your deployment's address (e.g. `https://api.motioncanvas.example.com`)
**Auth:** every request needs `Authorization: Bearer <your_api_key>`

---

## Create a motion artwork job

```
POST /v1/motion-artwork/jobs
```

**Request body**
```json
{
  "release_id": "release_123",
  "artist_id": "artist_456",
  "cover_art_url": "https://.../cover.png",
  "tier": "parametric",
  "duration_seconds": 12,
  "callback_url": "https://yourservice.com/webhooks/motion-canvas"
}
```

| Field | Required | Notes |
|---|---|---|
| `release_id` | yes | Your own identifier — passed through untouched, never interpreted. |
| `artist_id` | no | Same — pass-through only. |
| `cover_art_url` | yes | Must be publicly fetchable, minimum 3000×3000px source recommended. |
| `tier` | no (default `parametric`) | `parametric`, `stylized`, or `cinematic` — see **Tiers** below. |
| `platform` | no (default `apple`) | `apple` (square + vertical pair) or `spotify_canvas` (single 9:16 file) — see **Platforms** below. |
| `duration_seconds` | no (default 12) | 8–35, per Apple's spec. |
| `callback_url` | yes | Where the completion webhook is sent. |

**Response — `202 Accepted`**
```json
{
  "job_id": "9b0f9a6d-c172-48c1-aaad-e7f2d7f272f3",
  "status": "queued",
  "estimated_completion_seconds": 20,
  "tier": "parametric",
  "price_usd": 4.00
}
```

---

## Check job status

```
GET /v1/motion-artwork/jobs/{job_id}
```

**Response**
```json
{
  "job_id": "9b0f9a6d-...",
  "status": "complete",
  "qc_report": { "passed": true, "apple_ready": true, "checks": { "...": "..." } },
  "assets": {
    "square_1x1": { "url": "https://.../square_1x1.mp4" },
    "vertical_3x4": { "url": "https://.../vertical_3x4.mp4" },
    "preview_url": "https://.../preview/9b0f9a6d-..."
  }
}
```

`status` moves through: `queued` → `processing` → `qc_review` → one of
`complete`, `rejected`, or `failed`. A `rejected` job means the render did
not pass Apple's technical requirements and was not handed over — that's
the system working correctly, not an error on your end.

---

## Batch submission (catalog backfills)

```
POST /v1/motion-artwork/jobs/batch
```
Same job shape, submitted as a list under `"jobs"` — up to 5,000 per call.
```json
{ "jobs": [ { "release_id": "...", "cover_art_url": "...", "...": "..." } ] }
```
Returns `{ "batch_id": "...", "job_ids": ["...", "..."] }` — poll each
`job_id` individually, or wait for their webhooks.

---

## QC-only (validate assets made elsewhere)

```
POST /v1/motion-artwork/qc
```
Runs the same compliance checks against files you already have — no
rendering, no commitment to switching who makes your motion artwork.
```json
{
  "release_id": "release_123",
  "square_asset_url": "https://.../square.mp4",
  "vertical_asset_url": "https://.../vertical.mp4",
  "source_cover_url": "https://.../cover.png",
  "callback_url": "https://yourservice.com/webhooks/motion-canvas"
}
```
Flat $0.10 per check, same status lifecycle as above.

---

## Webhooks

Fired once, when a job reaches `complete`, `rejected`, or `failed`.

```json
{
  "event": "motion_artwork.completed",
  "job_id": "9b0f9a6d-...",
  "release_id": "release_123",
  "status": "complete",
  "assets": { "...": "..." },
  "qc_report": { "...": "..." },
  "billing": { "price_usd": 4.00 }
}
```

Every delivery includes an `X-Motion-Artwork-Signature: sha256=<hex>`
header — an HMAC-SHA256 of the raw request body, signed with your org's
webhook secret. Verify it before trusting a payload:

```python
import hmac, hashlib

def verify(request_body: bytes, signature_header: str, webhook_secret: str) -> bool:
    expected = hmac.new(webhook_secret.encode(), request_body, hashlib.sha256).hexdigest()
    got = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, got)
```

---

## Platforms

| `platform` | Deliverable | Default length | Asset keys in the response |
|---|---|---|---|
| `apple` (default) | Square 1:1 + vertical 3:4, checked against Apple's Album Motion rules | 12s | `square_1x1`, `vertical_3x4`, `preview_url` |
| `spotify_canvas` | One 9:16 vertical loop, 3-8s, no audio | 6s | `canvas_9x16`, `preview_url` |

The same three tiers (`parametric` / `stylized` / `cinematic`) work on either
platform, and the Apple pair is also the right asset set for iOS 26's
`MPMediaItemAnimatedArtwork` (see `IOS26_ANIMATED_ARTWORK_OPPORTUNITY.md`).
Canvas jobs are currently billed at the same per-tier price as Apple jobs.
Canvas limits come from published third-party guides and should be
re-checked against Spotify for Artists before you rely on exact numbers.

## Tiers

| Tier | Price | What it does |
|---|---|---|
| `parametric` | $4 | Subtle depth-based parallax — the cover pans/dollies gently over an estimated depth map. |
| `stylized` | $14 | Parametric motion plus film grain, vignette, and a warm/cool split-tone grade. |
| `cinematic` | $25 | Stylized look plus real depth-of-field blur (foreground stays sharp, background falls away) and a more pronounced camera move. |

All three are genuinely different renders, not the same output at three
prices — pick based on how much visual treatment you want, not just budget.

---

## Errors

Standard HTTP status codes. `401` = missing/invalid API key. `404` = job
not found (or belongs to a different org). `422` = malformed request body.
`400` on `/jobs/batch` = empty list or over the 5,000 cap.
