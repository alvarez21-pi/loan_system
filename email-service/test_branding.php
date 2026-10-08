<?php
/**
 * Phase 4: a small, dependency-free check (no PHPUnit — nothing else in
 * this service has a test framework, and adding one just for this would be
 * a new dependency for a handful of assertions) that the email templates
 * actually use the dynamic company block Email::setCompany() receives,
 * instead of a hardcoded name/colour (F-16/F-17). Run with:
 *   php test_branding.php
 * Exits non-zero with a message on the first failure.
 */

require_once __DIR__ . '/src/Email.php';

$failures = 0;

function check(bool $ok, string $message): void
{
    global $failures;
    if ($ok) {
        echo "  OK: $message\n";
    } else {
        echo "  FAIL: $message\n";
        $failures++;
    }
}

function call_private(string $method, ...$args)
{
    $reflection = new ReflectionMethod(Email::class, $method);
    $reflection->setAccessible(true);
    return $reflection->invoke(null, ...$args);
}

echo "F-17 regression: the verification email's source must never hardcode\n";
echo "the old product name bypassing the company name.\n";
$source = file_get_contents(__DIR__ . '/src/Email.php');
check(
    !str_contains($source, "Verify your Loan Management System"),
    "Email.php source no longer hardcodes 'Verify your Loan Management System'"
);
check(
    str_contains($source, 'self::companyName()'),
    'sendVerificationEmail() builds its body from the dynamic company name'
);

echo "\nDynamic company block (name, colours, footer line, contacts, reply-to):\n";
Email::setCompany([
    'name' => 'Acme Test Co',
    'primary_color' => '#112233',
    'accent_color' => '#445566',
    'navy_color' => '#778899',
    'footer_text' => 'Acme-only confidential footer line.',
    'address' => '123 Test Street',
    'phone' => '+255700000000',
    'email' => 'contact@acmetest.example',
]);

$header = call_private('header', 'Subtitle');
check(str_contains($header, 'Acme Test Co'), 'header shows the dynamic company name');
check(str_contains($header, '#112233'), 'header background uses the dynamic primary colour');
check(!str_contains($header, 'EJM Financial Services Company Limited'), 'header no longer shows the default name once one is set');

$footer = call_private('footer');
check(str_contains($footer, 'Acme Test Co'), 'footer shows the dynamic company name');
check(str_contains($footer, '#778899'), 'footer background uses the dynamic navy colour');
check(str_contains($footer, '123 Test Street'), 'footer shows the dynamic address');
check(str_contains($footer, 'contact@acmetest.example'), "footer's contact link uses the dynamic reply-to email");
check(str_contains($footer, 'Acme-only confidential footer line.'), 'footer shows the dynamic footer text line');

$button = call_private('button', 'Click me', 'https://example.test');
check(str_contains($button, '#445566'), 'button uses the dynamic accent colour');

$box = call_private('referenceBox', 'LOAN-123');
check(str_contains($box, '#112233') && str_contains($box, '#445566'), 'reference box uses both dynamic colours');

echo "\nFallback when no company block is sent:\n";
Email::setCompany([]);
$fallbackHeader = call_private('header', null);
check(str_contains($fallbackHeader, COMPANY_NAME), 'falls back to the generic COMPANY_NAME constant');
check(str_contains($fallbackHeader, DEFAULT_PRIMARY_COLOR), 'falls back to the generic default primary colour');
$fallbackFooter = call_private('footer');
check(str_contains($fallbackFooter, DEFAULT_NAVY_COLOR), 'falls back to the generic default navy colour');
check(str_contains($fallbackFooter, DEFAULT_FOOTER_TEXT), 'falls back to the generic default footer text');

echo "\n";
if ($failures > 0) {
    echo "$failures check(s) FAILED.\n";
    exit(1);
}
echo "All email branding checks passed.\n";
