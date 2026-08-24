"""
Stands in for a distributor's webhook receiver so the full delivery loop —
including HMAC signature verification — can be exercised for real, not just
asserted in code. Run standalone: python3 devserver/mock_distributor.py [port]
"""
import sys
import json
from flask import Flask, request, jsonify

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from webhook_utils import verify_signature

app = Flask(__name__)
RECEIVED = []
WEBHOOK_SECRET = None  # set via /configure before use


@app.get("/")
def index():
    return """
    <html><body style="font-family:sans-serif;background:#111;color:#eee;padding:2rem">
    <h3>This is the mock distributor, not the real API.</h3>
    <p>It exists only so <code>live_demo.py</code> can test webhook delivery.
    The actual API you want is on port <b>9000</b>, not this one.</p>
    <p>See received webhooks: <a href="/received" style="color:#8cf">/received</a></p>
    </body></html>
    """


@app.post("/configure")
def configure():
    global WEBHOOK_SECRET
    WEBHOOK_SECRET = request.json["webhook_secret"]
    return jsonify({"ok": True})


@app.post("/webhook")
def webhook():
    body = request.get_data()
    sig = request.headers.get("X-Motion-Artwork-Signature", "")
    valid = verify_signature(body, WEBHOOK_SECRET or "", sig) if WEBHOOK_SECRET else False
    payload = request.get_json()
    RECEIVED.append({"payload": payload, "signature_valid": valid, "signature_header": sig})
    print(f"[mock_distributor] received {payload.get('event')} for job {payload.get('job_id')} "
          f"(signature_valid={valid})", flush=True)
    return jsonify({"ok": True}), 200


@app.get("/received")
def received():
    return jsonify(RECEIVED)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9001
    app.run(host="127.0.0.1", port=port, threaded=True)
