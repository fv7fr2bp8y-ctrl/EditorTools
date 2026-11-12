"""EditorTools Pro: monthly subscription (Stripe on the web).

A paying user gets a random token (kept in the browser's localStorage) that
maps to their Stripe subscription. Requests send it in the X-Pro-Token header;
the server checks the subscription in Stripe at most once per hour.
"""
import hashlib
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

import requests
from fastapi import APIRouter, HTTPException, Request

STRIPE_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
PRICE_ID = os.environ.get("PRO_PRICE_ID", "").strip()
SITE = os.environ.get("SITE_URL", "https://www.editortools.online").rstrip("/")
RECHECK_SECONDS = 3600
PLAY_PACKAGE = "editortools.online"
PLAY_PRODUCT = "editortools_pro_monthly"
PLAY_API = f"https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{PLAY_PACKAGE}"
PLAY_ACTIVE = {"SUBSCRIPTION_STATE_ACTIVE", "SUBSCRIPTION_STATE_IN_GRACE_PERIOD"}
_META_TOKEN = ("http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
               "?scopes=https://www.googleapis.com/auth/androidpublisher")
_gtoken = {"value": "", "exp": 0.0}
ACTIVE = {"active", "trialing", "past_due"}

router = APIRouter(prefix="/pro")
# Set by app.py to its anonymous analytics logger: on_event(request, name, extra=...)
on_event = lambda request, name, extra="": None
_lock = threading.Lock()
DB: Path = Path("pro.db")


def init(data_dir: Path) -> Path:
    global DB
    DB = data_dir / "pro.db"
    with sqlite3.connect(DB) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pro (
            token TEXT PRIMARY KEY, email TEXT, customer TEXT, subscription TEXT UNIQUE,
            status TEXT, period_end INTEGER, checked_at INTEGER, created_at INTEGER)""")
    return DB


def _stripe(method: str, path: str, **data) -> dict:
    if not STRIPE_KEY:
        raise HTTPException(503, "Плащанията още не са настроени.")
    r = requests.request(method, f"https://api.stripe.com/v1/{path}",
                         auth=(STRIPE_KEY, ""), data=data or None, timeout=20)
    if r.status_code >= 400:
        raise HTTPException(503, "Stripe отказа заявката.")
    return r.json()


def _sub_state(sub: dict) -> tuple[str, int]:
    end = sub.get("current_period_end") or max(
        (i.get("current_period_end") or 0 for i in sub.get("items", {}).get("data", [])), default=0)
    return sub.get("status", ""), int(end or 0)


def _google_auth() -> dict:
    """Cloud Run's own service account; it must be invited in Play Console for this app."""
    if time.time() > _gtoken["exp"] - 60:
        r = requests.get(_META_TOKEN, headers={"Metadata-Flavor": "Google"}, timeout=5)
        r.raise_for_status()
        j = r.json()
        _gtoken["value"], _gtoken["exp"] = j["access_token"], time.time() + int(j.get("expires_in", 300))
    return {"Authorization": f"Bearer {_gtoken['value']}"}


def _verify_play(purchase_token: str) -> tuple[str, int] | None:
    """Look up a Google Play subscription; acknowledge it if needed. None = not ours / invalid."""
    r = requests.get(f"{PLAY_API}/purchases/subscriptionsv2/tokens/{purchase_token}",
                     headers=_google_auth(), timeout=20)
    if r.status_code in (400, 404, 410):
        return None
    if r.status_code >= 400:
        print(f"[pro] Google Play lookup {r.status_code}: {r.text[:200]}", flush=True)
        raise HTTPException(503, "Google Play не отговори.")
    p = r.json()
    item = (p.get("lineItems") or [{}])[0]
    if item.get("productId") != PLAY_PRODUCT:
        return None
    expiry = item.get("expiryTime") or ""
    end = 0
    if expiry:
        from datetime import datetime
        end = int(datetime.fromisoformat(expiry.replace("Z", "+00:00")).timestamp())
    state = p.get("subscriptionState", "")
    active = state in PLAY_ACTIVE or (state == "SUBSCRIPTION_STATE_CANCELED" and end > time.time())
    if active and p.get("acknowledgementState") != "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED":
        requests.post(f"{PLAY_API}/purchases/subscriptions/{PLAY_PRODUCT}/tokens/{purchase_token}:acknowledge",
                      headers=_google_auth(), json={}, timeout=20)
    return ("active" if active else "canceled"), end


def _row(token: str):
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        return db.execute("SELECT * FROM pro WHERE token=?", (token,)).fetchone()


