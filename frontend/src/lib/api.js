/**
 * Central API helper.
 *
 * - Base URL: same-origin by default (BASE_URL = "", so a call to
 *   ENDPOINTS.login becomes a plain relative fetch to "/api/auth/login").
 *   The browser never needs to know the backend's own host or port — in
 *   Docker, the frontend server proxies /api/* to the backend container
 *   (vite.config.ts's nitro routeRules); this also fixes production, where
 *   "http://localhost:5000" would only ever resolve on the machine running
 *   the backend, never on a visitor's own machine (Part 8.2). Set
 *   VITE_API_BASE_URL only for the unusual case of a frontend dev server
 *   that is NOT proxying to a backend of its own (e.g. pointing `vite dev`
 *   at a separately-running backend on another port).
 * - Attaches the JWT from sessionStorage as an Authorization Bearer token.
 *   sessionStorage (NOT localStorage) is deliberate: it is per-tab, never
 *   shared across tabs or windows of the same origin. localStorage IS shared
 *   across every tab, which was the root cause of a real bug — logging into
 *   a different account in one tab silently changed what another open tab
 *   showed, and a token-only page (verification/reset) could render based on
 *   whichever session happened to be sitting in shared storage instead of
 *   the token actually in its own URL. Never switch this back without
 *   re-solving that (see the cross-tab-isolation test in the frontend suite).
 * - On 401 (invalid/expired token) it clears the session and redirects to login
 * - On 403 (valid session, wrong role) it never touches the session — callers
 *   show an in-place "You don't have permission to do this." message instead
 * - Endpoint paths are grouped in ENDPOINTS so they are easy to rename
 */

