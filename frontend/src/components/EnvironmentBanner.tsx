import { useEffect, useState } from "react";
import { environment } from "../lib/api";

/**
 * Phase 7 item 1: a visible banner on EVERY page (mounted at the root,
 * above AppShell/the sidebar — including the login and public
 * verification/reset pages, which never render AppShell) whenever the
 * backend has ENVIRONMENT_LABEL set. No label -> no banner, not even an
 * empty bar — a real production deployment with ENVIRONMENT_LABEL unset
 * never shows anything here.
 */
export function EnvironmentBanner() {
  const [label, setLabel] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    environment
      .label()
      .then((result: any) => {
        if (!cancelled) setLabel(result?.environment_label || null);
      })
      .catch(() => {
        // Network/API hiccup: say nothing rather than show a stale/wrong banner.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!label) return null;

  return (
    <div className="w-full bg-amber-500 px-4 py-1.5 text-center text-xs font-semibold uppercase tracking-wide text-amber-950">
      {label}
    </div>
  );
}

export default EnvironmentBanner;
