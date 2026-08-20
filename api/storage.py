"""
Cloudflare R2 asset storage. R2 is S3-API-compatible, so this uses boto3
pointed at the R2 endpoint — no egress fees on downloads, which matters
at catalog-backfill volume (Phase 5).
"""
import os
import hashlib
import boto3
from botocore.client import Config

R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.environ.get("R2_BUCKET", "motion-artwork")

_client = None


def _r2_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
    return _client


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_asset(local_path: str, key: str, public_base_url: str) -> dict:
    """Uploads and returns the metadata block the webhook payload expects."""
    client = _r2_client()
    checksum = sha256_of_file(local_path)
    client.upload_file(local_path, R2_BUCKET, key)
    return {
        "url": f"{public_base_url.rstrip('/')}/{key}",
        "checksum_sha256": checksum,
    }


def signed_download_url(key: str, expires_in: int = 3600) -> str:
    client = _r2_client()
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": R2_BUCKET, "Key": key}, ExpiresIn=expires_in
    )