export const BASE_URL = String(import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");

export const TOKEN_KEY = "lms_token";
export const USER_KEY = "lms_user";
export const LOGIN_PATH = "/";

/* ------------------------------------------------------------------ session */

export function getToken() {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getUser() {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setSession(token, user) {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(TOKEN_KEY, token || "");
  if (user) window.sessionStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(TOKEN_KEY);
  window.sessionStorage.removeItem(USER_KEY);
}

export function isAuthenticated() {
  return Boolean(getToken());
}

/** The claims inside the JWT (never trusted for security — the API re-checks — only for matching). */
export function decodeToken(token = getToken()) {
  try {
    const payload = String(token || "").split(".")[1];
    if (!payload) return null;
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(decodeURIComponent(escape(json)));
  } catch {
    return null;
  }
}

/**
 * Whether the user record cached for display belongs to the token that is
 * currently stored. sessionStorage is per-tab, so this mismatch should now
 * only ever happen from a page restored from the back/forward cache (a
 * frozen render of a session that has since been signed out in THIS same
 * tab) — never from a different login in another tab, which sessionStorage
 * makes structurally impossible.
 */
export function sessionMatchesToken() {
  const claims = decodeToken();
  const user = getUser();
  if (!claims || !user) return false;
  if (claims.exp && claims.exp * 1000 < Date.now()) return false;
  return String(claims.sub) === String(user.id);
}

// Mirrors backend/services/permissions.py exactly — keep both in sync by hand.
export const ADMIN_ROLES = ["ceo", "head_manager"];

export function isAdmin(user) {
  return ADMIN_ROLES.includes(user?.role);
}

const UNSCOPED_ROLES = ["ceo", "head_manager"];

export const DEPARTMENTS = ["hr", "finance", "loans_credit", "general"];
/** @type {Record<string, string>} */
export const DEPARTMENT_LABELS = { hr: "HR", finance: "Finance", loans_credit: "Loans Credit", general: "General" };
const DEPARTMENT_MANAGER_TITLES = { hr: "HR Manager", finance: "Finance Manager", loans_credit: "Loans Manager", general: "General Manager" };
const ROLE_LABELS = { ceo: "CEO", head_manager: "Head Manager", department_manager: "Department Manager", checker: "Checker", maker: "Maker" };

export function roleLabel(role, department) {
  if (role === "department_manager") return DEPARTMENT_MANAGER_TITLES[department] || "Department Manager";
  return ROLE_LABELS[role] || role;
}

const DEPARTMENT_MODULES = {
  hr: ["employees", "payroll", "leave_requests"],
  finance: ["expenses", "capital", "assets", "reports"],
  loans_credit: ["borrowers", "loans", "repayments", "penalties", "calculator"],
  general: [
    "borrowers", "loans", "repayments", "penalties", "calculator",
    "employees", "payroll", "leave_requests", "expenses", "capital", "assets", "reports",
  ],
};

// The fixed set of modules a checker/maker's action set ever touches,
// department-independent (Part 4). Notably excludes employees/payroll/
// capital/assets/reports — neither tier reaches those no matter what.
const MAKER_CHECKER_MODULES = ["borrowers", "loans", "repayments", "expenses", "penalties", "leave_requests", "calculator"];

/** Whether this user's tier reaches `module` at all — used for nav
 * visibility on modules whose reads stay open to any authenticated user
 * (borrowers/loans/penalties/assets/calculator), not a security boundary. */
export function hasModuleAccess(user, module) {
  if (!user) return false;
  if (UNSCOPED_ROLES.includes(user.role)) return true;
  if (user.role === "checker" || user.role === "maker") return MAKER_CHECKER_MODULES.includes(module);
  if (user.role === "department_manager") return (DEPARTMENT_MODULES[user.department] || []).includes(module);
  return false;
}

const PERMISSION_MODULE = {
  "borrowers:view": "borrowers", "borrowers:manage": "borrowers",
  "loans:view": "loans", "loans:create": "loans", "loans:approve": "loans",
  "loan_products:manage": "loans",
  "penalties:view": "penalties", "penalties:create": "penalties", "penalties:approve": "penalties",
  "repayments:record": "repayments",
  "reports:view": "reports", "reports:financial": "reports",
  "capital:view": "capital", "capital:manage": "capital",
  "assets:manage": "assets",
  "expenses:manage": "expenses",
  "employees:manage": "employees",
  "payroll:manage": "payroll",
  "leave:request": "leave_requests", "leave:manage": "leave_requests",
};
// Fixed, department-independent action sets (Part 4). A checker approves
// ANY loan and never a leave request or penalty; a maker never approves
// anything.
const CHECKER_PERMISSIONS = ["loans:approve", "borrowers:manage", "repayments:record", "expenses:manage", "penalties:create", "leave:request"];
const MAKER_PERMISSIONS = ["borrowers:manage", "loans:create", "repayments:record", "expenses:manage", "penalties:create", "leave:request"];
const GLOBAL_ONLY_PERMISSIONS = ["users:manage", "audit:view", "backup:manage"];

/** Mirrors the backend's has_permission(): ceo/head_manager everything;
 * department_manager everything within their department; checker/maker a
 * fixed action set with NO department gating any more (Part 4). */
export function hasPermission(user, permission) {
  if (!user) return false;
  if (UNSCOPED_ROLES.includes(user.role)) return true;
  if (permission === "calculator:use" && (user.role === "checker" || user.role === "maker")) return true;
  if (permission === "calculator:use") return hasModuleAccess(user, "calculator");
  if (GLOBAL_ONLY_PERMISSIONS.includes(permission)) return false;

  const module = PERMISSION_MODULE[permission];
  if (!module) return false;

  if (user.role === "department_manager") return (DEPARTMENT_MODULES[user.department] || []).includes(module);
  if (user.role === "checker") return CHECKER_PERMISSIONS.includes(permission);
  if (user.role === "maker") return MAKER_PERMISSIONS.includes(permission);
  return false;
}

export function hasAnyPermission(user, ...permissions) {
  return permissions.some((p) => hasPermission(user, p));
}

/** Tiers this actor may hand out — drives the create-user form (Part 3). */
export function assignableRolesFor(actor) {
  if (!actor) return [];
  if (actor.role === "ceo") return ["head_manager", "department_manager", "checker", "maker"];
  if (actor.role === "head_manager") return ["department_manager", "checker", "maker"];
  if (actor.role === "department_manager") return ["checker", "maker"];
  return [];
}

/* -------------------------------------------------------------------- errors */

export class ApiError extends Error {
  constructor(message, status, payload, authRequest = true) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
    // Whether this request was sent with a bearer token (auth: true, the
    // default). A 403 on a public endpoint (e.g. login's "unverified email")
    // is a different situation than a 403 on an authenticated action.
    this.authRequest = authRequest;
  }
}

/**
 * Maker-checker: the backend refuses an approval when the approver is also
 * the creator of the record. Detect it so the UI can explain it clearly.
 */
export function isMakerCheckerError(error) {
  if (!(error instanceof ApiError)) return false;
  if (![400, 403, 409, 422].includes(error.status)) return false;
  const text = `${error.message} ${JSON.stringify(error.payload || {})}`;
  return /maker|checker|same user|own record|creator|created (this|the) record|cannot approve/i.test(
    text,
  );
}

/**
 * A genuine wrong-role permission failure on an authenticated request —
 * distinct from a 401 (bad/expired token, logs out) and distinct from a 403
 * on a public endpoint like login's "please verify your email" message.
 */
export function isPermissionError(error) {
  return (
    error instanceof ApiError &&
    error.status === 403 &&
    error.authRequest !== false &&
    !isMakerCheckerError(error)
  );
}

export function errorMessage(error) {
  if (isMakerCheckerError(error)) {
    return "Maker-checker rule: you created this record, so someone else must approve or reject it.";
  }
  // A 403 from the must_change_password gate (routes/auth.py's
  // auth_required) is NOT a permission problem — surface the real reason
  // rather than masking it as "You don't have permission to do this.",
  // which is what made this look like a permissions bug instead of what it
  // actually was (AppShell's gate below is what actually prevents this
  // from being hit in normal use; this is a defense-in-depth fallback).
  if (error instanceof ApiError && error.status === 403 && error.payload?.must_change_password) {
    return error.message || "You must set a new password before continuing.";
  }
  if (isPermissionError(error)) {
    // A scoped checker refused for one category is told which — anything else stays generic.
    return /not assigned to approve/i.test(error.message)
      ? error.message
      : "You don't have permission to do this.";
  }
  if (error instanceof ApiError && error.status === 404) {
    return "This API endpoint is not available yet.";
  }
  if (error instanceof ApiError && error.status === 0) {
    return `Unable to connect to the API${BASE_URL ? ` at ${BASE_URL}` : ""}. Check your connection and try again.`;
  }
  return error?.message || "Something went wrong.";
}

/* ------------------------------------------------------------------- request */

async function request(path, options = {}) {
  const { method = "GET", body, auth = true, headers = {} } = options;
  const token = auth ? getToken() : null;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;

  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        Accept: "application/json",
        ...(body !== undefined && !isForm ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    });
  } catch (networkError) {
    throw new ApiError(networkError?.message || "Network request failed", 0, null, auth);
  }

  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { message: text };
    }
  }

  if (response.status === 401) {
    // Only an authenticated request's 401 means "your token is bad/expired."
    // A public endpoint (login, register-verify) returning 401 is just a
    // normal request failure (e.g. wrong password) and must not log anyone out.
    if (auth) {
      clearSession();
      if (typeof window !== "undefined" && window.location.pathname !== LOGIN_PATH) {
        window.location.assign(LOGIN_PATH);
      }
      throw new ApiError("Your session expired. Please sign in again.", 401, payload, auth);
    }
    const message = payload?.message || payload?.error || "Incorrect email or password.";
    throw new ApiError(message, 401, payload, auth);
  }

  if (!response.ok) {
    const message =
      payload?.message || payload?.error || payload?.detail || `Request failed (${response.status})`;
    throw new ApiError(message, response.status, payload, auth);
  }

  return payload;
}

