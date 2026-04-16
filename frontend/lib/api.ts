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
  FerGroupOptionCollection,
  FerSearchResult,
  FerTableDetail,
  FerKnowledgeImportJobStatus,
  FerKnowledgeImportResponse,
  FerWordsCandidate,
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

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type RequestBehavior = {
  retry?: boolean;
  redirectOnUnauthorized?: boolean;
};

async function requestInternal<T>(
  path: string,
  options: RequestInit = {},
  behavior: RequestBehavior = {},
): Promise<T> {
  const { retry = true, redirectOnUnauthorized = true } = behavior;
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
    if (ok) {
      return requestInternal<T>(path, options, { retry: false, redirectOnUnauthorized });
    }
  }

  if (res.status === 401 && redirectOnUnauthorized) {
    window.location.href = "/auth/login";
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new ApiError(
      err?.detail ?? (res.status === 401 ? "Unauthorized" : `HTTP ${res.status}`),
      res.status,
    );
  }
  if (res.status === 204) return null as T;
  return res.json();
}

export async function request<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  return requestInternal<T>(path, options, { retry, redirectOnUnauthorized: true });
}

export async function requestQuiet<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  return requestInternal<T>(path, options, { retry, redirectOnUnauthorized: false });
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
  meQuiet:  () => requestQuiet<CurrentUser>("/auth/me"),
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
  list:      (pid: string, estimateBatchId?: string | null, limit?: number, offset?: number) => {
    const params = new URLSearchParams();
    if (estimateBatchId) params.set("estimate_batch_id", estimateBatchId);
    if (limit != null) params.set("limit", String(limit));
    if (offset != null) params.set("offset", String(offset));
    const query = params.toString();
    return request<any>(`/projects/${pid}/gantt${query ? `?${query}` : ""}`);
  },
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
  updateFer: (pid: string, eid: string, body: { fer_table_id: number | null }) =>
    request<any>(`/projects/${pid}/estimates/${eid}/fer`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  confirmFerGroup: (pid: string, eid: string, body: { kind: "section" | "collection"; ref_id: number }) =>
    request<any>(`/projects/${pid}/estimates/${eid}/fer-group`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  ferGroupOptions: (pid: string, eid: string) =>
    request<{ collections: FerGroupOptionCollection[] }>(`/projects/${pid}/estimates/${eid}/fer-group-options`),
  updateFerGroupManual: (pid: string, eid: string, body: { kind: "section" | "collection"; ref_id: number }) =>
    request<any>(`/projects/${pid}/estimates/${eid}/fer-group-manual`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  matchFerVectorRow: (pid: string, eid: string) =>
    request<any>(`/projects/${pid}/estimates/${eid}/match-fer-vector`, {
      method: "POST",
    }),
  matchFerGroupVectorRow: (pid: string, eid: string) =>
    request<any>(`/projects/${pid}/estimates/${eid}/match-fer-group-vector`, {
      method: "POST",
    }),
  updateFerWords: (pid: string, eid: string, body: { entry_id: number | null }) =>
    request<any>(`/projects/${pid}/estimates/${eid}/fer-words`, {
      method: "PATCH",
    body: JSON.stringify(body),
    }),
  ferWordsCandidates: (pid: string, eid: string, limit = 5) =>
    request<FerWordsCandidate[]>(`/projects/${pid}/estimates/${eid}/fer-words-candidates?limit=${limit}`),
  matchFer: (pid: string, batchId: string) =>
    request<{ job_id: string; message: string }>(`/projects/${pid}/estimate-batches/${batchId}/match-fer`, { method: "POST" }),
  matchFerWords: (pid: string, batchId: string) =>
    request<{ job_id: string; message: string }>(`/projects/${pid}/estimate-batches/${batchId}/match-fer-words`, { method: "POST" }),
  upload:  (
    pid: string,
    file: File,
    startDate: string,
    workers: number,
    estimateKind: number,
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
  listQuiet:  (unreadOnly = false)  => requestQuiet<any[]>(`/notifications?unread_only=${unreadOnly}`),
  markRead:   (id: string)          => request<void>(`/notifications/${id}/read`, { method: "POST" }),
  markReadQuiet: (id: string)       => requestQuiet<void>(`/notifications/${id}/read`, { method: "POST" }),
  markAllRead: ()                   => request<void>("/notifications/read-all", { method: "POST" }),
  markAllReadQuiet: ()              => requestQuiet<void>("/notifications/read-all", { method: "POST" }),
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

  search: (
    q: string,
    limit = 50,
    scope?: { collectionId?: number | null; sectionId?: number | null },
  ) => {
    const params = new URLSearchParams({
      q,
      limit: String(limit),
    });
    if (scope?.collectionId != null) {
      params.set("collection_id", String(scope.collectionId));
    }
    if (scope?.sectionId != null) {
      params.set("section_id", String(scope.sectionId));
    }
    return request<FerSearchResult[]>(`/fer/search?${params.toString()}`);
  },

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

export const users = {
  search: (email: string, projectId?: string) => {
    const params = new URLSearchParams({ email, limit: "8" });
    if (projectId) {
      params.set("project_id", projectId);
    }
    return request<Array<{ id: string; name: string; email: string; avatar_url?: string | null }>>(
      `/users/search?${params.toString()}`
    );
  },
  me: () => request<any>("/users/me"),
};

export const admin = {
  stats: () => request<any>("/admin/stats"),
  listOrgs: (q = "", offset = 0, limit = 100) =>
    request<any>(`/admin/organizations?q=${encodeURIComponent(q)}&offset=${offset}&limit=${limit}`),
  updateOrgPlan: (orgId: string, plan: string) =>
    request<any>(`/admin/organizations/${orgId}/plan`, {
      method: "PATCH",
      body: JSON.stringify({ plan }),
    }),
  deleteOrg: (orgId: string) =>
    request<void>(`/admin/organizations/${orgId}`, { method: "DELETE" }),
  listUsers: (q = "", offset = 0, limit = 100) =>
    request<any>(`/admin/users?q=${encodeURIComponent(q)}&offset=${offset}&limit=${limit}`),
  updateUser: (
    userId: string,
    body: { is_active?: boolean; is_superadmin?: boolean; name?: string },
  ) =>
    request<any>(`/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  updateFerIgnored: (
    entityKind: "collection" | "section" | "subsection" | "table",
    entityId: number,
    ignored: boolean,
  ) =>
    request<any>(`/admin/fer/${entityKind}/${entityId}`, {
      method: "PATCH",
      body: JSON.stringify({ ignored }),
    }),
  deleteUser: (userId: string) =>
    request<void>(`/admin/users/${userId}`, { method: "DELETE" }),
  importFerKnowledge: (batchId: string) =>
    request<FerKnowledgeImportResponse>("/admin/fer-knowledge/import-batch", {
      method: "POST",
      body: JSON.stringify({ batch_id: batchId }),
    }),
  listFerKnowledgeImports: (limit = 10) =>
    request<{ items: FerKnowledgeImportJobStatus[] }>(`/admin/fer-knowledge/import-batch?limit=${limit}`),
  getFerKnowledgeImportStatus: (jobId: string) =>
    request<FerKnowledgeImportJobStatus>(`/admin/fer-knowledge/import-batch/${jobId}`),
};
