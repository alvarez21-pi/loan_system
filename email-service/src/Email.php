<?php

use PHPMailer\PHPMailer\Exception;
use PHPMailer\PHPMailer\PHPMailer;

require_once __DIR__ . '/../vendor/autoload.php';
require_once __DIR__ . '/../config.php';

final class Email
{
    /**
     * The per-request branding block the backend sends with every email
     * (name, colours, footer line, address/phone/email, logo) — sourced
     * from backend/branding.py, which is static. Set once per request
     * (index.php calls Email::setCompany() before dispatching) and read by
     * every template below instead of a hardcoded constant/colour — falls
     * back to config.php's own defaults only if a field is ever missing.
     */
    private static array $company = [];

    public static function setCompany(array $company): void
    {
        self::$company = $company;
    }

    private static function companyName(): string
    {
        return trim((string) (self::$company['name'] ?? '')) !== '' ? self::$company['name'] : COMPANY_NAME;
    }

    private static function primaryColor(): string
    {
        return self::$company['primary_color'] ?? DEFAULT_PRIMARY_COLOR;
    }

    private static function accentColor(): string
    {
        return self::$company['accent_color'] ?? DEFAULT_ACCENT_COLOR;
    }

    private static function navyColor(): string
    {
        return self::$company['navy_color'] ?? DEFAULT_NAVY_COLOR;
    }

    private static function footerLine(): string
    {
        $text = trim((string) (self::$company['footer_text'] ?? ''));
        return $text !== '' ? $text : DEFAULT_FOOTER_TEXT;
    }

    private static function replyToEmail(): string
    {
        $email = trim((string) (self::$company['email'] ?? ''));
        return $email !== '' ? $email : FROM_EMAIL;
    }

    private static function contactLine(): string
    {
        $parts = array_filter([
            self::$company['address'] ?? null,
            self::$company['phone'] ?? null,
            self::$company['email'] ?? null,
        ], static fn ($v) => is_string($v) && trim($v) !== '');
        return implode(' &middot; ', array_map('htmlspecialchars', $parts));
    }

    /** A plain, externally-hosted logo URL (LOGO_URL) — when set, the logo
     * is a normal <img src>, never an attachment (e.g. so a payslip email
     * carries only its one real attachment, the PDF). */
    private static function logoUrl(): ?string
    {
        $url = trim((string) (self::$company['logo_url'] ?? ''));
        return $url !== '' ? $url : null;
    }

    /** Fallback only, when there's no logoUrl(): embedded as a real CID
     * attachment at send() time, so it isn't blocked as external content
     * by the recipient's mail client. */
    private static function hasLogo(): bool
    {
        return self::logoUrl() === null && !empty(self::$company['logo_base64']);
    }

    private static function shell(string $body): string
    {
        // Single column, max 600px, table-based, inline CSS throughout
        // (Gmail/Outlook strip <style> blocks) — readable on a phone
        // without zooming. The viewport meta tag is honoured by iOS/Apple
        // Mail; clients that ignore it still render fine because every
        // width below is already a fixed, mobile-safe pixel value.
        return '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>'
            . '<body style="margin:0;background:#f2f5f8;font-family:Arial,Helvetica,sans-serif;color:#203040">'
            . '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:24px 0"><tr><td align="center">'
            // width="100%" (not a fixed px) + max-width:600px — fluid, so it
            // shrinks to fit a 360-390px phone screen instead of forcing
            // horizontal scroll, and caps at 600px on desktop.
            . '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="width:100%;max-width:600px;background:#fff">'
            . $body . '</table></td></tr></table></body></html>';
    }