/**
 * Ask the server who this token really belongs to and refresh the cached
 * user (role and approval scopes can change while a tab stays open).
 * Resolves to the user, or null if there is no valid session (a 401 already
 * cleared it and sent the browser to the login page).
 */
export async function verifySession() {
  const token = getToken();
  if (!token) return null;
  const claims = decodeToken(token);
  if (claims?.exp && claims.exp * 1000 < Date.now()) {
    clearSession();
    return null;
  }
  const payload = await request("/api/auth/me");
  const user = payload?.user;
  if (!user || (claims?.sub !== undefined && String(claims.sub) !== String(user.id))) {
    clearSession();
    return null;
  }
  setSession(token, user);
  return user;
}

/** Accepts [..], {data: [..]}, {items: [..]} or {<key>: [..]} */
function toList(payload, key) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  for (const candidate of [key, "data", "items", "results"]) {
    if (candidate && Array.isArray(payload[candidate])) return payload[candidate];
  }
  return [];
}

function toItem(payload, key) {
  if (!payload || typeof payload !== "object") return null;
  if (key && payload[key] && !Array.isArray(payload[key])) return payload[key];
  if (payload.data && !Array.isArray(payload.data)) return payload.data;
  return payload;
}

async function list(path, key) {
  return { data: toList(await request(path), key) };
}

