# Loan Management System Specification

## 1. Runtime

- `db`: PostgreSQL 15 on port `5432`.
- `backend`: Flask API on port `5000`.
- `frontend`: TanStack Start Node server on port `3000`.
- Browser API base URL: `http://localhost:5000`.
- Local startup: `docker compose up -d --build`.
- `email-service`: PHP 8.2/Apache mail gateway on port `8080`, reachable by the backend as `http://email-service:80/index.php`.

## 1.1 Email Service

- `email-service/index.php`: internal-secret-protected JSON entrypoint.
- `email-service/src/Email.php`: PHPMailer SMTP sender and branded HTML/plain-text templates.
- `email-service/config.php`: SMTP and branding constants loaded only from environment variables.
- `email-service/composer.json`: PHPMailer dependency.
- `email-service/Dockerfile`: PHP 8.2 Apache image with Composer installation.
- `email-service/.env.example`: required SMTP configuration template.
- Replace the placeholder values in `email-service/.env` before testing real mailbox delivery.

## 2. Backend Files

- `backend/app.py`: Flask application factory, database URL, JWT, CORS, migrations, health endpoint, blueprint registration.
- `backend/extensions.py`: SQLAlchemy, JWT, and Flask-Migrate extension instances.
- `backend/models/user.py`: staff accounts, roles, password hashing, public serialization.
- `backend/models/borrower.py`: borrower records.
- `backend/models/loan.py`: loan products, loans, schedules, repayments, and penalties.
- `backend/models/accounting.py`: assets and expenses.
- `backend/models/employee.py`: employees, leave requests, and payroll runs.
- `backend/models/audit.py`: audit records.
- `backend/routes/auth.py`: login, registration, password reset request, password reset confirmation, and JWT guard.
- `backend/services/email_client.py`: internal email-service HTTP client.
- `backend/services/approval.py`: approval-domain service location; route integration is still required.
- `backend/migrations/`: Alembic migration environment and schema revisions.
- `backend/seed_admin.py`: creates the first administrator when none exists.

## 3. Frontend Files

- `frontend/src/routes/__root.tsx`: document shell, metadata, error boundary, and nested route outlet.
- `frontend/src/routes/index.tsx`: login and password reset request/confirmation screens.
- `frontend/src/components/AppShell.tsx`: authenticated layout, navigation, session guard, and sign out.
- `frontend/src/components/lms-ui.tsx`: shared buttons, fields, notices, tables, cards, status badges, and formatting.
- `frontend/src/hooks/useResource.js`: loading, error, and reload state for API resources.
- `frontend/src/lib/api.js`: API base URL, JWT storage, request handling, endpoint map, and resource methods.
- `frontend/src/lib/application-error-reporting.ts`: application error logging.
- `frontend/src/routes/dashboard.tsx`: live portfolio summary and recent activity.
- `frontend/src/routes/borrowers.index.tsx`: borrower list and creation form.
- `frontend/src/routes/borrowers.$id.tsx`: borrower detail view.
- `frontend/src/routes/loan-products.tsx`: loan product list, creation, and update forms.
- `frontend/src/routes/loans.tsx`: loan list and creation form.
- `frontend/src/routes/approvals.tsx`: approval queue for loans, expenses, payroll, and penalties.
- `frontend/src/routes/repayments.tsx`: repayment list and creation form.
- `frontend/src/routes/expenses.tsx`: expense list and creation form.
- `frontend/src/routes/employees.tsx`: employee list and creation form.
- `frontend/src/routes/payroll.tsx`: payroll list and creation form.
- `frontend/src/routes/audit-logs.tsx`: audit log list and filtering.
- `frontend/src/routes/loan-calculator.tsx`: standalone amortization preview.
- `frontend/src/routes/penalties.tsx`: penalty creation, filtering, and approval actions.
- `frontend/src/routes/assets.tsx`: asset CRUD and soft delete.
- `frontend/src/routes/leave-requests.tsx`: leave creation, filtering, and approval actions.
- `frontend/src/routes/reports.tsx`: report selection, JSON tables, PDF, and Excel downloads.

## 4. Authentication Flow

