import hashlib
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session
from .db import get_db
from .models import ApiKey, Org


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def get_current_org(
    authorization: str = Header(..., description="Bearer <api_key>"),
    db: Session = Depends(get_db),
) -> Org:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="expected 'Bearer <api_key>'")
    raw_key = authorization[len("Bearer "):].strip()
    key_hash = hash_key(raw_key)

    api_key = (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        .first()
    )
    if api_key is None:
        raise HTTPException(status_code=401, detail="invalid or revoked API key")

    org = db.query(Org).filter(Org.id == api_key.org_id).first()
    if org is None:
        raise HTTPException(status_code=401, detail="org not found for key")
    return org