    private static function header(?string $subtitle = null): string
    {
        $sub = $subtitle ? '<div style="margin-top:6px;color:#dcecff;font-size:13px">' . htmlspecialchars($subtitle) . '</div>' : '';
        $logoSrc = self::logoUrl() ? htmlspecialchars((string) self::logoUrl()) : (self::hasLogo() ? 'cid:company-logo' : null);
        $logo = $logoSrc
            ? '<img src="' . $logoSrc . '" alt="" height="32" style="vertical-align:middle;margin-right:10px;display:inline-block">'
            : '';
        $color = htmlspecialchars(self::primaryColor());
        return '<tr><td style="background:' . $color . ';padding:24px 24px;color:#fff">' . $logo . '<strong style="font-size:20px;vertical-align:middle">' . htmlspecialchars(self::companyName()) . '</strong>' . $sub . '</td></tr>';
    }

    private static function footer(): string
    {
        $color = htmlspecialchars(self::navyColor());
        $contact = self::contactLine();
        $contactHtml = $contact !== '' ? $contact . ' &middot; ' : '';
        $replyTo = htmlspecialchars(self::replyToEmail());
        $footerLine = htmlspecialchars(self::footerLine());
        return '<tr><td style="background:' . $color . ';padding:18px 24px;color:#fff;font-size:12px;line-height:1.5">'
            . htmlspecialchars(self::companyName()) . ' &middot; ' . $contactHtml
            . '<a href="mailto:' . $replyTo . '" style="color:#fff">Contact support</a>'
            . '<div style="margin-top:8px;color:#cfd6e4;font-size:11px">' . $footerLine . '</div>'
            . '</td></tr>';
    }

    private static function detailRow(string $label, string $value, bool $shade = false): string
    {
        $background = $shade ? '#f4f7fa' : '#fff';
        return '<tr style="background:' . $background . '"><td style="padding:11px 14px;font-weight:bold;width:38%">' . htmlspecialchars($label) . '</td><td style="padding:11px 14px">' . htmlspecialchars($value) . '</td></tr>';
    }

    private static function button(string $label, string $link): string
    {
        // A large, obviously-tappable button on a phone (~48px tall) —
        // table-based so Outlook's Word rendering engine doesn't collapse
        // the padding on an <a>.
        $color = htmlspecialchars(self::accentColor());
        $href = htmlspecialchars($link);
        $text = htmlspecialchars($label);
        return '<table role="presentation" cellspacing="0" cellpadding="0" style="margin:26px 0"><tr><td style="border-radius:6px;background:' . $color . '">'
            . '<a href="' . $href . '" style="display:inline-block;padding:16px 28px;font-size:16px;font-weight:bold;color:#fff;text-decoration:none;border-radius:6px">' . $text . '</a>'
            . '</td></tr></table>';
    }

    private static function referenceBox(string $reference): string
    {
        $accent = htmlspecialchars(self::accentColor());
        $primary = htmlspecialchars(self::primaryColor());
        return '<div style="background:#e9f2fb;border-left:5px solid ' . $accent . ';padding:18px;margin:20px 0;font-size:22px;font-weight:bold;color:' . $primary . '">' . htmlspecialchars($reference) . '</div>';
    }

    private static function htmlToText(string $html): string
    {
        return trim(html_entity_decode(preg_replace('/\s+/', ' ', strip_tags(str_replace(['</p>', '</tr>', '<br>', '<br/>'], "\n", $html)))));
    }

