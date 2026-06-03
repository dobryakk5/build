"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { estimates, ktpEstimate } from "@/lib/api";
import ColumnMapper, { type MappingPayload } from "@/components/ColumnMapper";
import { fmtMoney } from "@/lib/dateUtils";
import { CLARIFICATION_BY_KIND } from "@/lib/estimateClarificationQuestions";
import { useJobPoller } from "@/lib/useJobPoller";
import { trackActivity } from "@/lib/activity";
import type { EstimateBatch, PreviewResult, PreviewRow, PreviewEdits, PreviewAddedRow, EstimateItemType } from "@/lib/types";

const ITEM_TYPE_LABELS: Record<EstimateItemType, string> = {
  work: "Работы",
  material: "Материалы",
  mechanism: "Механизмы",
  overhead: "Накладные",
  unknown: "Сомнительные",
};

const KIND_OPTIONS = [
  { id: 1, title: "Земляные грунтовые работы" },
  { id: 2, title: "Строительство жилого помещения" },
  { id: 3, title: "Строительство нежилого помещения" },
  { id: 4, title: "Реконструкция нежилого помещения" },
  { id: 5, title: "Отделка жилого помещения" },
  { id: 6, title: "Отделка нежилого помещения" },
  { id: 7, title: "Инженерные работы внутренние" },
  { id: 8, title: "Инженерные работы наружные" },
  { id: 9, title: "Ландшафтные работы" },
] as const;

type EstimateKind = (typeof KIND_OPTIONS)[number]["id"];
type ClarificationUploadPayload = {
  version: "v1";
  estimate_kind: EstimateKind;
  kind_title: string;
  form: Record<string, { section: string; question: string; answers: string[] }>;
};

const KIND_LABEL = Object.fromEntries(
  KIND_OPTIONS.map((option) => [option.id, `${option.id}. ${option.title}`]),
) as Record<EstimateKind, string>;

const LEGACY_KIND_LABEL: Record<string, string> = {
  country_house: KIND_LABEL[2],
  apartment: KIND_LABEL[2],
  non_residential: KIND_LABEL[3],
};

function formatEstimateKind(kind: number | string | null | undefined) {
  if (typeof kind === "number" && kind in KIND_LABEL) {
    return KIND_LABEL[kind as EstimateKind];
  }
  if (typeof kind === "string" && kind in LEGACY_KIND_LABEL) {
    return LEGACY_KIND_LABEL[kind];
  }
  return "—";
}

function restoreClarificationAnswers(batch: EstimateBatch): Record<string, string[]> {
  const form = batch.clarification_answers?.form;
  if (!form || typeof form !== "object") return {};

  const restored: Record<string, string[]> = {};
  for (const [questionId, value] of Object.entries(form)) {
    if (!value || typeof value !== "object") continue;
    const answers = (value as { answers?: unknown }).answers;
    if (!Array.isArray(answers)) continue;
    restored[questionId] = answers
      .map((answer) => String(answer).trim())
      .filter(Boolean);
  }
  return restored;
}

