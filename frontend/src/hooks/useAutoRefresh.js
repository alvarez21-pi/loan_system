import { useEffect, useRef } from "react";

/**
 * Keeps an approval-relevant queue (pending loans, pending leave requests,
 * etc.) from going stale while it's open: reloads when the tab regains
 * focus/visibility, and again every `intervalMs` while it stays visible
 * (Part 8) — so a second approver's view reflects a decision made elsewhere
 * without needing a manual page refresh.
 */
export function useAutoRefresh(reload, intervalMs = 30_000) {
  const reloadRef = useRef(reload);
  reloadRef.current = reload;

  useEffect(() => {
    function onVisible() {
      if (document.visibilityState === "visible") reloadRef.current();
    }
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    const interval = setInterval(() => {
      if (document.visibilityState === "visible") reloadRef.current();
    }, intervalMs);
    return () => {
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
      clearInterval(interval);
    };
  }, [intervalMs]);
}

export default useAutoRefresh;
