<?php

use PHPMailer\PHPMailer\Exception;
use PHPMailer\PHPMailer\PHPMailer;

require_once __DIR__ . '/../vendor/autoload.php';
require_once __DIR__ . '/../config.php';

final class Email
{
    private static function shell(string $body): string
    {
        return '<!doctype html><html><body style="margin:0;background:#f2f5f8;font-family:Arial,sans-serif;color:#203040"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:24px 0"><tr><td align="center"><table role="presentation" width="620" cellspacing="0" cellpadding="0" style="max-width:620px;background:#fff">' . $body . '</table></td></tr></table></body></html>';
    }

    private static function header(?string $subtitle = null): string
    {
        $sub = $subtitle ? '<div style="margin-top:6px;color:#dcecff;font-size:13px">' . htmlspecialchars($subtitle) . '</div>' : '';
        return '<tr><td style="background:#1A3A5C;padding:26px 32px;color:#fff"><strong style="font-size:22px">' . htmlspecialchars(COMPANY_NAME) . '</strong>' . $sub . '</td></tr>';
    }

    private static function footer(): string
    {
        $contact = htmlspecialchars(FROM_EMAIL);
        return '<tr><td style="background:#2E75B6;padding:18px 32px;color:#fff;font-size:12px">' . htmlspecialchars(COMPANY_NAME) . ' &middot; <a href="mailto:' . $contact . '" style="color:#fff">Contact support</a></td></tr>';
    }

    private static function detailRow(string $label, string $value, bool $shade = false): string
    {
        $background = $shade ? '#f4f7fa' : '#fff';
        return '<tr style="background:' . $background . '"><td style="padding:11px 14px;font-weight:bold;width:38%">' . htmlspecialchars($label) . '</td><td style="padding:11px 14px">' . htmlspecialchars($value) . '</td></tr>';
    }

    private static function button(string $label, string $link): string
    {
        return '<p style="margin:26px 0"><a href="' . htmlspecialchars($link) . '" style="background:#2E75B6;color:#fff;text-decoration:none;padding:13px 22px;display:inline-block;font-weight:bold">' . htmlspecialchars($label) . '</a></p>';
    }

    private static function referenceBox(string $reference): string
    {
        return '<div style="background:#e9f2fb;border-left:5px solid #2E75B6;padding:18px;margin:20px 0;font-size:22px;font-weight:bold;color:#1A3A5C">' . htmlspecialchars($reference) . '</div>';
    }

    private static function htmlToText(string $html): string
    {
        return trim(html_entity_decode(preg_replace('/\s+/', ' ', strip_tags(str_replace(['</p>', '</tr>', '<br>', '<br/>'], "\n", $html)))));
    }

    private static function send(string $to, string $toName, string $subject, string $html): bool
    {
        $mail = new PHPMailer(true);
        try {
            $mail->isSMTP();
            $mail->Host = SMTP_HOST;
            $mail->SMTPAuth = true;
            $mail->Username = SMTP_USERNAME;
            $mail->Password = SMTP_PASSWORD;
            $mail->Port = SMTP_PORT;
            $mail->SMTPSecure = SMTP_ENCRYPTION === 'ssl' ? PHPMailer::ENCRYPTION_SMTPS : PHPMailer::ENCRYPTION_STARTTLS;
            $mail->setFrom(FROM_EMAIL, FROM_NAME);
            $mail->addAddress($to, $toName);
            $mail->Subject = $subject;
            $mail->isHTML(true);
            $mail->Body = $html;
            $mail->AltBody = self::htmlToText($html);
            return $mail->send();
        } catch (Exception $exception) {
            error_log('Email send failed: ' . $exception->getMessage());
            return false;
        }
    }

    public static function sendVerificationEmail(string $name, string $email, string $verifyLink): bool
    {
        $html = self::shell(self::header('Verify your account') . '<tr><td style="padding:32px"><p>Hello ' . htmlspecialchars($name) . ',</p><p>Verify your Loan Management System account to continue.</p>' . self::button('Verify account', $verifyLink) . '</td></tr>' . self::footer());
        return self::send($email, $name, 'Verify your account', $html);
    }

    public static function sendPasswordResetEmail(string $name, string $email, string $resetLink): bool
    {
        $html = self::shell(self::header('Password reset') . '<tr><td style="padding:32px"><p>Hello ' . htmlspecialchars($name) . ',</p><p>Use the link below to choose a new password. The link expires in one hour.</p>' . self::button('Reset password', $resetLink) . '</td></tr>' . self::footer());
        return self::send($email, $name, 'Reset your password', $html);
    }

    public static function sendLoanApprovedNotification(string $borrowerName, string $loanReference, string $principalAmount, string $interestRate, string $termMonths, string $email): bool
    {
        $html = self::shell(self::header('Loan approved') . '<tr><td style="padding:32px"><p>Hello ' . htmlspecialchars($borrowerName) . ',</p><p>Your loan has been approved.</p>' . self::referenceBox($loanReference) . '<table width="100%" cellspacing="0" cellpadding="0">' . self::detailRow('Principal', $principalAmount, true) . self::detailRow('Interest rate', $interestRate) . self::detailRow('Term', $termMonths . ' months', true) . '</table></td></tr>' . self::footer());
        return self::send($email, $borrowerName, 'Loan approved: ' . $loanReference, $html);
    }

    public static function sendPaymentReminderEmail(string $borrowerName, string $loanReference, string $amountDue, string $dueDate, string $email): bool
    {
        $html = self::shell(self::header('Payment reminder') . '<tr><td style="padding:32px"><p>Hello ' . htmlspecialchars($borrowerName) . ',</p><p>Your upcoming loan payment is due soon.</p>' . self::referenceBox($loanReference) . '<table width="100%" cellspacing="0" cellpadding="0">' . self::detailRow('Amount due', $amountDue, true) . self::detailRow('Due date', $dueDate) . '</table></td></tr>' . self::footer());
        return self::send($email, $borrowerName, 'Payment reminder: ' . $loanReference, $html);
    }

    public static function sendPaymentReceivedConfirmation(string $borrowerName, string $loanReference, string $amountPaid, string $balanceRemaining, string $paymentDate, string $email): bool
    {
        $html = self::shell(self::header('Payment received') . '<tr><td style="padding:32px"><p>Hello ' . htmlspecialchars($borrowerName) . ',</p><p>We received your payment.</p>' . self::referenceBox($loanReference) . '<table width="100%" cellspacing="0" cellpadding="0">' . self::detailRow('Amount paid', $amountPaid, true) . self::detailRow('Payment date', $paymentDate) . self::detailRow('Balance remaining', $balanceRemaining, true) . '</table></td></tr>' . self::footer());
        return self::send($email, $borrowerName, 'Payment received: ' . $loanReference, $html);
    }

    public static function sendNewUserCredentialsNotice(string $name, string $email, string $role): bool
    {
        $html = self::shell(self::header('New account') . '<tr><td style="padding:32px"><p>Hello ' . htmlspecialchars($name) . ',</p><p>Your staff account has been created.</p>' . self::detailRow('Role', $role, true) . '</td></tr>' . self::footer());
        return self::send($email, $name, 'Your staff account is ready', $html);
    }
}
