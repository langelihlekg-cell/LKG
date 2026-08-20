import hmac
import hashlib


def sign_payload(body_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


def verify_signature(body_bytes: bytes, secret: str, signature_header: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = sign_payload(body_bytes, secret)
    got = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, got)
