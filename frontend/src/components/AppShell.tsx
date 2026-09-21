import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import { clearSession, getUser, isAuthenticated } from "../lib/api";

const NAV = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/borrowers", label: "Borrowers" },
  { to: "/loan-products", label: "Loan Products" },
  { to: "/loan-calculator", label: "Loan Calculator" },
  { to: "/loans", label: "Loans" },
  { to: "/approvals", label: "Approvals" },
  { to: "/repayments", label: "Repayments" },
  { to: "/expenses", label: "Expenses" },
  { to: "/employees", label: "Employees" },
  { to: "/payroll", label: "Payroll" },
    { to: "/penalties", label: "Penalties" },
    { to: "/assets", label: "Assets" },
    { to: "/leave-requests", label: "Leave Requests" },
    { to: "/reports", label: "Reports" },
    { to: "/users", label: "Users" },
  { to: "/audit-logs", label: "Audit Logs" },
] as const;

export function AppShell({ children }: { children?: ReactNode }) {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<any>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!isAuthenticated()) {
      navigate({ to: "/", replace: true });
      return;
    }
    setUser(getUser());
    setReady(true);
  }, [navigate]);

  if (!ready) return null;

  function signOut() {
    clearSession();
    navigate({ to: "/", replace: true });
  }

  return (
    <div className="flex min-h-screen">
      <aside
        className={`${menuOpen ? "block" : "hidden"} fixed inset-y-0 left-0 z-20 w-60 shrink-0 overflow-y-auto bg-sidebar px-3 py-4 md:sticky md:top-0 md:block md:h-screen`}
      >
        <div className="px-2 pb-4">
          <p className="text-sm font-bold text-sidebar-foreground">Microfinance LMS</p>
          <p className="text-xs text-sidebar-muted">Loan Management System</p>
        </div>
        <nav className="space-y-1">
          {NAV.filter((item) => item.to !== "/users" || user?.role === "admin").map((item) => {
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
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-3">
          <button className="lms-btn lms-btn-outline md:hidden" onClick={() => setMenuOpen((v) => !v)}>
            Menu
          </button>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">
              {user?.name || user?.full_name || user?.phone || "Signed in"}
            </p>
            <p className="text-xs text-muted-foreground">{user?.role || "Staff"}</p>
          </div>
          <button className="lms-btn lms-btn-outline" onClick={signOut}>
            Sign out
          </button>
        </header>
        <main className="flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}

export default AppShell;
