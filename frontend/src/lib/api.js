/**
 * Central API helper.
 *
 * - Base URL comes from VITE_API_BASE_URL (fallback: http://localhost:5000)
 * - Attaches the JWT from localStorage as an Authorization Bearer token
 * - On 401 it clears the token and redirects to the login page
 * - Endpoint paths are grouped in ENDPOINTS so they are easy to rename
 */

export const BASE_URL = String(
  import.meta.env.VITE_API_BASE_URL || "http://localhost:5000",
).replace(/\/+$/, "");

export const TOKEN_KEY = "lms_token";
export const USER_KEY = "lms_user";
export const LOGIN_PATH = "/";

/* ------------------------------------------------------------------ session */

export function getToken() {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getUser() {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setSession(token, user) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token || "");
  if (user) window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export function isAuthenticated() {
  return Boolean(getToken());
}

/* -------------------------------------------------------------------- errors */

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
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

export function errorMessage(error) {
  if (isMakerCheckerError(error)) {
    return "Maker-checker rule: you created this record, so someone else must approve or reject it.";
  }
  if (error instanceof ApiError && error.status === 404) {
    return "This API endpoint is not available yet.";
  }
  if (error instanceof ApiError && error.status === 0) {
    return `Unable to connect to the API at ${BASE_URL}.`;
  }
  return error?.message || "Something went wrong.";
}

/* ------------------------------------------------------------------- request */

async function request(path, options = {}) {
  const { method = "GET", body, auth = true, headers = {} } = options;
  const token = auth ? getToken() : null;

  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        Accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (networkError) {
    throw new ApiError(networkError?.message || "Network request failed", 0);
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
    clearSession();
    if (typeof window !== "undefined" && window.location.pathname !== LOGIN_PATH) {
      window.location.assign(LOGIN_PATH);
    }
    throw new ApiError("Your session expired. Please sign in again.", 401, payload);
  }

  if (!response.ok) {
    const message =
      payload?.message || payload?.error || payload?.detail || `Request failed (${response.status})`;
    throw new ApiError(message, response.status, payload);
  }

  return payload;
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

/* ----------------------------------------------------------------- endpoints */

export const ENDPOINTS = {
  login: "/api/auth/login",
  passwordResetRequest: "/api/auth/password-reset/request",
  passwordResetConfirm: "/api/auth/password-reset/confirm",
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
  users: "/api/users",
};

export const auth = {
  async login({ email, password }) {
    const payload = await request(ENDPOINTS.login, {
      method: "POST",
      auth: false,
      body: { email, password },
    });
    const token = payload?.token || payload?.access_token || payload?.data?.token;
    if (!token) throw new ApiError("Login response did not include a token.", 500, payload);
    setSession(token, payload?.user || payload?.data?.user || { phone });
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
  logout() {
    clearSession();
  },
};

export const users = {
  list: () => list(ENDPOINTS.users, "users"),
  deactivate: (id) => request(`${ENDPOINTS.users}/${id}`, { method: "PATCH", body: { is_active: false } }),
};

export const health = {
  check: () => request(ENDPOINTS.health, { auth: false }),
};

export const borrowers = {
  list: () => list(ENDPOINTS.borrowers, "borrowers"),
  create: (data) => request(ENDPOINTS.borrowers, { method: "POST", body: data }),
  async get(id) {
    return { data: toItem(await request(`${ENDPOINTS.borrowers}/${id}`), "borrower") };
  },
};

export const loanProducts = {
  list: () => list(ENDPOINTS.loanProducts, "loan_products"),
  create: (data) => request(ENDPOINTS.loanProducts, { method: "POST", body: data }),
  update: (id, data) => request(`${ENDPOINTS.loanProducts}/${id}`, { method: "PUT", body: data }),
};

export const loans = {
  list: () => list(ENDPOINTS.loans, "loans"),
  create: (data) => request(ENDPOINTS.loans, { method: "POST", body: data }),
  approve: (id, body) => request(`${ENDPOINTS.loans}/${id}/approve`, { method: "POST", body: body || {} }),
  reject: (id, body) => request(`${ENDPOINTS.loans}/${id}/reject`, { method: "POST", body: body || {} }),
};

export const repayments = {
  list: () => list(ENDPOINTS.repayments, "repayments"),
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
};

export const payroll = {
  list: () => list(ENDPOINTS.payroll, "payroll"),
  create: (data) => request(ENDPOINTS.payroll, { method: "POST", body: data }),
  approve: (id, body) => request(`${ENDPOINTS.payroll}/${id}/approve`, { method: "POST", body: body || {} }),
  reject: (id, body) => request(`${ENDPOINTS.payroll}/${id}/reject`, { method: "POST", body: body || {} }),
};

export const penalties = {
  list: (params = {}) => list(`${ENDPOINTS.penalties}?${new URLSearchParams(params)}`, "penalties"),
  create: (data) => request(ENDPOINTS.penalties, { method: "POST", body: data }),
  approve: (id, body) => request(`${ENDPOINTS.penalties}/${id}/approve`, { method: "POST", body: body || {} }),
  reject: (id, body) => request(`${ENDPOINTS.penalties}/${id}/reject`, { method: "POST", body: body || {} }),
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

export const leaveRequests = {
  list: (params = {}) => list(`${ENDPOINTS.leaveRequests}?${new URLSearchParams(params)}`, "leave_requests"),
  create: (data) => request(ENDPOINTS.leaveRequests, { method: "POST", body: data }),
  approve: (id) => request(`${ENDPOINTS.leaveRequests}/${id}/approve`, { method: "POST", body: {} }),
  reject: (id, rejection_reason) => request(`${ENDPOINTS.leaveRequests}/${id}/reject`, { method: "POST", body: { rejection_reason } }),
};

export const capital = {
  summary: () => request(ENDPOINTS.capitalSummary),
};

export const reports = {
  get: (path, params = {}) => request(`/api/reports/${path}?${new URLSearchParams(params)}`, { method: "GET" }),
  download: async (path, format, params = {}) => {
    const query = new URLSearchParams({ ...params, format });
    const response = await fetch(`${BASE_URL}/api/reports/${path}?${query}`, { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!response.ok) throw new ApiError(`Report download failed (${response.status})`, response.status);
    return response.blob();
  },
};

export const auditLogs = {
  list: () => list(ENDPOINTS.auditLogs, "audit_logs"),
};

export const dashboard = {
  async summary() {
    return { data: toItem(await request(ENDPOINTS.dashboard), "summary") };
  },
};

export const api = {
  auth,
  health,
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
  penalties,
  assets,
  leaveRequests,
  capital,
  reports,
  users,
  request,
};

export default api;
