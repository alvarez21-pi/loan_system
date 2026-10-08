import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { Fragment, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Button, Field, Input, InlineNote, ToastContainer } from "./lms-ui";
import {
  auth,
  clearSession,
  errorMessage,
  getToken,
  getUser,
  hasAnyPermission,
  hasModuleAccess,
  hasPermission,
  isAdmin,
  roleLabel,
  sessionMatchesToken,
  setSession,
  verifySession,
} from "../lib/api";
import { COMPANY_NAME, LOGO_URL } from "../branding";

// Re-ask the server who we are at most this often on plain navigation/focus.
const REVERIFY_AFTER_MS = 30_000;

type NavItem = { to: string; label: string; permission?: string | string[]; anyOf?: boolean; adminOnly?: boolean; managerOnly?: boolean; module?: string };

// A user only sees a nav item for a page they can actually do something on —
// never a link that would just 403 on click (DESIGN.md section 2). Modules
// whose reads stay open to any authenticated user at the backend (borrowers,
// loans, penalties, assets, calculator) are gated on module ACCESS (tier +
// department); everything else is gated on the exact permission the backend
// enforces (services/permissions.py) — ceo/head_manager have everything.
const NAV: NavItem[] = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/borrowers", label: "Borrowers", module: "borrowers" },
  // ceo/head_manager, or a Loans Manager (department_manager, loans_credit) —
  // loan products live in that department (Part 4.1).
  { to: "/loan-products", label: "Loan Products", permission: "loan_products:manage" },
  { to: "/loan-calculator", label: "Loan Calculator", module: "calculator" },
  { to: "/loans", label: "Loans", module: "loans" },
  {
    to: "/approvals",
    label: "Approvals",
    permission: ["loans:approve", "penalties:approve", "leave:manage"],
    anyOf: true,
  },
  { to: "/repayments", label: "Repayments", permission: "repayments:record" },
  { to: "/expenses", label: "Expenses", permission: "expenses:manage" },
  { to: "/employees", label: "Employees", permission: "employees:manage" },
  { to: "/payroll", label: "Payroll", permission: "payroll:manage" },
  { to: "/deduction-types", label: "Deduction Types", permission: "payroll:manage" },
  { to: "/penalties", label: "Penalties", module: "penalties" },
  { to: "/capital", label: "Capital", permission: "capital:view" },
  // Reading the asset list is open to any authenticated user at the backend
  // (only creating/editing needs assets:manage), so it's gated on module reach.
  { to: "/assets", label: "Assets", module: "assets" },
  // Always visible: filing your OWN leave request is open to every tier
  // regardless of department (the backend's create_leave has no module gate
  // for a self-request at all) — only MANAGING someone else's is leave:manage/
  // department-gated, enforced on the page itself. A department_manager
  // outside hr (e.g. a Loans Manager) must still be able to reach this page
  // for their own request (Part 9.1).
  { to: "/leave-requests", label: "Leave Requests" },
  { to: "/reports", label: "Reports", permission: "reports:view" },
  // Anyone who could hand out at least one tier gets in — ceo, head_manager,
  // or a department_manager (scoped server-side to their own department).
  { to: "/users", label: "Users", managerOnly: true },
  // The audit trail is management-only (CEO/head_manager by default).
  { to: "/audit-logs", label: "Audit Logs", permission: "audit:view" },
  // Phase 6: CEO/head_manager only, same as Users/Audit Logs above.
  { to: "/backup", label: "Backup", permission: "backup:manage" },
];

/** The current page's own nav label, shown in the slim mobile header bar next
 * to the logo — falls back to the company name on a page with no nav entry
 * (e.g. a sub-route like a loan's own detail page). */
function currentPageTitle(pathname: string, user: any): string {
  const match = NAV.filter((item) => canSee(item, user)).find(
    (item) => pathname === item.to || pathname.startsWith(`${item.to}/`),
  );
  return match?.label || COMPANY_NAME;
}

function canSee(item: NavItem, user: any) {
  if (!user) return false;
  if (item.adminOnly) return isAdmin(user);
  if (item.managerOnly) return isAdmin(user) || user?.role === "department_manager";
  if (item.module) return hasModuleAccess(user, item.module);
  if (!item.permission) return true;
  const perms = Array.isArray(item.permission) ? item.permission : [item.permission];
  return item.anyOf ? hasAnyPermission(user, ...perms) : perms.every((p) => hasPermission(user, p));
}

/** The sidebar's own small logo — a static asset, not a fetch (see ../branding.ts). */
function SidebarLogo() {
  return <img src={LOGO_URL} alt="" className="h-6 w-auto" />;
}

/**
 * The one way out of must_change_password=true. Before this existed, the
 * backend's own `auth_required` (routes/auth.py) correctly blocked every
 * endpoint except auth.me/auth.change_password for such an account with a
 * 403 — but nothing in the frontend ever rendered a way to actually change
 * the password, and `errorMessage()` turned that 403 into the generic "You
 * don't have permission to do this." on every single page. A freshly
 * seeded or reset account was therefore permanently locked out, and it
 * looked exactly like a broken permissions system rather than what it
 * actually was: a required step with no UI for it. This gate renders
 * INSTEAD of the sidebar/page content — the same way the `!ready` check
 * below renders nothing — so no page's own API calls ever fire while this
 * is showing.
 */
