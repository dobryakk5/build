"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Check, Download, Trash2 } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { ktpEstimate, workTaxonomy } from "@/lib/api";
import { trackActivity } from "@/lib/activity";
import { useJobPoller } from "@/lib/useJobPoller";
import type {
  KtpEstimateCard,
  KtpQuestion,
  KtpWbs,
  KtpWbsGroup,
  KtpWbsItem,
  KtpSessionSubtype,
  WorkTaxonomySection,
  WorkTaxonomySubtype,
} from "@/lib/types";

const ORIGIN_BADGE: Partial<Record<KtpWbsItem["origin"], { label: string; color: string }>> = {
  from_catalog: { label: "из каталога", color: "#15803d" },
  manual: { label: "вручную", color: "#2563eb" },
};

function itemSourceBadge(item: KtpWbsItem): { label: string; color: string } | null {
  if (item.origin === "ai_added") return null;
  if (item.work_type_source === "manual") return ORIGIN_BADGE.manual ?? null;
  if (item.manual_override) return { label: "Утверждено", color: "#15803d" };
  if (item.origin === "from_estimate") return null;
  return ORIGIN_BADGE[item.origin] ?? null;
}

const card = {
  border: "1px solid var(--border)",
  borderRadius: 8,
  background: "var(--surface)",
};

const btn = (variant: "primary" | "ghost" | "danger" = "ghost"): React.CSSProperties => ({
  padding: "7px 13px",
  borderRadius: 6,
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  border: variant === "primary" ? "none" : "1px solid var(--border2)",
  background:
    variant === "primary" ? "var(--blue-dark)" : variant === "danger" ? "rgba(239,68,68,.08)" : "var(--surface)",
  color: variant === "primary" ? "#fff" : variant === "danger" ? "var(--red)" : "var(--text)",
});

const inputLike: React.CSSProperties = {
  padding: "7px 9px",
  border: "1px solid var(--border2)",
  borderRadius: 6,
  background: "var(--surface)",
  color: "var(--text)",
  fontSize: 12,
  outline: "none",
};

function buttonStyle(
  variant: "primary" | "ghost" | "danger" = "ghost",
  disabled = false,
): React.CSSProperties {
  const base = btn(variant);
  if (disabled) {
    return {
      ...base,
      border: "1px solid var(--border2)",
      background: "#e5e7eb",
      color: "#64748b",
      opacity: 1,
      cursor: "not-allowed",
      boxShadow: "none",
    };
  }
  return {
    ...base,
    opacity: 1,
    cursor: "pointer",
  };
}

function InlineSpinner() {
  return (
    <span
      aria-hidden="true"
      style={{
        width: 13,
        height: 13,
        borderRadius: "50%",
        border: "2px solid currentColor",
        borderTopColor: "transparent",
        display: "inline-block",
        flexShrink: 0,
        animation: "ktp-spin 0.8s linear infinite",
      }}
    />
  );
}

function ButtonContent({ loading, children }: { loading?: boolean; children: React.ReactNode }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 7 }}>
      {loading && <InlineSpinner />}
      {children}
    </span>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <span
      aria-hidden="true"
      style={{
        width: 7,
        height: 7,
        borderRight: "2px solid currentColor",
        borderBottom: "2px solid currentColor",
        display: "inline-block",
        transform: open ? "rotate(45deg)" : "rotate(-45deg)",
        transition: "transform .15s ease",
      }}
    />
  );
}

function confidenceLabel(value: string | number | null | undefined) {
  if (value == null || value === "") return "";
  if (typeof value === "number") return `${Math.round(value)}%`;
  const labels: Record<string, string> = {
    high: "высокая",
    medium: "средняя",
    low: "низкая",
    manual: "ручная",
  };
  return labels[value] ?? value;
}

function determinedTypeLabel(item: KtpWbsItem) {
  return (
    item.work_subtype_name ||
    item.work_subtype_code ||
    item.work_section_name ||
    item.work_section_code ||
    ""
  );
}

function displayStageGroupTitle(title: string | null | undefined) {
  return String(title || "")
    .replace(/^2\.7\.(?:[A-Z]\d+|\d+)(?:\.\d+)?\.\s*/, "")
    .trim();
}

function groupIdentifier(group: KtpWbsGroup) {
  return (
    group.wbs_code
    || group.stage_number
    || group.template_stage_number
    || (group.stage_instance_id ? group.stage_instance_id.split(":").at(-1) : null)
    || `G-${group.id.slice(0, 8)}`
  );
}

function groupIdentifierTitle(group: KtpWbsGroup) {
  return [
    group.stage_instance_id ? `stage_instance_id: ${group.stage_instance_id}` : null,
    group.template_stage_number ? `template_stage_number: ${group.template_stage_number}` : null,
    group.stage_number ? `stage_number: ${group.stage_number}` : null,
    group.wbs_code ? `wbs_code: ${group.wbs_code}` : null,
    group.floor_label ? `floor: ${group.floor_label}` : null,
    group.floor_component ? `component: ${group.floor_component}` : null,
    `group_id: ${group.id}`,
  ].filter(Boolean).join("\n");
}

function stageNumberParts(value: string | null | undefined) {
  const matches = String(value || "").match(/\d+/g);
  return matches?.map((part) => Number(part)) ?? [Number.MAX_SAFE_INTEGER];
}

function compareStageNumbers(a: string | null | undefined, b: string | null | undefined) {
  const left = stageNumberParts(a);
  const right = stageNumberParts(b);
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    const delta = (left[index] ?? 0) - (right[index] ?? 0);
    if (delta !== 0) return delta;
  }
  return 0;
}

function floorSortValue(group: KtpWbsGroup) {
  if (typeof group.floor_number === "number") return group.floor_number;
  return Number.MAX_SAFE_INTEGER;
}

function floorSectionTitle(group: KtpWbsGroup) {
  if (group.floor_number === 0) return "Цоколь";
  if (typeof group.floor_number === "number") return `${group.floor_number} этаж`;
  return group.floor_label || "Без этажа";
}

function compareStageGroups(a: KtpWbsGroup, b: KtpWbsGroup) {
  const floorDelta = floorSortValue(a) - floorSortValue(b);
  if (floorDelta !== 0) return floorDelta;
  const stageDelta = compareStageNumbers(
    a.template_stage_number || a.stage_number,
    b.template_stage_number || b.stage_number,
  );
  if (stageDelta !== 0) return stageDelta;
  return a.sort_order - b.sort_order || a.title.localeCompare(b.title, "ru");
}

function floorSections(groups: KtpWbsGroup[], sequenceLocked = false) {
  const sorted = [...groups].sort(
    sequenceLocked
      ? (a, b) => a.sort_order - b.sort_order || a.title.localeCompare(b.title, "ru")
      : compareStageGroups,
  );
  if (sequenceLocked) {
    // Older immutable taxonomy snapshots placed the global 2.7.12 stage
    // immediately before 2.7.11. Correct that legacy display pair without
    // disturbing the per-floor 2.7.8 → 2.7.9 → 2.7.10 loops.
    const reversedPairIndex = sorted.findIndex((group, index) => (
      group.template_stage_number === "2.7.12"
      && sorted[index + 1]?.template_stage_number === "2.7.11"
    ));
    if (reversedPairIndex >= 0) {
      [sorted[reversedPairIndex], sorted[reversedPairIndex + 1]] = [
        sorted[reversedPairIndex + 1],
        sorted[reversedPairIndex],
      ];
    }
    return [{ key: "__locked__", title: "", showTitle: false as const, groups: sorted }];
  }
  const hasFloors = sorted.some((group) => group.floor_number != null || group.floor_label);
  if (!hasFloors) {
    return [{ key: "__all__", title: "", showTitle: false, groups: sorted }];
  }
  const sections = new Map<string, { key: string; title: string; showTitle: true; groups: KtpWbsGroup[] }>();
  for (const group of sorted) {
    const key = group.floor_number != null ? `floor:${group.floor_number}` : "floor:none";
    const existing = sections.get(key);
    if (existing) {
      existing.groups.push(group);
    } else {
      sections.set(key, { key, title: floorSectionTitle(group), showTitle: true, groups: [group] });
    }
  }
  return Array.from(sections.values());
}

function sourceParentLines(item: KtpWbsItem) {
  const title = (item.source_parent?.title ?? item.section_title ?? "").trim();
  const description = (item.source_parent?.description ?? item.section_description ?? "").trim();
  return [title, description].filter((value, index, arr) => value && arr.indexOf(value) === index);
}

function buildStructureExportRows(wbs: KtpWbs) {
  return wbs.groups.flatMap((group) => {
    const groupRow = {
      name: group.title,
      confidence: confidenceLabel(group.work_type_confidence),
      type: group.wt_name || group.work_section_name || group.wt_code || group.work_section_code || "",
    };
    const itemRows = group.items
      .filter((item) => item.review_status !== "rejected")
      .map((item) => ({
        name: `  ${item.name}`,
        section: sourceParentLines(item).join(" / "),
        confidence: confidenceLabel(item.stage_confidence_percent ?? item.work_type_confidence),
        type: determinedTypeLabel(item),
      }));
    return [{ ...groupRow, section: "" }, ...itemRows];
  });
}

function wbsHasItem(wbs: KtpWbs, groupId: string, item: KtpWbsItem, previousMatchingCount = 0) {
  const group = wbs.groups.find((entry) => entry.id === groupId);
  if (!group) return false;
  if (group.items.some((entry) => entry.id === item.id)) return true;
  const matchingCount = group.items.filter(
    (entry) => entry.origin === "manual" && entry.name === item.name,
  ).length;
  return matchingCount > previousMatchingCount;
}

function ensureItemVisible(wbs: KtpWbs, groupId: string, item: KtpWbsItem, previousMatchingCount = 0) {
  if (wbsHasItem(wbs, groupId, item, previousMatchingCount)) return wbs;
  return {
    ...wbs,
    groups: wbs.groups.map((group) =>
      group.id === groupId ? { ...group, items: [...group.items, item] } : group,
    ),
  };
}

function stage1ItemNeedsReview(item: KtpWbsItem) {
  return (
    item.origin !== "ai_added" &&
    item.review_status !== "rejected" &&
    !item.manual_override &&
    (item.stage_needs_review || item.work_type_needs_review || item.operator_review_required)
  );
}

function acceptStage1ItemLocal(item: KtpWbsItem): KtpWbsItem {
  if (item.origin === "ai_added" && item.review_status === "pending") {
    return {
      ...item,
      review_status: "accepted",
      work_type_needs_review: false,
      operator_review_required: false,
    };
  }
  if (stage1ItemNeedsReview(item)) {
    return {
      ...item,
      manual_override: true,
      work_type_needs_review: false,
      operator_review_required: false,
      stage_needs_review: false,
      stage_review_reason: null,
      gpr_confirmed: false,
    };
  }
  return item;
}

function updateWbsItemLocal(
  wbs: KtpWbs,
  itemId: string,
  updater: (item: KtpWbsItem) => KtpWbsItem,
) {
  return {
    ...wbs,
    groups: wbs.groups.map((group) => ({
      ...group,
      items: group.items.map((item) => (item.id === itemId ? updater(item) : item)),
    })),
  };
}

function acceptAllStage1ItemsLocal(wbs: KtpWbs) {
  return {
    ...wbs,
    groups: wbs.groups.map((group) => ({
      ...group,
      items: group.items.map(acceptStage1ItemLocal),
    })),
  };
}

async function downloadStructureExcel(wbs: KtpWbs, sessionId: string) {
  const XLSX = await import("xlsx");
  const rows = [
    ["Наименование", "Раздел", "Уверенность", "Определенный тип"],
    ...buildStructureExportRows(wbs).map((row) => [row.name, row.section, row.confidence, row.type]),
  ];
  const worksheet = XLSX.utils.aoa_to_sheet(rows);
  worksheet["!cols"] = [{ wch: 56 }, { wch: 72 }, { wch: 16 }, { wch: 48 }];
  worksheet["!autofilter"] = { ref: `A1:D${Math.max(rows.length, 1)}` };

  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, worksheet, "Структура работ");
  XLSX.writeFile(workbook, `ktp-structure-${sessionId}.xlsx`, { compression: true });
}