/**
 * Phase 5: the opt-in paginated counterpart to list() — used only by the
 * five pages that pass page/page_size (loans, borrowers, repayments,
 * users, audit log). Keeps `pagination` (never present on the plain,
 * unpaginated response) alongside `data`, instead of toList() discarding
 * everything but the array.
 */
async function paginatedList(path, key, params = {}) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""),
  );
  const payload = await request(query.toString() ? `${path}?${query}` : path);
  return { data: toList(payload, key), pagination: payload?.pagination || null, raw: payload };
}

async function downloadBlob(path) {
  const token = getToken();
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (response.status === 401) {
    clearSession();
    if (typeof window !== "undefined" && window.location.pathname !== LOGIN_PATH) window.location.assign(LOGIN_PATH);
    throw new ApiError("Your session expired. Please sign in again.", 401, null, true);
  }
  if (!response.ok) {
    let message = `Download failed (${response.status})`;
    try {
      message = (await response.json())?.message || message;
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(message, response.status, null, true);
  }
  return response.blob();
}

/** Phase 6: the backup download needs a password in the request BODY
 * (never a query string, where it could end up logged) and returns a
 * binary blob, not JSON — the POST-and-JSON `request()` helper above
 * assumes a JSON response, and the GET-only `downloadBlob()` above can't
 * send a body, so this is its POST counterpart. */
async function postDownloadBlob(path, body) {
  const token = getToken();
  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });
  } catch (networkError) {
    throw new ApiError(networkError?.message || "Network request failed", 0, null, true);
  }
  if (response.status === 401) {
    clearSession();
    if (typeof window !== "undefined" && window.location.pathname !== LOGIN_PATH) window.location.assign(LOGIN_PATH);
    throw new ApiError("Your session expired. Please sign in again.", 401, null, true);
  }
  if (!response.ok) {
    let message = `Download failed (${response.status})`;
    let payload = null;
    try {
      payload = await response.json();
      message = payload?.message || message;
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(message, response.status, payload, true);
  }
  return response.blob();
}

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  // The anchor must actually be IN the document for `.click()` to reliably
  // trigger a download in every browser - Chrome tolerates an un-attached
  // anchor, but Firefox and some Safari versions silently do nothing with
  // one, which is exactly what made this look "unresponsive" (Part 5.1 -
  // this is the shared helper every PDF download in the app goes through,
  // payslips included).
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/* ----------------------------------------------------------------- endpoints */