    private static function send(string $to, string $toName, string $subject, string $html, ?array $attachment = null): bool
    {
        $mail = new PHPMailer(true);
        try {
            // Without this PHPMailer defaults to iso-8859-1, which mangles
            // any non-ASCII character (an em dash in the footer text, an
            // accented name) into garbage in real mail clients.
            $mail->CharSet = PHPMailer::CHARSET_UTF8;
            $mail->isSMTP();
            $mail->Host = SMTP_HOST;
            // Local dev (Mailpit, SMTP_ENCRYPTION unset/"none"): no auth, no
            // TLS — Mailpit's SMTP listener offers neither. Production
            // (SMTP_ENCRYPTION=tls, SMTP_USERNAME set): unchanged, both stay on.
            $mail->SMTPAuth = SMTP_USERNAME !== '';
            $mail->Username = SMTP_USERNAME;
            $mail->Password = SMTP_PASSWORD;
            $mail->Port = SMTP_PORT;
            $mail->SMTPSecure = match (SMTP_ENCRYPTION) {
                'ssl' => PHPMailer::ENCRYPTION_SMTPS,
                'tls' => PHPMailer::ENCRYPTION_STARTTLS,
                default => '',
            };

            // Bypass SSL certificate verification issues in Docker containers
            $mail->SMTPOptions = [
                'ssl' => [
                    'verify_peer' => false,
                    'verify_peer_name' => false,
                    'allow_self_signed' => true,
                ],
            ];

            $mail->setFrom(FROM_EMAIL, self::companyName());
            // Phase 4: replies go to the company's own settings email, not
            // the (often no-reply) SMTP sending address.
            $mail->addReplyTo(self::replyToEmail(), self::companyName());
            $mail->addAddress($to, $toName);
            $mail->Subject = $subject;
            $mail->isHTML(true);
            $mail->Body = $html;
            $mail->AltBody = self::htmlToText($html);
            if (self::hasLogo()) {
                $logoBytes = base64_decode((string) self::$company['logo_base64'], true);
                if ($logoBytes !== false && $logoBytes !== '') {
                    $mime = self::$company['logo_mime'] ?? 'image/png';
                    $mail->addStringEmbeddedImage($logoBytes, 'company-logo', 'logo', PHPMailer::ENCODING_BASE64, $mime);
                }
            }
            if ($attachment !== null) {
                $mail->addStringAttachment($attachment['content'], $attachment['filename'], PHPMailer::ENCODING_BASE64, 'application/pdf');
            }
            return $mail->send();
        } catch (Exception $exception) {
            error_log('Email send failed: ' . $exception->getMessage() . ' | PHPMailer Info: ' . $mail->ErrorInfo);
            return false;
        }
    }

    public static function sendVerificationEmail(string $name, string $email, string $verifyLink): bool
    {
        // F-17: this used to hardcode "Loan Management System" directly,
        // bypassing the company name entirely even when every other
        // template used it correctly.
        $html = self::shell(self::header('Verify your account') . '<tr><td style="padding:24px"><p>Hello ' . htmlspecialchars($name) . ',</p><p>Verify your ' . htmlspecialchars(self::companyName()) . ' account to continue.</p>' . self::button('Verify account', $verifyLink) . '</td></tr>' . self::footer());
        return self::send($email, $name, 'Verify your account', $html);
    }

    public static function sendPasswordResetEmail(string $name, string $email, string $resetLink): bool
    {
        $html = self::shell(self::header('Password reset') . '<tr><td style="padding:24px"><p>Hello ' . htmlspecialchars($name) . ',</p><p>Use the link below to choose a new password. The link expires in one hour.</p>' . self::button('Reset password', $resetLink) . '</td></tr>' . self::footer());
        return self::send($email, $name, 'Reset your password', $html);
    }

    public static function sendLoanApprovedNotification(string $borrowerName, string $loanReference, string $principalAmount, string $interestRate, string $termMonths, string $email): bool
    {
        $html = self::shell(self::header('Loan approved') . '<tr><td style="padding:24px"><p>Hello ' . htmlspecialchars($borrowerName) . ',</p><p>Your loan has been approved.</p>' . self::referenceBox($loanReference) . '<table width="100%" cellspacing="0" cellpadding="0">' . self::detailRow('Principal', $principalAmount, true) . self::detailRow('Monthly interest rate', $interestRate . '% per month') . self::detailRow('Term', $termMonths . ' months', true) . '</table></td></tr>' . self::footer());
        return self::send($email, $borrowerName, 'Loan approved: ' . $loanReference, $html);
    }

    public static function sendPaymentReminderEmail(string $borrowerName, string $loanReference, string $amountDue, string $dueDate, string $email): bool
    {
        $html = self::shell(self::header('Payment reminder') . '<tr><td style="padding:24px"><p>Hello ' . htmlspecialchars($borrowerName) . ',</p><p>Your upcoming loan payment is due soon.</p>' . self::referenceBox($loanReference) . '<table width="100%" cellspacing="0" cellpadding="0">' . self::detailRow('Amount due', $amountDue, true) . self::detailRow('Due date', $dueDate) . '</table></td></tr>' . self::footer());
        return self::send($email, $borrowerName, 'Payment reminder: ' . $loanReference, $html);
    }

