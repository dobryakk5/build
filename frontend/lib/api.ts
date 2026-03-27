// frontend/lib/api.ts
import type {
  EnirCollectionSummary,
  EnirParagraphFull,
  EnirParagraphShort,
  FerBrowseResponse,
  FerCollectionSummary,
  FerTableDetail,
  Project,
  User,
} from "./types";

const BASE = "/api";

type AuthPayload = {
  access_token: string;
  refresh_token: string;
  user: User;
};

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers ?? {}),
    },
  });

  if (res.status === 401) {
    const ok = await tryRefresh();
    if (!ok) { window.location.href = "/auth/login"; throw new Error("Unauthorized"); }
    return request<T>(path, options);
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail ?? `HTTP ${res.status}`);
  }
  if (res.status === 204) return null as T;
  return res.json();
}

async function tryRefresh(): Promise<boolean> {
  const refresh = localStorage.getItem("refresh_token");
  if (!refresh) return false;
  try {
    const res = await fetch(`${BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem("access_token",  data.access_token);
    localStorage.setItem("refresh_token", data.refresh_token);
    return true;
  } catch { return false; }
}

export const auth = {
  login:    (email: string, password: string) =>
    request<AuthPayload>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  register: (body: any) =>
    request<AuthPayload>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
  me:       () => request<User>("/auth/me"),
  logout:   () => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
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
  list:      (pid: string)                          => request<any>(`/projects/${pid}/gantt`),
  create:    (pid: string, body: any)               => request<any>(`/projects/${pid}/gantt`, { method: "POST", body: JSON.stringify(body) }),
  update:    (pid: string, tid: string, body: any)  => request<any>(`/projects/${pid}/gantt/${tid}`, { method: "PATCH", body: JSON.stringify(body) }),
  delete:    (pid: string, tid: string)             => request<any>(`/projects/${pid}/gantt/${tid}`, { method: "DELETE" }),
  reorder:   (pid: string, body: any)               => request<any>(`/projects/${pid}/gantt/reorder`, { method: "POST", body: JSON.stringify(body) }),
  resolve:   (pid: string)                          => request<any>(`/projects/${pid}/gantt/resolve`, { method: "POST" }),
  addDep:    (pid: string, tid: string, depId: string) =>
    request<any>(`/projects/${pid}/gantt/${tid}/dependencies`, { method: "POST", body: JSON.stringify({ depends_on: depId }) }),
  removeDep: (pid: string, tid: string, depId: string) =>
    request<void>(`/projects/${pid}/gantt/${tid}/dependencies/${depId}`, { method: "DELETE" }),
};

export const estimates = {
  list:    (pid: string)    => request<any[]>(`/projects/${pid}/estimates`),
  summary: (pid: string)    => request<any>(`/projects/${pid}/estimates/summary`),
  upload:  (pid: string, file: File, startDate: string, workers: number) => {
    const token = localStorage.getItem("access_token");
    const form  = new FormData();
    form.append("file", file);
    return fetch(
      `${BASE}/projects/${pid}/estimates/upload?start_date=${startDate}&workers=${workers}`,
      { method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {}, body: form }
    ).then(r => r.json());
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
