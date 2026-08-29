// One place that talks to the backend. Every screen goes through here so that
// polling cadence, error shape and the offline flag are consistent.
const BASE = import.meta.env.VITE_API_BASE ?? "";
const TOKEN_KEY = "galla.session";

export const session = {
  get: () => {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;          // private browsing, or storage blocked
    }
  },
  set: (token) => {
    try {
      localStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* the app still works for this session, it just will not be remembered */
    }
  },
  clear: () => {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* nothing to do */
    }
  },
};

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  const token = session.get();
  const headers = { ...(options.headers ?? {}) };
  if (options.body) headers["content-type"] = "application/json";
  if (token) headers.authorization = `Bearer ${token}`;

  const response = await fetch(`${BASE}${path}`, {
    ...options,
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (response.status === 401) {
    // The passcode changed, or the session simply aged out. Drop the stale
    // token so the app falls back to its lock screen rather than looping.
    session.clear();
    window.dispatchEvent(new Event("galla:signed-out"));
    throw new ApiError("sign in required", 401);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* a non-JSON error body is still an error */
    }
    throw new ApiError(detail, response.status);
  }
  return response.status === 204 ? null : response.json();
}

export const api = {
  setupState: () => request("/api/setup/state"),
  setupShop: (body) => request("/api/setup", { method: "POST", body }),
  signIn: (passcode) => request("/api/session", { method: "POST", body: { passcode } }),
  eraseEverything: (passcode, confirm) =>
    request("/api/setup/erase", { method: "POST", body: { passcode, confirm } }),

  fleet: () => request("/api/fleet"),
  shop: () => request("/api/shop"),
  counter: () => request("/api/counter"),
  order: (id) => request(`/api/orders/${id}`),
  trace: (id) => request(`/api/traces/${id}`),
  approvals: () => request("/api/approvals"),
  confirmQueue: () => request("/api/confirm-queue"),
  purchase: (id) => request(`/api/purchases/${id}`),
  khata: (id) => request(`/api/khata/${id}`),
  parties: () => request("/api/parties"),
  ledger: (id) => request(`/api/parties/${id}/ledger`),
  inventory: () => request("/api/inventory"),
  credit: () => request("/api/credit"),
  duplicates: () => request("/api/parties/duplicates"),
  dashboard: () => request("/api/dashboard"),
  gst: () => request("/api/gst"),
  gstPeriod: (period) => request(`/api/gst/${period}`),

  decide: (id, body) => request(`/api/orders/${id}/decision`, { method: "POST", body }),
  editLines: (id, edits) => request(`/api/orders/${id}/lines`, { method: "PATCH", body: edits }),
  substitute: (id, body) => request(`/api/orders/${id}/substitute`, { method: "POST", body }),
  resolveQueueItem: (id, body) =>
    request(`/api/confirm-queue/${id}/resolve`, { method: "POST", body }),
  editPurchaseLines: (id, edits) =>
    request(`/api/purchases/${id}/lines`, { method: "PATCH", body: edits }),
  confirmPurchase: (id) => request(`/api/purchases/${id}/confirm`, { method: "POST" }),
  editKhataRows: (id, rows) => request(`/api/khata/${id}/rows`, { method: "POST", body: rows }),
  commitKhata: (id) => request(`/api/khata/${id}/commit`, { method: "POST" }),
  mergeParties: (source_id, target_id) =>
    request("/api/parties/merge", { method: "POST", body: { source_id, target_id } }),

  demoScenarios: () => request("/api/demo/scenarios"),
  demoSend: (key) => request(`/api/demo/send/${key}`, { method: "POST" }),
  demoReset: () => request("/api/demo/reset", { method: "POST" }),

  scan: async (files, kind) => {
    const form = new FormData();
    [...files].forEach((f) => form.append("files", f));
    form.append("kind", kind);
    const token = session.get();
    const response = await fetch(`${BASE}/api/scan`, {
      method: "POST", body: form,
      headers: token ? { authorization: `Bearer ${token}` } : undefined,
    });
    if (!response.ok) throw new ApiError("upload failed", response.status);
    return response.json();
  },
  upload: async (file, kind) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    const token = session.get();
    const response = await fetch(`${BASE}/api/upload`, {
      method: "POST", body: form,
      headers: token ? { authorization: `Bearer ${token}` } : undefined,
    });
    if (!response.ok) throw new ApiError("upload failed", response.status);
    return response.json();
  },
  ingest: (body) => request("/ingest", { method: "POST", body }),
};
