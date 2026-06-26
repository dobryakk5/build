// frontend/lib/api.ts
import type {
  BaselineStatus,
  ActivityEvent,
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
  PreviewResult,
  PreviewEdits,
  KtpCard,
  KtpGenerateResponse,
  KtpGroup,
  KtpEstimateSession,
  KtpEstimateCard,
  KtpEstimateCardResponse,
  KtpSessionSubtype,
  KtpWbs,
  NwDictionaries,
  NwFerMapping,
  NwItem,
  NwItemDetail,
  NwWorkType,
  WorkTaxonomySection,
  WorkTaxonomySubtype,
  WorkProjectHierarchy,
  WorkEstimateType,
  WorkProjectVariant,
  WorkStage,
  WorkPlanAutoSummary,
  WorkPlanCard,
  WorkPlanCardPatch,
  WorkPlanCardDetail,
  WorkPlanPalette,
  WorkPlanResponse,
  Project,
  User,
} from "./types";

const BASE = "/api";
const DYNAMIC_FLOOR_VARIANT_ID = "residential_construction_kirpichnye_doma";

type Stage10PreviewRow = {
  source_row_key: string;
  source_row_index: number;
  source_text: string;
  parsed_data?: Record<string, any> | null;
  classification_result?: Record<string, any> | null;
};

type Stage10PreviewResponse = {
  preview_session_id: string;
  project_id: string;
  project_variant_id: string;
  status: string;
  preview_content_hash: string;
  expires_at?: string | null;
  building_params?: Record<string, any> | null;
  project_structure_options?: Record<string, any> | null;
  rows: Stage10PreviewRow[];
};

type Stage10ConfirmResponse = {
  preview_session_id: string;
  estimate_batch_id: string;
  outbox_record_id: string;
  idempotency_key: string;
  snapshot_hash: string;
};

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

let refreshPromise: Promise<boolean> | null = null;

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function apiErrorMessage(data: any, fallback: string): string {
  const detail = data?.detail;
  if (detail?.code === "database_unavailable") {
    return "База данных временно недоступна. Повторите попытку после восстановления PostgreSQL.";
  }
  if (detail?.code === "dynamic_floor_structure_2_7_disabled") {
    return "Вариант 2.7 выключен флагом DYNAMIC_FLOOR_STRUCTURE_2_7_MODE.";
  }
  if (detail?.code === "dynamic_floor_structure_2_7_not_allowed") {
    return "Вариант 2.7 доступен только пользователям из allowlist.";
  }
  if (detail?.code === "dynamic_floor_structure_2_7_allowlist_invalid") {
    return "Некорректная конфигурация allowlist для варианта 2.7.";
  }
  if (typeof detail === "string") return detail;
  if (detail?.code) return detail.code;
  if (detail?.detail) return detail.detail;
  if (detail?.error) return detail.error;
  return fallback;
}