def is_pro(token: str | None) -> bool:
    """True if the token belongs to an active subscription (rechecked hourly)."""
    if not token or len(token) > 80:
        return False
    row = _row(token)
    if not row:
        return False
    now = int(time.time())
    if now - (row["checked_at"] or 0) > RECHECK_SECONDS:
        try:
            if row["subscription"].startswith("play:"):
                res = _verify_play(row["customer"])
                status, end = res if res else ("canceled", 0)
            else:
                status, end = _sub_state(_stripe("GET", f"subscriptions/{row['subscription']}"))
            with _lock, sqlite3.connect(DB) as db:
                db.execute("UPDATE pro SET status=?, period_end=?, checked_at=? WHERE token=?",
                           (status, end, now, token))
            return status in ACTIVE
        except (HTTPException, requests.RequestException):
            pass  # Stripe or Google unreachable: trust the stored state
    return row["status"] in ACTIVE


@router.post("/checkout")
async def checkout(request: Request):
    if not PRICE_ID:
        raise HTTPException(503, "Плащанията още не са настроени.")
    lang = request.query_params.get("lang", "bg")
    s = _stripe("POST", "checkout/sessions",
                mode="subscription",
                **{"line_items[0][price]": PRICE_ID, "line_items[0][quantity]": 1},
                success_url=f"{SITE}/?pro_session={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{SITE}/?pro_cancel=1",
                locale="bg" if lang == "bg" else "auto",
                allow_promotion_codes="true")
    on_event(request, "pro_checkout_start", extra="stripe")
    return {"url": s["url"]}


@router.get("/claim")
async def claim(request: Request, session_id: str):
    """After Stripe Checkout: turn a paid session into a Pro token (idempotent)."""
    if not session_id.startswith("cs_"):
        raise HTTPException(400, "Невалидна сесия.")
    s = _stripe("GET", f"checkout/sessions/{session_id}")
    if s.get("status") != "complete" or not s.get("subscription"):
        raise HTTPException(402, "Плащането не е завършено.")
    sub_id = s["subscription"]
    status, end = _sub_state(_stripe("GET", f"subscriptions/{sub_id}"))
    email = (s.get("customer_details") or {}).get("email", "")
    now = int(time.time())
    with _lock, sqlite3.connect(DB) as db:
        row = db.execute("SELECT token FROM pro WHERE subscription=?", (sub_id,)).fetchone()
        token = row[0] if row else secrets.token_urlsafe(24)
        db.execute("""INSERT INTO pro (token,email,customer,subscription,status,period_end,checked_at,created_at)
                      VALUES (?,?,?,?,?,?,?,?)
                      ON CONFLICT(subscription) DO UPDATE SET status=excluded.status,
                      period_end=excluded.period_end, checked_at=excluded.checked_at""",
                   (token, email, s.get("customer"), sub_id, status, end, now, now))
    if not row:  # count each subscription once, not every reload of the success page
        on_event(request, "pro_paid", extra="stripe")
    return {"token": token, "email": email, "active": status in ACTIVE, "period_end": end}


@router.get("/status")
async def status(request: Request):
    token = request.headers.get("x-pro-token", "")
    active = is_pro(token)
    row = _row(token) if token else None
    return {"active": active,
            "email": row["email"] if row else "",
            "period_end": row["period_end"] if row else 0}


@router.post("/portal")
async def portal(request: Request):
    """Stripe customer portal: cancel, change card, invoices."""
    row = _row(request.headers.get("x-pro-token", ""))
    if not row:
        raise HTTPException(404, "Няма абонамент.")
    s = _stripe("POST", "billing_portal/sessions", customer=row["customer"], return_url=f"{SITE}/")
    return {"url": s["url"]}


@router.post("/play/claim")
async def play_claim(request: Request):
    """Inside the Android app: turn a Google Play purchase into a Pro token (idempotent)."""
    body = await request.json()
    purchase_token = str(body.get("purchaseToken", ""))[:600]
    if not purchase_token:
        raise HTTPException(400, "Няма покупка.")
    res = _verify_play(purchase_token)
    if not res:
        raise HTTPException(402, "Покупката не е потвърдена от Google Play.")
    status, end = res
    sub_id = "play:" + hashlib.sha256(purchase_token.encode()).hexdigest()
    now = int(time.time())
    with _lock, sqlite3.connect(DB) as db:
        row = db.execute("SELECT token FROM pro WHERE subscription=?", (sub_id,)).fetchone()
        token = row[0] if row else secrets.token_urlsafe(24)
        db.execute("""INSERT INTO pro (token,email,customer,subscription,status,period_end,checked_at,created_at)
                      VALUES (?,?,?,?,?,?,?,?)
                      ON CONFLICT(subscription) DO UPDATE SET status=excluded.status,
                      period_end=excluded.period_end, checked_at=excluded.checked_at""",
                   (token, "", purchase_token, sub_id, status, end, now, now))
    if not row and status in ACTIVE:
        on_event(request, "pro_paid", extra="play")
    return {"token": token, "active": status in ACTIVE, "period_end": end}
