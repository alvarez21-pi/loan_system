import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { auth, errorMessage, isAuthenticated } from "../lib/api";
import { Button, Field, Input, InlineNote } from "../components/lms-ui";
import { COMPANY_NAME, LOGO_URL } from "../branding";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Sign In — Microfinance Loan Management System" },
      {
        name: "description",
        content:
          "Staff sign-in for the microfinance loan management system: borrowers, loans, approvals, repayments and payroll.",
      },
      { property: "og:title", content: "Sign In — Microfinance Loan Management System" },
      {
        property: "og:description",
        content: "Secure staff access to borrowers, loans, approvals and payroll records.",
      },
    ],
  }),
  component: LoginPage,
});

function LoginPage() {
  const navigate = useNavigate();
  const [resetMode, setResetMode] = useState(false);
  const [form, setForm] = useState({ email: "", password: "" });
  const [resetEmail, setResetEmail] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState("");
  const [resetSent, setResetSent] = useState(false);
  const [resetToken, setResetToken] = useState("");
  const [isSetupLink, setIsSetupLink] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  // A verification/reset link can expire, be malformed, or already be used
  // (Part 2/8.3): show a clear message and a way to request a fresh one,
  // instead of a bare error — and, critically, never render the set-password
  // form until the token has actually been checked with the server first.
  const [linkExpired, setLinkExpired] = useState(false);
  const [validatingToken, setValidatingToken] = useState(false);
  const [freshLinkEmail, setFreshLinkEmail] = useState("");
  const [freshLinkSent, setFreshLinkSent] = useState(false);

  useEffect(() => {
    // Token-only page: a verification/reset link must behave the same
    // regardless of any session already active in this browser (e.g. the
    // CEO staying logged in) — and must NEVER show the set-password form on
    // the strength of the URL alone. The token is validated against the
    // server FIRST; the form only renders once that comes back valid (Part 2).
    const params = new URLSearchParams(window.location.search);
    const setupToken = params.get("setup");
    const token = params.get("token") || setupToken || "";
    if (token) {
      setResetToken(token);
      setIsSetupLink(Boolean(setupToken));
      setResetMode(true);
      setValidatingToken(true);
      auth
        .validateResetToken(token)
        .catch(() => setLinkExpired(true))
        .finally(() => setValidatingToken(false));
      return;
    }
    if (isAuthenticated()) navigate({ to: "/dashboard", replace: true });

    // A back/forward-cache restore revives this page exactly as it was left —
    // including a typed password. Wipe the form, and skip ahead if a session
    // has appeared (e.g. signed in from another tab) in the meantime.
    function onPageShow(event: PageTransitionEvent) {
      if (!event.persisted) return;
      setForm({ email: "", password: "" });
      setServerError("");
      if (!new URLSearchParams(window.location.search).get("token") && isAuthenticated()) {
        navigate({ to: "/dashboard", replace: true });
      }
    }
    window.addEventListener("pageshow", onPageShow);
    return () => window.removeEventListener("pageshow", onPageShow);
  }, [navigate]);

  function validate() {
    const next: Record<string, string> = {};
    if (!form.email.trim()) next.email = "Email address is required.";
    else if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email.trim()))
      next.email = "Enter a valid email address.";
    if (!form.password) next.password = "Password is required.";
    else if (form.password.length < 4) next.password = "Password is too short.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setServerError("");
    if (!validate()) return;
    setBusy(true);
    try {
      await auth.login({ email: form.email.trim(), password: form.password });
      navigate({ to: "/dashboard", replace: true });
    } catch (error) {
      setServerError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function onResetSubmit(e: React.FormEvent) {
    e.preventDefault();
    setServerError("");
    setResetSent(false);
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(resetEmail.trim())) {
      setServerError("Enter a valid email address.");
      return;
    }
    setBusy(true);
    try {
      await auth.requestPasswordReset(resetEmail.trim());
      setResetSent(true);
    } catch (error) {
      setServerError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function onConfirmReset(e: React.FormEvent) {
    e.preventDefault();
    setServerError("");
    setLinkExpired(false);
    if (newPassword.length < 8) {
      setServerError("Password must be at least 8 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setServerError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await auth.confirmPasswordReset(resetToken, newPassword);
      setResetMode(false);
      setServerError("");
      window.history.replaceState({}, "", "/");
    } catch (error: any) {
      if (error?.payload?.expired) {
        setLinkExpired(true);
      } else {
        setServerError(errorMessage(error));
      }
    } finally {
      setBusy(false);
    }
  }

  async function onRequestFreshLink(e: React.FormEvent) {
    e.preventDefault();
    setServerError("");
    setFreshLinkSent(false);
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(freshLinkEmail.trim())) {
      setServerError("Enter a valid email address.");
      return;
    }
    setBusy(true);
    try {
      // A setup link (new account) is resent via resend-verification; a
      // forgot-password link is resent via the ordinary reset-request flow —
      // both are generic responses that never confirm whether the account exists.
      if (isSetupLink) await auth.resendVerification(freshLinkEmail.trim());
      else await auth.requestPasswordReset(freshLinkEmail.trim());
      setFreshLinkSent(true);
    } catch (error) {
      setServerError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-sidebar px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <img src={LOGO_URL} alt="" className="mx-auto mb-2 h-10 w-auto" />
          <h1 className="text-xl font-bold text-sidebar-foreground">{COMPANY_NAME}</h1>
          <p className="text-sm text-sidebar-muted">Staff sign-in</p>
        </div>
        {resetMode && resetToken && validatingToken ? (
          <div className="lms-card space-y-2 p-5 text-center">
            <h2 className="font-semibold text-foreground">Checking your link…</h2>
            <p className="text-sm text-muted-foreground">One moment while we confirm it's still valid.</p>
          </div>
        ) : resetMode && resetToken && linkExpired ? (
          <form onSubmit={onRequestFreshLink} className="lms-card space-y-4 p-5" noValidate>
            <div>
              <h2 className="font-semibold text-foreground">This link isn't valid</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                It may have expired, already been used, or be incomplete. Enter your email and we'll send you a new{" "}
                {isSetupLink ? "verification" : "reset"} link.
              </p>
            </div>
            <InlineNote tone="danger">{serverError}</InlineNote>
            <InlineNote tone="success">{freshLinkSent ? "If an account needs one, a new link has been sent." : ""}</InlineNote>
            <Field label="Email address">
              <Input
                type="email"
                autoComplete="email"
                value={freshLinkEmail}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFreshLinkEmail(e.target.value)}
              />
            </Field>
            <Button type="submit" variant="primary" disabled={busy} className="w-full">
              {busy ? "Sending…" : "Send me a new link"}
            </Button>
            <button
              type="button"
              className="w-full text-sm text-muted-foreground underline"
              onClick={() => {
                setResetMode(false);
                setLinkExpired(false);
                window.history.replaceState({}, "", "/");
              }}
            >
              Back to sign in
            </button>
          </form>
        ) : resetMode && resetToken ? (
          <form onSubmit={onConfirmReset} className="lms-card space-y-4 p-5" noValidate>
            <div>
              <h2 className="font-semibold text-foreground">Choose a new password</h2>
              <p className="mt-1 text-sm text-muted-foreground">Use at least 8 characters.</p>
            </div>
            <InlineNote tone="danger">{serverError}</InlineNote>
            <Field label="New password">
              <Input
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewPassword(e.target.value)}
              />
            </Field>
            <Field label="Confirm password">
              <Input
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setConfirmPassword(e.target.value)}
              />
            </Field>
            <Button type="submit" variant="primary" disabled={busy} className="w-full">
              {busy ? "Updating…" : "Update password"}
            </Button>
          </form>
        ) : resetMode ? (
          <form onSubmit={onResetSubmit} className="lms-card space-y-4 p-5" noValidate>
            <div>
              <h2 className="font-semibold text-foreground">Reset your password</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Enter your account email and we will send reset instructions.
              </p>
            </div>
            <InlineNote tone="danger">{serverError}</InlineNote>
            <InlineNote tone="success">{resetSent ? "If an account exists, a reset email has been sent." : ""}</InlineNote>
            <Field label="Email address">
              <Input
                type="email"
                autoComplete="email"
                value={resetEmail}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setResetEmail(e.target.value)}
              />
            </Field>
            <Button type="submit" variant="primary" disabled={busy} className="w-full">
              {busy ? "Sending…" : "Send reset email"}
            </Button>
            <button
              type="button"
              className="w-full text-sm text-muted-foreground underline"
              onClick={() => {
                setResetMode(false);
                setServerError("");
                setResetSent(false);
              }}
            >
              Back to sign in
            </button>
          </form>
        ) : (
        <form onSubmit={onSubmit} className="lms-card space-y-4 p-5" noValidate>
          <InlineNote tone="danger">{serverError}</InlineNote>
          <Field label="Email address" error={errors.email}>
            <Input
              name="email"
              type="email"
              autoComplete="username"
              placeholder="ceo@example.com"
              value={form.email}
              aria-invalid={Boolean(errors.email)}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setForm({ ...form, email: e.target.value })
              }
            />
          </Field>
          <Field label="Password" error={errors.password}>
            <Input
              name="password"
              type="password"
              autoComplete="current-password"
              value={form.password}
              aria-invalid={Boolean(errors.password)}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setForm({ ...form, password: e.target.value })
              }
            />
          </Field>
          <Button type="submit" variant="primary" disabled={busy} className="w-full">
            {busy ? "Signing in…" : "Login"}
          </Button>
          <button
            type="button"
            className="w-full text-sm text-muted-foreground underline"
            onClick={() => {
              setResetMode(true);
              setServerError("");
            }}
          >
            Forgot password?
          </button>
        </form>
        )}
      </div>
    </div>
  );
}
