"""
Webhook delivery with HMAC signing (so distributors can verify a callback
really came from us) and exponential backoff retry. This module implements
one delivery attempt; scheduling retries is the caller's job (tasks.py),
since retries need to survive worker restarts via the webhook_deliveries table
rather than living in an in-process sleep loop.
"""
import hmac
import hashlib
import json
import httpx

RETRY_SCHEDULE_SECONDS = [30, 120, 600, 1800, 7200]  # ~5 attempts over ~2.5 hours


def sign_payload(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def send_webhook(url: str, payload: dict, signing_secret: str, timeout_s: float = 10.0) -> tuple[bool, str]:
    body = json.dumps(payload).encode("utf-8")
    signature = sign_payload(body, signing_secret)
    headers = {
        "Content-Type": "application/json",
        "X-Motion-Artwork-Signature": f"sha256={signature}",
    }
    try:
        resp = httpx.post(url, content=body, headers=headers, timeout=timeout_s)
        if 200 <= resp.status_code < 300:
            return True, ""
        return False, f"HTTP {resp.status_code}: {resp.text[:500]}"
    except httpx.RequestError as e:
        return False, f"request error: {e}"


def next_retry_delay(attempt: int) -> int | None:
    """attempt is 1-indexed (this call is scheduling the Nth retry)."""
    if attempt - 1 < len(RETRY_SCHEDULE_SECONDS):
        return RETRY_SCHEDULE_SECONDS[attempt - 1]
    return None  # exhausted — mark delivery as permanently failed