export default function UploadPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const fileRef = useRef<HTMLInputElement>(null);
  const batchIdFromQuery = searchParams.get("batch");
  const sessionIdFromQuery = searchParams.get("session");
  const fromKtpFlow = searchParams.get("fromKtp") === "1";

  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [startDate, setStartDate] = useState(new Date().toISOString().split("T")[0]);
  const [workers, setWorkers] = useState(3);
  const [estimateKind, setEstimateKind] = useState<EstimateKind | null>(null);
  const [clarificationAnswers, setClarificationAnswers] = useState<Record<string, string[]>>({});
  const [clarificationsConfirmed, setClarificationsConfirmed] = useState(false);
  const [complexMode, setComplexMode] = useState(false);
  const [buildGantt, setBuildGantt] = useState(true);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [mappingPayload, setMappingPayload] = useState<MappingPayload | null>(null);
  const [uploading, setUploading] = useState(false);
  const [ktpLoading, setKtpLoading] = useState<"estimate" | null>(null);
  const [resetting, setResetting] = useState(false);
  const [resetNotice, setResetNotice] = useState<string | null>(null);

  const { job, loading: polling } = useJobPoller(jobId);
  const status = job?.status;
  const result = job?.result;
  const currentClarification = estimateKind ? CLARIFICATION_BY_KIND[estimateKind] : null;
  const answeredCount = Object.values(clarificationAnswers).filter((answers) => answers.length > 0).length;
  const questionsCount = currentClarification?.sections.reduce((sum, section) => sum + section.questions.length, 0) ?? 0;
  const allClarificationsAnswered = questionsCount > 0 && answeredCount === questionsCount;
  const canUpload = estimateKind !== null && clarificationsConfirmed;
  const wasAllClarificationsAnsweredRef = useRef(false);
  const clarificationStartedRef = useRef(false);
  const trackedJobTerminalStatusRef = useRef<string | null>(null);
  const autoStartedKtpBatchRef = useRef<string | null>(null);
  const restoredBatchRef = useRef<string | null>(null);

  useEffect(() => {
    trackActivity("UPLOAD_PAGE_OPENED", {
      projectId: id,
      entityType: "project",
      entityId: id,
    });
  }, [id]);

  useEffect(() => {
    const wasAllAnswered = wasAllClarificationsAnsweredRef.current;

    if (allClarificationsAnswered && !wasAllAnswered && !clarificationsConfirmed && !status && !fromKtpFlow) {
      setClarificationsConfirmed(true);
      trackActivity("CLARIFICATIONS_COMPLETED", {
        projectId: id,
        entityType: "project",
        entityId: id,
        metadata: {
          estimate_kind: estimateKind,
          answered_count: answeredCount,
          questions_count: questionsCount,
        },
      });
    }

    wasAllClarificationsAnsweredRef.current = allClarificationsAnswered;
  }, [allClarificationsAnswered, answeredCount, clarificationsConfirmed, estimateKind, fromKtpFlow, id, questionsCount, status]);

  useEffect(() => {
    if (!batchIdFromQuery || restoredBatchRef.current === batchIdFromQuery) return;

    let cancelled = false;
    estimates
      .batches(id)
      .then((batches) => {
        if (cancelled) return;
        const batch = batches.find((item) => item.id === batchIdFromQuery);
        if (!batch) return;

        restoredBatchRef.current = batch.id;
        setEstimateKind(batch.estimate_kind as EstimateKind);
        setStartDate(batch.start_date || new Date().toISOString().split("T")[0]);
        setWorkers(batch.workers_count || 3);
        setClarificationAnswers(restoreClarificationAnswers(batch));
        setClarificationsConfirmed(!fromKtpFlow);
        setFile(null);
        setJobId(null);
        setMappingPayload(null);
        trackedJobTerminalStatusRef.current = null;
        autoStartedKtpBatchRef.current = null;
        wasAllClarificationsAnsweredRef.current = true;
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [batchIdFromQuery, fromKtpFlow, id]);

  useEffect(() => {
    if (!job || trackedJobTerminalStatusRef.current === `${job.id}:${job.status}`) return;

    if (job.status === "done") {
      trackedJobTerminalStatusRef.current = `${job.id}:${job.status}`;
      trackActivity("ESTIMATE_UPLOAD_COMPLETED", {
        projectId: id,
        entityType: "estimate_batch",
        entityId: result?.estimate_batch_id ?? null,
        metadata: {
          job_id: job.id,
          estimate_batch_id: result?.estimate_batch_id,
          estimate_batch_name: result?.estimate_batch_name,
          estimates_count: result?.estimates_count,
          total_price: result?.total_price,
          complex_mode: result?.complex_mode ?? complexMode,
        },
      });
    } else if (job.status === "failed") {
      trackedJobTerminalStatusRef.current = `${job.id}:${job.status}`;
      trackActivity("ESTIMATE_UPLOAD_FAILED", {
        projectId: id,
        entityType: "job",
        entityId: job.id,
        metadata: {
          job_id: job.id,
          error: result?.error,
        },
      });
    }
  }, [complexMode, id, job, result]);

  const handleDrop = useCallback((files: FileList | null) => {
    if (!canUpload) return;

    const nextFile = files?.[0];
    if (nextFile && (nextFile.name.endsWith(".xlsx") || nextFile.name.endsWith(".xls") || nextFile.name.endsWith(".pdf"))) {
      setFile(nextFile);
      setJobId(null);
      setPreview(null);
      trackedJobTerminalStatusRef.current = null;
      autoStartedKtpBatchRef.current = null;
      trackActivity("ESTIMATE_FILE_SELECTED", {
        projectId: id,
        entityType: "project",
        entityId: id,
        metadata: {
          file_name: nextFile.name,
          file_size: nextFile.size,
          estimate_kind: estimateKind,
          complex_mode: complexMode,
        },
      });
    }
  }, [canUpload, complexMode, estimateKind, id]);

  async function handleUpload() {
    if (!file || !estimateKind) return;

    setUploading(true);
    autoStartedKtpBatchRef.current = null;
    trackActivity("ESTIMATE_UPLOAD_STARTED", {
      projectId: id,
      entityType: "project",
      entityId: id,
      metadata: {
        file_name: file.name,
        file_size: file.size,
        start_date: startDate,
        workers,
        estimate_kind: estimateKind,
        complex_mode: complexMode,
        answered_count: answeredCount,
        questions_count: questionsCount,
      },
    });
    try {
      const res = await estimates.preview(
        id, file, startDate, workers, estimateKind, complexMode,
        "auto", buildGantt, buildClarificationPayload(),
      );
      setPreview(res);
      trackActivity("ESTIMATE_PREVIEW_READY", {
        projectId: id,
        entityType: "project",
        entityId: id,
        metadata: { parser_profile: res.parser_profile, preview_id: res.preview_id },
      });
    } catch (e: any) {
      if (e?.mappingPayload) {
        setMappingPayload(e.mappingPayload);
        trackActivity("ESTIMATE_UPLOAD_MAPPING_REQUIRED", {
          projectId: id,
          entityType: "project",
          entityId: id,
        });
        return;
      }
      trackActivity("ESTIMATE_UPLOAD_FAILED", {
        projectId: id,
        entityType: "project",
        entityId: id,
        metadata: { error: e.message },
      });
      alert(e.message);
    } finally {
      setUploading(false);
    }
  }

  async function handleConfirmImport(edits?: PreviewEdits) {
    if (!preview) return;
    setConfirming(true);
    try {
      const res = await estimates.confirmImport(id, preview.preview_id, buildGantt, edits);
      setPreview(null);
      setJobId(res.job_id);
      trackActivity("ESTIMATE_UPLOAD_JOB_CREATED", {
        projectId: id,
        entityType: "job",
        entityId: res.job_id,
        metadata: { job_id: res.job_id, parser_profile: preview?.parser_profile },
      });
    } catch (e: any) {
      // 410 — сессия истекла, нужно загрузить заново
      const msg = String(e?.message || "");
      if (msg.includes("410") || /истекл/i.test(msg)) {
        setPreview(null);
        alert("Превью истекло. Загрузите файл заново.");
      } else {
        alert(e.message);
      }
    } finally {
      setConfirming(false);
    }
  }

  async function handleResetProgress() {
    if (!sessionIdFromQuery) return;
    const confirmed = window.confirm("Сбросить прогресс КТП и начать заново с шага «Новая смета»?");
    if (!confirmed) return;

    setResetting(true);
    setResetNotice(null);
    try {
      await ktpEstimate.resetSession(id, sessionIdFromQuery);
      setFile(null);
      setJobId(null);
      setMappingPayload(null);
      autoStartedKtpBatchRef.current = null;
      trackedJobTerminalStatusRef.current = null;
      setClarificationsConfirmed(false);
      setResetNotice("Прогресс КТП сброшен. Ответы сохранены, можно изменить их или загрузить смету заново.");
      trackActivity("KTP_ESTIMATE_SESSION_RESET", {
        projectId: id,
        entityType: "ktp_estimate_session",
        entityId: sessionIdFromQuery,
        metadata: { estimate_batch_id: batchIdFromQuery },
      });
      const suffix = batchIdFromQuery ? `?batch=${batchIdFromQuery}` : "";
      router.replace(`/projects/${id}/upload${suffix}`);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setResetting(false);
    }
  }

  function buildClarificationPayload(): ClarificationUploadPayload | undefined {
    if (!estimateKind || !currentClarification) return undefined;

    const form: ClarificationUploadPayload["form"] = {};
    for (const section of currentClarification.sections) {
      for (const question of section.questions) {
        const answers = (clarificationAnswers[question.id] ?? [])
          .map((answer) => answer.trim())
          .filter((answer) => answer && answer !== "Требуется уточнить");
        if (answers.length) {
          form[question.id] = {
            section: section.title,
            question: question.text,
            answers,
          };
        }
      }
    }

    if (!Object.keys(form).length) return undefined;

    return {
      version: "v1",
      estimate_kind: estimateKind,
      kind_title: currentClarification.title,
      form,
    };
  }

  function resetClarifications(nextKind: EstimateKind | null) {
    setEstimateKind(nextKind);
    setClarificationAnswers({});
    setClarificationsConfirmed(false);
    setFile(null);
    setJobId(null);
    setMappingPayload(null);
    autoStartedKtpBatchRef.current = null;
    clarificationStartedRef.current = false;
    wasAllClarificationsAnsweredRef.current = false;
    if (nextKind) {
      trackActivity("ESTIMATE_KIND_SELECTED", {
        projectId: id,
        entityType: "project",
        entityId: id,
        metadata: {
          estimate_kind: nextKind,
          kind_title: KIND_LABEL[nextKind],
        },
      });
    }
  }

  function toggleClarification(questionId: string, option: string) {
    if (!clarificationStartedRef.current) {
      clarificationStartedRef.current = true;
      trackActivity("CLARIFICATIONS_STARTED", {
        projectId: id,
        entityType: "project",
        entityId: id,
        metadata: {
          estimate_kind: estimateKind,
          questions_count: questionsCount,
        },
      });
    }

    setClarificationAnswers((prev) => {
      const current = prev[questionId] ?? [];
      const next = current.includes(option)
        ? current.filter((item) => item !== option)
        : [...current, option];

      return {
        ...prev,
        [questionId]: next,
      };
    });
  }

  const handleKtpEstimate = useCallback(async (batchId: string) => {
    setKtpLoading("estimate");
    try {
      const { job_id, session_id } = await ktpEstimate.startSession(id, batchId);
      trackActivity("KTP_ESTIMATE_SESSION_STARTED", {
        projectId: id,
        entityType: "ktp_estimate_session",
        entityId: session_id,
        metadata: { estimate_batch_id: batchId, job_id },
      });
      const suffix = job_id ? `?job=${job_id}` : "";
      router.replace(`/projects/${id}/ktp-estimate/${session_id}${suffix}`);
    } catch (e: any) {
      alert(e.message);
      setKtpLoading(null);
    }
  }, [id, router]);

  useEffect(() => {
    const batchId = result?.estimate_batch_id;
    if (status !== "done" || !batchId || autoStartedKtpBatchRef.current === batchId) return;

    autoStartedKtpBatchRef.current = batchId;
    void handleKtpEstimate(batchId);
  }, [handleKtpEstimate, result?.estimate_batch_id, status]);

  return (
    <div
      style={{
        height: "100%",
        overflow: "auto",
        padding: 24,
        maxWidth: 980,
        boxSizing: "border-box",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 20 }}>
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>Загрузка сметы</h2>
          <div style={{ fontSize: 12, color: "var(--muted)", maxWidth: 620 }}>
            Сначала выберите тип объекта, затем заполните уточнения. Форма загрузки файла появится после этого шага.
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
          {sessionIdFromQuery && (
            <button
              type="button"
              onClick={handleResetProgress}
              disabled={resetting}
              style={{
                padding: "10px 14px",
                background: "rgba(239,68,68,.08)",
                border: "1px solid rgba(239,68,68,.24)",
                borderRadius: 8,
                color: "var(--red)",
                cursor: resetting ? "default" : "pointer",
                fontSize: 13,
                fontWeight: 600,
                opacity: resetting ? 0.7 : 1,
                whiteSpace: "nowrap",
              }}
            >
              {resetting ? "Сбрасываем..." : "Сброс"}
            </button>
          )}
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 14px",
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            <input
              type="checkbox"
              checked={complexMode}
              onChange={(e) => setComplexMode(e.target.checked)}
            />
            <span style={{ fontSize: 13, fontWeight: 600 }}>Комплекс</span>
          </label>
        </div>
      </div>

      {fromKtpFlow && (
        <div style={{ marginBottom: 16, padding: "12px 14px", borderRadius: 8, border: "1px solid rgba(59,130,246,.22)", background: "rgba(59,130,246,.06)", color: "var(--blue-dark)", fontSize: 12, lineHeight: 1.45 }}>
          Это шаг «Новая смета» текущего мастера КТП. Сохранённые ответы восстановлены; чтобы начать заново, нажмите «Сброс».
        </div>
      )}

      {resetNotice && (
        <div style={{ marginBottom: 16, padding: "12px 14px", borderRadius: 8, border: "1px solid rgba(34,197,94,.25)", background: "rgba(34,197,94,.06)", color: "#166534", fontSize: 12 }}>
          {resetNotice}
        </div>
      )}

      <div style={{ display: "grid", gap: 18, marginBottom: 20 }}>
        <div>
          <label
            htmlFor="estimate-kind"
            style={{
              display: "block",
              marginBottom: 8,
              fontSize: 14,
              fontWeight: 600,
            }}
          >
            1. Выберите тип объекта
          </label>
          <select
            id="estimate-kind"
            value={estimateKind ?? ""}
            onChange={(e) => resetClarifications(e.target.value ? Number(e.target.value) as EstimateKind : null)}
            style={{
              width: "100%",
              padding: "11px 12px",
              border: "1px solid var(--border2)",
              borderRadius: 8,
              background: "var(--surface)",
              fontSize: 14,
              outline: "none",
            }}
          >
            <option value="">Выберите тип объекта</option>
            {KIND_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {KIND_LABEL[option.id]}
              </option>
            ))}
          </select>
        </div>

        <div>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 600 }}>
            2. Уточните исходные данные
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>
            Для каждого вопроса выберите один или несколько чекбоксов. После подтверждения появится загрузка файла.
          </div>
        </div>
      </div>

      {currentClarification && !clarificationsConfirmed && !status && (
        <div style={{ marginBottom: 20, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700 }}>{currentClarification.title}</div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
                Отмечено вопросов: {answeredCount} из {questionsCount}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setClarificationsConfirmed(true)}
              disabled={!allClarificationsAnswered}
              style={{
                padding: "9px 14px",
                background: allClarificationsAnswered ? "var(--blue-dark)" : "#94a3b8",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                fontSize: 13,
                fontWeight: 600,
                cursor: allClarificationsAnswered ? "pointer" : "default",
                opacity: allClarificationsAnswered ? 1 : 0.75,
                whiteSpace: "nowrap",
              }}
            >
              {allClarificationsAnswered ? "Перейти к загрузке" : "Ответьте на все вопросы"}
            </button>
          </div>

          <div style={{ display: "grid", gap: 16, padding: 16 }}>
            {currentClarification.sections.map((section) => (
              <section key={section.title} style={{ display: "grid", gap: 10 }}>
                <h3 style={{ fontSize: 13, fontWeight: 700, color: "var(--hdr3)" }}>{section.title}</h3>
                {section.questions.map((question) => (
                  <div key={question.id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 12 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>
                      {question.id}. {question.text}
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                      {question.options.map((option) => {
                        const checked = clarificationAnswers[question.id]?.includes(option) ?? false;
                        return (
                          <label
                            key={option}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: 7,
                              padding: "7px 9px",
                              border: `1px solid ${checked ? "rgba(29,78,216,.55)" : "var(--border)"}`,
                              borderRadius: 6,
                              background: checked ? "rgba(59,130,246,.08)" : "rgba(248,250,252,.75)",
                              fontSize: 12,
                              cursor: "pointer",
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleClarification(question.id, option)}
                            />
                            <span>{option}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </section>
            ))}
          </div>
        </div>
      )}

      {currentClarification && clarificationsConfirmed && !status && (
        <div style={{ marginBottom: 20, padding: "12px 14px", borderRadius: 8, border: "1px solid rgba(34,197,94,.25)", background: "rgba(34,197,94,.06)", display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
          <div style={{ fontSize: 12, color: "#166534" }}>
            Уточнения заполнены: {answeredCount} из {questionsCount}. Теперь можно загрузить смету.
          </div>
          <button
            type="button"
            onClick={() => {
              setClarificationsConfirmed(false);
              setFile(null);
            }}
            style={{ padding: "6px 10px", border: "1px solid rgba(22,101,52,.35)", borderRadius: 5, background: "var(--surface)", color: "#166534", fontSize: 12, cursor: "pointer", whiteSpace: "nowrap" }}
          >
            Изменить уточнения
          </button>
        </div>
      )}

      <div
        style={{
          marginBottom: 20,
          padding: "12px 14px",
          borderRadius: 8,
          border: "1px solid var(--border)",
          background: complexMode ? "rgba(34,197,94,.06)" : "rgba(245,158,11,.08)",
          color: complexMode ? "#166534" : "#92400e",
          fontSize: 12,
        }}
      >
        {complexMode
          ? "Новая загрузка создаст отдельный блок работ с собственным гантом внутри текущего объекта."
          : "Новая загрузка заменит текущую активную смету и график объекта."}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
        {[
          { label: "Дата начала работ", type: "date", value: startDate, set: setStartDate },
          { label: "Рабочих в бригаде", type: "number", value: workers, set: (value: string) => setWorkers(+value) },
        ].map((field) => (
          <div key={field.label}>
            <label style={{ fontSize: 11, color: "var(--muted)", display: "block", marginBottom: 4, textTransform: "uppercase", letterSpacing: ".06em" }}>
              {field.label}
            </label>
            <input
              type={field.type}
              value={field.value}
              onChange={(e) => field.set(e.target.value)}
              min={field.type === "number" ? 1 : undefined}
              max={field.type === "number" ? 20 : undefined}
              style={{ width: "100%", padding: "8px 12px", border: "1px solid var(--border2)", borderRadius: 5, fontSize: 13, outline: "none" }}
            />
          </div>
        ))}
      </div>

      {!status && clarificationsConfirmed && !mappingPayload && !preview && (
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text)", cursor: "pointer" }}>
            <input type="checkbox" checked={buildGantt} onChange={(e) => setBuildGantt(e.target.checked)} />
            Построить Гант после импорта
          </label>
        </div>
      )}

      {!status && clarificationsConfirmed && !mappingPayload && !preview && (
        <div
          onClick={() => {
            if (canUpload) {
              fileRef.current?.click();
            }
          }}
          onDragOver={(e) => {
            if (!canUpload) return;
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            if (!canUpload) return;
            e.preventDefault();
            setDrag(false);
            handleDrop(e.dataTransfer.files);
          }}
          style={{
            border: `2px dashed ${!canUpload ? "var(--border)" : drag ? "var(--blue)" : file ? "#22c55e" : "var(--border2)"}`,
            borderRadius: 8,
            padding: "40px 24px",
            textAlign: "center",
            cursor: canUpload ? "pointer" : "not-allowed",
            background: !canUpload ? "rgba(148,163,184,.08)" : drag ? "rgba(59,130,246,.04)" : file ? "rgba(34,197,94,.04)" : "var(--surface)",
            transition: "all .15s",
            opacity: canUpload ? 1 : 0.7,
          }}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.pdf"
            disabled={!canUpload}
            style={{ display: "none" }}
            onChange={(e) => handleDrop(e.target.files)}
          />
          <div style={{ fontSize: 36, marginBottom: 10 }}>{file ? "📊" : canUpload ? "⬆" : "🔒"}</div>
          <div style={{ fontSize: 15, fontWeight: 500, marginBottom: 6 }}>
            {file ? file.name : canUpload ? "Перетащите смету сюда" : "Сначала заполните уточнения"}
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>
            {file
              ? `${(file.size / 1024).toFixed(1)} KB · нажмите для замены`
              : canUpload
                ? "Поддерживаются .xlsx, .xls, .pdf · ГрандСмета, CourtDoc, PDF-сметы"
                : "После уточнений поле загрузки станет активным"}
          </div>
        </div>
      )}

      {file && !status && canUpload && !mappingPayload && !preview && (
        <button
          onClick={handleUpload}
          disabled={uploading || polling}
          style={{
            marginTop: 16,
            width: "100%",
            padding: "11px",
            background: "var(--blue-dark)",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
            opacity: uploading || polling ? 0.7 : 1,
          }}
        >
          {uploading ? "Распознаём..." : "→ Показать превью"}
        </button>
      )}

      {preview && !status && !mappingPayload && (
        <EditablePreviewPanel
          preview={preview}
          confirming={confirming}
          complexMode={complexMode}
          onConfirm={handleConfirmImport}
          onCancel={() => { setPreview(null); }}
        />
      )}

      {mappingPayload && estimateKind && !status && (
        <div style={{ marginTop: 18, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "0 16px" }}>
          <ColumnMapper
            payload={mappingPayload}
            projectId={id}
            startDate={startDate}
            workers={workers}
            estimateKind={estimateKind}
            complexMode={complexMode}
            clarificationAnswers={buildClarificationPayload() ?? {}}
            onConfirm={(nextJobId) => {
              setMappingPayload(null);
              setJobId(nextJobId);
            }}
            onCancel={() => {
              setMappingPayload(null);
              setFile(null);
            }}
          />
        </div>
      )}

      {(status === "pending" || status === "processing") && (
        <div style={{ marginTop: 16, padding: "14px 16px", background: "rgba(59,130,246,.06)", border: "1px solid rgba(59,130,246,.2)", borderRadius: 6 }}>
          <div style={{ fontSize: 13, color: "var(--blue-dark)", fontWeight: 500 }}>
            ⏳ {status === "pending" ? "В очереди..." : "Парсим смету ..."}
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>Это займёт несколько секунд</div>
        </div>
      )}

      {status === "done" && result && (
        <div style={{ marginTop: 16, padding: "16px", background: "rgba(34,197,94,.06)", border: "1px solid rgba(34,197,94,.2)", borderRadius: 6 }}>
          <div style={{ color: "#15803d", fontWeight: 600, fontSize: 14, marginBottom: 10 }}>✓ Смета успешно обработана</div>
          <div style={{ display: "flex", gap: 20, fontSize: 12, color: "var(--muted)", flexWrap: "wrap" }}>
            {[
              ["Блок", result.estimate_batch_name],
              ["Тип", formatEstimateKind(result.estimate_kind ?? estimateKind)],
              ["Позиций сметы", result.estimates_count],
              ["Сумма", result.total_price ? `${fmtMoney(result.total_price)} ₽` : "—"],
            ].map(([label, value]) => (
              <span key={label as string}>
                {label}: <b style={{ color: "var(--text)", fontFamily: "var(--mono)" }}>{value}</b>
              </span>
            ))}
          </div>
          <div style={{ marginTop: 16, display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button
              onClick={() => handleKtpEstimate(result.estimate_batch_id!)}
              disabled={ktpLoading !== null}
              style={{
                flex: 1,
                minWidth: 180,
                padding: "11px 16px",
                background: "var(--blue-dark)",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                fontSize: 13,
                fontWeight: 600,
                cursor: ktpLoading !== null ? "default" : "pointer",
                opacity: ktpLoading !== null ? 0.7 : 1,
              }}
            >
              {ktpLoading === "estimate" ? "ИИ анализирует смету..." : "КТП по смете"}
            </button>
          </div>
        </div>
      )}

      {status === "failed" && (
        <div style={{ marginTop: 16, padding: "14px 16px", background: "rgba(239,68,68,.06)", border: "1px solid rgba(239,68,68,.2)", borderRadius: 6 }}>
          <div style={{ color: "var(--red)", fontWeight: 600, fontSize: 13 }}>❌ Ошибка обработки</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>{result?.error}</div>
          <button
            onClick={() => {
              setJobId(null);
              setFile(null);
              autoStartedKtpBatchRef.current = null;
            }}
            style={{ marginTop: 10, padding: "6px 14px", border: "1px solid var(--border2)", borderRadius: 4, background: "var(--surface)", fontSize: 12, cursor: "pointer" }}
          >
            Попробовать снова
          </button>
        </div>
      )}

      <div style={{ marginTop: 24, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, padding: 16 }}>
        <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 10, fontFamily: "var(--mono)" }}>
          Поддерживаемые форматы
        </div>
        {[
          ["ГрандСмета / АРПС", "Экспорт в Excel"],
          ["CourtDoc / A0", "Табличный формат"],
          ["1С: Подрядчик", "Выгрузка в .xlsx"],
          ["Excel вручную", "Строчный и столбцовый"],
          ["КП подрядчика", "Произвольная таблица"],
          ["PDF-смета", ".pdf с табличным содержимым"],
        ].map(([name, desc]) => (
          <div key={name} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--border)", fontSize: 12 }}>
            <span style={{ fontWeight: 500 }}>{name}</span>
            <span style={{ color: "var(--muted)", fontSize: 11 }}>{desc}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const ITEM_TYPE_COLORS: Record<EstimateItemType, string> = {
  work: "#2563eb",
  material: "#16a34a",
  mechanism: "#9333ea",
  overhead: "#d97706",
  unknown: "#dc2626",
};

const EDITABLE_TYPES: EstimateItemType[] = ["work", "material", "mechanism", "overhead", "unknown"];

function emptyAddedRow(): PreviewAddedRow {
  return { section: "", name: "", item_type: "work", unit: "", quantity: null, total_price: null };
}

function EditablePreviewPanel({
  preview,
  confirming,
  complexMode,
  onConfirm,
  onCancel,
}: {
  preview: PreviewResult;
  confirming: boolean;
  complexMode: boolean;
  onConfirm: (edits: PreviewEdits) => void;
  onCancel: () => void;
}) {
  const baseRows = preview.rows ?? [];
  // index → новый тип (только если отличается от исходного)
  const [overrides, setOverrides] = useState<Record<number, EstimateItemType>>({});
  const [addedRows, setAddedRows] = useState<PreviewAddedRow[]>([]);

  const effType = useCallback(
    (r: PreviewRow): EstimateItemType =>
      r.index != null && overrides[r.index] ? overrides[r.index] : r.item_type,
    [overrides],
  );

  const breakdown = useMemo(() => {
    const acc: Record<EstimateItemType, { count: number; total: number }> = {
      work: { count: 0, total: 0 }, material: { count: 0, total: 0 }, mechanism: { count: 0, total: 0 },
      overhead: { count: 0, total: 0 }, unknown: { count: 0, total: 0 },
    };
    for (const r of baseRows) { const t = effType(r); acc[t].count += 1; acc[t].total += r.total_price ?? 0; }
    for (const a of addedRows) { if (!a.name.trim()) continue; acc[a.item_type].count += 1; acc[a.item_type].total += a.total_price ?? 0; }
    return acc;
  }, [baseRows, addedRows, effType]);

  function setType(r: PreviewRow, t: EstimateItemType) {
    if (r.index == null) return;
    setOverrides((prev) => {
      const next = { ...prev };
      if (t === r.item_type) delete next[r.index!];
      else next[r.index!] = t;
      return next;
    });
  }

  function updateAdded(i: number, patch: Partial<PreviewAddedRow>) {
    setAddedRows((prev) => prev.map((row, j) => (j === i ? { ...row, ...patch } : row)));
  }

  function buildEdits(): PreviewEdits {
    const type_overrides = Object.entries(overrides)
      .map(([idx, item_type]) => {
        const row = baseRows.find((r) => r.index === Number(idx));
        return { index: Number(idx), row_hash: row?.row_hash ?? "", item_type };
      })
      .filter((o) => o.row_hash);
    const added_rows = addedRows
      .filter((a) => a.name.trim())
      .map((a) => ({
        section: a.section?.trim() || null,
        name: a.name.trim(),
        item_type: a.item_type,
        unit: a.unit?.trim() || null,
        quantity: a.quantity,
        total_price: a.total_price,
      }));
    return { type_overrides, added_rows };
  }

  const changedCount = Object.keys(overrides).length + addedRows.filter((a) => a.name.trim()).length;
  const numFromInput = (v: string): number | null => {
    const s = v.trim().replace(",", ".");
    if (s === "") return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  };

  return (
    <div style={{ marginTop: 18, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: 16 }}>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
        Проверьте и при необходимости поправьте типы строк
        <span style={{ fontSize: 11, color: "var(--muted)", fontWeight: 400, marginLeft: 8 }}>
          профиль: {preview.parser_profile}{preview.strategy ? ` · ${preview.strategy}` : ""}
        </span>
      </div>

      {/* Разбивка по типам (пересчитывается с учётом правок) */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 8, marginBottom: 14 }}>
        {EDITABLE_TYPES.map((t) => {
          const b = breakdown[t];
          return (
            <div key={t} style={{ border: "1px solid var(--border)", borderRadius: 6, padding: "8px 10px" }}>
              <div style={{ fontSize: 11, color: ITEM_TYPE_COLORS[t], fontWeight: 600, textTransform: "uppercase", letterSpacing: ".04em" }}>
                {ITEM_TYPE_LABELS[t]}
              </div>
              <div style={{ fontSize: 16, fontWeight: 600, fontFamily: "var(--mono)" }}>{b.count}</div>
              <div style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--mono)" }}>{fmtMoney(b.total)} ₽</div>
            </div>
          );
        })}
      </div>

      {/* Сверка сумм */}
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10 }}>
        Сумма строк: <b style={{ color: "var(--text)", fontFamily: "var(--mono)" }}>{fmtMoney(preview.computed_total_all_rows)} ₽</b>
        {preview.declared_total != null && (
          <> · Итог в смете: <b style={{ color: "var(--text)", fontFamily: "var(--mono)" }}>{fmtMoney(preview.declared_total)} ₽</b></>
        )}
      </div>
      {preview.no_section_count > 0 && (
        <div style={{ fontSize: 12, background: "rgba(245,158,11,.1)", color: "#92400e", borderRadius: 6, padding: "8px 10px", marginBottom: 10 }}>
          Есть строки без раздела: {preview.no_section_count}.
        </div>
      )}
      {preview.truncated && (
        <div style={{ fontSize: 12, background: "rgba(148,163,184,.12)", color: "var(--muted)", borderRadius: 6, padding: "8px 10px", marginBottom: 10 }}>
          Показаны не все строки (смета большая) — редактирование доступно для первых {baseRows.length}. Суммы посчитаны по всей смете.
        </div>
      )}

      {/* Полная редактируемая таблица */}
      <div style={{ overflowX: "auto", border: "1px solid var(--border)", borderRadius: 6, marginTop: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "rgba(148,163,184,.08)" }}>
              {["Тип", "Подтип", "Раздел", "Наименование", "Ед.", "Кол-во", "Сумма"].map((h) => (
                <th key={h} style={{ textAlign: "left", padding: "6px 8px", fontWeight: 600, color: "var(--muted)" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {baseRows.map((r) => {
              const t = effType(r);
              const changed = r.index != null && overrides[r.index] != null;
              return (
                <Fragment key={r.index ?? r.name}>
                  <tr style={{ borderTop: "1px solid var(--border)", background: changed ? "rgba(59,130,246,.06)" : undefined }}>
                    <td style={{ padding: "4px 8px" }}>
                      <select
                        value={t}
                        onChange={(e) => setType(r, e.target.value as EstimateItemType)}
                        style={{ fontSize: 12, padding: "3px 6px", border: "1px solid var(--border2)", borderRadius: 4, background: "var(--surface)", color: ITEM_TYPE_COLORS[t], fontWeight: 600 }}
                      >
                        {EDITABLE_TYPES.map((opt) => (
                          <option key={opt} value={opt} style={{ color: "var(--text)" }}>{ITEM_TYPE_LABELS[opt]}</option>
                        ))}
                      </select>
                    </td>
                    <td style={{ padding: "6px 8px", color: "var(--muted)" }}>
                      {t === "work" && r.subtype_code ? `${r.subtype_code} · ${r.subtype_name ?? ""}` : "—"}
                    </td>
                    <td style={{ padding: "6px 8px", color: "var(--muted)" }}>{r.section ?? "—"}</td>
                    <td style={{ padding: "6px 8px" }}>{r.name}</td>
                    <td style={{ padding: "6px 8px", color: "var(--muted)" }}>{r.unit ?? "—"}</td>
                    <td style={{ padding: "6px 8px", fontFamily: "var(--mono)" }}>{r.quantity ?? "—"}</td>
                    <td style={{ padding: "6px 8px", fontFamily: "var(--mono)" }}>{r.total_price != null ? fmtMoney(r.total_price) : "—"}</td>
                  </tr>
                  {(r.materials ?? []).map((m, j) => (
                    <tr key={`m${r.index}-${j}`} style={{ borderTop: "1px dashed var(--border)", background: "rgba(22,163,74,.04)" }}>
                      <td style={{ padding: "4px 8px", color: ITEM_TYPE_COLORS.material, fontSize: 11 }}>└ материал</td>
                      <td style={{ padding: "4px 8px" }} />
                      <td style={{ padding: "4px 8px" }} />
                      <td style={{ padding: "4px 8px", color: "var(--muted)" }}>{m.name}</td>
                      <td style={{ padding: "4px 8px", color: "var(--muted)" }}>{m.unit ?? "—"}</td>
                      <td style={{ padding: "4px 8px", fontFamily: "var(--mono)" }}>{m.quantity ?? "—"}</td>
                      <td style={{ padding: "4px 8px", fontFamily: "var(--mono)" }}>{m.total_price != null ? fmtMoney(m.total_price) : "—"}</td>
                    </tr>
                  ))}
                </Fragment>
              );
            })}

            {/* Добавленные оператором строки */}
            {addedRows.map((a, i) => (
              <tr key={`added-${i}`} style={{ borderTop: "1px solid var(--border)", background: "rgba(34,197,94,.06)" }}>
                <td style={{ padding: "4px 8px" }}>
                  <select
                    value={a.item_type}
                    onChange={(e) => updateAdded(i, { item_type: e.target.value as EstimateItemType })}
                    style={{ fontSize: 12, padding: "3px 6px", border: "1px solid var(--border2)", borderRadius: 4, background: "var(--surface)", color: ITEM_TYPE_COLORS[a.item_type], fontWeight: 600 }}
                  >
                    {EDITABLE_TYPES.map((opt) => (
                      <option key={opt} value={opt} style={{ color: "var(--text)" }}>{ITEM_TYPE_LABELS[opt]}</option>
                    ))}
                  </select>
                </td>
                <td style={{ padding: "6px 8px", color: "var(--muted)" }}>авто</td>
                <td style={{ padding: "4px 8px" }}>
                  <input value={a.section ?? ""} onChange={(e) => updateAdded(i, { section: e.target.value })} placeholder="раздел"
                    style={{ width: 90, fontSize: 12, padding: "3px 6px", border: "1px solid var(--border2)", borderRadius: 4 }} />
                </td>
                <td style={{ padding: "4px 8px" }}>
                  <input value={a.name} onChange={(e) => updateAdded(i, { name: e.target.value })} placeholder="наименование"
                    style={{ width: "100%", minWidth: 160, fontSize: 12, padding: "3px 6px", border: "1px solid var(--border2)", borderRadius: 4 }} />
                </td>
                <td style={{ padding: "4px 8px" }}>
                  <input value={a.unit ?? ""} onChange={(e) => updateAdded(i, { unit: e.target.value })} placeholder="ед."
                    style={{ width: 50, fontSize: 12, padding: "3px 6px", border: "1px solid var(--border2)", borderRadius: 4 }} />
                </td>
                <td style={{ padding: "4px 8px" }}>
                  <input value={a.quantity ?? ""} onChange={(e) => updateAdded(i, { quantity: numFromInput(e.target.value) })} placeholder="0"
                    style={{ width: 60, fontSize: 12, padding: "3px 6px", border: "1px solid var(--border2)", borderRadius: 4, fontFamily: "var(--mono)" }} />
                </td>
                <td style={{ padding: "4px 8px", display: "flex", gap: 6, alignItems: "center" }}>
                  <input value={a.total_price ?? ""} onChange={(e) => updateAdded(i, { total_price: numFromInput(e.target.value) })} placeholder="0"
                    style={{ width: 80, fontSize: 12, padding: "3px 6px", border: "1px solid var(--border2)", borderRadius: 4, fontFamily: "var(--mono)" }} />
                  <button type="button" onClick={() => setAddedRows((prev) => prev.filter((_, j) => j !== i))}
                    title="Удалить строку"
                    style={{ border: "none", background: "transparent", color: "var(--red)", cursor: "pointer", fontSize: 14 }}>✕</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button
        type="button"
        onClick={() => setAddedRows((prev) => [...prev, emptyAddedRow()])}
        style={{ marginTop: 10, padding: "7px 12px", background: "var(--surface)", border: "1px dashed var(--border2)", borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
      >
        ➕ Добавить строку
      </button>

      <div style={{ marginTop: 14, display: "flex", gap: 10, alignItems: "center" }}>
        <button
          onClick={() => onConfirm(buildEdits())}
          disabled={confirming}
          style={{ flex: 1, padding: "11px", background: "var(--blue-dark)", color: "#fff", border: "none", borderRadius: 6, fontSize: 14, fontWeight: 600, cursor: "pointer", opacity: confirming ? 0.7 : 1 }}
        >
          {confirming ? "Импортируем..." : complexMode ? "→ Добавить смету в комплекс" : "→ Импортировать смету"}
        </button>
        <button
          onClick={onCancel}
          disabled={confirming}
          style={{ padding: "11px 16px", background: "var(--surface)", color: "var(--muted)", border: "1px solid var(--border2)", borderRadius: 6, fontSize: 14, cursor: "pointer" }}
        >
          Отмена
        </button>
      </div>
      {changedCount > 0 && (
        <div style={{ marginTop: 8, fontSize: 11, color: "var(--muted)" }}>Правок к применению: {changedCount}</div>
      )}
    </div>
  );
}
