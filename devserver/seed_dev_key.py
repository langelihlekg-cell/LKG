#!/usr/bin/env python3
"""
Creates a dev org + API key so you can test the API by hand (with curl, or
a tool like Postman) instead of only through live_demo.py.

Run once, with the server stopped or running (either is fine):
    python3 devserver/seed_dev_key.py

The raw key is only ever shown here -- the database stores just a hash of
it, the same way a real production system would. Copy it somewhere before
closing the terminal.
"""
import sys
import os
import hashlib
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

if __name__ == "__main__":
    db.init_db(fresh=False)  # creates tables if missing; leaves existing data alone
    org = db.create_org("Manual Test Org")
    raw_key = uuid.uuid4().hex + uuid.uuid4().hex
    db.create_api_key(org["id"], hashlib.sha256(raw_key.encode()).hexdigest())
    print(f"Org created: {org['id']}")
    print("Your API key (copy this now -- it will not be shown again):")
    print(raw_key)
