<?php

require_once __DIR__ . '/src/Email.php';

header('Content-Type: application/json');
$secret = $_SERVER['HTTP_X_INTERNAL_SECRET'] ?? '';
if (!hash_equals((string) getenv('EMAIL_SERVICE_SECRET'), $secret)) {
    http_response_code(401);
    echo json_encode(['error' => 'unauthorized']);
    exit;
}

$payload = json_decode(file_get_contents('php://input'), true);
$type = $payload['type'] ?? '';
$to = $payload['to'] ?? '';
$data = $payload['data'] ?? [];
// Phase 4: the branding block the backend sends with every request — set
// once here, read by every Email:: template instead of a hardcoded
// constant/colour.
Email::setCompany(is_array($payload['company'] ?? null) ? $payload['company'] : []);
$allowed = ['verification', 'password_reset', 'loan_approved', 'payment_reminder', 'payment_received', 'new_user_notice', 'loan_schedule', 'payslip'];
if (!filter_var($to, FILTER_VALIDATE_EMAIL) || !in_array($type, $allowed, true)) {
    http_response_code(400);
    echo json_encode(['error' => 'invalid type or recipient']);
    exit;
}

$required = [
    'verification' => ['name', 'verify_link'],
    'password_reset' => ['name', 'reset_link'],
    'loan_approved' => ['borrower_name', 'loan_reference', 'principal_amount', 'interest_rate', 'term_months'],
    'payment_reminder' => ['borrower_name', 'loan_reference', 'amount_due', 'due_date'],
    'payment_received' => ['borrower_name', 'loan_reference', 'amount_paid', 'balance_remaining', 'payment_date'],
    'new_user_notice' => ['name', 'role'],
    'loan_schedule' => ['borrower_name', 'loan_reference', 'schedule'],
    'payslip' => ['employee_name', 'month', 'pdf_base64', 'filename'],
];
foreach ($required[$type] as $field) {
    if (!array_key_exists($field, $data)) {
        http_response_code(400);
        echo json_encode(['error' => 'missing field: ' . $field]);
        exit;
    }
}

$sent = match ($type) {
    'verification' => Email::sendVerificationEmail($data['name'], $to, $data['verify_link']),
    'password_reset' => Email::sendPasswordResetEmail($data['name'], $to, $data['reset_link']),
    'loan_approved' => Email::sendLoanApprovedNotification($data['borrower_name'], $data['loan_reference'], $data['principal_amount'], $data['interest_rate'], $data['term_months'], $to),
    'payment_reminder' => Email::sendPaymentReminderEmail($data['borrower_name'], $data['loan_reference'], $data['amount_due'], $data['due_date'], $to),
    'payment_received' => Email::sendPaymentReceivedConfirmation($data['borrower_name'], $data['loan_reference'], $data['amount_paid'], $data['balance_remaining'], $data['payment_date'], $to),
    'new_user_notice' => Email::sendNewUserCredentialsNotice($data['name'], $to, $data['role']),
    'loan_schedule' => Email::sendLoanScheduleEmail($data['borrower_name'], $data['loan_reference'], $data['schedule'], $to),
    'payslip' => Email::sendPayslipEmail($data['employee_name'], $data['month'], $data['pdf_base64'], $data['filename'], $to),
};
if (!$sent) {
    http_response_code(500);
    echo json_encode(['error' => 'email could not be sent']);
    exit;
}
echo json_encode(['status' => 'sent']);