export const ENDPOINTS = {
  login: "/api/auth/login",
  passwordResetRequest: "/api/auth/password-reset/request",
  passwordResetConfirm: "/api/auth/password-reset/confirm",
  passwordResetValidate: "/api/auth/password-reset/validate",
  health: "/api/health",
  borrowers: "/api/borrowers",
  loanProducts: "/api/loan-products",
  loans: "/api/loans",
  repayments: "/api/repayments",
  expenses: "/api/expenses",
  employees: "/api/employees",
  payroll: "/api/payroll",
  auditLogs: "/api/audit-logs",
  dashboard: "/api/dashboard/summary",
  calculator: "/api/loan-calculator/preview",
  penalties: "/api/penalties",
  assets: "/api/assets",
  leaveRequests: "/api/leave-requests",
  capitalSummary: "/api/capital/summary",
  capitalOpening: "/api/capital/opening",
  capitalEntries: "/api/capital/entries",
  capitalInjections: "/api/capital/injections",
  capitalWithdrawals: "/api/capital/withdrawals",
  capitalProjection: "/api/capital/projection",
  users: "/api/users",
  assetTypes: "/api/asset-types",
  environmentLabel: "/api/environment-label",
};

export const auth = {
  async login({ email, password }) {
    const payload = await request(ENDPOINTS.login, {
      method: "POST",
      auth: false,
      body: { email, password },
    });
    const token = payload?.token || payload?.access_token || payload?.data?.token;
    if (!token) throw new ApiError("Login response did not include a token.", 500, payload, false);
    setSession(token, payload?.user || payload?.data?.user || null);
    return { token, user: getUser() };
  },
  register: (data) => request("/api/auth/register", { method: "POST", body: data }),
  requestPasswordReset: (email) =>
    request(ENDPOINTS.passwordResetRequest, {
      method: "POST",
      auth: false,
      body: { email },
    }),
  confirmPasswordReset: (token, password) =>
    request(ENDPOINTS.passwordResetConfirm, {
      method: "POST",
      auth: false,
      body: { token, password },
    }),
  // Called BEFORE the set-password form ever renders (Part 2) — auth:false
  // means no Authorization header is sent at all, so whatever session is
  // active in this browser is structurally irrelevant to the result.
  validateResetToken: (token) =>
    request(ENDPOINTS.passwordResetValidate, {
      method: "POST",
      auth: false,
      body: { token },
    }),
  resendVerification: (email) => request("/api/auth/resend-verification", { method: "POST", auth: false, body: { email } }),
  // The only way out of must_change_password=true (AppShell's gate) — also
  // usable any time by an already-signed-in user to change their password
  // voluntarily, mirroring the backend's one `/api/auth/change-password`.
  changePassword: (current_password, new_password) =>
    request("/api/auth/change-password", { method: "POST", body: { current_password, new_password } }),
  me: verifySession,
  logout() {
    clearSession();
  },
};

export const users = {
  async list(params) {
    if (params) {
      const result = await paginatedList(ENDPOINTS.users, "users", params);
      return { ...result, retentionDays: result.raw?.retention_days ?? 30 };
    }
    const payload = await request(ENDPOINTS.users);
    return { data: toList(payload, "users"), retentionDays: payload?.retention_days ?? 30 };
  },
  deactivate: (id) => request(`${ENDPOINTS.users}/${id}`, { method: "PATCH", body: { is_active: false } }),
  reactivate: (id) => request(`${ENDPOINTS.users}/${id}`, { method: "PATCH", body: { is_active: true } }),
  updateRole: (id, role, department) =>
    request(`${ENDPOINTS.users}/${id}`, { method: "PATCH", body: department !== undefined ? { role, department } : { role } }),
  updateDepartment: (id, department) => request(`${ENDPOINTS.users}/${id}`, { method: "PATCH", body: { department } }),
  resendVerification: (id) => request(`${ENDPOINTS.users}/${id}/resend-verification`, { method: "POST", body: {} }),
  linkEmployee: (id, employee_id) =>
    request(`${ENDPOINTS.users}/${id}/link-employee`, { method: "POST", body: { employee_id } }),
  remove: (id) => request(`${ENDPOINTS.users}/${id}`, { method: "DELETE" }),
};

export const health = {
  check: () => request(ENDPOINTS.health, { auth: false }),
};

