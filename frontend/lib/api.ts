// frontend/lib/api.ts
import type {
  BaselineStatus,
  CurrentUser,
  EnirCollectionSummary,
  EnirParagraphFull,
  EnirParagraphShort,
  JournalEntry,
  FerBrowseResponse,
  FerCollectionSummary,
  FerSearchResult,
  FerTableDetail,
  EstimateBatch,
  EstimateRow,
  EstimateSummary,
  Project,
  User,
} from "./types";

const BASE = "/api";

type AuthPayload = {
  user: User;
  email_verified: boolean;
  requires_email_verification: boolean;
};

const AUTH_REFRESH_SKIP = new Set([
  "/auth/login",
  "/auth/register",
  "/auth/refresh",
  "/auth/forgot-password",
  "/auth/reset-password",
  "/auth/verify-email",
]);

async function request<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;

  const res = await fetch(`${BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers ?? {}),
    },
  });

  if (res.status === 401 && retry && !AUTH_REFRESH_SKIP.has(path)) {
    const ok = await tryRefresh();
    if (!ok) { window.location.href = "/auth/login"; throw new Error("Unauthorized"); }
    return request<T>(path, options, false);
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail ?? `HTTP ${res.status}`);
  }
  if (res.status === 204) return null as T;
  return res.json();
}

async function tryRefresh(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) return false;
    return true;
  } catch { return false; }
}

export const auth = {
  login:    (email: string, password: string) =>
    request<AuthPayload>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  register: (body: any) =>
    request<AuthPayload>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
  me:       () => request<CurrentUser>("/auth/me"),
  verifyEmail: (token: string) =>
    request<{ verified: boolean }>("/auth/verify-email", { method: "POST", body: JSON.stringify({ token }) }),
  resendVerification: () =>
    request<void>("/auth/resend-verification", { method: "POST" }),
  forgotPassword: (email: string) =>
    request<void>("/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) }),
  resetPassword: (token: string, newPassword: string) =>
    request<void>("/auth/reset-password", { method: "POST", body: JSON.stringify({ token, new_password: newPassword }) }),
  logout:   async () => {
    await request<void>("/auth/logout", { method: "POST" }).catch(() => undefined);
    window.location.href = "/auth/login";
  },
};

export const projects = {
  list:         ()                          => request<Project[]>("/projects"),
  get:          (id: string)               => request<Project>(`/projects/${id}`),
  create:       (body: any)                => request<Project>("/projects", { method: "POST", body: JSON.stringify(body) }),
  update:       (id: string, body: any)    => request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  delete:       (id: string)               => request<void>(`/projects/${id}`, { method: "DELETE" }),
  listMembers:  (id: string)               => request<any[]>(`/projects/${id}/members`),
  addMember:    (id: string, body: any)    => request<any>(`/projects/${id}/members`, { method: "POST", body: JSON.stringify(body) }),
  updateMember: (id: string, uid: string, body: any) =>
    request<any>(`/projects/${id}/members/${uid}`, { method: "PATCH", body: JSON.stringify(body) }),
  removeMember: (id: string, uid: string)  => request<void>(`/projects/${id}/members/${uid}`, { method: "DELETE" }),
};

export const gantt = {
  list:      (pid: string, estimateBatchId?: string | null) =>
    request<any>(`/projects/${pid}/gantt${estimateBatchId ? `?estimate_batch_id=${estimateBatchId}` : ""}`),
  create:    (pid: string, body: any)               => request<any>(`/projects/${pid}/gantt`, { method: "POST", body: JSON.stringify(body) }),
  update:    (pid: string, tid: string, body: any)  => request<any>(`/projects/${pid}/gantt/${tid}`, { method: "PATCH", body: JSON.stringify(body) }),
  split:     (pid: string, tid: string, body: any)  => request<any>(`/projects/${pid}/gantt/${tid}/split`, { method: "POST", body: JSON.stringify(body) }),
  delete:    (pid: string, tid: string)             => request<any>(`/projects/${pid}/gantt/${tid}`, { method: "DELETE" }),
  reorder:   (pid: string, body: any)               => request<any>(`/projects/${pid}/gantt/reorder`, { method: "POST", body: JSON.stringify(body) }),
  resolve:   (pid: string)                          => request<any>(`/projects/${pid}/gantt/resolve`, { method: "POST" }),
  baselineStatus: (pid: string)                    => request<BaselineStatus>(`/projects/${pid}/gantt/baseline-status`),
  acceptOverdue: (pid: string, body: { reason?: string | null }) =>
    request<any>(`/projects/${pid}/gantt/accept-overdue`, { method: "POST", body: JSON.stringify(body) }),
  addDep:    (pid: string, tid: string, depId: string) =>
    request<any>(`/projects/${pid}/gantt/${tid}/dependencies`, { method: "POST", body: JSON.stringify({ depends_on: depId }) }),
  removeDep: (pid: string, tid: string, depId: string) =>
    request<void>(`/projects/${pid}/gantt/${tid}/dependencies/${depId}`, { method: "DELETE" }),
};

export const estimates = {
  list:    (pid: string, estimateBatchId?: string | null) =>
    request<EstimateRow[]>(`/projects/${pid}/estimates${estimateBatchId ? `?estimate_batch_id=${estimateBatchId}` : ""}`),
  summary: (pid: string, estimateBatchId?: string | null) =>
    request<EstimateSummary>(`/projects/${pid}/estimates/summary${estimateBatchId ? `?estimate_batch_id=${estimateBatchId}` : ""}`),
  batches: (pid: string) => request<EstimateBatch[]>(`/projects/${pid}/estimate-batches`),
  updateActs: (pid: string, eid: string, body: {
    req_hidden_work_act?: boolean;
    req_intermediate_act?: boolean;
    req_ks2_ks3?: boolean;
  }) =>
    request<any>(`/projects/${pid}/estimates/${eid}/acts`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  matchFer: (pid: string, batchId: string) =>
    request<{ job_id: string; message: string }>(`/projects/${pid}/estimate-batches/${batchId}/match-fer`, { method: "POST" }),
  upload:  (
    pid: string,
    file: File,
    startDate: string,
    workers: number,
    estimateKind: string,
    complexMode: boolean,
  ) => {
    const form  = new FormData();
    form.append("file", file);
    return fetch(
      `${BASE}/projects/${pid}/estimates/upload?start_date=${startDate}&workers=${workers}&estimate_kind=${encodeURIComponent(estimateKind)}&complex_mode=${complexMode}`,
      { method: "POST", credentials: "include", body: form }
    ).then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (r.status === 401) {
        const ok = await tryRefresh();
        if (ok) {
          return estimates.upload(pid, file, startDate, workers, estimateKind, complexMode);
        }
      }
      if (!r.ok) {
        throw new Error(data?.detail?.error ?? data?.detail ?? `HTTP ${r.status}`);
      }
      return data;
    });
  },
};

export const jobs = {
  get: (jobId: string) => request<any>(`/jobs/${jobId}`),
};

export const comments = {
  list:   (pid: string, tid: string)                    => request<any[]>(`/projects/${pid}/tasks/${tid}/comments`),
  create: (pid: string, tid: string, body: any)         => request<any>(`/projects/${pid}/tasks/${tid}/comments`, { method: "POST", body: JSON.stringify(body) }),
  update: (pid: string, tid: string, cid: string, body: any) =>
    request<any>(`/projects/${pid}/tasks/${tid}/comments/${cid}`, { method: "PATCH", body: JSON.stringify(body) }),
  delete: (pid: string, tid: string, cid: string)       => request<void>(`/projects/${pid}/tasks/${tid}/comments/${cid}`, { method: "DELETE" }),
};

export const reports = {
  list:   (pid: string)               => request<any[]>(`/projects/${pid}/reports`),
  journal:(pid: string)               => request<JournalEntry[]>(`/projects/${pid}/reports/journal`),
  today:  (pid: string)               => request<any>(`/projects/${pid}/reports/today`),
  get:    (pid: string, rid: string)  => request<any>(`/projects/${pid}/reports/${rid}`),
  create: (pid: string, body: any)    => request<any>(`/projects/${pid}/reports`, { method: "POST", body: JSON.stringify(body) }),
  submit: (pid: string, rid: string)  => request<any>(`/projects/${pid}/reports/${rid}/submit`, { method: "POST" }),
  review: (pid: string, rid: string)  => request<any>(`/projects/${pid}/reports/${rid}/review`, { method: "POST" }),
};

export const notifications = {
  list:       (unreadOnly = false)  => request<any[]>(`/notifications?unread_only=${unreadOnly}`),
  markRead:   (id: string)          => request<void>(`/notifications/${id}/read`, { method: "POST" }),
  markAllRead: ()                   => request<void>("/notifications/read-all", { method: "POST" }),
};

export const dashboard = {
  get: () => request<any>("/dashboard"),
};

export const materials = {
  list:   (pid: string, type?: string) =>
    request<any[]>(`/projects/${pid}/materials${type ? `?type=${type}` : ""}`),
  create: (pid: string, body: any) =>
    request<any>(`/projects/${pid}/materials`, { method: "POST", body: JSON.stringify(body) }),
  update: (pid: string, mid: string, body: any) =>
    request<any>(`/projects/${pid}/materials/${mid}`, { method: "PATCH", body: JSON.stringify(body) }),
  reportDelay: (pid: string, mid: string, body: { new_delivery_date: string; reason: string }) =>
    request<any>(`/projects/${pid}/materials/${mid}/delay`, { method: "POST", body: JSON.stringify(body) }),
  delete: (pid: string, mid: string) =>
    request<void>(`/projects/${pid}/materials/${mid}`, { method: "DELETE" }),
};

// ── ЕНИР ──────────────────────────────────────────────────────────────────────
export const enir = {
  /** Список всех сборников (Е1, Е2, Е3 …) с числом параграфов */
  collections: () =>
    request<EnirCollectionSummary[]>("/enir"),

  /** Параграфы одного сборника, с опциональным текстовым фильтром */
  paragraphs: (collectionId: number, q?: string) =>
    request<EnirParagraphShort[]>(
      `/enir/${collectionId}/paragraphs${q ? `?q=${encodeURIComponent(q)}` : ""}`
    ),

  /** Полный параграф (нормы, состав работ, звено, примечания) */
  paragraph: (paragraphId: number) =>
    request<EnirParagraphFull>(`/enir/paragraph/${paragraphId}`),

  /** Поиск по всем сборникам */
  search: (q: string, collectionId?: number) =>
    request<EnirParagraphShort[]>(
      `/enir/search?q=${encodeURIComponent(q)}` +
      (collectionId != null ? `&collection_id=${collectionId}` : "")
    ),
};

export const fer = {
  collections: () =>
    request<FerCollectionSummary[]>("/fer/collections"),

  search: (q: string, limit = 50) =>
    request<FerSearchResult[]>(`/fer/search?q=${encodeURIComponent(q)}&limit=${limit}`),

  browse: (params: { collectionId: number; sectionId?: number; subsectionId?: number }) => {
    const search = new URLSearchParams({
      collection_id: String(params.collectionId),
    });
    if (params.sectionId != null) {
      search.set("section_id", String(params.sectionId));
    }
    if (params.subsectionId != null) {
      search.set("subsection_id", String(params.subsectionId));
    }
    return request<FerBrowseResponse>(`/fer/browse?${search.toString()}`);
  },

  table: (tableId: number) =>
    request<FerTableDetail>(`/fer/table/${tableId}`),
};
