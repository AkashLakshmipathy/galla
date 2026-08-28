// One place that talks to the backend. Every screen goes through here so that
// polling cadence, error shape and the offline flag are consistent.
const BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    headers: options.body ? { "content-type": "application/json" } : undefined,
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
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

  demoScenarios: () => request("/api/demo/scenarios"),
  demoSend: (key) => request(`/api/demo/send/${key}`, { method: "POST" }),
  demoReset: () => request("/api/demo/reset", { method: "POST" }),

  upload: async (file, kind) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    const response = await fetch(`${BASE}/api/upload`, { method: "POST", body: form });
    if (!response.ok) throw new ApiError("upload failed", response.status);
    return response.json();
  },
  ingest: (body) => request("/ingest", { method: "POST", body }),
};