export const environment = {
  // Phase 7 item 1: public — the login page needs this before anyone is
  // signed in. { environment_label: string | null }.
  label: () => request(ENDPOINTS.environmentLabel, { auth: false }),
};

export const borrowers = {
  list: (params) => (params ? paginatedList(ENDPOINTS.borrowers, "borrowers", params) : list(ENDPOINTS.borrowers, "borrowers")),
  /** data is a plain object; files: { photo?: File, id_document?: File } are sent as multipart. */
  create(data, files = {}) {
    const hasFiles = Boolean(files.photo || files.id_document);
    if (!hasFiles) return request(ENDPOINTS.borrowers, { method: "POST", body: data });
    const form = new FormData();
    Object.entries(data).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") form.append(key, value);
    });
    if (files.photo) form.append("photo", files.photo);
    if (files.id_document) form.append("id_document", files.id_document);
    return request(ENDPOINTS.borrowers, { method: "POST", body: form });
  },
  async get(id) {
    return { data: toItem(await request(`${ENDPOINTS.borrowers}/${id}`), "borrower") };
  },
  update: (id, data) => request(`${ENDPOINTS.borrowers}/${id}`, { method: "PUT", body: data }),
  verifyId: (id) => request(`${ENDPOINTS.borrowers}/${id}/verify-id`, { method: "POST", body: {} }),
  upload(id, kind, file) {
    const form = new FormData();
    form.append("file", file);
    return request(`${ENDPOINTS.borrowers}/${id}/${kind}`, { method: "POST", body: form });
  },
  /** Uploaded files are behind auth, so they are fetched with the token.
   * Returns the raw Blob (its `.type` tells the caller whether to render an
   * <img> or a PDF viewer — Part 3.1: an ID document upload can be a PDF). */
  fileBlob(id, kind) {
    return downloadBlob(`${ENDPOINTS.borrowers}/${id}/${kind}`);
  },
};

export const loanProducts = {
  list: () => list(ENDPOINTS.loanProducts, "loan_products"),
  create: (data) => request(ENDPOINTS.loanProducts, { method: "POST", body: data }),
  update: (id, data) => request(`${ENDPOINTS.loanProducts}/${id}`, { method: "PUT", body: data }),
};

export const loans = {
  list: (params) => (params ? paginatedList(ENDPOINTS.loans, "loans", params) : list(ENDPOINTS.loans, "loans")),
  create: (data) => request(ENDPOINTS.loans, { method: "POST", body: data }),
  async get(id) {
    return { data: toItem(await request(`${ENDPOINTS.loans}/${id}`), "loan") };
  },
  approve: (id, body) => request(`${ENDPOINTS.loans}/${id}/approve`, { method: "POST", body: body || {} }),
  reject: (id, body) => request(`${ENDPOINTS.loans}/${id}/reject`, { method: "POST", body: body || {} }),
  async downloadSchedule(id) {
    triggerBlobDownload(await downloadBlob(`${ENDPOINTS.loans}/${id}/schedule/export`), `loan-${id}-schedule.pdf`);
  },
  settle: (id, data) => request(`${ENDPOINTS.loans}/${id}/settle`, { method: "POST", body: data || {} }),
};

export const repayments = {
  list: (params) => (params ? paginatedList(ENDPOINTS.repayments, "repayments", params) : list(ENDPOINTS.repayments, "repayments")),
  create: (data) => request(ENDPOINTS.repayments, { method: "POST", body: data }),
};

export const expenses = {
  list: () => list(ENDPOINTS.expenses, "expenses"),
  create: (data) => request(ENDPOINTS.expenses, { method: "POST", body: data }),
  approve: (id, body) => request(`${ENDPOINTS.expenses}/${id}/approve`, { method: "POST", body: body || {} }),
  reject: (id, body) => request(`${ENDPOINTS.expenses}/${id}/reject`, { method: "POST", body: body || {} }),
};

