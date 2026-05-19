import { requestQuiet } from "./api";

const ACTIVITY_SESSION_KEY = "construction_activity_session_id";

export type ActivityMetadata = Record<string, unknown>;

export function getActivitySessionId(): string {
  if (typeof window === "undefined") return "";

  const existing = window.sessionStorage.getItem(ACTIVITY_SESSION_KEY);
  if (existing) return existing;

  const next =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
          (
            Number(c) ^
            (Math.random() * 16) >> (Number(c) / 4)
          ).toString(16),
        );
  window.sessionStorage.setItem(ACTIVITY_SESSION_KEY, next);
  return next;
}

export function trackActivity(
  eventType: string,
  options: {
    projectId?: string | null;
    entityType?: string | null;
    entityId?: string | null;
    metadata?: ActivityMetadata;
  } = {},
) {
  if (typeof window === "undefined") return;

  void requestQuiet("/activity-events", {
    method: "POST",
    body: JSON.stringify({
      project_id: options.projectId ?? null,
      session_id: getActivitySessionId(),
      event_type: eventType,
      entity_type: options.entityType ?? null,
      entity_id: options.entityId ?? null,
      path: window.location.pathname + window.location.search,
      metadata: options.metadata ?? {},
    }),
  }).catch(() => undefined);
}
