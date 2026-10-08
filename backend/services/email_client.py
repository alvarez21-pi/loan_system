import base64
import os
import time

import requests

import branding


def _company_block():
    """The branding block sent with EVERY email-service request — all of
    it static (branding.py); the logo is base64-inlined so PHPMailer can
    embed it with a `cid:` reference, never a separate fetch the
    recipient's mail client might block. Never raises: a problem building
    this must never block an email from sending — it just goes out with
    the service's own PHP-side fallback defaults instead.
    """
    try:
        block = {
            "name": branding.COMPANY_NAME,
            "primary_color": branding.PRIMARY_COLOR,
            "accent_color": branding.ACCENT_COLOR,
            "navy_color": branding.NAVY_COLOR,
            "footer_text": branding.FOOTER_TEXT,
            "address": branding.COMPANY_ADDRESS or None,
            "phone": branding.COMPANY_PHONE or None,
            "email": branding.COMPANY_EMAIL or None,
        }
        # LOGO_URL (e.g. https://app.example.com/logo.png, served statically
        # by the frontend) lets the logo be a plain <img src>, never an
        # attachment — avoids a payslip email carrying two attachments (its
        # PDF, plus the logo). Falls back to the base64/CID embed below when
        # LOGO_URL isn't set, exactly as before.
        logo_url = os.getenv("LOGO_URL") or None
        block["logo_url"] = logo_url
        if not logo_url:
            logo = branding.logo_bytes()
            if logo:
                block["logo_base64"] = base64.b64encode(logo).decode("ascii")
                block["logo_mime"] = "image/png"
        return block
    except Exception:
        return {}


def send_email(email_type, to, data, retries=2, backoff_seconds=0.5):
    """POST to the email-service. Retries a small, bounded number of times on
    a transient CONNECTION failure only (e.g. the email-service container
    isn't accepting connections yet right after a fresh `docker compose up`
    — Part 3's race condition) — never on a real application-level failure
    (a non-2xx response, a bad payload), which is returned as-is so the
    caller can log it, not retried into a different kind of silence.
    """
    url = os.getenv("EMAIL_SERVICE_URL", "http://email-service:80/index.php")
    headers = {"X-Internal-Secret": os.getenv("EMAIL_SERVICE_SECRET")}
    payload = {"type": email_type, "to": to, "data": data, "company": _company_block()}
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
        except requests.ConnectionError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(backoff_seconds * (attempt + 1))
                continue
            return {"error": str(exc)}
        except requests.RequestException as exc:
            return {"error": str(exc)}
        try:
            return response.json()
        except ValueError as exc:
            return {"error": str(exc)}
    return {"error": str(last_error) if last_error else "unknown error"}