export const employees = {
  list: () => list(ENDPOINTS.employees, "employees"),
  create: (data) => request(ENDPOINTS.employees, { method: "POST", body: data }),
  update: (id, data) => request(`${ENDPOINTS.employees}/${id}`, { method: "PUT", body: data }),
  deactivate: (id) => request(`${ENDPOINTS.employees}/${id}`, { method: "DELETE" }),
  reactivate: (id) => request(`${ENDPOINTS.employees}/${id}`, { method: "PUT", body: { is_active: true } }),
  linkUser: (id, user_id) =>
    request(`${ENDPOINTS.employees}/${id}/link-user`, { method: "POST", body: { user_id } }),
  createLogin: (id, data) => request(`${ENDPOINTS.employees}/${id}/create-login`, { method: "POST", body: data }),
};

export const payroll = {
  /** Batches, each with its lines (employee names already resolved). */
  list: () => list(ENDPOINTS.payroll, "payroll"),
  create: (data) => request(ENDPOINTS.payroll, { method: "POST", body: data }),
  editLine: (batchId, lineId, data) =>
    request(`${ENDPOINTS.payroll}/${batchId}/lines/${lineId}`, { method: "PATCH", body: data }),
  adjustDeductionLine: (batchId, lineId, dlId, data) =>
    request(`${ENDPOINTS.payroll}/${batchId}/lines/${lineId}/deduction-lines/${dlId}`, { method: "PATCH", body: data }),
  removeLine: (batchId, lineId) =>
    request(`${ENDPOINTS.payroll}/${batchId}/lines/${lineId}`, { method: "DELETE" }),
  finalize: (id) => request(`${ENDPOINTS.payroll}/${id}/finalize`, { method: "POST", body: {} }),
  cancel: (id) => request(`${ENDPOINTS.payroll}/${id}/cancel`, { method: "POST", body: {} }),
  async downloadPayslip(lineId, filename) {
    triggerBlobDownload(await downloadBlob(`${ENDPOINTS.payroll}/lines/${lineId}/payslip`), filename || `payslip-${lineId}.pdf`);
  },
  sendPayslip: (lineId, resend = false) =>
    request(`${ENDPOINTS.payroll}/lines/${lineId}/payslip/send`, { method: "POST", body: { resend } }),
  sendAllPayslips: (batchId, resend = false) =>
    request(`${ENDPOINTS.payroll}/${batchId}/payslips/send-all`, { method: "POST", body: { resend } }),
};

export const deductionTypes = {
  list: () => list(`${ENDPOINTS.payroll}/deduction-types`, "deduction_types"),
  create: (data) => request(`${ENDPOINTS.payroll}/deduction-types`, { method: "POST", body: data }),
  update: (id, data) => request(`${ENDPOINTS.payroll}/deduction-types/${id}`, { method: "PUT", body: data }),
};

export const employeeDeductions = {
  list: (employeeId) => list(`${ENDPOINTS.payroll}/employee-deductions?employee_id=${employeeId}`, "employee_deductions"),
  listAll: () => list(`${ENDPOINTS.payroll}/employee-deductions`, "employee_deductions"),
  create: (data) => request(`${ENDPOINTS.payroll}/employee-deductions`, { method: "POST", body: data }),
  update: (id, data) => request(`${ENDPOINTS.payroll}/employee-deductions/${id}`, { method: "PUT", body: data }),
  stop: (id) => request(`${ENDPOINTS.payroll}/employee-deductions/${id}`, { method: "DELETE" }),
};

export const penalties = {
  list: (params = {}) => list(`${ENDPOINTS.penalties}?${new URLSearchParams(params)}`, "penalties"),
  create: (data) => request(ENDPOINTS.penalties, { method: "POST", body: data }),
  approve: (id, body) => request(`${ENDPOINTS.penalties}/${id}/approve`, { method: "POST", body: body || {} }),
  reject: (id, body) => request(`${ENDPOINTS.penalties}/${id}/reject`, { method: "POST", body: body || {} }),
  reverse: (id, reason) => request(`${ENDPOINTS.penalties}/${id}/reverse`, { method: "POST", body: { reason } }),
};

export const calculator = {
  preview: (data) => request(ENDPOINTS.calculator, { method: "POST", body: data }),
};

