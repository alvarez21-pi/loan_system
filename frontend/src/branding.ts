/**
 * The ONE place the company's identity lives on the frontend. A different
 * client later means editing the values below and swapping
 * src/assets/ejm_logo.png — nothing else. Mirrors backend/branding.py;
 * keep the two in sync by hand (they're read by two different runtimes
 * and can't share a single file).
 */
import logo from "./assets/ejm_logo.png";

export const COMPANY_NAME = "EJM Financial Services Company Limited";

export const PRIMARY_COLOR = "#029105"; // green
export const ACCENT_COLOR = "#F89800"; // orange
export const NAVY_COLOR = "#001058"; // navy

// EDIT ME: replace with the real line you want in the app footer/about area
// — never repeat the company name, COMPANY_NAME is already shown once.
export const FOOTER_TEXT = "This document is confidential and intended solely for the addressee.";

export const LOGO_URL = logo;
