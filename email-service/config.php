<?php

define('SMTP_HOST', getenv('SMTP_HOST') ?: '');
define('SMTP_USERNAME', getenv('SMTP_USERNAME') ?: '');
define('SMTP_PASSWORD', getenv('SMTP_PASSWORD') ?: '');
define('SMTP_PORT', (int) (getenv('SMTP_PORT') ?: 587));
define('SMTP_ENCRYPTION', strtolower(getenv('SMTP_ENCRYPTION') ?: 'tls'));
define('FROM_EMAIL', getenv('FROM_EMAIL') ?: '');
define('FROM_NAME', getenv('FROM_NAME') ?: 'Loan Management System');
define('COMPANY_NAME', getenv('COMPANY_NAME') ?: 'Loan Management System');
