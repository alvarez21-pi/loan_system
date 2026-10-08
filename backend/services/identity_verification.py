"""Borrower ID verification — a plug point, not a working integration.

There is no official NIDA/NIN verification API access configured for this
project yet, and unofficial scrapers are deliberately not used (they violate
NIDA's terms and are unreliable). verify_nin() is the seam a real, licensed
provider gets wired into later: swap its body for an HTTP call and it slots
straight into borrower creation/detail without touching any caller.

16-part-v2 Part 6.2: the verification UI (button, status) is only ever shown
when a provider is actually configured — never a permanent "not configured"
message sitting on every borrower's page. Flip PROVIDER_CONFIGURED to True
(and give verify_nin() a real body) once a real provider is wired in.
"""

PROVIDER_CONFIGURED = False


def is_configured():
    return PROVIDER_CONFIGURED


def verify_nin(id_number, id_type="nida"):
    """Attempt to verify a borrower's ID against an official source.

    Returns a dict always shaped {"status": ..., ...}. Today it always reports
    "not_configured" — the UI shows "Verification not configured" rather than
    a false positive or a broken-looking error.
    """
    return {
        "status": "not_configured",
        "message": "ID verification is not configured yet. Add a licensed NIDA/KYC provider here to enable it.",
    }


def normalize_nida(raw):
    """Strip dashes/spaces from a NIDA number for storage. Does not validate
    length — the 20-digit format is shown as a soft warning only, never
    enforced, since it has not been confirmed against real cards yet."""
    return "".join(ch for ch in str(raw or "") if ch.isalnum())
