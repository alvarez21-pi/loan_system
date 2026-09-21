import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { auth, errorMessage, isAuthenticated } from "../lib/api";
import { Button, Field, Input, Notice } from "../components/lms-ui";

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
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (isAuthenticated()) navigate({ to: "/dashboard", replace: true });
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token") || params.get("setup") || "";
    setResetToken(token);
    setResetMode(Boolean(token));
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
          <h1 className="text-xl font-bold text-sidebar-foreground">Microfinance LMS</h1>
          <p className="text-sm text-sidebar-muted">Staff sign-in</p>
        </div>
        {resetMode && resetToken ? (
          <form onSubmit={onConfirmReset} className="lms-card space-y-4 p-5" noValidate>
            <div>
              <h2 className="font-semibold text-foreground">Choose a new password</h2>
              <p className="mt-1 text-sm text-muted-foreground">Use at least 8 characters.</p>
            </div>
            <Notice tone="danger">{serverError}</Notice>
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
            <Notice tone="danger">{serverError}</Notice>
            <Notice tone="success">{resetSent ? "If an account exists, a reset email has been sent." : ""}</Notice>
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
          <Notice tone="danger">{serverError}</Notice>
          <Field label="Email address" error={errors.email}>
            <Input
              name="email"
              type="email"
              autoComplete="username"
              placeholder="admin@example.com"
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
