import { useEffect } from "react";
import { useRouterState } from "@tanstack/react-router";
import { COMPANY_NAME, PRIMARY_COLOR } from "../branding";

// Every literal variant actually hardcoded across the route files' static
// head() titles — longest first, so "Microfinance Loan Management System"
// is replaced whole rather than leaving "Microfinance " in front of the
// real name after a shorter substring match consumes it.
const NAME_VARIANTS = [
  "Microfinance Loan Management System",
  "Microfinance LMS",
  "Loan Management System",
].sort((a, b) => b.length - a.length);

/**
 * Mounted once at the app root (__root.tsx). Branding is static (see
 * ../branding.ts), so both effects below run once on mount, not behind a
 * fetch:
 *
 * 1. Runtime theme — sets --primary (and --ring/--sidebar-active, which
 *    this design system currently derives from the same brand colour).
 * 2. Browser tab title — every route's own head() still sets its own
 *    page-specific static title (e.g. "Loan Detail — Microfinance LMS");
 *    this swaps the one shared hardcoded suffix for the real company name
 *    wherever it appears, re-run on every navigation since TanStack resets
 *    document.title per route.
 */
export function BrandingEffects() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  useEffect(() => {
    const root = document.documentElement.style;
    root.setProperty("--primary", PRIMARY_COLOR);
    root.setProperty("--ring", PRIMARY_COLOR);
    root.setProperty("--sidebar-active", PRIMARY_COLOR);
  }, []);

  useEffect(() => {
    let title = document.title;
    for (const variant of NAME_VARIANTS) {
      if (title.includes(variant)) {
        title = title.split(variant).join(COMPANY_NAME);
        break;
      }
    }
    if (title !== document.title) document.title = title;
  }, [pathname]);

  return null;
}

export default BrandingEffects;
