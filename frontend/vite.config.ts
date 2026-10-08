// The shared Vite configuration includes the TanStack, React and Tailwind plugins.
// or the app will break with duplicate plugins:
//   - TanStack devtools (dev-only, first), tanstackStart, viteReact, tailwindcss, tsConfigPaths,
//     nitro (build-only using cloudflare as a default target), VITE_* env injection, @ path alias,
//     React/TanStack dedupe, error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

// The backend's address as SEEN FROM WHEREVER THIS SERVER PROCESS RUNS —
// never a host-facing localhost/127.0.0.1 URL, since that only resolves on
// the machine viewing the page in a browser, not necessarily here. In Docker
// this is the compose service name (set as a build arg — see Dockerfile);
// running the frontend directly on a host machine (`npm run dev`/`build`
// outside Docker) falls back to plain localhost.
const backendInternalUrl = process.env.BACKEND_INTERNAL_URL || "http://localhost:5000";

export default defineConfig({
	// Cast: the wrapped config's nitro type doesn't list routeRules, but Nitro
	// itself supports it and passes it straight through at build time.
	nitro: {
		preset: "node-server",
		// The browser always calls its own origin's /api/* (see lib/api.js) —
		// this server-side proxy is what actually reaches the backend container,
		// so the browser's host/port (localhost, 127.0.0.1, a VPS domain, ...)
		// never has to match wherever the backend happens to be reachable
		// (Part 8.2 — the set-password "Unable to connect to the API" bug).
		routeRules: {
			"/api/**": { proxy: `${backendInternalUrl}/api/**` },
			// Phase 2 item 8: security headers on every page response. CSP is
			// scoped to the app's own origin plus exactly what it needs:
			// 'unsafe-inline' on script-src is required because TanStack
			// Start's own SSR streaming hydration emits inline <script> tags
			// (no app code uses dangerouslySetInnerHTML, so the residual risk
			// is confined to the framework's own fixed bootstrap script, never
			// user-supplied data); blob: on img-src is for borrower photo/
			// company-logo previews built with URL.createObjectURL().
			"/**": {
				headers: {
					"Content-Security-Policy": [
						"default-src 'self'",
						"script-src 'self' 'unsafe-inline'",
						"style-src 'self' 'unsafe-inline'",
						"img-src 'self' blob: data:",
						"font-src 'self'",
						"connect-src 'self'",
						"object-src 'none'",
						"base-uri 'self'",
						"form-action 'self'",
						"frame-ancestors 'none'",
					].join("; "),
					"X-Frame-Options": "DENY",
					"X-Content-Type-Options": "nosniff",
					"Referrer-Policy": "no-referrer",
					"Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
					// Safe to send unconditionally: per spec, a browser only ever
					// honors Strict-Transport-Security when it arrived over an
					// actual HTTPS connection — it's a no-op over plain HTTP
					// (local dev, or behind a load balancer that already
					// terminates TLS before this header would matter).
					"Strict-Transport-Security": "max-age=31536000; includeSubDomains",
				},
			},
		},
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
	} as any,
});