function MustChangePasswordGate({
  onDone,
  onSignOut,
}: {
  onDone: (user: any) => void;
  onSignOut: () => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (newPassword.length < 12) {
      setError("The new password must be at least 12 characters long.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("The two passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      const result: any = await auth.changePassword(currentPassword, newPassword);
      onDone(result?.user);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-sidebar px-4 py-10">
      <div className="w-full max-w-sm">
        <form onSubmit={onSubmit} className="lms-card space-y-4 p-5" noValidate>
          <div>
            <h2 className="font-semibold text-foreground">Set a new password</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              You must choose your own password before continuing.
            </p>
          </div>
          <InlineNote tone="danger">{error}</InlineNote>
          <Field label="Current password">
            <Input
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setCurrentPassword(e.target.value)}
            />
          </Field>
          <Field label="New password" hint="At least 12 characters.">
            <Input
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewPassword(e.target.value)}
            />
          </Field>
          <Field label="Confirm new password">
            <Input
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setConfirmPassword(e.target.value)}
            />
          </Field>
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Saving…" : "Set password"}
          </Button>
          <button type="button" className="w-full text-sm text-muted-foreground underline" onClick={onSignOut}>
            Sign out instead
          </button>
        </form>
      </div>
    </div>
  );
}

/**
 * The single layout every authenticated page renders inside — sidebar,
 * header and the session guard live here so no page can bypass them.
 *
 * Session guard (why this is more than a redirect):
 *  - Every mount checks the cached user still belongs to the stored JWT and
 *    re-asks the API who the token is (GET /api/auth/me) so what is displayed
 *    is always the token's own user.
 *  - `pageshow` with `persisted` fires when the browser restores this page
 *    from the back/forward cache — a frozen render that may belong to a
 *    session that was since signed out in THIS tab. The page is hidden at
 *    once, the session re-verified, and the content remounted so it
 *    re-fetches its data.
 *  - Coming back to a tab left open a while (`visibilitychange`) triggers
 *    the same re-verification, in case the token expired server-side while
 *    the tab was in the background.
 * The session itself lives in sessionStorage, not localStorage — each tab is
 * independent, so a login/logout in ANOTHER tab never touches this one; there
 * is deliberately no cross-tab `storage`-event listener here any more (it
 * would do nothing, since sessionStorage never fires that event across tabs).
 * None of this depends on the environment: it is plain browser events plus
 * the API, so it behaves the same in production as on localhost.
 */
