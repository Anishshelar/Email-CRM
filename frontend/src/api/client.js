const BASE = "";  // proxied via Vite to http://localhost:8000

async function get(path) {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json();
}

async function post(path, body) {
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
  return res.json();
}

async function patch(path, body) {
  const res = await fetch(BASE + path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PATCH ${path} → ${res.status}`);
  return res.json();
}

export const api = {
  // Email list + detail
  emails: (params = "") => get(`/api/emails${params}`),
  email: (id) => get(`/api/emails/${id}`),
  status: (jobId) => get(`/api/status/${jobId}`),

  // Thread
  threads: (contactEmail) => get(`/threads/${encodeURIComponent(contactEmail)}`),

  // Actions
  respond: (emailId, content, by = "human") =>
    post(`/respond/${emailId}`, { content, performed_by: by }),
  approveDraft: (draftId, approvedBy = "human") =>
    post(`/drafts/${draftId}/approve`, { approved_by: approvedBy }),
  updateDraft: (draftId, content) =>
    patch(`/drafts/${draftId}`, { proposed_content: content }),

  // Agent
  agentRun: (emailId) => post(`/agent/run/${emailId}`, {}),
  agentDryRun: (emailId) => post(`/agent/dry-run/${emailId}`, {}),

  // Analytics
  sentimentTrend: (sender, days = 30) =>
    get(`/analytics/sentiment-trend?sender=${encodeURIComponent(sender)}&days=${days}`),
  categoryBreakdown: () => get(`/analytics/category-breakdown`),

  // Dashboard
  dashboardStats: () => get(`/dashboard/stats`),

  // RAG
  ragSearch: (q, topK = 3) =>
    get(`/rag/search?q=${encodeURIComponent(q)}&top_k=${topK}`),

  // Web intelligence
  reputation: (company) =>
    get(`/intelligence/reputation?company=${encodeURIComponent(company)}`),

  // Contacts
  contact: (email) => get(`/contacts/${encodeURIComponent(email)}`),
  updateContactStatus: (email, status) =>
    patch(`/contacts/${encodeURIComponent(email)}/status`, { status }),

  // Audit
  audit: (entityType, entityId) => get(`/audit/${entityType}/${entityId}`),
};
