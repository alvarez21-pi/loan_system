"""The ONE place the company's identity lives in this app (Python side).

A different client later means editing the values below and swapping
assets/ejm_logo.png — nothing else. This deliberately replaces the old
database-backed "Company Settings" branding fields (name/logo/colours/
footer), which made every PDF, payslip, Excel export and email template
depend on an admin having filled in a form correctly. Every one of those
surfaces now imports straight from here.

Colour roles (used consistently everywhere this feeds):
  PRIMARY_COLOR  - main header/band colour on PDFs, payslips, Excel headers
                   and the email header bar.
  ACCENT_COLOR   - buttons, rules, highlights (PDF totals-row rule, email
                   call-to-action buttons).
  NAVY_COLOR     - the email footer bar and anywhere a darker, more formal
                   tone is wanted. Not currently used by the PDF/Excel
                   surfaces, which only have a primary/accent pair.
"""
import os

COMPANY_NAME = "EJM Financial Services Company Limited"

PRIMARY_COLOR = "#029105"  # green
ACCENT_COLOR = "#F89800"   # orange
NAVY_COLOR = "#001058"     # navy

# EDIT ME: replace with the real line you want at the bottom of every PDF,
# payslip and email (registered office, licence number, disclaimer, etc.)
# — never repeat the company name here, every surface that uses this
# already shows COMPANY_NAME once on its own.
FOOTER_TEXT = "This document is confidential and intended solely for the addressee."

LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "ejm_logo.png")

# --------------------------------------------------------------------------
# Operational settings — previously a database-backed "Company Settings"
# page; moved here so nothing about money rules or contact details is
# editable from the UI. Changing any of these only ever means editing this
# file (and redeploying), never a database write.
# --------------------------------------------------------------------------

# Fixed company contact details — shown on PDFs and in every email footer
# (as the Reply-To address, never a staff member's own login email, e.g.
# the CEO's). EDIT ME with the real values.
COMPANY_ADDRESS = ""  # EDIT ME: registered office address, if you want it on PDFs/emails
COMPANY_PHONE = "+255 700 000 000"  # EDIT ME: contact phone shown on PDFs/emails
COMPANY_EMAIL = "info@ejmfinancial.co.tz"  # EDIT ME: contact email shown on PDFs/emails and used as email Reply-To

# Default instalment-rounding step (whole shillings) for a NEW loan — an
# existing loan always keeps its own already-stored step regardless of this.
DEFAULT_ROUNDING_STEP = 1000


def logo_bytes():
    """Returns the logo file's raw bytes, or None if it's ever missing —
    callers must degrade gracefully (no logo on the page/email) rather than
    fail the whole document/send."""
    try:
        with open(LOGO_PATH, "rb") as handle:
            return handle.read()
    except OSError:
        return None