export function AppShell({ children }: { children?: ReactNode }) {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<any>(null);
  const [epoch, setEpoch] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const shownUserId = useRef<string | null>(null);
  const lastVerified = useRef(0);
  const verifying = useRef(false);

  const toLogin = useCallback(() => {
    shownUserId.current = null;
    setReady(false);
    setUser(null);
    navigate({ to: "/", replace: true });
  }, [navigate]);

  /** force: remount the page even if the user is unchanged (bfcache restore). */
  const verify = useCallback(
    async (force = false) => {
      if (!getToken()) {
        toLogin();
        return;
      }
      // Cheap local check first: does the cached user match the token?
      if (!sessionMatchesToken()) {
        setReady(false);
        shownUserId.current = null;
      }
      if (verifying.current) return;
      verifying.current = true;
      try {
        const fresh = await verifySession();
        if (!fresh) {
          toLogin();
          return;
        }
        lastVerified.current = Date.now();
        const changed = shownUserId.current !== String(fresh.id);
        shownUserId.current = String(fresh.id);
        setUser(fresh);
        if (changed || force) setEpoch((n) => n + 1);
        setReady(true);
      } catch {
        // A 401 already cleared the session and redirected. Anything else
        // (network) — keep showing only if the cached user still matches.
        if (!sessionMatchesToken()) toLogin();
        else setReady(true);
      } finally {
        verifying.current = false;
        document.documentElement.style.visibility = "";
      }
    },
    [toLogin],
  );

  useEffect(() => {
    // Show at once when the cache is trustworthy; the server check refreshes it.
    if (getToken() && sessionMatchesToken()) {
      shownUserId.current = String(getUser()?.id);
      setUser(getUser());
      setReady(true);
    }
    verify();

    function onPageShow(event: PageTransitionEvent) {
      if (!event.persisted) return;
      // Restored from bfcache: hide the stale render immediately, then verify.
      document.documentElement.style.visibility = "hidden";
      setReady(false);
      verify(true);
    }
    function onVisible() {
      if (document.visibilityState === "visible" && Date.now() - lastVerified.current > REVERIFY_AFTER_MS) verify();
    }
    window.addEventListener("pageshow", onPageShow);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("pageshow", onPageShow);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [verify]);

  if (!ready || !user) return null;

  function signOut() {
    clearSession();
    navigate({ to: "/", replace: true });
  }

  // Blocks every page/API call behind a password-change form instead of
  // the normal layout, until the account's own must_change_password flag
  // is actually cleared server-side — see MustChangePasswordGate above.
  if (user.must_change_password) {
    return (
      <MustChangePasswordGate
        onSignOut={signOut}
        onDone={(freshUser) => {
          const updated = freshUser || { ...user, must_change_password: false };
          setSession(getToken() as string, updated);
          setUser(updated);
        }}
      />
    );
  }

  return (
    <>
    {/* Fixed to exactly the height __root.tsx's flex column gives this slot
        (the full viewport, minus the environment banner's height when one
        is showing — Phase 7 item 1), never taller — this is what lets the
        sidebar stay genuinely pinned while only <main> below scrolls.
        (`min-h-screen` + document-level scroll — an earlier approach —
        combined with `overflow-x-hidden` here forces an implicit
        `overflow-y: auto` on this unbounded-height div per the CSS overflow
        spec, which is an unreliable base for a sticky sidebar: the div never
        actually overflows itself, so the outer document ends up scrolling
        instead and the "sticky" sidebar can visibly break. `h-full
        overflow-hidden` + an explicit scroll region on <main> avoids that
        class of bug entirely.) */}
    <div className="flex h-full w-full max-w-full overflow-hidden">
      {/* Backdrop behind the mobile drawer (same dismiss-on-click-outside
          pattern as Modal) - mobile only, since the sidebar is simply static
          on md+ and never needs one. */}
      {menuOpen ? (
        <div
          className="fixed inset-0 z-10 bg-black/40 md:hidden"
          onClick={() => setMenuOpen(false)}
          aria-hidden="true"
        />
      ) : null}
      <aside
        className={`${menuOpen ? "block" : "hidden"} fixed inset-y-0 left-0 z-20 flex w-72 max-w-[85vw] shrink-0 flex-col overflow-y-auto bg-sidebar px-3 py-4 md:static md:block md:h-full md:w-60 md:max-w-none`}
      >
        <div className="flex items-center gap-2 px-2 pb-4">
          <SidebarLogo />
          <p className="text-sm font-bold text-sidebar-foreground">{COMPANY_NAME}</p>
        </div>
        <nav className="flex-1 space-y-1">
          {NAV.filter((item) => canSee(item, user)).map((item) => {
            const active = pathname === item.to || pathname.startsWith(`${item.to}/`);
            return (
              <Link
                key={item.to}
                to={item.to}
                onClick={() => setMenuOpen(false)}
                className={`lms-nav-link ${active ? "lms-nav-link-active" : ""}`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        {/* Sign out lives in the drawer on mobile (keeps the slim header bar
            down to logo + title + Menu) - the md+ header keeps its own copy. */}
        <div className="mt-2 border-t border-sidebar-border pt-2 md:hidden">
          <button
            type="button"
            className="lms-nav-link w-full text-left"
            onClick={() => {
              setMenuOpen(false);
              signOut();
            }}
          >
            Sign out ({user?.name || user?.full_name || "Signed in"})
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Slim sticky bar on phones: Menu button, logo + current page title.
            The fuller user-info/sign-out header is md+ only (sign-out moved
            into the drawer above on mobile, see Part 14). */}
        <header className="sticky top-0 z-30 flex shrink-0 items-center gap-3 border-b border-border bg-surface px-4 py-3">
          <button
            className="lms-btn lms-btn-outline shrink-0 md:hidden"
            aria-label="Open menu"
            onClick={() => setMenuOpen((v) => !v)}
          >
            Menu
          </button>
          <div className="flex min-w-0 flex-1 items-center gap-2 md:hidden">
            <SidebarLogo />
            <p className="truncate text-sm font-semibold">{currentPageTitle(pathname, user)}</p>
          </div>
          <div className="hidden min-w-0 flex-1 md:block">
            <p className="truncate text-sm font-medium">
              {user?.name || user?.full_name || user?.phone || "Signed in"}
            </p>
            <p className="text-xs text-muted-foreground">{user ? roleLabel(user.role, user.department) : "Staff"}</p>
          </div>
          <button className="lms-btn lms-btn-outline hidden shrink-0 md:block" onClick={signOut}>
            Sign out
          </button>
        </header>
        {/* Keyed on the signed-in user + restore epoch: a different user (or a
            bfcache restore) remounts every page below, so it fetches its data
            afresh instead of showing what the previous render held.
            max-w-[1600px] keeps content readable on ultra-wide screens without
            stretching tables/forms edge to edge; min-w-0 lets the flex child
            shrink so a wide table scrolls INSIDE its own card instead of
            pushing the whole page wider than the viewport. overflow-y-auto
            here is the ONE scroll region for page content — the sidebar and
            header above are outside it and never move. */}
        <main className="min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-4 md:p-6">
          <div className="mx-auto w-full max-w-[1600px]">
            <Fragment key={`${user.id}:${epoch}`}>{children}</Fragment>
          </div>
        </main>
      </div>
    </div>
    <ToastContainer />
    </>
  );
}

export default AppShell;