1. User opens `/`.
2. Login sends `POST /api/auth/login` with `{ phone, password }`.
3. API returns `{ access_token, user }`.
4. Frontend stores the JWT and user in local storage.
5. Protected screens attach `Authorization: Bearer <token>`.
6. A `401` clears the session and returns the user to `/`.
7. Password reset request sends `POST /api/auth/password-reset/request` with an email.
8. Backend sends a one-hour signed token through the email service.
9. The emailed URL opens `/?token=<token>`.
10. Password confirmation sends `POST /api/auth/password-reset/confirm` with `{ token, password }`.

## 5. Required Backend API Contract

These endpoints are referenced by the frontend. Read endpoints are implemented; write and approval endpoints remain to be completed:

- `GET /api/dashboard/summary`
- `POST /api/loan-calculator/preview`
- `GET/POST/PUT/DELETE /api/assets`
- `GET/POST /api/leave-requests` and leave approval/rejection routes
- `GET /api/capital/summary`
- `GET /api/borrowers`
- `POST /api/borrowers`
- `GET /api/borrowers/<id>`
- `GET /api/loan-products`
- `POST /api/loan-products`
- `PUT /api/loan-products/<id>`
- `GET /api/loans`
- `POST /api/loans`
- `POST /api/loans/<id>/approve`
- `POST /api/loans/<id>/reject`
- `GET /api/repayments`
- `POST /api/repayments`
- `GET /api/expenses`
- `POST /api/expenses`
- `POST /api/expenses/<id>/approve`
- `POST /api/expenses/<id>/reject`
- `GET /api/employees`
- `POST /api/employees`
- `GET /api/payroll`
- `POST /api/payroll`
- `POST /api/payroll/<id>/approve`
- `POST /api/payroll/<id>/reject`
- `GET /api/penalties`
- `POST /api/penalties/<id>/approve`
- `POST /api/penalties/<id>/reject`
- `GET /api/audit-logs`

Implemented currently:

- `GET /api/health`
- `POST /api/auth/login`
- `POST /api/auth/register`
- `POST /api/auth/password-reset/request`
- `POST /api/auth/password-reset/confirm`
- Authenticated `GET` collection/detail endpoints for borrowers, loan products, loans, repayments, expenses, employees, payroll, penalties, and audit logs.
- Authenticated `GET /api/dashboard/summary`
- `POST /api/loan-calculator/preview`
- Asset and leave-request CRUD/approval routes
- `GET /api/capital/summary`
- Five report routes with JSON, PDF, and Excel output

## 6. Business Rules To Implement

- Require JWT on all operational endpoints.
- Enforce roles: `admin`, `maker`, and `checker`.
- Enforce maker-checker: the creator cannot approve or reject their own record.
- Set new loan, expense, payroll, and penalty records to a pending status.
- Record approving/rejecting user and timestamp.
- Require rejection reasons where applicable.
- Update loan outstanding balance when a repayment is posted.
- Generate payment schedules when a loan is approved or activated.
- Write an audit log for every create, update, approve, reject, repayment, and login-sensitive action.
- Return consistent JSON shapes, preferably `{ borrowers: [] }`, `{ loans: [] }`, or the matching resource key.

## 7. Test Plan

### Infrastructure

- `docker compose config --quiet`
- `docker compose up -d --build`
- `curl http://localhost:5000/api/health`
- `curl -I http://localhost:3000`
- `docker compose exec backend flask --app app db current`

### Authentication

- Valid admin login returns a JWT.
- Invalid password returns `401`.
- Registration rejects invalid email, short password, and duplicate email/phone.
- Reset request always returns a generic response.
- Reset confirmation rejects invalid or expired tokens.
- Reset confirmation changes the password.

### Operational API

For every required endpoint, test unauthenticated, authorized, invalid payload, successful create/update, and not-found cases. For approval endpoints, test both maker and checker users.

### Frontend

- Login redirects to dashboard.
- Empty API responses show empty states, never sample records.
- API failures show an error message, never fabricated rows.
- Navigation requires authentication.
- Create forms refresh their list after success.
- Approval actions refresh their queue.
- Sign out clears local storage and returns to login.

## 8. Current Gaps

1. Write endpoints and approval endpoints are still missing for business resources.
2. Real mailbox delivery requires valid SMTP values in `email-service/.env`; placeholder SMTP values intentionally produce a controlled send failure.
3. Registration has an API but no registration screen.
4. No automated test suite exists.
5. `@lovable.dev/vite-tanstack-config` remains a build dependency because it supplies the TanStack/Vite integration; it is not used as product branding.