export default function KtpEstimateWizardPage() {
  const { id: projectId, sessionId } = useParams<{ id: string; sessionId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const pageScrollRef = useRef<HTMLDivElement | null>(null);

  const [wbs, setWbs] = useState<KtpWbs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(searchParams.get("job"));

  const { job } = useJobPoller(activeJobId);
  const session = wbs?.session;
  const status = session?.status;
  const batchId = session?.estimate_batch_id;

  useEffect(() => {
    trackActivity("KTP_ESTIMATE_WIZARD_OPENED", {
      projectId,
      entityType: "ktp_estimate_session",
      entityId: sessionId,
      metadata: {
        estimate_batch_id: searchParams.get("batch"),
        job_id: searchParams.get("job"),
      },
    });
  }, [projectId, searchParams, sessionId]);

  const loadWbs = useCallback(async () => {
    try {
      setWbs(await ktpEstimate.getWbs(projectId, sessionId));
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  }, [projectId, sessionId]);

  // WBS грузим всегда: stale ?job= не должен блокировать вход в мастер.
  useEffect(() => {
    void loadWbs();
  }, [loadWbs]);

  // сеанс ещё обрабатывается, но мы зашли без ?job= — подцепляем поллер по
  // сохранённому job_id (recovery после перезагрузки страницы)
  useEffect(() => {
    if (!wbs || activeJobId) return;
    const s = wbs.session;
    const recoverJob =
      s.status === "stage1_processing" || s.status === "stage1_pending"
        ? s.stage1_job_id
        : s.status === "gpr_processing"
        ? s.gpr_job_id
        : null;
    if (recoverJob) setActiveJobId(recoverJob);
  }, [wbs, activeJobId]);

  // Если пользователь открыл старую ссылку с ?job=, но сеанс уже ушёл дальше,
  // не держим экран на processing-состоянии.
  useEffect(() => {
    if (!session || !activeJobId) return;
    const expectedJob =
      session.status === "stage1_processing" || session.status === "stage1_pending"
        ? session.stage1_job_id
        : session.status === "gpr_processing"
        ? session.gpr_job_id
        : null;

    if (expectedJob && expectedJob !== activeJobId) {
      setActiveJobId(expectedJob);
    } else if (!expectedJob) {
      setActiveJobId(null);
    }
  }, [activeJobId, session]);

  // job завершился — перегружаем WBS
  useEffect(() => {
    if (!job) return;
    if (job.status === "done") {
      if (status === "gpr_processing") {
        trackActivity("GPR_BUILD_COMPLETED", {
          projectId,
          entityType: "ktp_estimate_session",
          entityId: sessionId,
          metadata: {
            job_id: job.id,
            estimate_batch_id: batchId,
          },
        });
      }
      setActiveJobId(null);
      void loadWbs();
    } else if (job.status === "failed") {
      setActiveJobId(null);
      setError(job.result?.error || "Задача завершилась с ошибкой");
    }
  }, [job, loadWbs]);

  const run = useCallback(
    async (fn: () => Promise<KtpWbs>) => {
      setBusy(true);
      try {
        setWbs(await fn());
        setError(null);
      } catch (e: any) {
        setError(e.message);
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const addItemOptimistic = useCallback(
    async (groupId: string, name: string) => {
      const previousMatchingCount =
        wbs?.groups
          .find((group) => group.id === groupId)
          ?.items.filter((item) => item.origin === "manual" && item.name === name).length ?? 0;
      const tempId = `tmp-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const tempItem: KtpWbsItem = {
        id: tempId,
        group_id: groupId,
        name,
        sort_order: Date.now(),
        origin: "manual",
        review_status: "accepted",
        work_type_needs_review: false,
        work_type_candidates: [],
        stage_needs_review: false,
        stage_review_reason: null,
        stage_confidence_percent: null,
        operator_review_required: false,
        manual_override: false,
        gpr_confirmed: false,
        gpr_blocker: false,
      };
      setWbs((prev) =>
        prev
          ? {
              ...prev,
              groups: prev.groups.map((group) =>
                group.id === groupId ? { ...group, items: [...group.items, tempItem] } : group,
              ),
            }
          : prev,
      );
      setBusy(true);
      try {
        let nextWbs = await ktpEstimate.createItem(projectId, groupId, { name });
        if (!wbsHasItem(nextWbs, groupId, tempItem, previousMatchingCount)) {
          nextWbs = await ktpEstimate.getWbs(projectId, sessionId);
        }
        setWbs(ensureItemVisible(nextWbs, groupId, tempItem, previousMatchingCount));
        setError(null);
      } catch (e: any) {
        setWbs((prev) =>
          prev
            ? {
                ...prev,
                groups: prev.groups.map((group) => ({
                  ...group,
                  items: group.items.filter((item) => item.id !== tempId),
                })),
              }
            : prev,
        );
        setError(e.message);
      } finally {
        setBusy(false);
      }
    },
    [projectId, sessionId, wbs],
  );

  const acceptRecommendedItemOptimistic = useCallback(
    async (itemId: string) => {
      const previousWbs = wbs;
      setWbs((prev) => (prev ? updateWbsItemLocal(prev, itemId, acceptStage1ItemLocal) : prev));
      setBusy(true);
      try {
        setWbs(await ktpEstimate.updateItem(projectId, itemId, { review_status: "accepted" }));
        setError(null);
      } catch (e: any) {
        setWbs(previousWbs);
        setError(e.message);
      } finally {
        setBusy(false);
      }
    },
    [projectId, wbs],
  );

  const approveReviewItemOptimistic = useCallback(
    async (itemId: string) => {
      const previousWbs = wbs;
      setWbs((prev) => (prev ? updateWbsItemLocal(prev, itemId, acceptStage1ItemLocal) : prev));
      setBusy(true);
      try {
        setWbs(await ktpEstimate.updateItem(projectId, itemId, { manual_override: true }));
        setError(null);
      } catch (e: any) {
        setWbs(previousWbs);
        setError(e.message);
      } finally {
        setBusy(false);
      }
    },
    [projectId, wbs],
  );

  const acceptAllStage1ItemsOptimistic = useCallback(async () => {
    const previousWbs = wbs;
    setWbs((prev) => (prev ? acceptAllStage1ItemsLocal(prev) : prev));
    setBusy(true);
    try {
      setWbs(await ktpEstimate.acceptStage1Items(projectId, sessionId));
      setError(null);
    } catch (e: any) {
      setWbs(previousWbs);
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [projectId, sessionId, wbs]);

  const stage1Processing = status === "stage1_processing" || status === "stage1_pending";
  const gprProcessing = status === "gpr_processing";
  const actualStepIndex =
    status === "stage1_review"
      ? 2
      : status === "stage2_review"
      ? 3
      : status === "prod_pending" || status === "prod_review"
      ? 4
      : 5;
  const [viewStep, setViewStep] = useState<number | null>(null);
  const stepIndex = viewStep ?? actualStepIndex;
  const revisitingCompletedStep = stepIndex < actualStepIndex;

  useEffect(() => {
    setViewStep(null);
  }, [actualStepIndex]);

  const restartStage1 = useCallback(async () => {
    if (!batchId) return;
    setBusy(true);
    try {
      const started = await ktpEstimate.startSession(
        projectId,
        batchId,
        true,
        Boolean(session?.preserve_estimate_structure),
      );
      trackActivity("KTP_ESTIMATE_SESSION_RESTARTED", {
        projectId,
        entityType: "ktp_estimate_session",
        entityId: started.session_id,
        metadata: {
          estimate_batch_id: batchId,
          previous_session_id: sessionId,
          job_id: started.job_id,
          preserve_estimate_structure: Boolean(session?.preserve_estimate_structure),
        },
      });
      const suffix = started.job_id ? `?job=${started.job_id}` : "";
      router.replace(`/projects/${projectId}/ktp-estimate/${started.session_id}${suffix}`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [batchId, projectId, router, session?.preserve_estimate_structure, sessionId]);

  const openUploadStep = useCallback(() => {
    router.push(
      `/projects/${projectId}/upload${
        batchId ? `?batch=${batchId}&session=${sessionId}&fromKtp=1` : ""
      }`,
    );
  }, [batchId, projectId, router, sessionId]);

  // ── состояния загрузки ───────────────────────────────────────────────
  if (!wbs && activeJobId) {
    return (
      <ProcessingScreen
        title="Анализируем смету"
        subtitle="Строим структуру работ — группируем позиции и проверяем полноту охвата"
        progress={job?.result?._progress ?? null}
      />
    );
  }
  if (stage1Processing) {
    return (
      <ProcessingScreen
        title="Анализируем смету"
        subtitle="Строим структуру работ — группируем позиции и проверяем полноту охвата"
        progress={job?.result?._progress ?? null}
      />
    );
  }
  if (gprProcessing) {
    return (
      <ProcessingScreen
        title="Строим график производства работ"
        subtitle="ИИ рассчитывает нормы, длительности и зависимости"
        progress={job?.result?._progress ?? null}
      />
    );
  }
  if (error) {
    return (
      <Centered>
        <div style={{ color: "var(--red)", fontSize: 13, marginBottom: 12 }}>❌ {error}</div>
        <button style={btn()} onClick={() => void loadWbs()}>
          Обновить
        </button>
      </Centered>
    );
  }
  if (!wbs || !session) return <Centered>Загрузка…</Centered>;
  if (status === "stage1_failed" || status === "gpr_failed") {
    return (
      <Centered>
        <div style={{ color: "var(--red)", fontSize: 13, maxWidth: 560, lineHeight: 1.5 }}>
          ❌ {session.error_message || "Ошибка обработки"}
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap", justifyContent: "center" }}>
          {status === "stage1_failed" && (
            <button
              type="button"
              style={buttonStyle("primary", busy)}
              disabled={busy || !batchId}
              onClick={() => void restartStage1()}
            >
              <ButtonContent loading={busy}>Запустить заново</ButtonContent>
            </button>
          )}
          <button type="button" style={btn()} onClick={openUploadStep}>
            К шагу «Новая смета»
          </button>
        </div>
      </Centered>
    );
  }

  const scrollToTop = () => {
    pageScrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div
      ref={pageScrollRef}
      style={{ height: "100%", overflow: "auto", padding: 24, maxWidth: 1080, margin: "0 auto", boxSizing: "border-box" }}
    >
      <Steps
        current={stepIndex}
        maxAvailable={actualStepIndex}
        onStep={(step) => {
          if (step === 1) {
            router.push(
              `/projects/${projectId}/upload${batchId ? `?batch=${batchId}&session=${sessionId}&fromKtp=1` : ""}`,
            );
            return;
          }
          if (step <= actualStepIndex) setViewStep(step === actualStepIndex ? null : step);
        }}
        onNewEstimate={() =>
          router.push(
            `/projects/${projectId}/upload${batchId ? `?batch=${batchId}&session=${sessionId}&fromKtp=1` : ""}`,
          )
        }
      />

      {stepIndex === 2 && (
        <Stage1
          wbs={wbs}
          busy={busy}
          run={run}
          projectId={projectId}
          sessionId={sessionId}
          addItemOptimistic={addItemOptimistic}
          acceptRecommendedItemOptimistic={acceptRecommendedItemOptimistic}
          approveReviewItemOptimistic={approveReviewItemOptimistic}
          acceptAllStage1ItemsOptimistic={acceptAllStage1ItemsOptimistic}
          revisiting={revisitingCompletedStep}
          onReturn={() => setViewStep(null)}
          onApprove={async () => {
            setBusy(true);
            try {
              await ktpEstimate.approveStage1(projectId, sessionId);
              trackActivity("KTP_STAGE1_APPROVED", {
                projectId,
                entityType: "ktp_estimate_session",
                entityId: sessionId,
                metadata: { estimate_batch_id: batchId },
              });
              await loadWbs();
            } catch (e: any) {
              setError(e.message);
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {stepIndex === 3 && (
        <Stage2
          wbs={wbs}
          projectId={projectId}
          sessionId={sessionId}
          busy={busy}
          setBusy={setBusy}
          setError={setError}
          reload={loadWbs}
          revisiting={revisitingCompletedStep}
          onReturn={() => setViewStep(null)}
        />
      )}

      {stepIndex === 4 && (
        <StageProductivity
          wbs={wbs}
          projectId={projectId}
          sessionId={sessionId}
          busy={busy}
          setBusy={setBusy}
          setError={setError}
          reload={loadWbs}
          onApprove={async () => {
            setBusy(true);
            try {
              await ktpEstimate.approveProd(projectId, sessionId);
              await loadWbs();
            } catch (e: any) {
              setError(e.message);
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {(status === "gpr_pending" || status === "gpr_done") && (
        <Stage3
          wbs={wbs}
          projectId={projectId}
          sessionId={sessionId}
          busy={busy}
          run={run}
          done={status === "gpr_done"}
          onBuild={async () => {
            setBusy(true);
            try {
              trackActivity("GPR_BUILD_STARTED", {
                projectId,
                entityType: "ktp_estimate_session",
                entityId: sessionId,
                metadata: { estimate_batch_id: batchId },
              });
              const { job_id } = await ktpEstimate.buildGpr(projectId, sessionId);
              setActiveJobId(job_id);
              await loadWbs();
            } catch (e: any) {
              setError(e.message);
              setBusy(false);
            }
          }}
          onOpenGantt={() => {
            trackActivity("GPR_GANTT_OPENED", {
              projectId,
              entityType: "estimate_batch",
              entityId: batchId ?? null,
              metadata: {
                estimate_batch_id: batchId,
                ktp_estimate_session_id: sessionId,
              },
            });
            router.push(`/projects/${projectId}/gantt?batch=${batchId}`);
          }}
        />
      )}

      <div style={{ display: "flex", justifyContent: "center", marginTop: 22, paddingBottom: 8 }}>
        <button
          type="button"
          onClick={scrollToTop}
          aria-label="Вернуться наверх"
          title="Вернуться наверх"
          style={{
            ...buttonStyle("ghost"),
            width: 34,
            height: 34,
            padding: 0,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <ArrowUp size={16} strokeWidth={2.2} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--muted)",
        fontSize: 13,
        textAlign: "center",
        padding: 24,
      }}
    >
      {children}
    </div>
  );
}

function ProcessingScreen({
  title,
  subtitle,
  progress,
}: {
  title: string;
  subtitle: string;
  progress: string | null;
}) {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  useEffect(() => {
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);
    return () => clearInterval(t);
  }, []);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const elapsedStr = mins > 0 ? `${mins} мин ${secs} сек` : `${secs} сек`;

  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: 32,
        gap: 0,
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 480,
          border: "1px solid var(--border)",
          borderRadius: 12,
          background: "var(--surface)",
          padding: 28,
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Spinner />
          <div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{title}</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>{subtitle}</div>
          </div>
        </div>

        {progress && (
          <div
            style={{
              padding: "10px 14px",
              borderRadius: 6,
              background: "rgba(59,130,246,.06)",
              border: "1px solid rgba(59,130,246,.15)",
              fontSize: 12,
              color: "var(--blue-dark, #1d4ed8)",
              fontFamily: "var(--mono)",
            }}
          >
            {progress}
          </div>
        )}

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 11,
            color: "var(--muted)",
            borderTop: "1px solid var(--border)",
            paddingTop: 10,
          }}
        >
          <span>Время: {elapsedStr}</span>
          <span>Можно закрыть — обработка идёт на сервере</span>
        </div>
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <div
      style={{
        width: 28,
        height: 28,
        borderRadius: "50%",
        border: "3px solid rgba(59,130,246,.2)",
        borderTopColor: "var(--blue-dark, #1d4ed8)",
        flexShrink: 0,
        animation: "ktp-spin 0.8s linear infinite",
      }}
    />
  );
}

function Steps({
  current,
  maxAvailable,
  onStep,
  onNewEstimate,
}: {
  current: number;
  maxAvailable: number;
  onStep: (step: number) => void;
  onNewEstimate: () => void;
}) {
  const labels = ["Новая смета", "Структура работ", "КТП", "Производительность", "ГПР"];
  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
      {labels.map((label, i) => {
        const n = i + 1;
        const active = n === current;
        const done = n < maxAvailable;
        const available = n <= maxAvailable;
        const stepStyle: React.CSSProperties = {
          flex: 1,
          padding: "9px 12px",
          borderRadius: 6,
          fontSize: 12,
          fontWeight: 600,
          textAlign: "center",
          border: "1px solid var(--border)",
          background: active ? "var(--blue-dark)" : done ? "rgba(34,197,94,.1)" : "var(--surface)",
          color: active ? "#fff" : done ? "#15803d" : "var(--muted)",
        };
        if (n === 1 || available) {
          return (
            <button
              key={label}
              type="button"
              onClick={() => (n === 1 ? onNewEstimate() : onStep(n))}
              style={{
                ...stepStyle,
                cursor: "pointer",
                fontFamily: "var(--sans)",
              }}
            >
              {done && !active ? "✓ " : `${n}. `}
              {label}
            </button>
          );
        }
        return (
          <div
            key={label}
            style={stepStyle}
          >
            {done ? "✓ " : `${n}. `}
            {label}
          </div>
        );
      })}
    </div>
  );
}

// ── ЭТАП 1 ───────────────────────────────────────────────────────────────────

function Stage1({
  wbs,
  busy,
  run,
  projectId,
  sessionId,
  addItemOptimistic,
  acceptRecommendedItemOptimistic,
  approveReviewItemOptimistic,
  acceptAllStage1ItemsOptimistic,
  revisiting,
  onReturn,
  onApprove,
}: {
  wbs: KtpWbs;
  busy: boolean;
  run: (fn: () => Promise<KtpWbs>) => Promise<void>;
  projectId: string;
  sessionId: string;
  addItemOptimistic: (groupId: string, name: string) => Promise<void>;
  acceptRecommendedItemOptimistic: (itemId: string) => Promise<void>;
  approveReviewItemOptimistic: (itemId: string) => Promise<void>;
  acceptAllStage1ItemsOptimistic: () => Promise<void>;
  revisiting?: boolean;
  onReturn?: () => void;
  onApprove: () => void;
}) {
  const [newGroup, setNewGroup] = useState("");
  const pendingAi = wbs.groups.reduce(
    (sum, group) =>
      sum +
      group.items.filter((item) => item.origin === "ai_added" && item.review_status === "pending").length,
    0,
  );
  const pendingReview = wbs.groups.reduce(
    (sum, group) =>
      sum +
      group.items.filter(
        (item) =>
          item.origin !== "ai_added" &&
          item.review_status !== "rejected" &&
          !item.manual_override &&
          (item.stage_needs_review || item.work_type_needs_review || item.operator_review_required),
      ).length,
    0,
  );
  const unresolvedDisputes = pendingAi + pendingReview;
  const approveDisabled = busy || unresolvedDisputes > 0;
  const stageFloorSections = useMemo(
    () => floorSections(wbs.groups, wbs.sequence_locked),
    [wbs.groups, wbs.sequence_locked],
  );
  const orderedGroups = useMemo(
    () => stageFloorSections.flatMap((section) => section.groups),
    [stageFloorSections],
  );
  const groupOptions = orderedGroups.map((g) => ({ id: g.id, title: displayStageGroupTitle(g.title) || g.title }));

  return (
    <div>
      <Header
        title="Структура работ"
        hint="Алгоритм собрал позиции сметы в группы и добавил недостающие работы. Проверьте и поправьте структуру, затем утвердите."
        right={
          revisiting ? (
            <button type="button" style={btn("primary")} onClick={onReturn}>
              Вернуться к производительности
            </button>
          ) : (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button
                type="button"
                style={{
                  ...btn(),
                  width: 34,
                  height: 34,
                  padding: 0,
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
                onClick={() => void downloadStructureExcel(wbs, sessionId)}
                title="Экспортировать структуру в Excel"
                aria-label="Экспортировать структуру в Excel"
              >
                <Download size={16} strokeWidth={2.2} aria-hidden="true" />
              </button>
              <button
                style={buttonStyle("primary", approveDisabled)}
                disabled={approveDisabled}
                onClick={onApprove}
                title={
                  pendingAi > 0
                    ? `Проверьте ${pendingAi} добавленных ИИ работ`
                    : pendingReview > 0
                    ? `Подтвердите ${pendingReview} строк с низкой уверенностью`
                    : ""
                }
              >
                Утвердить структуру →
              </button>
            </div>
          )
        }
      />
      {wbs.sequence_locked && (
        <div style={{ ...feedbackStyle, marginBottom: 14 }}>
          Порядок задан справочником
        </div>
      )}
      {unresolvedDisputes > 0 && (
        <div style={{ ...feedbackStyle, marginBottom: 14 }}>
          До утверждения структуры закройте все спорные строки: {unresolvedDisputes}.
          {pendingReview > 0 ? " Подтвердите выбранный этап кнопкой «Утвердить» или перенесите строку в другую группу." : ""}
          {pendingAi > 0 ? " Добавленные ИИ работы нужно принять или отклонить." : ""}
        </div>
      )}

      {stageFloorSections.map((section) => (
        <div key={section.key} style={{ marginBottom: section.showTitle ? 16 : 0 }}>
          {section.showTitle && (
            <div
              style={{
                margin: "18px 0 8px",
                paddingBottom: 6,
                borderBottom: "1px solid var(--border)",
                color: "var(--text)",
                fontSize: 14,
                fontWeight: 700,
              }}
            >
              {section.title}
            </div>
          )}
          {section.groups.map((g) => (
            <Stage1Group
              key={g.id}
              group={g}
              groupOptions={groupOptions}
              busy={busy}
              run={run}
              projectId={projectId}
              addItemOptimistic={addItemOptimistic}
              acceptRecommendedItemOptimistic={acceptRecommendedItemOptimistic}
              approveReviewItemOptimistic={approveReviewItemOptimistic}
              sequenceLocked={wbs.sequence_locked}
            />
          ))}
        </div>
      ))}

      {!wbs.sequence_locked && <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <input
          value={newGroup}
          onChange={(e) => setNewGroup(e.target.value)}
          placeholder="Новая группа работ"
          style={inputStyle}
        />
        <button
          style={btn()}
          disabled={busy || !newGroup.trim()}
          onClick={() =>
            run(async () => {
              const r = await ktpEstimate.createGroup(projectId, sessionId, newGroup.trim());
              setNewGroup("");
              return r;
            })
          }
        >
          + Группа
        </button>
      </div>}
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>
        <button
          type="button"
          style={buttonStyle("primary", busy || unresolvedDisputes === 0)}
          disabled={busy || unresolvedDisputes === 0}
          onClick={() => void acceptAllStage1ItemsOptimistic()}
          title="Принять все рекомендованные работы и утвердить строки, требующие проверки"
        >
          <ButtonContent loading={busy}>Принять все работы</ButtonContent>
        </button>
      </div>
    </div>
  );
}

function Stage1Group({
  group,
  groupOptions,
  busy,
  run,
  projectId,
  addItemOptimistic,
  acceptRecommendedItemOptimistic,
  approveReviewItemOptimistic,
  sequenceLocked,
}: {
  group: KtpWbsGroup;
  groupOptions: { id: string; title: string }[];
  busy: boolean;
  run: (fn: () => Promise<KtpWbs>) => Promise<void>;
  projectId: string;
  addItemOptimistic: (groupId: string, name: string) => Promise<void>;
  acceptRecommendedItemOptimistic: (itemId: string) => Promise<void>;
  approveReviewItemOptimistic: (itemId: string) => Promise<void>;
  sequenceLocked: boolean;
}) {
  const [title, setTitle] = useState(() => displayStageGroupTitle(group.title) || group.title);
  const [newItem, setNewItem] = useState("");
  const identifier = groupIdentifier(group);
  useEffect(() => {
    setTitle(displayStageGroupTitle(group.title) || group.title);
  }, [group.id, group.title]);
  const submitNewItem = () => {
    const name = newItem.trim();
    if (!name || busy) return;
    setNewItem("");
    void addItemOptimistic(group.id, name);
  };

  return (
    <div style={{ ...card, marginBottom: 12, padding: 14 }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <span
          title={groupIdentifierTitle(group)}
          style={{
            flex: "0 0 auto",
            alignSelf: "center",
            minWidth: 74,
            maxWidth: 128,
            padding: "5px 8px",
            border: "1px solid var(--border)",
            borderRadius: 6,
            background: "var(--bg)",
            color: "var(--muted)",
            fontSize: 12,
            fontWeight: 700,
            lineHeight: 1,
            textAlign: "center",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {identifier}
        </span>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => {
            if (sequenceLocked) return;
            const cleanTitle = title.trim();
            const persistedTitle = displayStageGroupTitle(group.title) || group.title;
            if (cleanTitle && cleanTitle !== persistedTitle) {
              void run(() => ktpEstimate.updateGroup(projectId, group.id, { title: title.trim() }));
            }
          }}
          disabled={sequenceLocked}
          style={{ ...inputStyle, fontWeight: 600, flex: 1 }}
        />
        {group.wt_code && (
          <span
            title={group.wt_name || group.wt_code}
            style={{ fontSize: 11, color: "var(--muted)", alignSelf: "center" }}
          >
            WT {group.wt_code}
          </span>
        )}
        {!sequenceLocked && <button
          style={btn("danger")}
          disabled={busy}
          onClick={() => run(() => ktpEstimate.deleteGroup(projectId, group.id))}
          title={group.items.length ? "Сначала перенесите или удалите работы" : "Удалить группу"}
        >
          Удалить группу
        </button>}
      </div>

      {group.items.map((it) => {
        const badge = itemSourceBadge(it);
        const rejected = it.review_status === "rejected";
        const isAiAdded = it.origin === "ai_added";
        const pendingAi = isAiAdded && it.review_status === "pending";
        const needsReview =
          !isAiAdded && (it.stage_needs_review || it.work_type_needs_review || it.operator_review_required);
        const reviewReason =
          it.stage_review_reason ||
          (it.work_type_needs_review || it.operator_review_required ? "Нужно проверить тип работ" : null);
        const sectionLines = sourceParentLines(it);
        return (
          <div
            key={it.id}
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(220px, 1.2fr) minmax(150px, .8fr) minmax(96px, auto) minmax(170px, 260px) 38px",
              alignItems: "center",
              gap: 8,
              padding: pendingAi ? "7px 8px" : "7px 0",
              borderTop: "1px solid var(--border)",
              borderRadius: pendingAi ? 6 : 0,
              background: pendingAi ? "rgba(245,158,11,.08)" : "transparent",
              opacity: rejected ? 0.5 : 1,
            }}
          >
            <span style={{ minWidth: 0, fontSize: 13 }}>{it.name}</span>
            <div
              title={isAiAdded ? it.ai_reason || "Рекомендовано" : sectionLines.join("\n")}
              style={{
                minWidth: 0,
                color: "var(--muted)",
                fontSize: 11,
                lineHeight: 1.35,
              }}
            >
              {isAiAdded ? (
                <span style={{ fontWeight: 600, color: "#92400e" }}>Рекомендовано</span>
              ) : sectionLines.length ? (
                sectionLines.map((line, index) => (
                  <div key={line}>
                    {index === 0 ? "Раздел: " : "Подраздел: "}
                    {line}
                  </div>
                ))
              ) : (
                <span>Раздел: —</span>
              )}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", minWidth: 0 }}>
              {badge && (
                <span style={{ fontSize: 10, fontWeight: 600, color: badge.color, whiteSpace: "nowrap" }}>
                  {badge.label}
                </span>
              )}
              {isAiAdded && (
                <button
                  style={{
                    ...btn(),
                    width: 32,
                    height: 30,
                    padding: 0,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: it.review_status === "accepted" ? "#15803d" : "var(--text)",
                  }}
                  disabled={busy}
                  onClick={() => void acceptRecommendedItemOptimistic(it.id)}
                  title="Принять рекомендованную работу"
                  aria-label="Принять рекомендованную работу"
                >
                  <Check size={14} strokeWidth={3} aria-hidden="true" />
                </button>
              )}
              {needsReview && !it.manual_override && (
                <button
                  style={{ ...btn(), padding: "4px 9px", color: "#92400e" }}
                  disabled={busy}
                  onClick={() => void approveReviewItemOptimistic(it.id)}
                  title="Подтвердить выбранный этап и тип"
                >
                  Утвердить
                </button>
              )}
            </div>
            <select
              value={group.id}
              disabled={busy}
              onChange={(e) =>
                run(() => ktpEstimate.updateItem(projectId, it.id, { group_id: e.target.value }))
              }
              style={{
                ...inputStyle,
                width: "100%",
                minWidth: 0,
                boxSizing: "border-box",
                padding: "4px 28px 4px 8px",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {groupOptions.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.title}
                </option>
              ))}
            </select>
            <button
              style={{
                ...btn("danger"),
                width: 32,
                height: 30,
                padding: 0,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
              }}
              disabled={busy}
              onClick={() => run(() => ktpEstimate.deleteItem(projectId, it.id))}
              title="Удалить строку из структуры"
              aria-label="Удалить строку из структуры"
            >
              <Trash2 size={14} strokeWidth={2.2} aria-hidden="true" />
            </button>
          </div>
        );
      })}

      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <input
          value={newItem}
          onChange={(e) => setNewItem(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              submitNewItem();
            }
          }}
          placeholder="Добавить работу вручную"
          style={inputStyle}
        />
        <button
          style={btn()}
          disabled={busy || !newItem.trim()}
          onClick={submitNewItem}
        >
          Добавить работу
        </button>
      </div>
    </div>
  );
}

// ── ЭТАП 2 ───────────────────────────────────────────────────────────────────

function Stage2({
  wbs,
  projectId,
  sessionId,
  busy,
  setBusy,
  setError,
  reload,
  revisiting,
  onReturn,
}: {
  wbs: KtpWbs;
  projectId: string;
  sessionId: string;
  busy: boolean;
  setBusy: (v: boolean) => void;
  setError: (v: string | null) => void;
  reload: () => Promise<void>;
  revisiting?: boolean;
  onReturn?: () => void;
}) {
  const groupsWithWorks = wbs.groups.filter((g) =>
    g.items.some((item) => item.review_status !== "rejected"),
  );
  const allReady = groupsWithWorks.every((g) => g.status === "card_generated");
  const [approving, setApproving] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [generatingGroupIds, setGeneratingGroupIds] = useState<Set<string>>(new Set());
  const missingCards = groupsWithWorks.filter((g) => g.status !== "card_generated").length;
  const hasGeneratingCards = generatingGroupIds.size > 0;

  const markGenerating = useCallback((groupId: string, generating: boolean) => {
    setGeneratingGroupIds((prev) => {
      const next = new Set(prev);
      if (generating) {
        next.add(groupId);
      } else {
        next.delete(groupId);
      }
      return next;
    });
  }, []);

  return (
    <div>
      <Header
        title="КТП"
        hint="Создайте КТП для каждой группы работ. ИИ может задать уточняющие вопросы."
        right={
          revisiting ? (
            <button type="button" style={buttonStyle("primary", busy || hasGeneratingCards)} disabled={busy || hasGeneratingCards} onClick={onReturn}>
              Вернуться к производительности
            </button>
          ) : (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
              <button
                type="button"
                style={buttonStyle("ghost", busy || hasGeneratingCards)}
                disabled={busy || hasGeneratingCards}
                onClick={async () => {
                  if (hasGeneratingCards) {
                    setNotice(`Дождитесь завершения создания КТП. В работе: ${generatingGroupIds.size}.`);
                    return;
                  }
                  setNotice(null);
                  setSkipping(true);
                  setBusy(true);
                  try {
                    await ktpEstimate.skipStage2(projectId, sessionId);
                    trackActivity("KTP_STAGE2_SKIPPED", {
                      projectId,
                      entityType: "ktp_estimate_session",
                      entityId: sessionId,
                      metadata: {
                        estimate_batch_id: wbs.session.estimate_batch_id,
                        groups_count: groupsWithWorks.length,
                      },
                    });
                    await reload();
                  } catch (e: any) {
                    setError(e.message);
                  } finally {
                    setSkipping(false);
                    setBusy(false);
                  }
                }}
              >
                <ButtonContent loading={skipping}>Без КТП</ButtonContent>
              </button>
              <button
                style={buttonStyle("primary", busy || hasGeneratingCards)}
                disabled={busy || hasGeneratingCards}
                onClick={async () => {
                  if (hasGeneratingCards) {
                    setNotice(`Дождитесь завершения создания КТП. В работе: ${generatingGroupIds.size}.`);
                    return;
                  }
                  if (!allReady) {
                    setNotice(`Сначала создайте все КТП. Осталось: ${missingCards}.`);
                    return;
                  }
                  setNotice(null);
                  setApproving(true);
                  setBusy(true);
                  try {
                    await ktpEstimate.approveStage2(projectId, sessionId);
                    trackActivity("KTP_STAGE2_APPROVED", {
                      projectId,
                      entityType: "ktp_estimate_session",
                      entityId: sessionId,
                      metadata: {
                        estimate_batch_id: wbs.session.estimate_batch_id,
                        groups_count: groupsWithWorks.length,
                      },
                    });
                    await reload();
                  } catch (e: any) {
                    setError(e.message);
                  } finally {
                    setApproving(false);
                    setBusy(false);
                  }
                }}
              >
                <ButtonContent loading={approving}>Все карточки готовы → к производительности</ButtonContent>
              </button>
            </div>
          )
        }
      />
      {notice && (
        <div
          role="alert"
          style={{
            ...feedbackStyle,
            marginTop: -4,
            marginBottom: 12,
          }}
        >
          {notice}
        </div>
      )}
      {groupsWithWorks.map((g) => (
        <Stage2Group
          key={g.id}
          group={g}
          projectId={projectId}
          busy={busy}
          setError={setError}
          reload={reload}
          onGeneratingChange={markGenerating}
        />
      ))}
    </div>
  );
}

function Stage2Group({
  group,
  projectId,
  busy,
  setError,
  reload,
  onGeneratingChange,
}: {
  group: KtpWbsGroup;
  projectId: string;
  busy: boolean;
  setError: (v: string | null) => void;
  reload: () => Promise<void>;
  onGeneratingChange: (groupId: string, generating: boolean) => void;
}) {
  const [questions, setQuestions] = useState<KtpQuestion[] | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [cardData, setCardData] = useState<KtpEstimateCard | null>(null);
  const [generating, setGenerating] = useState(false);
  const [validation, setValidation] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (group.status === "card_generated" || group.status === "card_questions") {
      void ktpEstimate.getCard(projectId, group.id).then((c) => {
        setCardData(c);
        if (c.status === "card_questions" && c.questions_json) setQuestions(c.questions_json);
      });
    }
  }, [projectId, group.id, group.status]);

  const generate = async (withAnswers: Record<string, string>) => {
    if (generating) return;
    setGenerating(true);
    onGeneratingChange(group.id, true);
    trackActivity("KTP_STAGE2_CARD_GENERATION_STARTED", {
      projectId,
      entityType: "ktp_wbs_group",
      entityId: group.id,
      metadata: {
        group_title: group.title,
        answers_count: Object.keys(withAnswers).length,
      },
    });
    try {
      const res = await ktpEstimate.generateCard(projectId, group.id, withAnswers);
      setValidation(null);
      if (res.sufficient) {
        setQuestions(null);
        setCardData(res.card);
        trackActivity("KTP_STAGE2_CARD_GENERATED", {
          projectId,
          entityType: "ktp_wbs_group",
          entityId: group.id,
          metadata: {
            group_title: group.title,
            card_status: res.card.status,
          },
        });
      } else {
        setQuestions(res.questions);
        trackActivity("KTP_STAGE2_CARD_QUESTIONS_REQUIRED", {
          projectId,
          entityType: "ktp_wbs_group",
          entityId: group.id,
          metadata: {
            group_title: group.title,
            questions_count: res.questions.length,
          },
        });
      }
      await reload();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setGenerating(false);
      onGeneratingChange(group.id, false);
    }
  };

  const requiredAnswersMissing = questions?.some((q) => !answers[q.key]?.trim()) ?? false;

  const statusLabel: Record<KtpWbsGroup["status"], string> = {
    draft: "Не создана",
    not_applicable: "Не выполняется",
    card_questions: "Нужны данные",
    card_generated: "Готова",
    card_failed: "Ошибка",
  };

  return (
    <div style={{ ...card, marginBottom: 12, padding: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 9,
            minWidth: 0,
            flex: 1,
            padding: 0,
            border: "none",
            background: "transparent",
            color: "var(--text)",
            cursor: "pointer",
            fontFamily: "var(--sans)",
            textAlign: "left",
          }}
        >
          <span
            style={{
              width: 22,
              height: 22,
              borderRadius: 5,
              border: "1px solid var(--border)",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--muted)",
              flexShrink: 0,
            }}
          >
            <Chevron open={expanded} />
          </span>
          <span style={{ fontSize: 14, fontWeight: 600, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
            {group.title}
          </span>
          <span style={{ fontSize: 11, color: "var(--muted)", whiteSpace: "nowrap" }}>
            {group.items.length} работ
          </span>
        </button>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              color:
                group.status === "card_generated"
                  ? "#15803d"
                  : group.status === "card_failed"
                  ? "var(--red)"
                  : "var(--muted)",
            }}
          >
            {statusLabel[group.status]}
          </span>
          <button style={buttonStyle("ghost", busy || generating)} disabled={busy || generating} onClick={() => generate(answers)}>
            <ButtonContent loading={generating}>
              {group.status === "card_generated" ? "Пересоздать КТП" : "Создать КТП"}
            </ButtonContent>
          </button>
        </div>
      </div>

      {expanded && (
        <div
          style={{
            marginTop: 12,
            padding: "10px 12px",
            borderRadius: 6,
            border: "1px solid var(--border)",
            background: "rgba(148,163,184,.06)",
            display: "grid",
            gap: 7,
          }}
        >
          {group.items.length ? (
            group.items.map((item, index) => (
              <div
                key={item.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "34px minmax(0, 1fr) auto",
                  gap: 10,
                  alignItems: "start",
                  fontSize: 12,
                  color: "var(--text)",
                }}
              >
                <span style={{ color: "var(--muted)", fontFamily: "var(--mono)" }}>{index + 1}</span>
                <span style={{ minWidth: 0 }}>{item.name}</span>
                {(item.quantity != null || item.unit) && (
                  <span style={{ color: "var(--muted)", whiteSpace: "nowrap" }}>
                    {item.quantity ?? ""} {item.unit ?? ""}
                  </span>
                )}
              </div>
            ))
          ) : (
            <div style={{ fontSize: 12, color: "var(--muted)" }}>В группе пока нет работ.</div>
          )}
        </div>
      )}

      {questions && (
        <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
          {questions.map((q) => (
            <div key={q.key}>
              <label style={{ fontSize: 12, fontWeight: 600, display: "block", marginBottom: 3 }}>
                {q.label}
              </label>
              {q.hint && (
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 3 }}>{q.hint}</div>
              )}
              <input
                style={inputStyle}
                value={answers[q.key] || ""}
                onChange={(e) => {
                  setValidation(null);
                  setAnswers((a) => ({ ...a, [q.key]: e.target.value }));
                }}
              />
            </div>
          ))}
          {validation && (
            <div role="alert" style={feedbackStyle}>
              {validation}
            </div>
          )}
          <button
            style={buttonStyle("primary", busy || generating)}
            disabled={busy || generating}
            onClick={() => {
              if (requiredAnswersMissing) {
                setValidation("Заполните ответы на вопросы, чтобы создать КТП.");
                return;
              }
              void generate(answers);
            }}
          >
            <ButtonContent loading={generating}>Ответить и создать КТП</ButtonContent>
          </button>
        </div>
      )}

      {cardData && cardData.status === "card_generated" && (
        <CardView
          card={cardData}
          busy={busy || generating}
          onSave={async (patch) => {
            try {
              setCardData(await ktpEstimate.updateCard(projectId, group.id, patch));
            } catch (e: any) {
              setError(e.message);
            }
          }}
        />
      )}
    </div>
  );
}

function CardView({
  card,
  busy,
  onSave,
}: {
  card: KtpEstimateCard;
  busy: boolean;
  onSave: (patch: { title?: string; goal?: string }) => Promise<void>;
}) {
  const [title, setTitle] = useState(card.title || "");
  const [goal, setGoal] = useState(card.goal || "");
  const [saving, setSaving] = useState(false);
  // sync локальный state при перегенерации/обновлении карточки
  useEffect(() => {
    setTitle(card.title || "");
    setGoal(card.goal || "");
  }, [card.id, card.title, card.goal]);
  const dirty = title !== (card.title || "") || goal !== (card.goal || "");

  return (
    <div style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
      <div style={{ display: "grid", gap: 8, marginBottom: 10 }}>
        <input
          style={{ ...inputStyle, width: "100%", fontWeight: 600 }}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <textarea
          style={{ ...inputStyle, width: "100%", minHeight: 50, resize: "vertical" }}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="Цель"
        />
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, marginBottom: 8 }}>
        <thead>
          <tr style={{ background: "rgba(148,163,184,.08)" }}>
            <th style={thCell}>№</th>
            <th style={thCell}>Этап</th>
            <th style={thCell}>Содержание работ</th>
            <th style={thCell}>Контроль</th>
          </tr>
        </thead>
        <tbody>
          {(card.steps || []).map((s: any, i: number) => (
            <tr key={i} style={{ borderTop: "1px solid var(--border)" }}>
              <td style={tdCell}>{s.no ?? i + 1}</td>
              <td style={tdCell}>{s.stage}</td>
              <td style={tdCell}>{s.work_details}</td>
              <td style={tdCell}>{s.control_points}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!!card.recommendations?.length && (
        <ul style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 8px", paddingLeft: 18 }}>
          {card.recommendations.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      {dirty && (
        <button
          style={buttonStyle("primary", busy)}
          disabled={busy}
          onClick={async () => {
            setSaving(true);
            try {
              await onSave({ title, goal });
            } finally {
              setSaving(false);
            }
          }}
        >
          <ButtonContent loading={saving}>Сохранить правки</ButtonContent>
        </button>
      )}
    </div>
  );
}

// ── ЭТАП 2.5 ───────────────────────────────────────────────────────────────

function fmtMetric(value: number | null | undefined): string | null {
  if (value == null || !Number.isFinite(value)) return null;
  const abs = Math.abs(value);
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: abs > 0 && abs < 1 ? 4 : 2 }).format(value);
}

function fmtMetricRange(
  min: number | null | undefined,
  avg: number | null | undefined,
  max: number | null | undefined,
): string | null {
  const values = [fmtMetric(min), fmtMetric(avg), fmtMetric(max)];
  if (!values.some(Boolean)) return null;
  return `${values[0] ?? "—"} / ${values[1] ?? "—"} / ${values[2] ?? "—"}`;
}

const RATE_REVIEW_REASON_LABELS: Record<string, string> = {
  no_approved_compatible_rate: "нет утверждённой совместимой расценки",
  multiple_equivalent_rate_candidates: "несколько равнозначных расценок",
  unit_incompatible: "несовместимые единицы измерения",
  operation_missing: "не определена операция для подбора расценки",
  operation_unit_conflict: "конфликт операции и единицы",
  package_conflict: "конфликт пакетной расценки",
  package_conflict_unresolved: "конфликт пакетной и атомарных расценок",
  taxonomy_or_operation_missing: "нет таксономии или операции",
  operation_resolution_failed: "не удалось определить операцию",
  rate_not_approved: "расценка не утверждена",
  catalog_labor_not_available: "нет каталожной трудоёмкости",
  provisional_rate_requires_approval: "расценка требует утверждения",
  quantity_missing: "не задан объём работы",
  user_rate_input_required: "нужно ввести пользовательскую норму",
  user_rate_identity_required: "нужен пользователь для нормы по факту",
  special_masonry_operation_mismatch: "операция кладки не совпадает с типом работы",
  roof_covering_material_conflict: "конфликт материала кровли",
  roof_covering_material_not_resolved: "материал кровли не определён",
  brick_pillar_rate_not_available: "нет расценки для кладки столбов",
  vent_shaft_masonry_rate_not_available: "нет расценки для кладки вентканалов",
  facade_cladding_rate_not_available: "нет расценки для облицовки фасада",
  membrane_context_not_resolved: "не удалось определить тип мембраны и место её монтажа",
  rate_variant_required: "не хватает обязательных параметров работы для выбора нормы",
};

function rateReviewLabel(reason: string | null | undefined): string {
  if (!reason) return "нет применимой каталожной нормы";
  return RATE_REVIEW_REASON_LABELS[reason] || "требуется уточнить параметры работы для выбора нормы";
}

const RATE_VARIANT_FIELD_LABELS: Record<string, string> = {
  insulation_location: "место утепления (фундамент, фасад, кровля или внутренние стены)",
  insulation_material: "материал утеплителя",
  membrane_type: "тип мембраны",
  installation_position: "место монтажа мембраны",
  roof_structure_material: "материал несущей конструкции кровли",
  roof_covering_material: "материал кровельного покрытия",
  base_type: "тип основания",
};

function rateSelectionSubReasonLabel(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const fields = value
    .split(",")
    .map((field) => RATE_VARIANT_FIELD_LABELS[field.trim()])
    .filter((field): field is string => Boolean(field));
  return fields.length ? fields.join(", ") : null;
}

function catalogWarningLabel(row: KtpSessionSubtype): string {
  const missingFields = rateSelectionSubReasonLabel(row.rate_trace?.selection_sub_reason);
  if (row.rate_review_reason === "rate_variant_required" && missingFields) {
    return `не определено: ${missingFields}`;
  }
  return row.rate_review_label || rateReviewLabel(row.rate_review_reason);
}

function rateRequiredAction(row: KtpSessionSubtype): NonNullable<KtpSessionSubtype["required_action"]> {
  if (row.required_action && row.required_action !== "none") return row.required_action;
  if (row.rate_review_reason === "user_rate_input_required") return "enter_labor_rate";
  if (row.rate_review_reason === "quantity_missing") return "enter_quantity";
  if (row.rate_review_reason === "work_unit_required") return "clarify_unit";
  if (row.rate_review_reason === "atomic_work_required") return "decompose_or_choose_type";
  if (
    row.rate_review_reason === "operation_resolution_failed" ||
    row.rate_review_reason === "work_classification_required" ||
    row.rate_review_reason === "object_scope_required" ||
    row.rate_review_reason === "rate_context_required" ||
    row.rate_review_reason === "rate_variant_required"
  ) {
    return "clarify_work_type";
  }
  return row.required_action || "none";
}

function acceptedCatalogOutput(row: KtpSessionSubtype): number | null {
  const labor = row.effective_labor_hours_per_unit_avg ?? row.labor_hours_per_unit_avg;
  const crew = row.crew_size;
  if (!labor || labor <= 0 || !crew || crew <= 0) return null;
  return Math.round((crew * 8 / labor) * 10000) / 10000;
}

function rateTraceTitle(row: KtpSessionSubtype): string {
  const trace = row.rate_trace;
  const first = trace?.rate_candidates?.[0];
  const candidateCount = trace?.rate_candidates?.length || 0;
  const subReason = rateSelectionSubReasonLabel(trace?.selection_sub_reason);
  const lines = [
    `Результат: ${catalogWarningLabel(row)}`,
    subReason ? `Не хватает данных: ${subReason}` : null,
    rateIssueDifficulty(row),
    trace?.source_row_text ? `Строка: ${trace.source_row_text}` : null,
    trace?.detected_operations?.length ? `Операции: ${trace.detected_operations.join(", ")}` : null,
    candidateCount ? `Кандидатов ставок: ${candidateCount}` : null,
    first?.rate_context_code ? `Контекст: ${first.rate_context_code}` : null,
    first?.source_file ? `Источник: ${first.source_file}` : null,
    first?.source_rate_id ? `ID нормы: ${first.source_rate_id}` : null,
    first?.source_value != null ? `Исходно: ${first.source_value} ${first.source_unit ?? ""}`.trim() : null,
    first?.normalized_value != null ? `Нормализовано: ${first.normalized_value} ${first.normalized_unit ?? ""}`.trim() : null,
    first?.approval_status ? `Статус: ${first.approval_status}` : null,
    first?.target_kind === "multi_operation" ? "Проверьте декомпозицию: исходная норма относится к нескольким операциям." : null,
  ].filter(Boolean);
  return lines.join("\n");
}

function rateIssueDifficulty(row: KtpSessionSubtype): string {
  const reason = row.rate_review_reason;
  const trace = row.rate_trace;
  const candidateCount = trace?.rate_candidates?.length || 0;
  if (reason === "multiple_equivalent_rate_candidates") {
    return `Трудность: найдено ${candidateCount} равнозначных ставок, нужен выбор оператора.`;
  }
  if (reason === "unit_incompatible") {
    return "Трудность: норма найдена, но единицы разных измерений; нужен параметр, точный объём или коэффициент.";
  }
  if (reason === "taxonomy_or_operation_missing" || reason === "operation_resolution_failed") {
    return "Трудность: строка не сведена к одной операции; нужна корректировка mapping или разбиение на операции.";
  }
  if (reason === "no_approved_compatible_rate") {
    if (trace?.selection_sub_reason === "package_expansion_required") {
      return "Трудность: строка описывает полный цикл, а в каталоге есть ставки только на отдельные компоненты; нужно разложить работу или подтвердить частичный расчёт.";
    }
    return "Трудность: утверждённой auto-ставки нет; нужна ставка, package-разложение или подтверждение provisional нормы.";
  }
  if (reason === "provisional_rate_requires_approval") {
    return "Трудность: норма есть, но источник требует ручного подтверждения.";
  }
  return "Трудность: требуется проверка оператора.";
}

function unitLabel(code: string | null | undefined): string {
  const map: Record<string, string> = {
    m2: "м²",
    m3: "м³",
    m: "м",
    t: "т",
    kg: "кг",
    pcs: "шт.",
    object: "объект",
    building: "здание",
    floor: "этаж",
    block: "блок",
    pile_head: "оголовок сваи",
    slab: "плита",
    set: "компл.",
    unit: "ед.",
  };
  return code ? map[code] || code : "ед.";
}

type RateTraceCandidate = NonNullable<NonNullable<KtpSessionSubtype["rate_trace"]>["rate_candidates"]>[number];

function candidateUnitCode(candidate: RateTraceCandidate | undefined | null): string | null {
  if (!candidate) return null;
  if (candidate.unit_code) return candidate.unit_code;
  const normalizedUnit = candidate.normalized_unit || "";
  const slash = normalizedUnit.lastIndexOf("/");
  return slash >= 0 ? normalizedUnit.slice(slash + 1) : null;
}

function equivalentRateCandidates(row: KtpSessionSubtype): RateTraceCandidate[] {
  if (row.rate_review_reason !== "multiple_equivalent_rate_candidates") return [];
  const sourceUnit = row.item_unit_code || null;
  return (row.rate_trace?.rate_candidates || [])
    .filter((candidate) => {
      const targetUnit = candidateUnitCode(candidate);
      return typeof candidate.normalized_value === "number" && (!sourceUnit || !targetUnit || sourceUnit === targetUnit);
    })
    .slice(0, 3);
}

function packageComponentRateCandidates(row: KtpSessionSubtype): RateTraceCandidate[] {
  const trace = row.rate_trace;
  if (trace?.selection_sub_reason !== "package_expansion_required") return [];
  const sourceUnit = row.item_unit_code || null;
  return (trace.rate_candidates || [])
    .filter((candidate) => {
      const targetUnit = candidateUnitCode(candidate);
      return (
        (candidate as any).candidate_scope === "package_component" &&
        typeof candidate.normalized_value === "number" &&
        (!sourceUnit || !targetUnit || sourceUnit === targetUnit)
      );
    })
    .slice(0, 3);
}

function outputFromCandidate(row: KtpSessionSubtype, candidate: RateTraceCandidate): number | null {
  const labor = candidate.normalized_value;
  const crew = row.crew_size;
  if (typeof labor !== "number" || labor <= 0 || !crew || crew <= 0) return null;
  return Math.round((crew * 8 / labor) * 10000) / 10000;
}

function fmtNumber(value: number | null | undefined, digits = 4): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return String(Math.round(value * 10 ** digits) / 10 ** digits).replace(".", ",");
}

function workDaysInfo(row: KtpSessionSubtype): { days: number | null; title: string } {
  const volume = row.volume;
  const output = row.output_per_day;
  const labor = row.session_calculated_labor_hours_avg;
  const crew = row.crew_size;
  const lines: string[] = [];
  let exactDays: number | null = null;

  if (volume && volume > 0 && output && output > 0) {
    exactDays = volume / output;
    lines.push(`${fmtNumber(volume)} ${row.unit || "ед."} / ${fmtNumber(output)} ${row.unit || "ед."}/день = ${fmtNumber(exactDays)} дн.`);
  }

  if (labor && labor > 0 && crew && crew > 0) {
    const laborDays = labor / (crew * 8);
    if (exactDays == null) exactDays = laborDays;
    lines.push(`${fmtNumber(labor)} чел-ч / (${crew} чел × 8 ч) = ${fmtNumber(laborDays)} дн.`);
  }

  if (exactDays == null || exactDays <= 0) {
    return { days: null, title: "Нужны объём и производительность либо трудоёмкость и бригада" };
  }

  const days = Math.max(1, Math.ceil(exactDays));
  lines.push(`Округление вверх: ${days} дн.`);
  return { days, title: lines.join("\n") };
}

function StageProductivity({
  wbs,
  projectId,
  sessionId,
  busy,
  setBusy,
  setError,
  reload,
  onApprove,
}: {
  wbs: KtpWbs;
  projectId: string;
  sessionId: string;
  busy: boolean;
  setBusy: (v: boolean) => void;
  setError: (v: string | null) => void;
  reload: () => Promise<void>;
  onApprove: () => Promise<void>;
}) {
  const [optimisticSubtypePatches, setOptimisticSubtypePatches] = useState<Record<string, Partial<KtpSessionSubtype>>>({});
  const [optimisticItemPatches, setOptimisticItemPatches] = useState<Record<string, Partial<KtpWbsItem>>>({});
  const subtypes = useMemo(
    () =>
      (wbs.session_subtypes ?? []).map((row) => ({
        ...row,
        ...(optimisticSubtypePatches[row.id] || {}),
      })),
    [optimisticSubtypePatches, wbs.session_subtypes],
  );
  const itemById = useMemo(() => {
    const map = new Map<string, KtpWbsItem>();
    for (const group of wbs.groups) {
      for (const item of group.items) {
        map.set(item.id, {
          ...item,
          ...(optimisticItemPatches[item.id] || {}),
        });
      }
    }
    return map;
  }, [optimisticItemPatches, wbs.groups]);
  const groupedSubtypes = useMemo(() => {
    const rowsByGroup = new Map<string, KtpSessionSubtype[]>();
    for (const row of subtypes) {
      const item = row.item_id ? itemById.get(row.item_id) : undefined;
      const key = item?.group_id || "__ungrouped__";
      const rows = rowsByGroup.get(key) || [];
      rows.push(row);
      rowsByGroup.set(key, rows);
    }

    const groups = wbs.groups
      .map((group) => ({
        key: group.id,
        title: group.title,
        rows: rowsByGroup.get(group.id) || [],
      }))
      .filter((group) => group.rows.length > 0);

    const ungrouped = rowsByGroup.get("__ungrouped__") || [];
    if (ungrouped.length) {
      groups.push({ key: "__ungrouped__", title: "Без группы", rows: ungrouped });
    }
    return groups;
  }, [itemById, subtypes, wbs.groups]);
  const [taxonomySections, setTaxonomySections] = useState<WorkTaxonomySection[]>([]);
  const [taxonomySubtypes, setTaxonomySubtypes] = useState<WorkTaxonomySubtype[]>([]);
  const [selectingSubtypeId, setSelectingSubtypeId] = useState<string | null>(null);
  const [selectedTaxonomySection, setSelectedTaxonomySection] = useState<string>("");
  const [userRateDrafts, setUserRateDrafts] = useState<Record<string, string>>({});
  const [quantityDrafts, setQuantityDrafts] = useState<Record<string, string>>({});
  const [hoveredRateCandidateKey, setHoveredRateCandidateKey] = useState<string | null>(null);
  const filled = subtypes.filter(
    (s) => s.output_per_day != null && s.output_per_day > 0 && s.volume != null && s.volume > 0 && Boolean(s.unit?.trim()),
  ).length;
  const canContinue = subtypes.length > 0 && filled === subtypes.length;

  useEffect(() => {
    setOptimisticSubtypePatches({});
    setOptimisticItemPatches({});
  }, [wbs]);

  useEffect(() => {
    workTaxonomy
      .sections()
      .then((data) => {
        setTaxonomySections(data);
        setSelectedTaxonomySection((current) => current || data[0]?.section_code || "");
      })
      .catch((e) => setError(e.message));
  }, [setError]);

  useEffect(() => {
    if (!selectedTaxonomySection) {
      setTaxonomySubtypes([]);
      return;
    }
    workTaxonomy
      .subtypes({ section_code: selectedTaxonomySection })
      .then(setTaxonomySubtypes)
      .catch((e) => setError(e.message));
  }, [selectedTaxonomySection, setError]);

  async function saveField(
    subtypeId: string,
    patch: Partial<{
      unit: string | null;
      volume: number | null;
      output_per_day: number | null;
      crew_size: number | null;
      lag_after_days: number;
      selected_rate_item_id: string | null;
      selected_rate_mapping_id: string | null;
    }>,
  ) {
    setBusy(true);
    try {
      await ktpEstimate.updateSessionSubtype(projectId, subtypeId, patch);
      await reload();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function parsePositiveNumber(value: string | undefined): number | null {
    const parsed = Number(String(value || "").trim().replace(",", "."));
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }

  async function saveUserRate(row: KtpSessionSubtype) {
    const laborHoursPerUnit = parsePositiveNumber(userRateDrafts[row.id]);
    if (!row.can_create_user_rate) {
      setError(row.can_create_user_rate_reason || "Для этой строки пока нельзя сохранить личную норму");
      return;
    }
    if (laborHoursPerUnit == null) {
      setError("Укажите положительную трудоёмкость на единицу работы");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      await ktpEstimate.saveUserRate(projectId, sessionId, row.id, laborHoursPerUnit);
      setUserRateDrafts((current) => {
        const next = { ...current };
        delete next[row.id];
        return next;
      });
      await reload();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveRequiredQuantity(row: KtpSessionSubtype) {
    const quantity = parsePositiveNumber(quantityDrafts[row.id]);
    if (quantity == null) {
      setError("Укажите положительный объём работы");
      return;
    }
    await saveField(row.id, { volume: quantity });
    setQuantityDrafts((current) => {
      const next = { ...current };
      delete next[row.id];
      return next;
    });
  }

  async function rebuild() {
    setBusy(true);
    try {
      await ktpEstimate.buildSubtypes(projectId, sessionId);
      await reload();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function openSubtypeSelector(row: KtpSessionSubtype) {
    const code = row.work_subtype_code || row.subtype_code;
    const sectionCode = code.includes("/") ? code.split("/", 1)[0] : "";
    if (sectionCode && taxonomySections.some((section) => section.section_code === sectionCode)) {
      setSelectedTaxonomySection(sectionCode);
    }
    setSelectingSubtypeId(row.id);
  }

  async function saveManualSubtype(row: KtpSessionSubtype, workSubtypeCode: string) {
    if (!row.item_id || !workSubtypeCode) return;
    const selectedSubtype = taxonomySubtypes.find((subtype) => subtype.work_subtype_code === workSubtypeCode);
    const currentItem = itemById.get(row.item_id);
    const fallbackName = selectedSubtype?.work_subtype_name || row.work_subtype_name || row.subtype_name;
    const previousSubtypePatch = optimisticSubtypePatches[row.id];
    const previousItemPatch = optimisticItemPatches[row.item_id];

    setOptimisticSubtypePatches((current) => ({
      ...current,
      [row.id]: {
        ...current[row.id],
        subtype_code: workSubtypeCode,
        subtype_name: fallbackName,
        work_subtype_code: workSubtypeCode,
        work_subtype_name: fallbackName,
        taxonomy_code: selectedSubtype?.taxonomy_code ?? row.taxonomy_code,
        macro_name: selectedSubtype?.section_name ?? row.macro_name,
      },
    }));
    setOptimisticItemPatches((current) => ({
      ...current,
      [row.item_id!]: {
        ...current[row.item_id!],
        work_section_code: selectedSubtype?.section_code ?? current[row.item_id!]?.work_section_code ?? currentItem?.work_section_code,
        work_section_name: selectedSubtype?.section_name ?? current[row.item_id!]?.work_section_name ?? currentItem?.work_section_name,
        work_subtype_code: workSubtypeCode,
        work_subtype_name: fallbackName,
        work_type_source: "manual",
        work_type_confidence: "manual",
        work_type_needs_review: false,
        operator_review_required: false,
        manual_override: true,
      },
    }));
    setSelectingSubtypeId(null);
    try {
      await ktpEstimate.updateItem(projectId, row.item_id, { work_subtype_code: workSubtypeCode });
      await reload();
    } catch (e: any) {
      setOptimisticSubtypePatches((current) => {
        const next = { ...current };
        if (previousSubtypePatch) next[row.id] = previousSubtypePatch;
        else delete next[row.id];
        return next;
      });
      setOptimisticItemPatches((current) => {
        const next = { ...current };
        if (previousItemPatch) next[row.item_id!] = previousItemPatch;
        else delete next[row.item_id!];
        return next;
      });
      setError(e.message);
      await reload();
    }
  }

  function subtypeDictionaryHref(row: KtpSessionSubtype) {
    const code = row.work_subtype_code || row.subtype_code;
    const sectionCode = code.includes("/") ? code.split("/", 1)[0] : "";
    const params = new URLSearchParams({ tab: "work-types" });
    if (sectionCode) params.set("section", sectionCode);
    const query = row.work_subtype_name || row.subtype_name;
    if (query && !code.startsWith("__unknown__") && code !== "unknown/needs_review") params.set("q", query);
    return `/projects/${projectId}/types?${params.toString()}`;
  }

  const cols = "minmax(260px, 1fr) 145px 150px 110px 120px";

  return (
    <div>
      <Header
        title="Производительность работ"
        hint="Для каждого вида работ задайте объём, производительность бригады за смену и размер бригады. Колонка дней считается для 8-часового рабочего дня."
        right={
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <button type="button" style={buttonStyle("ghost", busy)} disabled={busy} onClick={() => void rebuild()}>
              <ButtonContent loading={busy}>Перестроить из сметы</ButtonContent>
            </button>
            <button type="button" style={buttonStyle("primary", busy || !canContinue)} disabled={busy || !canContinue} onClick={() => void onApprove()}>
              Перейти к ГПР
            </button>
          </div>
        }
      />

      <div style={{ ...card, padding: 14, marginBottom: 14, display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center", fontSize: 12 }}>
        <span>Видов работ: <b>{subtypes.length}</b></span>
        <span>Заполнено: <b>{filled}</b></span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color: "var(--muted)" }}>
          <span style={{ color: "var(--blue-dark)", fontWeight: 700 }}>к</span> из каталога
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5, color: "var(--muted)" }}>
          <span style={{ width: 11, height: 11, borderRadius: 3, background: "#22c55e22", border: "1px solid #16a34a55", display: "inline-block" }} /> задано оператором
        </span>
        {!canContinue && subtypes.length > 0 && (
          <span style={{ color: "var(--muted)" }}>Заполните объём, единицу и производительность у всех строк, чтобы продолжить</span>
        )}
      </div>

      {subtypes.length === 0 ? (
        <div style={{ ...card, padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>
          Таблица подтипов пуста. Нажмите «Перестроить из сметы».
        </div>
      ) : (
        <div style={{ ...card, overflow: "hidden" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: cols,
              gap: 10,
              alignItems: "center",
              padding: "10px 14px",
              borderBottom: "1px solid var(--border)",
              fontSize: 11,
              fontWeight: 700,
              color: "var(--muted)",
            }}
          >
            <div>Вид работ</div>
            <div>Объём{`, `}ед.</div>
            <div>Произв./смену</div>
            <div>Бригада</div>
            <div>Дней</div>
          </div>
          {groupedSubtypes.map((group) => (
            <div key={group.key}>
              <div
                style={{
                  padding: "9px 14px",
                  borderBottom: "1px solid var(--border)",
                  background: "#f8fafc",
                  color: "var(--text)",
                  fontSize: 12,
                  fontWeight: 700,
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                }}
              >
                <span>{group.title}</span>
                <span style={{ color: "var(--muted)", fontWeight: 600 }}>{group.rows.length}</span>
              </div>
              {group.rows.map((s) => {
                const unknown =
                  s.subtype_code.startsWith("__unknown__") ||
                  s.subtype_code === "unknown/needs_review";
                const sourceItem = s.item_id ? itemById.get(s.item_id) : undefined;
                const typeName = s.work_subtype_name || s.subtype_name;
                const dictionarySelected =
                  !unknown &&
                  Boolean(sourceItem?.manual_override) &&
                  sourceItem?.work_type_source === "manual";
                const selectorOpen = selectingSubtypeId === s.id;
                const rowUnitLabel = s.display_unit || unitLabel(s.item_unit_code || s.unit);
                const requiredAction = rateRequiredAction(s);
                const needsUserRate = requiredAction === "enter_labor_rate";
                const needsQuantity = requiredAction === "enter_quantity";
                const laborPerUnit = fmtMetricRange(
                  s.effective_labor_hours_per_unit_min ?? s.labor_hours_per_unit_min,
                  s.effective_labor_hours_per_unit_avg ?? s.labor_hours_per_unit_avg,
                  s.effective_labor_hours_per_unit_max ?? s.labor_hours_per_unit_max,
                );
                const sessionLabor = fmtMetricRange(
                  s.session_calculated_labor_hours_min,
                  s.session_calculated_labor_hours_avg,
                  s.session_calculated_labor_hours_max,
                );
                const catalogWarning =
                  s.rate_auto_applicable === false && !needsUserRate
                    ? catalogWarningLabel(s)
                    : null;
                const isProvisionalRate = s.rate_review_reason === "provisional_rate_requires_approval";
                const operatorRateConfirmed = s.output_source === "manual" && Boolean(s.selected_rate_item_id) && s.output_per_day != null;
                const provisionalConfirmed = isProvisionalRate && operatorRateConfirmed;
                const provisionalOutput = isProvisionalRate ? acceptedCatalogOutput(s) : null;
                const traceTitle = s.rate_trace ? rateTraceTitle(s) : undefined;
                const equivalentCandidates = equivalentRateCandidates(s);
                const componentCandidates = packageComponentRateCandidates(s);
                const numericCandidate = s.rate_trace?.rate_candidates?.find(
                  (candidate) => typeof candidate.normalized_value === "number",
                );
                const userRateValue = parsePositiveNumber(userRateDrafts[s.id]);
                const quantityValue = parsePositiveNumber(quantityDrafts[s.id]);
                const daysInfo = workDaysInfo(s);
                return (
                  <div
                    key={s.id}
                    style={{
                      display: "grid",
                      gridTemplateColumns: cols,
                      gap: 10,
                      alignItems: "center",
                      padding: "10px 14px",
                      borderBottom: "1px solid var(--border)",
                      fontSize: 12,
                      background: unknown ? "#fef9f9" : dictionarySelected ? "#f0fdf4" : undefined,
                    }}
                  >
                    <div>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 7,
                          flexWrap: "wrap",
                          fontWeight: 600,
                          color: unknown ? "var(--red)" : dictionarySelected ? "#15803d" : "var(--text)",
                        }}
                      >
                        {!unknown && s.taxonomy_code ? (
                          <a
                            href={subtypeDictionaryHref(s)}
                            title={`Открыть в справочнике: ${typeName}`}
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              flex: "0 0 auto",
                              minWidth: 34,
                              padding: "2px 6px",
                              borderRadius: 5,
                              border: "1px solid var(--border2)",
                              background: "var(--surface)",
                              color: dictionarySelected ? "#15803d" : "var(--blue-dark)",
                              fontFamily: "var(--mono)",
                              fontSize: 11,
                              fontWeight: 700,
                              lineHeight: 1.2,
                              textDecoration: "none",
                            }}
                          >
                            {s.taxonomy_code}
                          </a>
                        ) : null}
                        <span>{unknown ? "Тип работы не определён" : typeName}</span>
                        {dictionarySelected ? (
                          <button
                            type="button"
                            disabled={busy || !s.item_id}
                            onClick={() => openSubtypeSelector(s)}
                            title="Тип работы выбран оператором из справочника. Нажмите, чтобы перевыбрать."
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              padding: "2px 6px",
                              borderRadius: 5,
                              border: "1px solid #16a34a55",
                              background: "#22c55e22",
                              color: "#15803d",
                              fontSize: 11,
                              fontWeight: 700,
                              lineHeight: 1.2,
                              cursor: busy || !s.item_id ? "not-allowed" : "pointer",
                              opacity: busy || !s.item_id ? 0.65 : 1,
                            }}
                          >
                            из справочника
                          </button>
                        ) : null}
                      </div>
                      {!unknown && s.macro_name && (
                        <div style={{ marginTop: 3, color: "var(--muted)", fontSize: 11, lineHeight: 1.35 }}>
                          <span>{s.macro_name}</span>
                        </div>
                      )}
                      {sourceItem && (
                        <div style={{ marginTop: 3, color: "var(--muted)", fontSize: 11, lineHeight: 1.35 }}>
                          Работа: {sourceItem.name}
                        </div>
                      )}
                      {(laborPerUnit || sessionLabor || catalogWarning || needsUserRate || needsQuantity) && (
                        <div style={{ marginTop: 5, color: "var(--muted)", fontSize: 11, lineHeight: 1.35 }}>
                          {laborPerUnit ? (
                            <div>
                              Трудоёмкость: {laborPerUnit} чел-ч/{rowUnitLabel}
                            </div>
                          ) : null}
                          {sessionLabor ? <div>По объёму: {sessionLabor} чел-ч</div> : null}
                          {catalogWarning ? (
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 6,
                                flexWrap: "wrap",
                              }}
                            >
                              <button
                                type="button"
                                title={traceTitle}
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: 6,
                                  maxWidth: "100%",
                                  padding: "3px 7px",
                                  borderRadius: 5,
                                  border: operatorRateConfirmed
                                    ? "1px solid #16a34a55"
                                    : isProvisionalRate
                                      ? "1px solid #f59e0b66"
                                      : "1px solid #ef444466",
                                  background: operatorRateConfirmed
                                    ? "#22c55e12"
                                    : isProvisionalRate
                                      ? "#f59e0b14"
                                      : "#ef444414",
                                  color: operatorRateConfirmed ? "#15803d" : isProvisionalRate ? "#b45309" : "var(--red)",
                                  fontSize: 11,
                                  fontWeight: 700,
                                  lineHeight: 1.25,
                                  textAlign: "left",
                                  cursor: "help",
                                }}
                              >
                                {operatorRateConfirmed
                                  ? "Каталог подтверждён оператором"
                                  : isProvisionalRate
                                    ? "Каталог требует подтверждения"
                                    : `Каталог не применён: ${catalogWarning}`}
                              </button>
                              {isProvisionalRate && !provisionalConfirmed && provisionalOutput != null ? (
                                <button
                                  type="button"
                                  disabled={busy}
                                  onClick={() => void saveField(s.id, {
                                    output_per_day: provisionalOutput,
                                    selected_rate_item_id: numericCandidate?.rate_item_id || s.selected_rate_item_id || null,
                                    selected_rate_mapping_id: numericCandidate?.rate_mapping_id || s.selected_rate_mapping_id || null,
                                  })}
                                  title={`${traceTitle ?? catalogWarning}\n\nПринять: ${fmtMetric(provisionalOutput) ?? provisionalOutput} ${rowUnitLabel}/см`}
                                  style={{
                                    display: "inline-flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    width: 22,
                                    height: 22,
                                    padding: 0,
                                    borderRadius: 5,
                                    border: "1px solid #16a34a55",
                                    background: busy ? "#e5e7eb" : "#22c55e22",
                                    color: busy ? "#64748b" : "#15803d",
                                    cursor: busy ? "not-allowed" : "pointer",
                                  }}
                                >
                                  <Check size={14} strokeWidth={3} />
                                </button>
                              ) : null}
                            </div>
                          ) : null}
                          {equivalentCandidates.length > 0 && !operatorRateConfirmed ? (
                            <div
                              style={{
                                marginTop: 6,
                                display: "grid",
                                gap: 6,
                                padding: "8px 9px",
                                border: "1px solid #f59e0b55",
                                borderRadius: 6,
                                background: "#fffbeb",
                                color: "#78350f",
                              }}
                            >
                              <div style={{ fontWeight: 700 }}>
                                Выберите ставку: найдено {equivalentCandidates.length} равнозначных варианта
                              </div>
                              {equivalentCandidates.map((candidate, candidateIndex) => {
                                const candidateOutput = outputFromCandidate(s, candidate);
                                const candidateUnit = candidateUnitCode(candidate);
                                const title = [
                                  candidate.name,
                                  candidate.source_file ? `Источник: ${candidate.source_file}` : null,
                                  candidate.source_rate_id ? `ID: ${candidate.source_rate_id}` : null,
                                  candidate.normalized_value != null ? `Ставка: ${fmtNumber(candidate.normalized_value)} чел-ч/${unitLabel(candidateUnit)}` : null,
                                  candidateOutput != null ? `Производительность: ${fmtNumber(candidateOutput)} ${rowUnitLabel}/см` : null,
                                ].filter(Boolean).join("\n");
                                const disabled = busy || candidateOutput == null;
                                const candidateKey = [
                                  "equivalent",
                                  s.id,
                                  candidate.rate_item_id,
                                  candidate.source_rate_id,
                                  candidate.name,
                                  candidateIndex,
                                ].filter(Boolean).join(":");
                                const hovered = hoveredRateCandidateKey === candidateKey;
                                return (
                                  <button
                                    type="button"
                                    key={candidateKey}
                                    disabled={disabled}
                                    onMouseEnter={() => !disabled && setHoveredRateCandidateKey(candidateKey)}
                                    onMouseLeave={() => setHoveredRateCandidateKey((current) => current === candidateKey ? null : current)}
                                    onClick={() => candidateOutput != null && void saveField(s.id, {
                                      output_per_day: candidateOutput,
                                      selected_rate_item_id: candidate.rate_item_id || null,
                                      selected_rate_mapping_id: candidate.rate_mapping_id || null,
                                    })}
                                    title={candidateOutput == null ? "Нужен размер бригады для расчёта производительности" : title}
                                    style={{
                                      display: "block",
                                      width: "100%",
                                      padding: "6px 8px",
                                      borderRadius: 6,
                                      border: hovered ? "1px solid #f59e0b88" : "1px solid transparent",
                                      background: disabled ? "transparent" : hovered ? "#ffedd5" : "#fff7ed",
                                      color: "inherit",
                                      textAlign: "left",
                                      cursor: disabled ? "not-allowed" : "pointer",
                                      opacity: disabled ? 0.65 : 1,
                                    }}
                                  >
                                    <div style={{ fontWeight: 650, color: "var(--text)" }}>
                                      {candidate.name || "Кандидат нормы"}
                                    </div>
                                    <div style={{ color: "#92400e" }}>
                                      {fmtNumber(candidate.normalized_value)} чел-ч/{unitLabel(candidateUnit)}
                                      {candidateOutput != null ? ` · ${fmtNumber(candidateOutput)} ${rowUnitLabel}/см` : ""}
                                      {candidate.source_file ? ` · ${candidate.source_file}` : ""}
                                    </div>
                                  </button>
                                );
                              })}
                            </div>
                          ) : null}
                          {componentCandidates.length > 0 && !operatorRateConfirmed ? (
                            <div
                              style={{
                                marginTop: 6,
                                display: "grid",
                                gap: 6,
                                padding: "8px 9px",
                                border: "1px solid #f59e0b55",
                                borderRadius: 6,
                                background: "#fffbeb",
                                color: "#78350f",
                              }}
                            >
                              <div style={{ fontWeight: 700 }}>
                                Полной нормы нет. Найдена ставка на компонент пакета
                              </div>
                              <div>
                                Можно применить предварительно только к указанному компоненту; полный цикл нужно разложить или проверить вручную.
                              </div>
                              {componentCandidates.map((candidate, candidateIndex) => {
                                const candidateOutput = outputFromCandidate(s, candidate);
                                const candidateUnit = candidateUnitCode(candidate);
                                const componentCode = String((candidate as any).component_operation_code || "компонент");
                                const limitation = String((candidate as any).limitation || "");
                                const title = [
                                  candidate.name,
                                  `Компонент: ${componentCode}`,
                                  candidate.source_file ? `Источник: ${candidate.source_file}` : null,
                                  candidate.source_rate_id ? `ID: ${candidate.source_rate_id}` : null,
                                  limitation || null,
                                  candidate.normalized_value != null ? `Ставка: ${fmtNumber(candidate.normalized_value)} чел-ч/${unitLabel(candidateUnit)}` : null,
                                  candidateOutput != null ? `Производительность: ${fmtNumber(candidateOutput)} ${rowUnitLabel}/см` : null,
                                ].filter(Boolean).join("\n");
                                const disabled = busy || candidateOutput == null;
                                const candidateKey = [
                                  "component",
                                  s.id,
                                  componentCode,
                                  candidate.rate_item_id,
                                  candidate.source_rate_id,
                                  candidate.name,
                                  candidateIndex,
                                ].filter(Boolean).join(":");
                                const hovered = hoveredRateCandidateKey === candidateKey;
                                return (
                                  <button
                                    type="button"
                                    key={candidateKey}
                                    disabled={disabled}
                                    onMouseEnter={() => !disabled && setHoveredRateCandidateKey(candidateKey)}
                                    onMouseLeave={() => setHoveredRateCandidateKey((current) => current === candidateKey ? null : current)}
                                    onClick={() => candidateOutput != null && void saveField(s.id, {
                                      output_per_day: candidateOutput,
                                      selected_rate_item_id: candidate.rate_item_id || null,
                                      selected_rate_mapping_id: candidate.rate_mapping_id || null,
                                    })}
                                    title={candidateOutput == null ? "Нужен размер бригады для расчёта производительности" : title}
                                    style={{
                                      display: "block",
                                      width: "100%",
                                      padding: "6px 8px",
                                      borderRadius: 6,
                                      border: hovered ? "1px solid #f59e0b88" : "1px solid transparent",
                                      background: disabled ? "transparent" : hovered ? "#ffedd5" : "#fff7ed",
                                      color: "inherit",
                                      textAlign: "left",
                                      cursor: disabled ? "not-allowed" : "pointer",
                                      opacity: disabled ? 0.65 : 1,
                                    }}
                                  >
                                    <div style={{ fontWeight: 650, color: "var(--text)" }}>
                                      {candidate.name || "Кандидат нормы"}
                                    </div>
                                    <div style={{ color: "#92400e" }}>
                                      {componentCode}: {fmtNumber(candidate.normalized_value)} чел-ч/{unitLabel(candidateUnit)}
                                      {candidateOutput != null ? ` · ${fmtNumber(candidateOutput)} ${rowUnitLabel}/см` : ""}
                                      {candidate.source_file ? ` · ${candidate.source_file}` : ""}
                                    </div>
                                  </button>
                                );
                              })}
                            </div>
                          ) : null}
                          {needsUserRate ? (
                            <div
                              style={{
                                marginTop: 6,
                                display: "grid",
                                gap: 8,
                                padding: "8px 9px",
                                border: "1px solid #2563eb55",
                                borderRadius: 6,
                                background: "#eff6ff",
                                color: "#1e3a8a",
                              }}
                            >
                              <div style={{ fontWeight: 750 }}>Нет нормы трудозатрат для этой работы</div>
                              <div>
                                Укажите, сколько человеко-часов требуется на 1 {rowUnitLabel}. Норма сохранится в ваш личный справочник.
                              </div>
                              <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                                <span style={{ fontWeight: 650 }}>Трудозатраты на 1 {rowUnitLabel}:</span>
                                <input
                                  value={userRateDrafts[s.id] || ""}
                                  disabled={busy || !s.can_create_user_rate}
                                  onChange={(e) =>
                                    setUserRateDrafts((current) => ({
                                      ...current,
                                      [s.id]: e.target.value,
                                    }))
                                  }
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter" && userRateValue != null && s.can_create_user_rate) {
                                      void saveUserRate(s);
                                    }
                                  }}
                                  placeholder="0,85"
                                  inputMode="decimal"
                                  aria-label={`Трудозатраты на 1 ${rowUnitLabel}`}
                                  style={{ ...inputLike, width: 90, height: 30, padding: "4px 7px" }}
                                />
                                <span>чел.-ч</span>
                                <button
                                  type="button"
                                  disabled={busy || !s.can_create_user_rate || userRateValue == null}
                                  onClick={() => void saveUserRate(s)}
                                  style={buttonStyle(
                                    "primary",
                                    busy || !s.can_create_user_rate || userRateValue == null,
                                  )}
                                >
                                  Сохранить в мой справочник
                                </button>
                              </div>
                              {!s.can_create_user_rate && s.can_create_user_rate_reason ? (
                                <div style={{ color: "#92400e" }}>{s.can_create_user_rate_reason}</div>
                              ) : null}
                            </div>
                          ) : null}
                          {needsQuantity ? (
                            <div
                              style={{
                                marginTop: 6,
                                display: "grid",
                                gap: 7,
                                padding: "8px 9px",
                                border: "1px solid #f59e0b66",
                                borderRadius: 6,
                                background: "#fffbeb",
                                color: "#78350f",
                              }}
                            >
                              <div style={{ fontWeight: 750 }}>Норма найдена</div>
                              <div>Укажите объём работы, чтобы рассчитать общие трудозатраты.</div>
                              <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                                <span style={{ fontWeight: 650 }}>Объём работы:</span>
                                <input
                                  value={quantityDrafts[s.id] || ""}
                                  disabled={busy || s.can_update_quantity === false}
                                  onChange={(e) =>
                                    setQuantityDrafts((current) => ({
                                      ...current,
                                      [s.id]: e.target.value,
                                    }))
                                  }
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter" && quantityValue != null) {
                                      void saveRequiredQuantity(s);
                                    }
                                  }}
                                  placeholder="0"
                                  inputMode="decimal"
                                  aria-label={`Объём работы в ${rowUnitLabel}`}
                                  style={{ ...inputLike, width: 90, height: 30, padding: "4px 7px" }}
                                />
                                <span>{rowUnitLabel}</span>
                                <button
                                  type="button"
                                  disabled={busy || s.can_update_quantity === false || quantityValue == null}
                                  onClick={() => void saveRequiredQuantity(s)}
                                  style={buttonStyle(
                                    "primary",
                                    busy || s.can_update_quantity === false || quantityValue == null,
                                  )}
                                >
                                  Сохранить объём
                                </button>
                              </div>
                            </div>
                          ) : null}
                        </div>
                      )}
                      {(unknown || selectorOpen) && (
                        <div style={{ marginTop: 6 }}>
                          {selectorOpen ? (
                            <div style={{ display: "grid", gap: 6, maxWidth: 360 }}>
                              <select
                                value={selectedTaxonomySection}
                                disabled={busy}
                                onChange={(e) => setSelectedTaxonomySection(e.target.value)}
                                style={{ ...inputLike, width: "100%" }}
                              >
                                {taxonomySections.map((section) => (
                                  <option key={section.section_code} value={section.section_code}>
                                    {section.section_name}
                                  </option>
                                ))}
                              </select>
                              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                                <select
                                  value=""
                                  disabled={busy || !s.item_id}
                                  onChange={(e) => void saveManualSubtype(s, e.target.value)}
                                  style={{ ...inputLike, width: "100%", flex: 1 }}
                                >
                                  <option value="">Выберите новый подтип работ…</option>
                                  {taxonomySubtypes.map((subtype) => (
                                    <option key={subtype.work_subtype_code} value={subtype.work_subtype_code}>
                                      {subtype.work_subtype_name}
                                    </option>
                                  ))}
                                </select>
                                {!unknown ? (
                                  <button
                                    type="button"
                                    disabled={busy}
                                    onClick={() => setSelectingSubtypeId(null)}
                                    style={buttonStyle("ghost", busy)}
                                  >
                                    Отмена
                                  </button>
                                ) : null}
                              </div>
                            </div>
                          ) : (
                            <button
                              type="button"
                              disabled={busy || !s.item_id}
                              onClick={() => openSubtypeSelector(s)}
                              style={buttonStyle("ghost", busy || !s.item_id)}
                            >
                              Выбрать из справочника
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 5, minWidth: 0 }}>
                      <NumCell
                        value={s.volume}
                        disabled={busy}
                        onSave={(v) => void saveField(s.id, { volume: v })}
                      />
                      <UnitCell
                        value={s.unit}
                        displayValue={s.display_unit || unitLabel(s.unit)}
                        disabled={busy}
                        onSave={(unit) => void saveField(s.id, { unit })}
                      />
                    </div>
                    <NumCell
                      value={s.output_per_day}
                      suffix={s.unit ? `${rowUnitLabel}/см` : "/см"}
                      disabled={busy}
                      source={s.output_source}
                      onSave={(v) => void saveField(s.id, { output_per_day: v })}
                    />
                    <NumCell
                      value={s.crew_size}
                      suffix="чел"
                      disabled={busy}
                      source={s.crew_source}
                      onSave={(v) => void saveField(s.id, { crew_size: v })}
                    />
                    <div
                      title={daysInfo.title}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "flex-start",
                        minHeight: 30,
                        color: daysInfo.days == null ? "var(--muted)" : "var(--text)",
                        fontWeight: daysInfo.days == null ? 500 : 700,
                      }}
                    >
                      {daysInfo.days == null ? "—" : `${daysInfo.days} дн.`}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function NumCell({
  value,
  suffix,
  disabled,
  source,
  allowZero,
  onSave,
}: {
  value: number | null | undefined;
  suffix?: string;
  disabled?: boolean;
  source?: "catalog" | "manual" | "none" | "default" | "estimate";
  allowZero?: boolean;
  onSave: (v: number | null) => void;
}) {
  const initial = value != null ? String(value) : "";
  const [text, setText] = useState(initial);
  const lastSaved = useRef(initial);

  useEffect(() => {
    const next = value != null ? String(value) : "";
    setText(next);
    lastSaved.current = next;
  }, [value]);

  function commit() {
    if (text === lastSaved.current) return;
    const trimmed = text.trim();
    if (trimmed === "") {
      lastSaved.current = "";
      onSave(null);
      return;
    }
    const parsed = Number(trimmed.replace(",", "."));
    if (!Number.isFinite(parsed) || (parsed <= 0 && !allowZero) || parsed < 0) {
      setText(lastSaved.current); // откат при невалидном вводе
      return;
    }
    lastSaved.current = String(parsed);
    onSave(parsed);
  }

  const isManual = source === "manual";
  const isCatalog = source === "catalog" && value != null;
  const isApprox = source === "default" && value != null;
  const isFromEstimate = source === "estimate";
  const isMissing = source === "none" && value == null;
  const border = isManual
    ? "#16a34a55"
    : isCatalog
      ? "#2563eb66"
      : isApprox
        ? "#f59e0b66"
        : isMissing
          ? "#ef444466"
          : "var(--border2)";
  const bg = isManual
    ? "#22c55e0d"
    : isCatalog
      ? "#2563eb0f"
      : isApprox
        ? "#f59e0b0f"
        : isMissing
          ? "#ef44440a"
          : "var(--bg)";
  const indicator = isCatalog ? "к" : isApprox ? "≈" : "";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
      <span
        title={isCatalog ? "Рассчитано из каталога расценок" : isApprox ? "Legacy-значение из старого справочника" : undefined}
        style={{ width: 9, fontSize: 12, fontWeight: 700, color: isCatalog ? "var(--blue-dark)" : "#b45309", textAlign: "center" }}
      >
        {indicator}
      </span>
      <input
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        }}
        inputMode="decimal"
        placeholder="—"
        title={
          isCatalog
            ? "Рассчитано из каталога расценок — измените, чтобы зафиксировать вручную"
            : isApprox
            ? "Legacy-значение — измените, чтобы зафиксировать вручную"
            : isManual
            ? "Задано оператором"
            : isFromEstimate
            ? "Размер бригады из загрузки сметы — можно изменить"
            : isMissing
            ? "Нет применимой каталожной нормы — заполните вручную"
            : undefined
        }
        style={{
          width: 60,
          padding: "5px 7px",
          boxSizing: "border-box",
          border: `1px solid ${border}`,
          background: bg,
          color: isApprox ? "var(--muted)" : "var(--text)",
          fontStyle: isApprox ? "italic" : "normal",
          borderRadius: 6,
          fontSize: 12,
          outline: "none",
        }}
      />
      {suffix && <span style={{ fontSize: 10, color: "var(--muted)" }}>{suffix}</span>}
    </div>
  );
}

function UnitCell({
  value,
  displayValue,
  disabled,
  onSave,
}: {
  value: string | null | undefined;
  displayValue?: string | null;
  disabled?: boolean;
  onSave: (v: string | null) => void;
}) {
  const initial = displayValue ?? value ?? "";
  const [text, setText] = useState(initial);
  const lastSaved = useRef(initial);

  useEffect(() => {
    const next = displayValue ?? value ?? "";
    setText(next);
    lastSaved.current = next;
  }, [displayValue, value]);

  function commit() {
    const next = text.trim();
    if (next === lastSaved.current) return;
    lastSaved.current = next;
    onSave(next || null);
  }

  const missing = !text.trim();

  return (
    <input
      value={text}
      disabled={disabled}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
      placeholder="ед."
      title={missing ? "Укажите единицу измерения" : "Единица измерения"}
      style={{
        width: 54,
        padding: "5px 7px",
        boxSizing: "border-box",
        border: `1px solid ${missing ? "#ef444466" : "var(--border2)"}`,
        background: missing ? "#ef44440a" : "var(--bg)",
        color: "var(--text)",
        borderRadius: 6,
        fontSize: 12,
        outline: "none",
      }}
    />
  );
}

// ── ЭТАП 3 ───────────────────────────────────────────────────────────────────

const HOURS_PER_DAY = 8;

function isSubDay(it: KtpWbsItem): boolean {
  if (it.labor_hours == null) return false;
  const brigade = it.brigade_size ?? 1;
  return it.labor_hours / brigade < HOURS_PER_DAY;
}

function fmtDuration(it: KtpWbsItem): string | null {
  if (!it.duration_days && it.labor_hours == null) return null;
  if (isSubDay(it)) {
    const brigade = it.brigade_size ?? 1;
    const h = (it.labor_hours as number) / brigade;
    const hStr = Number.isInteger(h) ? String(h) : h.toFixed(1);
    return `${hStr} ч.${it.norm_kind === "fallback" ? " (нет оценки)" : ""}`;
  }
  if (!it.duration_days) return null;
  return `${it.duration_days} дн.${it.norm_kind === "fallback" ? " (нет оценки)" : ""}`;
}

function normTooltip(it: KtpWbsItem): string | undefined {
  if (!it.duration_days && it.labor_hours == null) return undefined;
  const qty = it.quantity != null ? `${it.quantity}${it.unit ? ` ${it.unit}` : ""}` : "?";
  const brigade = it.brigade_size ?? 1;
  const sub = isSubDay(it);

  if (it.norm_kind === "norm_time" && it.norm_value != null) {
    const labor = it.labor_hours != null ? `${it.labor_hours.toFixed(1)} чел-ч` : "?";
    const result = sub
      ? `${((it.labor_hours as number) / brigade).toFixed(1)} ч. на бригаду (${brigade} чел.)`
      : `${brigade} чел. → ${it.duration_days} дн.`;
    return `${qty} × ${it.norm_value} чел-ч/${it.norm_unit || "ед"} = ${labor}\n${result}`;
  }
  if (it.norm_kind === "vyrabotka" && it.norm_value != null) {
    const result = sub
      ? `${((it.labor_hours as number) / brigade).toFixed(1)} ч. на бригаду (${brigade} чел.)`
      : `= ${it.duration_days} дн.`;
    return `${qty} ÷ (${it.norm_value} ${it.norm_unit || "ед"}/чел-день × ${brigade} чел.) ${result}`;
  }
  if (it.norm_kind === "fallback") {
    return "Норму определить не удалось — поставлен 1 день по умолчанию";
  }
  return undefined;
}

function Stage3({
  wbs,
  projectId,
  busy,
  run,
  done,
  onBuild,
  onOpenGantt,
}: {
  wbs: KtpWbs;
  projectId: string;
  sessionId: string;
  busy: boolean;
  run: (fn: () => Promise<KtpWbs>) => Promise<void>;
  done: boolean;
  onBuild: () => Promise<void> | void;
  onOpenGantt: () => void;
}) {
  const missingQty = useMemo(
    () =>
      wbs.groups
        .flatMap((g) => g.items)
        .filter((it) => it.origin !== "from_estimate" && (it.quantity == null || !it.unit)),
    [wbs],
  );
  const [building, setBuilding] = useState(false);
  const qtyRefs = useRef<(HTMLInputElement | null)[]>([]);

  return (
    <div>
      <Header
        title="График производства работ"
        hint="Укажите объёмы для добавленных работ — ИИ подберёт нормы, система рассчитает длительности и зависимости."
        right={
          done ? (
            <button style={buttonStyle("primary")} onClick={onOpenGantt}>
              Открыть Гант →
            </button>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 5 }}>
              <button
                style={buttonStyle("primary", busy)}
                disabled={busy}
                onClick={async () => {
                  setBuilding(true);
                  try {
                    await onBuild();
                  } finally {
                    setBuilding(false);
                  }
                }}
              >
                <ButtonContent loading={building}>Построить ГПР</ButtonContent>
              </button>
              {building && (
                <span style={{ fontSize: 11, color: "var(--muted)" }}>
                  Идёт процесс оценки трудоёмкости…
                </span>
              )}
            </div>
          )
        }
      />

      {done && (
        <div
          style={{
            ...card,
            padding: 14,
            marginBottom: 14,
            color: "#15803d",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          ✓ ГПР построен и записан в график проекта
        </div>
      )}

      {missingQty.length > 0 && !done && (
        <div style={{ ...card, padding: 14, marginBottom: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
            Объёмы и единицы для добавленных работ ({missingQty.length})
          </div>
          {missingQty.map((it, idx) => (
            <QtyRow
              key={it.id}
              item={it}
              projectId={projectId}
              inputRef={(el) => { qtyRefs.current[idx] = el; }}
              onNext={idx < missingQty.length - 1 ? () => qtyRefs.current[idx + 1]?.focus() : undefined}
            />
          ))}
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 6 }}>
            Если оставить пустым — объём оценит ИИ.
          </div>
        </div>
      )}

      {wbs.groups
        .filter(
          (g) =>
            g.items.some((item) => item.review_status === "accepted")
            && (
              !wbs.sequence_locked
              || !["Прочие позиции сметы", "Прочие работы сметы", "Нераспределённые работы"].includes(g.title.trim())
            ),
        )
        .map((g) => (
        <div key={g.id} style={{ ...card, padding: 14, marginBottom: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, fontWeight: 600 }}>
            <span>{g.title}</span>
            <span style={{ color: "var(--muted)", fontWeight: 400 }}>
              {g.start_date ? `${g.start_date} · ` : ""}
              {g.duration_days ? `${g.duration_days} дн.` : "—"}
            </span>
          </div>
          {g.items.map((it) => (
            <div
              key={it.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 12,
                color: "var(--muted)",
                padding: "4px 0",
                gap: 8,
              }}
            >
              <span style={{ flex: 1 }}>{it.name}</span>
              <span style={{ whiteSpace: "nowrap", display: "flex", gap: 8, alignItems: "center" }}>
                {fmtQty(it) && (
                  <span style={{ color: "var(--text)", fontFamily: "var(--mono)", fontSize: 11 }}>
                    {fmtQty(it)}
                  </span>
                )}
                <span
                  title={normTooltip(it)}
                  style={normTooltip(it) ? { cursor: "help", borderBottom: "1px dotted var(--border2)" } : undefined}
                >
                  {fmtDuration(it) ?? (fmtQty(it) ? "" : "—")}
                </span>
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function parseQty(raw: string): { quantity: number | null; unit: string | null } {
  // "100 м3" → 100, "м3"; "12,5 м²" → 12.5, "м²"; "м3" → null, "м3"
  const m = raw.trim().match(/^([\d]+(?:[.,]\d+)?)\s*(.*)$/);
  if (m) {
    const n = Number(m[1].replace(",", "."));
    return {
      quantity: Number.isFinite(n) ? n : null,
      unit: m[2].trim() || null,
    };
  }
  return { quantity: null, unit: raw.trim() || null };
}

function fmtQty(item: KtpWbsItem): string {
  const q = item.quantity ?? "";
  const u = item.unit ?? "";
  return q !== "" || u !== "" ? `${q}${q !== "" && u ? " " : ""}${u}`.trim() : "";
}

function QtyRow({
  item,
  projectId,
  inputRef,
  onNext,
}: {
  item: KtpWbsItem;
  projectId: string;
  inputRef?: (el: HTMLInputElement | null) => void;
  onNext?: () => void;
}) {
  const [value, setValue] = useState(fmtQty(item));
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const lastSaved = useRef(fmtQty(item));

  const save = async () => {
    const trimmed = value.trim();
    if (trimmed === lastSaved.current || saving) return;
    const { quantity, unit } = parseQty(trimmed);
    setSaving(true);
    try {
      await ktpEstimate.updateItem(projectId, item.id, { quantity, unit });
      lastSaved.current = trimmed;
      setConfirmed(trimmed || null);
    } catch {
      // не блокируем UI — пользователь может попробовать ещё раз
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 0" }}>
      <span style={{ flex: 1, fontSize: 12 }}>{item.name}</span>
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => { setValue(e.target.value); setConfirmed(null); }}
        onBlur={() => void save()}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            // фокус на следующую строку → браузер сам вызовет blur → save
            if (onNext) onNext();
            else (e.target as HTMLInputElement).blur();
          }
        }}
        placeholder="например: 100 м3"
        disabled={saving}
        style={{ ...inputStyle, maxWidth: 180 }}
      />
      <span style={{ fontSize: 11, minWidth: 60, textAlign: "right" }}>
        {saving
          ? <span style={{ color: "var(--muted)" }}>…</span>
          : confirmed
            ? <span style={{ color: "#15803d", fontWeight: 600 }}>{confirmed}</span>
            : null}
      </span>
    </div>
  );
}

// ── общее ────────────────────────────────────────────────────────────────────

function Header({
  title,
  hint,
  right,
}: {
  title: string;
  hint: string;
  right: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        gap: 16,
        marginBottom: 16,
      }}
    >
      <div>
        <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 4 }}>{title}</div>
        <div style={{ fontSize: 12, color: "var(--muted)", maxWidth: 640, lineHeight: 1.5 }}>{hint}</div>
      </div>
      {right}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "7px 10px",
  border: "1px solid var(--border2)",
  borderRadius: 5,
  fontSize: 13,
  outline: "none",
  flex: 1,
  background: "var(--surface)",
  color: "var(--text)",
};

const feedbackStyle: React.CSSProperties = {
  padding: "9px 11px",
  borderRadius: 6,
  border: "1px solid rgba(245,158,11,.3)",
  background: "rgba(245,158,11,.08)",
  color: "#92400e",
  fontSize: 12,
  lineHeight: 1.4,
};

const thCell: React.CSSProperties = {
  padding: "7px 10px",
  textAlign: "left",
  fontSize: 10,
  color: "var(--muted)",
  textTransform: "uppercase",
};

const tdCell: React.CSSProperties = {
  padding: "7px 10px",
  fontSize: 12,
  verticalAlign: "top",
};