    public static function sendPaymentReceivedConfirmation(string $borrowerName, string $loanReference, string $amountPaid, string $balanceRemaining, string $paymentDate, string $email): bool
    {
        $html = self::shell(self::header('Payment received') . '<tr><td style="padding:24px"><p>Hello ' . htmlspecialchars($borrowerName) . ',</p><p>We received your payment.</p>' . self::referenceBox($loanReference) . '<table width="100%" cellspacing="0" cellpadding="0">' . self::detailRow('Amount paid', $amountPaid, true) . self::detailRow('Payment date', $paymentDate) . self::detailRow('Balance remaining', $balanceRemaining, true) . '</table></td></tr>' . self::footer());
        return self::send($email, $borrowerName, 'Payment received: ' . $loanReference, $html);
    }

    public static function sendNewUserCredentialsNotice(string $name, string $email, string $role): bool
    {
        $html = self::shell(self::header('New account') . '<tr><td style="padding:24px"><p>Hello ' . htmlspecialchars($name) . ',</p><p>Your staff account has been created.</p>' . self::detailRow('Role', $role, true) . '</td></tr>' . self::footer());
        return self::send($email, $name, 'Your staff account is ready', $html);
    }

    public static function sendPayslipEmail(string $employeeName, string $month, string $pdfBase64, string $filename, string $email): bool
    {
        $content = base64_decode($pdfBase64, true);
        if ($content === false || $content === '') {
            return false;
        }
        $html = self::shell(self::header('Payslip') . '<tr><td style="padding:24px"><p>Hello ' . htmlspecialchars($employeeName) . ',</p><p>Your payslip for ' . htmlspecialchars($month) . ' is attached as a PDF.</p></td></tr>' . self::footer());
        return self::send($email, $employeeName, 'Your payslip for ' . $month, $html, ['content' => $content, 'filename' => basename($filename)]);
    }

    public static function sendLoanScheduleEmail(string $borrowerName, string $loanReference, array $schedule, string $email): bool
    {
        $primary = htmlspecialchars(self::primaryColor());
        $rows = '';
        foreach ($schedule as $i => $row) {
            $shade = $i % 2 === 1 ? '#f4f7fa' : '#fff';
            // Tight padding and a small font — this table has 5 columns and
            // needs to still fit a 360px phone screen without the body's
            // own side padding forcing a horizontal scroll (Part 8).
            $cell = static fn (string $value): string => '<td style="padding:5px 3px;border-bottom:1px solid #e2e8f0;white-space:nowrap">' . htmlspecialchars($value) . '</td>';
            $rows .= '<tr style="background:' . $shade . '">'
                . $cell((string) ($i + 1))
                . $cell((string) ($row['due_date'] ?? ''))
                . $cell((string) ($row['principal_portion'] ?? ''))
                . $cell((string) ($row['interest_portion'] ?? ''))
                . $cell((string) ($row['payment_amount'] ?? ''))
                . '</tr>';
        }
        $headCell = static fn (string $label): string => '<td style="padding:5px 3px">' . $label . '</td>';
        $table = '<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:16px;font-size:11px">'
            . '<tr style="background:' . $primary . ';color:#fff">' . $headCell('#') . $headCell('Due') . $headCell('Principal') . $headCell('Interest') . $headCell('Payment') . '</tr>'
            . $rows . '</table>';
        $html = self::shell(self::header('Your repayment schedule') . '<tr><td style="padding:16px"><p>Hello ' . htmlspecialchars($borrowerName) . ',</p><p>Your loan has been approved. Here is your repayment schedule.</p>' . self::referenceBox($loanReference) . $table . '</td></tr>' . self::footer());
        return self::send($email, $borrowerName, 'Repayment schedule: ' . $loanReference, $html);
    }
}
