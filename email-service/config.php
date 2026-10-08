<?php

define('SMTP_HOST', getenv('SMTP_HOST') ?: '');
define('SMTP_USERNAME', getenv('SMTP_USERNAME') ?: '');
define('SMTP_PASSWORD', getenv('SMTP_PASSWORD') ?: '');
define('SMTP_PORT', (int) (getenv('SMTP_PORT') ?: 587));
define('SMTP_ENCRYPTION', strtolower(getenv('SMTP_ENCRYPTION') ?: 'tls'));
define('FROM_EMAIL', getenv('FROM_EMAIL') ?: '');
// Fallback only — used if the backend's per-request "company" block
// (branding.py's values) is ever missing or incomplete. Kept in sync by
// hand with backend/branding.py and frontend/src/branding.ts.
define('FROM_NAME', getenv('FROM_NAME') ?: 'EJM Financial Services Company Limited');
define('COMPANY_NAME', getenv('COMPANY_NAME') ?: 'EJM Financial Services Company Limited');
define('DEFAULT_PRIMARY_COLOR', '#029105');
define('DEFAULT_ACCENT_COLOR', '#F89800');
define('DEFAULT_NAVY_COLOR', '#001058');
define('DEFAULT_FOOTER_TEXT', 'This document is confidential and intended solely for the addressee.');
