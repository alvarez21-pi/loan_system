import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, Field, Input, InlineNote, PageHeader } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { backup, errorMessage, getUser, hasPermission } from "../lib/api";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/backup")({
  head: () => ({
    meta: [
      { title: "Backup — Microfinance LMS" },
      { name: "description", content: "Download an encrypted copy of the database and uploaded files." },
    ],
  }),
  component: () => (
    <AppShell>
      <BackupPage />
    </AppShell>
  ),
});

function formatWhen(iso: string | null) {
  if (!iso) return "Never";
  return new Date(iso).toLocaleString();
}

function BackupPage() {
  const user = getUser();
  const allowed = hasPermission(user, "backup:manage");
  const status = useResource(() => (allowed ? backup.status() : Promise.resolve({ data: null })), [allowed]);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  if (!allowed) return <InlineNote tone="danger">Ceo or head manager role required.</InlineNote>;

  const s: any = status.data || {};
  const canSubmit = password.length >= 12 && confirm.length > 0 && !busy;

  async function onDownload(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 12) {
      showToast("Choose a password at least 12 characters long.", "danger");
      return;
    }
    if (password !== confirm) {
      showToast("The two passwords don't match.", "danger");
      return;
    }
    setBusy(true);
    try {
      await backup.download(password);
      showToast(
        "Backup downloaded. Store this file and its password somewhere safe and separate from " +
          "each other — the password is never saved anywhere and cannot be recovered if you lose it.",
        "success",
      );
      setPassword("");
      setConfirm("");
      status.reload();
    } catch (error) {
      showToast(errorMessage(error), "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Backup" description="Encrypted backup of your database and files." />

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Backup status">
          <InlineNote tone="danger">{status.error}</InlineNote>
          {s.stale ? (
            <InlineNote tone="warning">
              No backup has been downloaded in the last {s.stale_after_days || 7} days. Download one below and store
              it somewhere off this server.
            </InlineNote>
          ) : null}
          <dl className="space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">Last downloaded by a person</dt>
              <dd className="font-medium">{formatWhen(s.last_manual_download)}</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">Last automatic server copy</dt>
              <dd className="font-medium">{formatWhen(s.last_nightly_backup)}</dd>
            </div>
          </dl>
          <p className="mt-4 text-xs text-muted-foreground">
            The server also keeps its own automatic copy every night, retained for 14 days — this protects against
            local disk or database corruption, but it never leaves the server. Downloading a copy here is what
            actually gets one off-site.
          </p>
        </Card>

        <Card title="Download an encrypted backup">
          <form onSubmit={onDownload} className="space-y-3" noValidate>
            <p className="text-sm text-muted-foreground">
              Choose a password below. It encrypts the downloaded file (AES-256) and is used only for this one
              download — it is never sent anywhere else, stored, or logged. Without it, the backup file cannot be
              opened again, by anyone, including this system's own developers.
            </p>
            <Field label="Password" hint="At least 12 characters — cannot be recovered.">
              <Input
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e: any) => setPassword(e.target.value)}
              />
            </Field>
            <Field label="Confirm password">
              <Input
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e: any) => setConfirm(e.target.value)}
              />
            </Field>
            <Button type="submit" disabled={!canSubmit} className="w-full">
              {busy ? "Preparing backup…" : "Download backup"}
            </Button>
            {!busy && password.length === 0 ? (
              <p className="text-xs text-muted-foreground">Enter a password above to enable the download.</p>
            ) : null}
          </form>
        </Card>
      </div>
    </>
  );
}
