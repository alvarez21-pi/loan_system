/**
 * A floating toast notification — appears near the bottom of the screen and
 * disappears on its own, rather than a fixed banner pinned in the page's
 * layout flow (Part 12). Deliberately a tiny module-level store (not a React
 * Context) so any route can call `showToast()` without needing a Provider
 * wrapped around the router root — `<ToastContainer/>` (mounted once, in
 * AppShell) is the only thing that actually subscribes to it.
 */
let listeners = [];
let toasts = [];
let nextId = 1;

function emit() {
  listeners.forEach((fn) => fn(toasts));
}

export function subscribeToasts(fn) {
  listeners.push(fn);
  fn(toasts);
  return () => {
    listeners = listeners.filter((l) => l !== fn);
  };
}

// Success/info are low-stakes confirmations - they can disappear on their
// own. Danger/warning report something the user may still need to act on
// (an error, a permission problem) - those stay until explicitly closed
// rather than risk vanishing before they're read.
const DEFAULT_DURATION_MS = { success: 6000, info: 6000, danger: 0, warning: 0 };

// A toast with a clickable link needs a moment longer to be noticed and
// clicked than a plain confirmation - only applies to tones that actually
// auto-dismiss (danger/warning already never auto-dismiss, link or not).
const LINK_DURATION_MS = 8000;

/**
 * tone: "success" | "danger" | "warning" | "info". Falsy messages are a
 * no-op.
 *
 * Third argument is either a plain number (explicit duration override in ms,
 * or 0 for "never auto-dismiss" - the original signature, still supported),
 * or an options object: `{ durationMs, link }`.
 *   - durationMs: explicit override, same meaning as above.
 *   - link: `{ label, to }` - `to` is a TanStack Router path. Renders as a
 *     clickable link inside the toast (ToastContainer/lms-ui.tsx) that
 *     navigates there. When a link is present and no explicit durationMs was
 *     given, the toast stays up for LINK_DURATION_MS instead of the tone's
 *     normal default.
 */
export function showToast(message, tone = "success", options) {
  if (!message) return null;
  const opts = typeof options === "number" ? { durationMs: options } : options || {};
  const { durationMs, link } = opts;
  const id = nextId++;
  const defaultDuration = DEFAULT_DURATION_MS[tone] ?? 6000;
  const duration =
    durationMs !== undefined ? durationMs : link && defaultDuration > 0 ? LINK_DURATION_MS : defaultDuration;
  toasts = [...toasts, { id, message, tone, link: link || null }];
  emit();
  if (duration > 0) setTimeout(() => dismissToast(id), duration);
  return id;
}

export function dismissToast(id) {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}