export const assets = {
  list: () => list(ENDPOINTS.assets, "assets"),
  create: (data) => request(ENDPOINTS.assets, { method: "POST", body: data }),
  update: (id, data) => request(`${ENDPOINTS.assets}/${id}`, { method: "PUT", body: data }),
  remove: (id) => request(`${ENDPOINTS.assets}/${id}`, { method: "DELETE" }),
};

export const assetTypes = {
  list: () => list(ENDPOINTS.assetTypes, "asset_types"),
  create: (name) => request(ENDPOINTS.assetTypes, { method: "POST", body: { name } }),
};

export const leaveRequests = {
  list: (params = {}) => list(`${ENDPOINTS.leaveRequests}?${new URLSearchParams(params)}`, "leave_requests"),
  create: (data) => request(ENDPOINTS.leaveRequests, { method: "POST", body: data }),
  // body may carry { start_date, end_date } to adjust the requested range
  // before approving (Part 9.2) — omitted, it approves as originally asked.
  approve: (id, body) => request(`${ENDPOINTS.leaveRequests}/${id}/approve`, { method: "POST", body: body || {} }),
  reject: (id, rejection_reason) => request(`${ENDPOINTS.leaveRequests}/${id}/reject`, { method: "POST", body: { rejection_reason } }),
};

export const capital = {
  // useResource() expects a { data } shape; these two endpoints return a
  // flat object (not a list), so wrap it rather than returning it bare.
  async summary() {
    return { data: await request(ENDPOINTS.capitalSummary) };
  },
  async projection() {
    return { data: await request(ENDPOINTS.capitalProjection) };
  },
  listOpening: () => list(ENDPOINTS.capitalOpening, "capital_entries"),
  listEntries: (type) => list(`${ENDPOINTS.capitalEntries}${type ? `?type=${type}` : ""}`, "capital_entries"),
  setOpening: (new_value, reason) => request(ENDPOINTS.capitalOpening, { method: "POST", body: { new_value, reason } }),
  injection: (amount, date, note) => request(ENDPOINTS.capitalInjections, { method: "POST", body: { amount, date, note } }),
  withdrawal: (amount, date, note) => request(ENDPOINTS.capitalWithdrawals, { method: "POST", body: { amount, date, note } }),
};

export const reports = {
  get: (path, params = {}) => request(`/api/reports/${path}?${new URLSearchParams(params)}`, { method: "GET" }),
  download: async (path, format, params = {}) => {
    const query = new URLSearchParams({ ...params, format });
    const response = await fetch(`${BASE_URL}/api/reports/${path}?${query}`, { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!response.ok) throw new ApiError(`Report download failed (${response.status})`, response.status, null, true);
    return response.blob();
  },
};

export const auditLogs = {
  list: (params) => (params ? paginatedList(ENDPOINTS.auditLogs, "audit_logs", params) : list(ENDPOINTS.auditLogs, "audit_logs")),
  async listActions() {
    return { data: (await request(`${ENDPOINTS.auditLogs}/actions`)).actions || [] };
  },
};

export const dashboard = {
  async summary() {
    return { data: toItem(await request(ENDPOINTS.dashboard), "summary") };
  },
};

export const backup = {
  status: () => request("/api/backup/status"),
  /** Downloads and saves the encrypted backup file; never returns the raw
   * bytes to the caller — the password that produced them is this
   * request's body only, never logged or stored. */
  async download(password) {
    const blob = await postDownloadBlob("/api/backup/download", { password });
    const filename = `backup-${new Date().toISOString().replace(/[:.]/g, "-")}.lmsbackup`;
    triggerBlobDownload(blob, filename);
  },
};

export const api = {
  auth,
  health,
  environment,
  borrowers,
  loanProducts,
  loans,
  repayments,
  expenses,
  employees,
  payroll,
  penalties,
  auditLogs,
  dashboard,
  calculator,
  assets,
  assetTypes,
  leaveRequests,
  capital,
  reports,
  users,
  request,
};

export default api;
