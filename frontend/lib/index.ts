// ─── frontend/lib/api.ts ──────────────────────────────────────────────────────
// Типизированный API клиент

const BASE = "/api";

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = typeof window !== "undefined"
    ? localStorage.getItem("access_token")
    : null;

  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  if (res.status === 401) {
    // Попытка обновить токен
    const refreshed = await tryRefresh();
    if (!refreshed) {
      window.location.href = "/auth/login";
      throw new Error("Unauthorized");
    }
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
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem("access_token",  data.access_token);
    localStorage.setItem("refresh_token", data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

// Auth
export const auth = {
  login:    (email: string, password: string) =>
    request<any>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  register: (body: any) =>
    request<any>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
  me:       () => request<any>("/auth/me"),
  logout:   () => { localStorage.removeItem("access_token"); localStorage.removeItem("refresh_token"); },
};

// Projects
export const projects = {
  list:         ()           => request<any[]>("/projects"),
  get:          (id: string) => request<any>(`/projects/${id}`),
  create:       (body: any)  => request<any>("/projects", { method: "POST", body: JSON.stringify(body) }),
  update:       (id: string, body: any) => request<any>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  delete:       (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" }),
  listMembers:  (id: string) => request<any[]>(`/projects/${id}/members`),
  addMember:    (id: string, body: any) => request<any>(`/projects/${id}/members`, { method: "POST", body: JSON.stringify(body) }),
  removeMember: (id: string, userId: string) => request<void>(`/projects/${id}/members/${userId}`, { method: "DELETE" }),
};

// Gantt
export const gantt = {
  list:          (projectId: string) => request<any>(`/projects/${projectId}/gantt`),
  create:        (projectId: string, body: any) =>
    request<any>(`/projects/${projectId}/gantt`, { method: "POST", body: JSON.stringify(body) }),
  update:        (projectId: string, taskId: string, body: any) =>
    request<any>(`/projects/${projectId}/gantt/${taskId}`, { method: "PATCH", body: JSON.stringify(body) }),
  delete:        (projectId: string, taskId: string) =>
    request<any>(`/projects/${projectId}/gantt/${taskId}`, { method: "DELETE" }),
  reorder:       (projectId: string, body: any) =>
    request<any>(`/projects/${projectId}/gantt/reorder`, { method: "POST", body: JSON.stringify(body) }),
  resolve:       (projectId: string) =>
    request<any>(`/projects/${projectId}/gantt/resolve`, { method: "POST" }),
  addDep:        (projectId: string, taskId: string, dependsOn: string) =>
    request<any>(`/projects/${projectId}/gantt/${taskId}/dependencies`, { method: "POST", body: JSON.stringify({ depends_on: dependsOn }) }),
  removeDep:     (projectId: string, taskId: string, depId: string) =>
    request<void>(`/projects/${projectId}/gantt/${taskId}/dependencies/${depId}`, { method: "DELETE" }),
};

// Estimates
export const estimates = {
  list:    (projectId: string)           => request<any[]>(`/projects/${projectId}/estimates`),
  summary: (projectId: string)           => request<any>(`/projects/${projectId}/estimates/summary`),
  upload:  (projectId: string, file: File, startDate: string, workers: number) => {
    const token = localStorage.getItem("access_token");
    const form  = new FormData();
    form.append("file", file);
    return fetch(`${BASE}/projects/${projectId}/estimates/upload?start_date=${startDate}&workers=${workers}`, {
      method:  "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body:    form,
    }).then(r => r.json());
  },
};

// Jobs
export const jobs = {
  get: (jobId: string) => request<any>(`/jobs/${jobId}`),
};

// Comments
export const comments = {
  list:   (projectId: string, taskId: string) =>
    request<any[]>(`/projects/${projectId}/tasks/${taskId}/comments`),
  create: (projectId: string, taskId: string, body: any) =>
    request<any>(`/projects/${projectId}/tasks/${taskId}/comments`, { method: "POST", body: JSON.stringify(body) }),
  update: (projectId: string, taskId: string, commentId: string, body: any) =>
    request<any>(`/projects/${projectId}/tasks/${taskId}/comments/${commentId}`, { method: "PATCH", body: JSON.stringify(body) }),
  delete: (projectId: string, taskId: string, commentId: string) =>
    request<void>(`/projects/${projectId}/tasks/${taskId}/comments/${commentId}`, { method: "DELETE" }),
};

// Reports
export const reports = {
  list:   (projectId: string) => request<any[]>(`/projects/${projectId}/reports`),
  today:  (projectId: string) => request<any>(`/projects/${projectId}/reports/today`),
  get:    (projectId: string, reportId: string) => request<any>(`/projects/${projectId}/reports/${reportId}`),
  create: (projectId: string, body: any) =>
    request<any>(`/projects/${projectId}/reports`, { method: "POST", body: JSON.stringify(body) }),
  submit: (projectId: string, reportId: string) =>
    request<any>(`/projects/${projectId}/reports/${reportId}/submit`, { method: "POST" }),
};

// Notifications
export const notifications = {
  list:       (unreadOnly = false) => request<any[]>(`/notifications?unread_only=${unreadOnly}`),
  markRead:   (id: string) => request<void>(`/notifications/${id}/read`, { method: "POST" }),
  markAllRead: ()          => request<void>("/notifications/read-all",   { method: "POST" }),
};


// ─── frontend/lib/dateUtils.ts ────────────────────────────────────────────────
// Зеркало Python date_utils.py — рабочие дни на фронте

export function addWorkingDays(
  start: Date,
  workingDays: number,
  holidays: Set<string> = new Set()
): Date {
  if (workingDays <= 0) return new Date(start);
  let current = new Date(start);
  let added = 0;
  while (added < workingDays) {
    current.setDate(current.getDate() + 1);
    const iso = current.toISOString().split("T")[0];
    if (current.getDay() !== 0 && current.getDay() !== 6 && !holidays.has(iso)) {
      added++;
    }
  }
  return current;
}

export function taskEndDate(startDate: string, workingDays: number): string {
  const end = addWorkingDays(new Date(startDate), workingDays);
  return end.toISOString().split("T")[0];
}

export function workingDaysBetween(start: Date, end: Date): number {
  let count = 0;
  let current = new Date(start);
  while (current < end) {
    current.setDate(current.getDate() + 1);
    if (current.getDay() !== 0 && current.getDay() !== 6) count++;
  }
  return count;
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getDate()).padStart(2,"0")}.${String(d.getMonth()+1).padStart(2,"0")}`;
}


// ─── frontend/lib/useJobPoller.ts ─────────────────────────────────────────────
// Polling для async upload

import { useState, useEffect, useRef } from "react";
import { jobs } from "./api";

type JobStatus = "pending" | "processing" | "done" | "failed";

interface JobResult {
  estimates_count?:   number;
  gantt_tasks_count?: number;
  strategy?:          string;
  confidence?:        number;
  total_price?:       number;
  error?:             string;
}

export interface Job {
  job_id:      string;
  status:      JobStatus;
  result:      JobResult | null;
  finished_at: string | null;
}

export function useJobPoller(jobId: string | null, intervalMs = 1500) {
  const [job,     setJob]     = useState<Job | null>(null);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!jobId) return;
    setLoading(true);

    const poll = async () => {
      try {
        const data = await jobs.get(jobId);
        setJob(data);
        if (data.status === "done" || data.status === "failed") {
          if (timerRef.current) clearInterval(timerRef.current);
          setLoading(false);
        }
      } catch {
        if (timerRef.current) clearInterval(timerRef.current);
        setLoading(false);
      }
    };

    poll();
    timerRef.current = setInterval(poll, intervalMs);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [jobId, intervalMs]);

  return { job, loading };
}