function stage10PreviewToLegacyPreview(data: Stage10PreviewResponse, filename: string, parserProfile: string): PreviewResult {
  const rows = (data.rows ?? []).map((row): any => {
    const parsed = row.parsed_data ?? {};
    const classification = row.classification_result ?? {};
    const total = Number(parsed.total_price ?? parsed.total ?? 0);
    return {
      index: row.source_row_index,
      row_order: row.source_row_index,
      section: parsed.section ?? null,
      item_type: classification.item_type ?? parsed.item_type ?? "work",
      name: parsed.work_name ?? parsed.name ?? row.source_text,
      unit: parsed.unit ?? null,
      quantity: parsed.quantity ?? null,
      total_price: Number.isFinite(total) ? total : 0,
      confidence: classification.classification_confidence ?? null,
      reason: classification.classification_review_reason ?? null,
      row_hash: row.source_row_key,
    };
  });
  const computedTotal = rows.reduce((sum, row) => sum + (Number(row.total_price) || 0), 0);
  const type_breakdown = {
    work: { count: 0, total: 0 },
    material: { count: 0, total: 0 },
    mechanism: { count: 0, total: 0 },
    overhead: { count: 0, total: 0 },
    unknown: { count: 0, total: 0 },
  } as PreviewResult["type_breakdown"];
  for (const row of rows) {
    const key = row.item_type in type_breakdown ? row.item_type : "unknown";
    type_breakdown[key as keyof typeof type_breakdown].count += 1;
    type_breakdown[key as keyof typeof type_breakdown].total += Number(row.total_price) || 0;
  }
  return {
    preview_id: data.preview_session_id,
    preview_backend: "db_stage10",
    preview_status: data.status,
    project_id: data.project_id,
    project_variant_id: data.project_variant_id,
    preview_content_hash: data.preview_content_hash,
    filename,
    parser_profile: parserProfile,
    detected_format: null,
    strategy: "db-backed 2.7",
    confidence: null,
    type_breakdown,
    computed_total_all_rows: computedTotal,
    declared_total: null,
    difference: null,
    difference_reason: null,
    unknown_count: type_breakdown.unknown.count,
    unknown_rows: rows.filter((row) => row.item_type === "unknown"),
    low_confidence_rows: [],
    sample_rows: rows.slice(0, 20),
    rows,
    ignored_subtotal_rows_count: 0,
    groups: [],
    stage_groups: [],
    hierarchy_suggestions: null,
    stage_review_count: 0,
    truncated: false,
    no_section_count: rows.filter((row) => !row.section).length,
    warnings: [],
  };
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
      apiErrorMessage(err, res.status === 401 ? "Unauthorized" : `HTTP ${res.status}`),
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
  if (!refreshPromise) {
    refreshPromise = fetch(`${BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
      .then((res) => res.ok)
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
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

export const activityEvents = {
  list: (pid: string, params: { eventType?: string; limit?: number; offset?: number } = {}) => {
    const search = new URLSearchParams();
    if (params.eventType) search.set("event_type", params.eventType);
    if (params.limit != null) search.set("limit", String(params.limit));
    if (params.offset != null) search.set("offset", String(params.offset));
    const query = search.toString();
    return request<ActivityEvent[]>(`/projects/${pid}/activity-events${query ? `?${query}` : ""}`);
  },
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
  clear:     (pid: string, estimateBatchId?: string | null) => {
    const params = new URLSearchParams();
    if (estimateBatchId) params.set("estimate_batch_id", estimateBatchId);
    const query = params.toString();
    return request<{ deleted: string[]; deleted_count: number }>(`/projects/${pid}/gantt/clear${query ? `?${query}` : ""}`, { method: "DELETE" });
  },
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
  createMechanism: (pid: string, body: {
    estimate_batch_id: string;
    section?: string | null;
    name: string;
    unit?: string | null;
    quantity?: number | null;
    unit_price?: number | null;
    total_price?: number | null;
  }) =>
    request<EstimateRow>(`/projects/${pid}/estimates/mechanisms`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteMechanism: (pid: string, estimateId: string) =>
    request<void>(`/projects/${pid}/estimates/${estimateId}`, { method: "DELETE" }),
  batches: (pid: string) => request<EstimateBatch[]>(`/projects/${pid}/estimate-batches`),
  updateBatchSchedule: (pid: string, batchId: string, body: { workers_count?: number; hours_per_day?: number }) =>
    request<{ id: string; workers_count: number; hours_per_day: number; updated_gantt_tasks_count: number }>(`/projects/${pid}/estimate-batches/${batchId}/schedule`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  updateBatchWorkers: (pid: string, batchId: string, workersCount: number) =>
    request<{ id: string; workers_count: number; updated_gantt_tasks_count: number }>(`/projects/${pid}/estimate-batches/${batchId}/workers`, {
      method: "PATCH",
      body: JSON.stringify({ workers_count: workersCount }),
    }),
  buildGantt: (pid: string, batchId: string, startDate?: string | null) =>
    request<{ id: string; start_date: string; gantt_tasks_count: number }>(`/projects/${pid}/estimate-batches/${batchId}/build-gantt`, {
      method: "POST",
      body: JSON.stringify({ start_date: startDate ?? null }),
    }),
  updateActs: (pid: string, eid: string, body: {
    req_hidden_work_act?: boolean;
    req_intermediate_act?: boolean;
    req_ks2_ks3?: boolean;
  }) =>
    request<any>(`/projects/${pid}/estimates/${eid}/acts`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  updateLaborHours: (pid: string, eid: string, laborHours: number | null) =>
    request<{ id: string; labor_hours: number | null }>(`/projects/${pid}/estimates/${eid}/labor-hours`, {
      method: "PATCH",
      body: JSON.stringify({ labor_hours: laborHours }),
    }),
  updateFerMultiplier: (pid: string, eid: string, ferMultiplier: number) =>
    request<{ id: string; fer_multiplier: number }>(`/projects/${pid}/estimates/${eid}/fer-multiplier`, {
      method: "PATCH",
      body: JSON.stringify({ fer_multiplier: ferMultiplier }),
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
    estimateTypeId?: string | null,
    projectVariantId?: string | null,
    clarificationAnswers?: Record<string, unknown>,
  ) => {
    const form  = new FormData();
    form.append("file", file);
    if (clarificationAnswers) {
      form.append("clarification_answers", JSON.stringify(clarificationAnswers));
    }
    return fetch(
      `${BASE}/projects/${pid}/estimates/upload?start_date=${startDate}&workers=${workers}&estimate_kind=${encodeURIComponent(estimateKind)}&complex_mode=${complexMode}` +
      `${estimateTypeId ? `&estimate_type_id=${encodeURIComponent(estimateTypeId)}` : ""}` +
      `${projectVariantId ? `&project_variant_id=${encodeURIComponent(projectVariantId)}` : ""}`,
      { method: "POST", credentials: "include", body: form }
    ).then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (r.status === 401) {
        const ok = await tryRefresh();
        if (ok) {
          return estimates.upload(pid, file, startDate, workers, estimateKind, complexMode, estimateTypeId, projectVariantId, clarificationAnswers);
        }
      }
      if (!r.ok) {
        if (r.status === 422 && data?.detail?.needs_mapping) {
          throw Object.assign(new Error("Требуется ручное сопоставление колонок"), {
            mappingPayload: data.detail,
          });
        }
        throw new Error(data?.detail?.error ?? data?.detail ?? `HTTP ${r.status}`);
      }
      return data;
    });
  },
  parserProfiles: (pid: string) =>
    request<{ profiles: { value: string; label: string }[] }>(
      `/projects/${pid}/estimates/parser-profiles`
    ),
  preview: (
    pid: string,
    file: File,
    startDate: string,
    workers: number,
    estimateKind: number,
    complexMode: boolean,
    estimateTypeId: string | null | undefined,
    projectVariantId: string | null | undefined,
    parserProfile: string,
    buildGantt: boolean,
    clarificationAnswers?: Record<string, unknown>,
    buildingParams?: Record<string, unknown>,
    projectStructureOptions?: Record<string, unknown>,
  ): Promise<PreviewResult> => {
    if (projectVariantId === DYNAMIC_FLOOR_VARIANT_ID) {
      return estimates.previewDbStage10(
        pid,
        file,
        estimateTypeId,
        projectVariantId,
        parserProfile,
        clarificationAnswers,
        buildingParams,
        projectStructureOptions,
      );
    }
    const form = new FormData();
    form.append("file", file);
    if (clarificationAnswers) {
      form.append("clarification_answers", JSON.stringify(clarificationAnswers));
    }
    const qs =
      `start_date=${startDate}&workers=${workers}` +
      `&estimate_kind=${encodeURIComponent(estimateKind)}` +
      `&complex_mode=${complexMode}` +
      `${estimateTypeId ? `&estimate_type_id=${encodeURIComponent(estimateTypeId)}` : ""}` +
      `${projectVariantId ? `&project_variant_id=${encodeURIComponent(projectVariantId)}` : ""}` +
      `&parser_profile=${encodeURIComponent(parserProfile)}` +
      `&build_gantt=${buildGantt}`;
    return fetch(`${BASE}/projects/${pid}/estimates/upload/preview?${qs}`, {
      method: "POST",
      credentials: "include",
      body: form,
    }).then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (r.status === 401) {
        const ok = await tryRefresh();
        if (ok) {
          return estimates.preview(pid, file, startDate, workers, estimateKind, complexMode, estimateTypeId, projectVariantId, parserProfile, buildGantt, clarificationAnswers, buildingParams, projectStructureOptions);
        }
      }
      if (!r.ok) {
        if (r.status === 422 && data?.detail?.needs_mapping) {
          throw Object.assign(new Error("Требуется ручное сопоставление колонок"), {
            mappingPayload: data.detail,
          });
        }
        throw new Error(data?.detail?.detail ?? data?.detail?.error ?? data?.detail ?? `HTTP ${r.status}`);
      }
      return data as PreviewResult;
    });
  },
  previewDbStage10: (
    pid: string,
    file: File,
    estimateTypeId: string | null | undefined,
    projectVariantId: string | null | undefined,
    parserProfile: string,
    clarificationAnswers?: Record<string, unknown>,
    buildingParams?: Record<string, unknown>,
    projectStructureOptions?: Record<string, unknown>,
  ): Promise<PreviewResult> => {
    const form = new FormData();
    form.append("file", file);
    form.append("metadata_json", JSON.stringify({
      project_id: pid,
      estimate_type_id: estimateTypeId,
      project_variant_id: projectVariantId,
      parser_profile: parserProfile,
      clarification_answers: clarificationAnswers ?? {},
      building_params: buildingParams ?? {},
      project_structure_options: projectStructureOptions ?? {},
    }));
    return fetch(`${BASE}/api/estimate-previews`, {
      method: "POST",
      credentials: "include",
      body: form,
    }).then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (r.status === 401) {
        const ok = await tryRefresh();
        if (ok) {
          return estimates.previewDbStage10(pid, file, estimateTypeId, projectVariantId, parserProfile, clarificationAnswers, buildingParams, projectStructureOptions);
        }
      }
      if (!r.ok) {
        throw new Error(apiErrorMessage(data, `HTTP ${r.status}`));
      }
      return stage10PreviewToLegacyPreview(data as Stage10PreviewResponse, file.name, parserProfile);
    });
  },
  getDbStage10Preview: (
    previewId: string,
    filename = "Восстановленное превью",
    parserProfile = "auto",
  ): Promise<PreviewResult> =>
    request<Stage10PreviewResponse>(`/estimate-previews/${encodeURIComponent(previewId)}`)
      .then((data) => stage10PreviewToLegacyPreview(data, filename, parserProfile)),
  cancelDbStage10: (previewId: string) =>
    request<void>(`/estimate-previews/${encodeURIComponent(previewId)}/cancel`, {
      method: "POST",
    }),
  confirmImport: (pid: string, previewId: string, buildGantt?: boolean, edits?: PreviewEdits) =>
    request<{ job_id: string }>(`/projects/${pid}/estimates/upload/confirm`, {
      method: "POST",
      body: JSON.stringify({ preview_id: previewId, build_gantt: buildGantt ?? null, edits: edits ?? null }),
    }),
  confirmDbStage10: (previewId: string, expectedPreviewContentHash: string) =>
    request<Stage10ConfirmResponse>(`/api/estimate-previews/${previewId}/confirm`, {
      method: "POST",
      body: JSON.stringify({
        expected_preview_content_hash: expectedPreviewContentHash,
        row_decisions: [],
      }),
    }),
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

export const foremanReports = {
  list: (pid: string, date?: string) =>
    request<any[]>(`/projects/${pid}/foreman-reports${date ? `?report_date=${date}` : ""}`),
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

export const ktp = {
  groups: (projectId: string, batchId: string) =>
    request<KtpGroup[]>(`/projects/${projectId}/ktp/groups?estimate_batch_id=${batchId}`),
  buildGroups: (projectId: string, batchId: string, force = false) =>
    request<KtpGroup[]>(`/projects/${projectId}/ktp/groups/build`, {
      method: "POST",
      body: JSON.stringify({ estimate_batch_id: batchId, force }),
    }),
  matchAi: (projectId: string, batchId: string, onlyUnmatched = true) =>
    request<KtpGroup[]>(`/projects/${projectId}/ktp/groups/match-ai`, {
      method: "POST",
      body: JSON.stringify({ estimate_batch_id: batchId, only_unmatched: onlyUnmatched }),
    }),
  group: (projectId: string, groupId: string) =>
    request<{ group: KtpGroup; card: KtpCard | null }>(`/projects/${projectId}/ktp/groups/${groupId}`),
  generate: (projectId: string, groupId: string, answers: Record<string, string> = {}) =>
    request<KtpGenerateResponse>(`/projects/${projectId}/ktp/groups/${groupId}/generate`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),
  card: (projectId: string, groupId: string) =>
    request<KtpCard>(`/projects/${projectId}/ktp/groups/${groupId}/card`),
};

export const ktpEstimate = {
  startSession: (
    projectId: string,
    batchId: string,
    force = false,
    preserveEstimateStructure = false,
  ) =>
    request<{ job_id: string | null; session_id: string; status: string }>(
      `/projects/${projectId}/ktp-estimate/sessions`,
      {
        method: "POST",
        body: JSON.stringify({
          estimate_batch_id: batchId,
          force,
          preserve_estimate_structure: preserveEstimateStructure,
        }),
      },
    ),
  getSession: (projectId: string, batchId: string) =>
    request<KtpEstimateSession | null>(
      `/projects/${projectId}/ktp-estimate/sessions?estimate_batch_id=${batchId}`,
    ),
  getWbs: (projectId: string, sessionId: string) =>
    request<KtpWbs>(`/projects/${projectId}/ktp-estimate/sessions/${sessionId}/wbs`),
  resetSession: (projectId: string, sessionId: string) =>
    request<void>(`/projects/${projectId}/ktp-estimate/sessions/${sessionId}`, {
      method: "DELETE",
    }),
  updateItem: (
    projectId: string,
    itemId: string,
    patch: Partial<{
      name: string;
      group_id: string;
      review_status: string;
      unit: string | null;
      quantity: number | null;
      sort_order: number;
      work_subtype_code: string;
      manual_override: boolean;
      reclassify: boolean;
    }>,
  ) =>
    request<KtpWbs>(`/projects/${projectId}/ktp-estimate/items/${itemId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  acceptStage1Items: (projectId: string, sessionId: string) =>
    request<KtpWbs>(`/projects/${projectId}/ktp-estimate/sessions/${sessionId}/accept-stage1-items`, {
      method: "POST",
    }),
  createItem: (
    projectId: string,
    groupId: string,
    payload: { name: string; unit?: string | null; quantity?: number | null },
  ) =>
    request<KtpWbs>(`/projects/${projectId}/ktp-estimate/groups/${groupId}/items`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteItem: (projectId: string, itemId: string) =>
    request<KtpWbs>(`/projects/${projectId}/ktp-estimate/items/${itemId}`, {
      method: "DELETE",
    }),
  createGroup: (projectId: string, sessionId: string, title: string) =>
    request<KtpWbs>(
      `/projects/${projectId}/ktp-estimate/sessions/${sessionId}/groups`,
      { method: "POST", body: JSON.stringify({ title }) },
    ),
  updateGroup: (
    projectId: string,
    groupId: string,
    patch: Partial<{ title: string; sort_order: number; wt_code: string | null }>,
  ) =>
    request<KtpWbs>(`/projects/${projectId}/ktp-estimate/groups/${groupId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  deleteGroup: (projectId: string, groupId: string) =>
    request<KtpWbs>(`/projects/${projectId}/ktp-estimate/groups/${groupId}`, {
      method: "DELETE",
    }),
  approveStage1: (projectId: string, sessionId: string) =>
    request<KtpEstimateSession>(
      `/projects/${projectId}/ktp-estimate/sessions/${sessionId}/approve-stage1`,
      { method: "POST" },
    ),
  generateCard: (
    projectId: string,
    groupId: string,
    answers: Record<string, string> = {},
  ) =>
    request<KtpEstimateCardResponse>(
      `/projects/${projectId}/ktp-estimate/groups/${groupId}/generate-card`,
      { method: "POST", body: JSON.stringify({ answers }) },
    ),
  getCard: (projectId: string, groupId: string) =>
    request<KtpEstimateCard>(
      `/projects/${projectId}/ktp-estimate/groups/${groupId}/card`,
    ),
  updateCard: (
    projectId: string,
    groupId: string,
    patch: Partial<{
      title: string;
      goal: string;
      steps: unknown[];
      recommendations: string[];
    }>,
  ) =>
    request<KtpEstimateCard>(
      `/projects/${projectId}/ktp-estimate/groups/${groupId}/card`,
      { method: "PATCH", body: JSON.stringify(patch) },
    ),
  approveStage2: (projectId: string, sessionId: string) =>
    request<KtpEstimateSession>(
      `/projects/${projectId}/ktp-estimate/sessions/${sessionId}/approve-stage2`,
      { method: "POST" },
    ),
  skipStage2: (projectId: string, sessionId: string) =>
    request<KtpEstimateSession>(
      `/projects/${projectId}/ktp-estimate/sessions/${sessionId}/skip-stage2`,
      { method: "POST" },
    ),
  matchFer: (projectId: string, sessionId: string) =>
    request<{ job_id: string }>(
      `/projects/${projectId}/ktp-estimate/sessions/${sessionId}/match-fer`,
      { method: "POST" },
    ),
  approveFer: (projectId: string, sessionId: string) =>
    request<KtpEstimateSession>(
      `/projects/${projectId}/ktp-estimate/sessions/${sessionId}/approve-fer`,
      { method: "POST" },
    ),
  updateItemFer: (projectId: string, itemId: string, ferTableId: number | null) =>
    request<KtpWbs>(`/projects/${projectId}/ktp-estimate/items/${itemId}/fer`, {
      method: "PATCH",
      body: JSON.stringify({ fer_table_id: ferTableId }),
    }),
  matchItemFer: (projectId: string, itemId: string) =>
    request<KtpWbs>(
      `/projects/${projectId}/ktp-estimate/items/${itemId}/match-fer`,
      { method: "POST" },
    ),
  // Этап 4 — производительность по подтипам работ.
  buildSubtypes: (projectId: string, sessionId: string) =>
    request<KtpWbs>(
      `/projects/${projectId}/ktp-estimate/sessions/${sessionId}/build-subtypes`,
      { method: "POST" },
    ),
  updateSessionSubtype: (
    projectId: string,
    subtypeId: string,
    patch: Partial<{
      unit: string | null;
      volume: number | null;
      output_per_day: number | null;
      crew_size: number | null;
      lag_after_days: number;
      rate_unit_conversion: KtpSessionSubtype["rate_unit_conversion"] | null;
      selected_rate_item_id: string | null;
      selected_rate_mapping_id: string | null;
    }>,
  ) =>
    request<KtpWbs>(
      `/projects/${projectId}/ktp-estimate/session-subtypes/${subtypeId}`,
      { method: "PATCH", body: JSON.stringify(patch) },
    ),
  approveProd: (projectId: string, sessionId: string) =>
    request<KtpEstimateSession>(
      `/projects/${projectId}/ktp-estimate/sessions/${sessionId}/approve-prod`,
      { method: "POST" },
    ),
  // Подшаг ГПР: ИИ строит линейную последовательность групп (2-й уровень).
  // Возвращает WBS с группами в предложенном порядке (статус → gpr_sequence_review).
  proposeSequence: (projectId: string, sessionId: string) =>
    request<KtpWbs>(
      `/projects/${projectId}/ktp-estimate/sessions/${sessionId}/propose-sequence`,
      { method: "POST" },
    ),
  // Оператор правит порядок через updateGroup({sort_order}); затем фиксирует.
  // Группа «Прочие позиции сметы» принудительно ставится в конец (статус → gpr_ready).
  approveSequence: (projectId: string, sessionId: string) =>
    request<KtpEstimateSession>(
      `/projects/${projectId}/ktp-estimate/sessions/${sessionId}/approve-sequence`,
      { method: "POST" },
    ),
  buildGpr: (projectId: string, sessionId: string) =>
    request<{ job_id: string }>(
      `/projects/${projectId}/ktp-estimate/sessions/${sessionId}/build-gpr`,
      { method: "POST" },
    ),
};

export const nw = {
  workTypes: () => request<NwWorkType[]>("/nw/work-types"),
  dictionaries: () => request<NwDictionaries>("/nw/dictionaries"),
  items: (filters: {
    work_type?: string;
    q?: string;
    object_type?: string;
    location_scope?: string;
    stage?: string;
    repair_class?: string;
  } = {}) => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => {
      if (v) params.set(k, v);
    });
    const qs = params.toString();
    return request<NwItem[]>(`/nw/items${qs ? `?${qs}` : ""}`);
  },
  item: (code: string) => request<NwItemDetail>(`/nw/items/${code}`),
  mapping: (filters: {
    nw_code?: string;
    fer_collection_num?: number;
    fer_section_num?: number;
    mapping_type?: string;
    confidence?: string;
    primary_only?: boolean;
  } = {}) => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
    });
    const qs = params.toString();
    return request<NwFerMapping[]>(`/nw/mapping${qs ? `?${qs}` : ""}`);
  },
};

export const workTaxonomy = {
  sections: () => request<WorkTaxonomySection[]>("/work-taxonomy/sections"),
  subtypes: (filters: { section_code?: string; q?: string } = {}) => {
    const params = new URLSearchParams();
    if (filters.section_code) params.set("section_code", filters.section_code);
    if (filters.q) params.set("q", filters.q);
    const qs = params.toString();
    return request<WorkTaxonomySubtype[]>(`/work-taxonomy/subtypes${qs ? `?${qs}` : ""}`);
  },
  projectHierarchy: (filters: { dictionary_version?: string; include_stages?: boolean } = {}) => {
    const params = new URLSearchParams();
    if (filters.dictionary_version) params.set("dictionary_version", filters.dictionary_version);
    if (filters.include_stages) params.set("include_stages", "true");
    const qs = params.toString();
    return request<WorkProjectHierarchy>(`/work-taxonomy/project-hierarchy${qs ? `?${qs}` : ""}`);
  },
  estimateTypes: () => request<WorkEstimateType[]>("/work-taxonomy/estimate-types"),
  projectVariants: (estimateTypeId: string) =>
    request<WorkProjectVariant[]>(`/work-taxonomy/estimate-types/${encodeURIComponent(estimateTypeId)}/variants`),
  projectVariantStages: (estimateTypeId: string, projectVariantId: string) =>
    request<WorkStage[]>(
      `/work-taxonomy/estimate-types/${encodeURIComponent(estimateTypeId)}/variants/${encodeURIComponent(projectVariantId)}/stages`
    ),
  updateProjectStageTitle: (stageId: string, title: string) =>
    request<WorkStage>(`/work-taxonomy/project-hierarchy/stages/${encodeURIComponent(stageId)}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  canonicalStages: () => request<Record<string, unknown>>("/work-taxonomy/canonical-stages"),
};

export const workPlan = {
  base: (pid: string, bid: string) => `/projects/${pid}/batches/${bid}/work-plan`,
  list: (pid: string, bid: string) =>
    request<WorkPlanResponse>(`/projects/${pid}/batches/${bid}/work-plan`),
  palette: (pid: string, bid: string) =>
    request<WorkPlanPalette>(`/projects/${pid}/batches/${bid}/work-plan/palette`),
  autoCreate: (pid: string, bid: string, force = false) =>
    request<WorkPlanAutoSummary>(`/projects/${pid}/batches/${bid}/work-plan/auto?force=${force}`, {
      method: "POST",
    }),
  update: (pid: string, bid: string, planId: number, body: WorkPlanCardPatch) =>
    request<{ id: number; updated: string[] }>(
      `/projects/${pid}/batches/${bid}/work-plan/${planId}`,
      { method: "PATCH", body: JSON.stringify(body) },
    ),
  confirm: (pid: string, bid: string, planId: number) =>
    request<{ id: number; status: string }>(
      `/projects/${pid}/batches/${bid}/work-plan/${planId}/confirm`,
      { method: "POST" },
    ),
  confirmAll: (pid: string, bid: string) =>
    request<{ confirmed: number }>(`/projects/${pid}/batches/${bid}/work-plan/confirm-all`, {
      method: "POST",
    }),
  add: (pid: string, bid: string, body: { nw_item_code: string; unit?: string; quantity?: number; notes?: string }) =>
    request<{ id: number; status: string }>(`/projects/${pid}/batches/${bid}/work-plan`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  remove: (pid: string, bid: string, planId: number, hard = false) =>
    request<{ id: number; deleted: boolean; hard: boolean }>(
      `/projects/${pid}/batches/${bid}/work-plan/${planId}?hard=${hard}`,
      { method: "DELETE" },
    ),
  llmResolve: (pid: string, bid: string) =>
    request<{
      unmatched_before: number;
      matched_by_llm: number;
      still_unmatched: number;
      new_cards: number;
      linked_to_existing: number;
    }>(`/projects/${pid}/batches/${bid}/work-plan/llm-resolve`, { method: "POST" }),
  unmatched: (pid: string, bid: string) =>
    request<{ items: Array<{ id: string; section: string | null; work_name: string; unit: string | null; quantity: number | null; total_price: number | null }>; total: number }>(
      `/projects/${pid}/batches/${bid}/work-plan/unmatched`,
    ),
  linkEstimates: (pid: string, bid: string, planId: number, estimateIds: string[]) =>
    request<{ plan_id: number; linked: number }>(
      `/projects/${pid}/batches/${bid}/work-plan/${planId}/link-estimates`,
      { method: "POST", body: JSON.stringify({ estimate_ids: estimateIds }) },
    ),
  detail: (pid: string, bid: string, planId: number) =>
    request<WorkPlanCardDetail>(`/projects/${pid}/batches/${bid}/work-plan/${planId}/details`),
  matchFer: (pid: string, bid: string, planId: number) =>
    request<{ plan_id: number; fer_table_id: number | null; score: number; candidates_count: number; reason: string | null; source: string }>(
      `/projects/${pid}/batches/${bid}/work-plan/${planId}/match-fer`,
      { method: "POST" },
    ),
  setFerTable: (pid: string, bid: string, planId: number, ferTableId: number | null) =>
    request<{ plan_id: number; fer_table_id: number | null; fer_table_title?: string | null; fer_match_score: number | null; fer_match_source: string | null }>(
      `/projects/${pid}/batches/${bid}/work-plan/${planId}/set-fer-table`,
      { method: "POST", body: JSON.stringify({ fer_table_id: ferTableId }) },
    ),
  matchFerAll: (pid: string, bid: string) =>
    request<{ total_processed: number; fer_mapped: number; needs_review: number; no_candidates: number; errors: number }>(
      `/projects/${pid}/batches/${bid}/work-plan/match-fer-all`,
      { method: "POST" },
    ),
  computeDurations: (pid: string, bid: string) =>
    request<{ total: number; computed: number; skipped: number }>(
      `/projects/${pid}/batches/${bid}/work-plan/compute-durations`,
      { method: "POST" },
    ),
  buildGantt: (pid: string, bid: string, body: { start_date: string; hours_per_day?: number; replace?: boolean }) =>
    request<{ created: number; deps: number; stages: number; warning?: string; fallback_used?: number; fallback_note?: string | null }>(
      `/projects/${pid}/batches/${bid}/work-plan/build-gantt`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  ferRows: (pid: string, bid: string, planId: number) =>
    request<{ items: import("./types").FerRowOption[]; total: number }>(
      `/projects/${pid}/batches/${bid}/work-plan/${planId}/fer-rows`,
    ),
  ferScopes: (pid: string, bid: string) =>
    request<{ estimate_kind: number; work_name: string; scopes: import("./types").WorkPlanFerScope[] }>(
      `/projects/${pid}/batches/${bid}/work-plan/fer-scopes`,
    ),
  setFerRow: (pid: string, bid: string, planId: number, ferRowId: number | null) =>
    request<{ plan_id: number; fer_row_id: number | null; duration_recomputed: any }>(
      `/projects/${pid}/batches/${bid}/work-plan/${planId}/set-fer-row`,
      { method: "POST", body: JSON.stringify({ fer_row_id: ferRowId }) },
    ),
  autoPickFerRow: (pid: string, bid: string, planId: number) =>
    request<{ plan_id: number; fer_row_id: number | null; score?: number; reason?: string; duration?: any; skipped?: string }>(
      `/projects/${pid}/batches/${bid}/work-plan/${planId}/auto-pick-fer-row`,
      { method: "POST" },
    ),
};
