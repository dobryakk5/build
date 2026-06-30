"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { estimates, ktpEstimate, workTaxonomy } from "@/lib/api";
import ColumnMapper, { type MappingPayload } from "@/components/ColumnMapper";
import { fmtMoney } from "@/lib/dateUtils";
import { CLARIFICATION_BY_KIND } from "@/lib/estimateClarificationQuestions";
import { useJobPoller } from "@/lib/useJobPoller";
import { trackActivity } from "@/lib/activity";
import type {
  EstimateBatch,
  PreviewResult,
  PreviewRow,
  PreviewEdits,
  PreviewAddedRow,
  EstimateItemType,
  WorkEstimateType,
  WorkProjectHierarchy,
  WorkProjectVariant,
  WorkStage,
} from "@/lib/types";

const ITEM_TYPE_LABELS: Record<EstimateItemType, string> = {
  work: "Работы",
  material: "Материалы",
  mechanism: "Механизмы",
  overhead: "Накладные",
  unknown: "Сомнительные",
};

type EstimateKind = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;
type ClarificationUploadPayload = {
  version: "v1";
  estimate_kind: EstimateKind;
  kind_title: string;
  form: Record<string, { section: string; question: string; answers: string[] }>;
};

type RestoredHierarchySnapshot = {
  estimate_type_id: string | null;
  estimate_type_title: string | null;
  estimate_type_number: string | null;
  estimate_kind: number | null;
  project_variant_id: string | null;
  project_variant_title: string | null;
  project_variant_number: string | null;
};

const DYNAMIC_FLOOR_VARIANT_ID = "residential_construction_kirpichnye_doma";

function latestCompletedStage10Batch(batches: EstimateBatch[]) {
  return [...batches]
    .filter((batch) =>
      batch.project_variant_id === DYNAMIC_FLOOR_VARIANT_ID
      && (batch.import_status === "completed" || batch.calculation_status === "calculated")
      && (batch.estimates_count ?? 0) > 0,
    )
    .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at))
    .at(-1) ?? null;
}

function ktpSessionHref(projectId: string, session: { id: string; status: string; stage1_job_id?: string | null; gpr_job_id?: string | null }) {
  const jobId =
    session.status === "stage1_pending" || session.status === "stage1_processing"
      ? session.stage1_job_id
      : session.status === "gpr_processing"
        ? session.gpr_job_id
        : null;
  return `/projects/${projectId}/ktp-estimate/${session.id}${jobId ? `?job=${jobId}` : ""}`;
}
const BASEMENT_TOP_SLAB_STAGE_ID = "residential_construction.ustroystvo_perekrytiy_cokolya";
const BASEMENT_BRANCH_STAGE_IDS = new Set([
  "residential_construction.vysokiy_cokol",
  BASEMENT_TOP_SLAB_STAGE_ID,
]);
const STAGE10_PREVIEW_STORAGE_PREFIX = "stage10-estimate-preview:";

type Stage10BuildingParams = {
  floors_count: number;
  has_basement: boolean;
  has_mansard: boolean;
};

type Stage10PreviewRestoreState = {
  previewId: string;
  projectId: string;
  filename: string;
  parserProfile: string;
  estimateKind: EstimateKind | null;
  estimateTypeId: string | null;
  projectVariantId: string | null;
  startDate: string;
  workers: number;
  buildingParams: Stage10BuildingParams;
  projectStructureOptions: Record<string, string>;
  savedAt: string;
};

const LEGACY_KIND_LABEL_BY_ID: Record<EstimateKind, string> = {
  1: "1. Земляные грунтовые работы",
  2: "2. Строительство жилого помещения",
  3: "3. Строительство нежилого помещения",
  4: "4. Реконструкция нежилого помещения",
  5: "5. Отделка жилого помещения",
  6: "6. Отделка нежилого помещения",
  7: "7. Инженерные работы внутренние",
  8: "8. Инженерные работы наружные",
  9: "9. Ландшафтные работы",
};

const LEGACY_KIND_LABEL: Record<string, string> = {
  country_house: LEGACY_KIND_LABEL_BY_ID[2],
  apartment: LEGACY_KIND_LABEL_BY_ID[2],
  non_residential: LEGACY_KIND_LABEL_BY_ID[3],
};

function formatEstimateKind(kind: number | string | null | undefined) {
  if (typeof kind === "number" && kind in LEGACY_KIND_LABEL_BY_ID) {
    return LEGACY_KIND_LABEL_BY_ID[kind as EstimateKind];
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

function stage10PreviewStorageKey(projectId: string) {
  return `${STAGE10_PREVIEW_STORAGE_PREFIX}${projectId}`;
}

function readStage10PreviewRestore(projectId: string): Stage10PreviewRestoreState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(stage10PreviewStorageKey(projectId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Stage10PreviewRestoreState>;
    if (!parsed.previewId || parsed.projectId !== projectId) return null;
    return {
      previewId: String(parsed.previewId),
      projectId,
      filename: String(parsed.filename || "Восстановленное превью"),
      parserProfile: String(parsed.parserProfile || "auto"),
      estimateKind: (parsed.estimateKind ?? null) as EstimateKind | null,
      estimateTypeId: parsed.estimateTypeId ? String(parsed.estimateTypeId) : null,
      projectVariantId: parsed.projectVariantId ? String(parsed.projectVariantId) : null,
      startDate: String(parsed.startDate || new Date().toISOString().split("T")[0]),
      workers: Number.isFinite(Number(parsed.workers)) ? Number(parsed.workers) : 3,
      buildingParams: {
        floors_count: Math.max(1, Math.min(100, Number(parsed.buildingParams?.floors_count) || 1)),
        has_basement: Boolean(parsed.buildingParams?.has_basement),
        has_mansard: Boolean(parsed.buildingParams?.has_mansard),
      },
      projectStructureOptions: Object.fromEntries(
        Object.entries(parsed.projectStructureOptions || {})
          .map(([stageId, optionId]) => [String(stageId), String(optionId)])
          .filter(([stageId, optionId]) => stageId && optionId),
      ),
      savedAt: String(parsed.savedAt || ""),
    };
  } catch {
    return null;
  }
}

function writeStage10PreviewRestore(projectId: string, state: Stage10PreviewRestoreState) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(stage10PreviewStorageKey(projectId), JSON.stringify(state));
}

function clearStage10PreviewRestore(projectId: string) {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(stage10PreviewStorageKey(projectId));
}

function replacePreviewQuery(previewId: string | null) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (previewId) {
    url.searchParams.set("preview", previewId);
  } else {
    url.searchParams.delete("preview");
  }
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

export default function UploadPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const fileRef = useRef<HTMLInputElement>(null);
  const batchIdFromQuery = searchParams.get("batch");
  const sessionIdFromQuery = searchParams.get("session");
  const previewIdFromQuery = searchParams.get("preview");
  const fromKtpFlow = searchParams.get("fromKtp") === "1";

  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [startDate, setStartDate] = useState(new Date().toISOString().split("T")[0]);
  const [workers, setWorkers] = useState(3);
  const [estimateKind, setEstimateKind] = useState<EstimateKind | null>(null);
  const [hierarchy, setHierarchy] = useState<WorkProjectHierarchy | null>(null);
  const [hierarchyLoading, setHierarchyLoading] = useState(true);
  const [hierarchyError, setHierarchyError] = useState<string | null>(null);
  const [estimateTypeId, setEstimateTypeId] = useState<string | null>(null);
  const [projectVariantId, setProjectVariantId] = useState<string | null>(null);
  const [restoredHierarchySnapshot, setRestoredHierarchySnapshot] = useState<RestoredHierarchySnapshot | null>(null);
  const [clarificationAnswers, setClarificationAnswers] = useState<Record<string, string[]>>({});
  const [clarificationsConfirmed, setClarificationsConfirmed] = useState(false);
  const [complexMode, setComplexMode] = useState(false);
  const [buildGantt, setBuildGantt] = useState(true);
  const [preserveEstimateStructure, setPreserveEstimateStructure] = useState(false);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [mappingPayload, setMappingPayload] = useState<MappingPayload | null>(null);
  const [uploading, setUploading] = useState(false);
  const [ktpLoading, setKtpLoading] = useState<"estimate" | null>(null);
  const [resetting, setResetting] = useState(false);
  const [resetNotice, setResetNotice] = useState<string | null>(null);
  const [stage10ImportNotice, setStage10ImportNotice] = useState<string | null>(null);
  const [stage10PendingBatchId, setStage10PendingBatchId] = useState<string | null>(null);
  const [stage10BuildingParams, setStage10BuildingParams] = useState<Stage10BuildingParams>({
    floors_count: 1,
    has_basement: false,
    has_mansard: false,
  });
  const [stage10SelectedOptions, setStage10SelectedOptions] = useState<Record<string, string>>({});
  const [stage10OptionsSaving, setStage10OptionsSaving] = useState(false);

  const { job, loading: polling } = useJobPoller(jobId);
  const status = job?.status;
  const result = job?.result;
  const activeStatus = jobId ? status : undefined;
  const currentClarification = estimateKind ? CLARIFICATION_BY_KIND[estimateKind] : null;
  const isDynamicFloorVariant = projectVariantId === DYNAMIC_FLOOR_VARIANT_ID;
  const activeClarification = isDynamicFloorVariant ? null : currentClarification;
  const estimateTypes = hierarchy?.estimate_types ?? [];
  const estimateTypeOptions = useMemo(() => {
    if (!restoredHierarchySnapshot?.estimate_type_id) return estimateTypes;
    if (estimateTypes.some((item) => item.id === restoredHierarchySnapshot.estimate_type_id)) return estimateTypes;

    const fallbackVariant: WorkProjectVariant | null = restoredHierarchySnapshot.project_variant_id
      ? {
        id: restoredHierarchySnapshot.project_variant_id,
        number: restoredHierarchySnapshot.project_variant_number || "",
        title: restoredHierarchySnapshot.project_variant_title || "Сохранённый подтип",
        stages_count: 0,
      }
      : null;

    const fallbackType: WorkEstimateType = {
      id: restoredHierarchySnapshot.estimate_type_id,
      number: restoredHierarchySnapshot.estimate_type_number || "",
      title: restoredHierarchySnapshot.estimate_type_title || "Сохранённый тип",
      estimate_kind: restoredHierarchySnapshot.estimate_kind || 1,
      estimate_profile_id: restoredHierarchySnapshot.estimate_type_id,
      project_variants: fallbackVariant ? [fallbackVariant] : [],
    };

    return [...estimateTypes, fallbackType];
  }, [estimateTypes, restoredHierarchySnapshot]);
  const selectedEstimateType = useMemo(
    () => estimateTypeOptions.find((item) => item.id === estimateTypeId) ?? null,
    [estimateTypeId, estimateTypeOptions],
  );
  const projectVariants = selectedEstimateType?.project_variants ?? [];
  const selectedProjectVariant = useMemo(
    () => projectVariants.find((item) => item.id === projectVariantId) ?? null,
    [projectVariantId, projectVariants],
  );
  const stage10RadioGroups = useMemo(() => {
    if (!isDynamicFloorVariant || !selectedProjectVariant?.stages?.length) return [];

    if (preview?.preview_backend === "db_stage10" && preview.stage_option_requirements?.length) {
      return preview.stage_option_requirements.map((requirement) => ({
        id: requirement.canonical_stage_id,
        number: requirement.template_stage_number,
        title: requirement.title,
        canonical_stage_id: requirement.canonical_stage_id,
        stage_options_mode: "selectable_one",
        stage_options: requirement.options,
      } as WorkStage));
    }

    return selectedProjectVariant.stages.filter((stage): stage is WorkStage => {
      const stageId = String(stage.canonical_stage_id || "").trim();
      const mode = stage.stage_options_mode;
      if (!stageId || !["selectable_one", "selectable_many"].includes(mode)) return false;
      if (!stage.stage_options?.some((option) => String(option.id || "").trim())) return false;
      if (!stage10BuildingParams.has_basement && BASEMENT_BRANCH_STAGE_IDS.has(stageId)) return false;
      if (stage.number === "2.7.10" && stage10BuildingParams.floors_count === 1 && stage10BuildingParams.has_mansard) return false;
      return true;
    });
  }, [isDynamicFloorVariant, preview, selectedProjectVariant, stage10BuildingParams]);
  useEffect(() => {
    if (preview?.preview_backend !== "db_stage10") return;
    const normalized = Object.fromEntries(
      Object.entries(preview.project_structure_options || {}).filter(([, value]) => typeof value === "string"),
    ) as Record<string, string>;
    setStage10SelectedOptions(normalized);
    if (preview.building_params) {
      setStage10BuildingParams((current) => ({
        floors_count: Number(preview.building_params?.floors_count || current.floors_count),
        has_basement: Boolean(preview.building_params?.has_basement),
        has_mansard: Boolean(preview.building_params?.has_mansard),
      }));
    }
  }, [preview]);
  const answeredCount = Object.values(clarificationAnswers).filter((answers) => answers.length > 0).length;
  const questionsCount = activeClarification?.sections.reduce((sum, section) => sum + section.questions.length, 0) ?? 0;
  const allClarificationsAnswered = questionsCount > 0 && answeredCount === questionsCount;
  const hasRequiredSelection = estimateKind !== null && !!estimateTypeId && (!!projectVariantId || projectVariants.length === 0);
  const stage10StructureComplete = !isDynamicFloorVariant || stage10RadioGroups.every((stage) => {
    const stageId = String(stage.canonical_stage_id || "").trim();
    return !!stage10SelectedOptions[stageId];
  });
  const canUpload = hasRequiredSelection && stage10StructureComplete;
  const uploadDisabledTitle = !hasRequiredSelection
    ? "Выберите тип и подтип объекта"
    : "Выберите ветвления работ";
  const uploadDisabledHint = !hasRequiredSelection
    ? "После выбора объекта поле загрузки станет активным"
    : "Перед загрузкой нужно выбрать по одному варианту в каждой radio-группе";
  const wasAllClarificationsAnsweredRef = useRef(false);
  const clarificationStartedRef = useRef(false);
  const trackedJobTerminalStatusRef = useRef<string | null>(null);
  const autoStartedKtpBatchRef = useRef<string | null>(null);
  const restoredBatchRef = useRef<string | null>(null);
  const restoredPreviewRef = useRef<string | null>(null);

  useEffect(() => {
    trackActivity("UPLOAD_PAGE_OPENED", {
      projectId: id,
      entityType: "project",
      entityId: id,
    });
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    setHierarchyLoading(true);
    setHierarchyError(null);
    workTaxonomy
      .projectHierarchy({ include_stages: true })
      .then((data) => {
        if (cancelled) return;
        setHierarchy(data);
      })
      .catch((error) => {
        if (cancelled) return;
        setHierarchyError(error?.message || "Не удалось загрузить справочник типов смет");
      })
      .finally(() => {
        if (!cancelled) setHierarchyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (preview || activeStatus || mappingPayload || stage10PendingBatchId) return;

    const stored = readStage10PreviewRestore(id);
    const previewId = previewIdFromQuery || stored?.previewId;
    if (!previewId || restoredPreviewRef.current === previewId) return;

    let cancelled = false;
    restoredPreviewRef.current = previewId;
    estimates
      .getDbStage10Preview(
        previewId,
        stored?.filename || "Восстановленное превью",
        stored?.parserProfile || "auto",
      )
      .then((restoredPreview) => {
        if (cancelled) return;
        if (restoredPreview.project_id && restoredPreview.project_id !== id) {
          if (stored?.previewId === previewId) {
            clearStage10PreviewRestore(id);
          }
          replacePreviewQuery(null);
          return;
        }
        if (restoredPreview.preview_status && restoredPreview.preview_status !== "active") {
          if (stored?.previewId === previewId) {
            clearStage10PreviewRestore(id);
          }
          replacePreviewQuery(null);
          return;
        }

        if (stored?.previewId === previewId) {
          setEstimateKind(stored.estimateKind);
          setEstimateTypeId(stored.estimateTypeId);
          setProjectVariantId(stored.projectVariantId);
          setStartDate(stored.startDate);
          setWorkers(stored.workers);
          setStage10BuildingParams(stored.buildingParams);
          setStage10SelectedOptions(stored.projectStructureOptions);
        }
        setFile(null);
        setPreview(restoredPreview);
        setMappingPayload(null);
        setUploading(false);
        setConfirming(false);
        setStage10ImportNotice(null);
        setStage10PendingBatchId(null);
        if (!previewIdFromQuery) {
          replacePreviewQuery(previewId);
        }
      })
      .catch(() => {
        if (cancelled) return;
        if (stored?.previewId === previewId) {
          clearStage10PreviewRestore(id);
        }
        replacePreviewQuery(null);
      });

    return () => {
      cancelled = true;
    };
  }, [activeStatus, id, mappingPayload, preview, previewIdFromQuery, stage10PendingBatchId]);

  useEffect(() => {
    const wasAllAnswered = wasAllClarificationsAnsweredRef.current;

    if (selectedEstimateType && allClarificationsAnswered && !wasAllAnswered && !clarificationsConfirmed && !status && !fromKtpFlow) {
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
  }, [allClarificationsAnswered, answeredCount, clarificationsConfirmed, estimateKind, fromKtpFlow, id, questionsCount, selectedEstimateType, status]);

  useEffect(() => {
    if (!batchIdFromQuery || restoredBatchRef.current === batchIdFromQuery) return;

    let cancelled = false;
    estimates
      .batches(id)
      .then((batches) => {
        if (cancelled) return;
        const batch = batches.find((item) => item.id === batchIdFromQuery);
        if (!batch) return;
        const restoredType =
          batch.estimate_type_id
          || hierarchy?.estimate_types.find((item) => item.estimate_kind === batch.estimate_kind)?.id
          || null;
        const restoredKind =
          hierarchy?.estimate_types.find((item) => item.id === restoredType)?.estimate_kind
          || batch.estimate_kind;
        if (!batch.estimate_type_id && !restoredType && !hierarchyLoading) return;

        restoredBatchRef.current = batch.id;
        setRestoredHierarchySnapshot({
          estimate_type_id: batch.estimate_type_id ?? restoredType,
          estimate_type_title: batch.estimate_type_title ?? null,
          estimate_type_number: batch.estimate_type_number ?? null,
          estimate_kind: restoredKind ?? null,
          project_variant_id: batch.project_variant_id ?? null,
          project_variant_title: batch.project_variant_title ?? null,
          project_variant_number: batch.project_variant_number ?? null,
        });
        setEstimateTypeId(restoredType);
        setProjectVariantId(batch.project_variant_id ?? null);
        setEstimateKind(restoredKind as EstimateKind);
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
  }, [batchIdFromQuery, fromKtpFlow, hierarchy, hierarchyLoading, id]);

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
      setMappingPayload(null);
      setUploading(false);
      setConfirming(false);
      setKtpLoading(null);
      setStage10ImportNotice(null);
      setStage10PendingBatchId(null);
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
          estimate_type_id: estimateTypeId,
          project_variant_id: projectVariantId,
          complex_mode: complexMode,
        },
      });
    }
  }, [canUpload, complexMode, estimateKind, estimateTypeId, id, projectVariantId]);

  async function handleUpload() {
    if (!file || !canUpload || !estimateKind || !estimateTypeId) return;

    setUploading(true);
    setStage10ImportNotice(null);
    setStage10PendingBatchId(null);
    autoStartedKtpBatchRef.current = null;
    const clarificationPayload = buildClarificationPayload();
    const stage10SavedBuildingParams = buildStage10BuildingParams();
    const stage10SavedProjectStructureOptions = buildStage10ProjectStructureOptions();
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
        estimate_type_id: estimateTypeId,
        project_variant_id: projectVariantId,
        complex_mode: complexMode,
        answered_count: answeredCount,
        questions_count: questionsCount,
      },
    });
    try {
      const res = await estimates.preview(
        id, file, startDate, workers, estimateKind, complexMode,
        estimateTypeId, projectVariantId,
        "auto", buildGantt, clarificationPayload, stage10SavedBuildingParams, stage10SavedProjectStructureOptions,
      );
      setPreview(res);
      if (res.preview_backend === "db_stage10") {
        writeStage10PreviewRestore(id, {
          previewId: res.preview_id,
          projectId: id,
          filename: file.name,
          parserProfile: res.parser_profile || "auto",
          estimateKind,
          estimateTypeId,
          projectVariantId: projectVariantId ?? null,
          startDate,
          workers,
          buildingParams: stage10SavedBuildingParams as Stage10BuildingParams,
          projectStructureOptions: (stage10SavedProjectStructureOptions ?? {}) as Record<string, string>,
          savedAt: new Date().toISOString(),
        });
        replacePreviewQuery(res.preview_id);
      }
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
      if (preview.preview_backend === "db_stage10") {
        if (!preview.preview_content_hash) {
          throw new Error("Не найден hash DB preview");
        }
        const res = await estimates.confirmDbStage10(preview.preview_id, preview.preview_content_hash);
        const workersCount = Number(workers) > 0 ? Number(workers) : 3;
        await estimates.updateBatchSchedule(id, res.estimate_batch_id, {
          workers_count: workersCount,
          hours_per_day: 8,
        });
        restoredPreviewRef.current = preview.preview_id;
        clearStage10PreviewRestore(id);
        replacePreviewQuery(null);
        setPreview(null);
        setJobId(null);
        setStage10PendingBatchId(res.estimate_batch_id);
        setStage10ImportNotice("Процесс распознавания больших смет может длится несколько минут");
        trackActivity("ESTIMATE_UPLOAD_JOB_CREATED", {
          projectId: id,
          entityType: "estimate_batch",
          entityId: res.estimate_batch_id,
          metadata: {
            estimate_batch_id: res.estimate_batch_id,
            outbox_record_id: res.outbox_record_id,
            idempotency_key: res.idempotency_key,
            parser_profile: preview?.parser_profile,
            preview_backend: preview.preview_backend,
          },
        });
        return;
      }
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
        if (preview?.preview_backend === "db_stage10") {
          clearStage10PreviewRestore(id);
          replacePreviewQuery(null);
        }
        setPreview(null);
        alert("Превью истекло. Загрузите файл заново.");
      } else {
        alert(e.message);
      }
    } finally {
      setConfirming(false);
    }
  }

  async function handleCancelPreview() {
    const currentPreview = preview;
    setPreview(null);
    if (currentPreview?.preview_backend === "db_stage10") {
      restoredPreviewRef.current = currentPreview.preview_id;
      clearStage10PreviewRestore(id);
      replacePreviewQuery(null);
      await estimates.cancelDbStage10(currentPreview.preview_id).catch(() => undefined);
    }
  }

  async function handleResetProgress() {
    if (!sessionIdFromQuery) return;
    const confirmed = window.confirm("Сбросить прогресс КТП и начать заново с шага «Новая смета»?");
    if (!confirmed) return;

    setResetting(true);
    setResetNotice(null);
    setStage10ImportNotice(null);
    setStage10PendingBatchId(null);
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
    if (!estimateKind || !activeClarification) return undefined;

    const form: ClarificationUploadPayload["form"] = {};
    for (const section of activeClarification.sections) {
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
      kind_title: activeClarification.title,
      form,
    };
  }

  function buildStage10BuildingParams() {
    if (!isDynamicFloorVariant) return undefined;
    return {
      floors_count: stage10BuildingParams.floors_count,
      has_basement: stage10BuildingParams.has_basement,
      has_mansard: stage10BuildingParams.has_mansard,
    };
  }

  function buildStage10ProjectStructureOptions() {
    if (!isDynamicFloorVariant) {
      return undefined;
    }
    const options: Record<string, string> = {};
    const visibleStageIds = new Set(stage10RadioGroups.map((stage) => String(stage.canonical_stage_id || "").trim()));
    for (const [stageId, optionId] of Object.entries(stage10SelectedOptions)) {
      if (visibleStageIds.has(stageId) && optionId) {
        options[stageId] = optionId;
      }
    }
    return Object.keys(options).length ? options : undefined;
  }

  function resetClarificationState() {
    if (previewIdFromQuery) {
      restoredPreviewRef.current = previewIdFromQuery;
    }
    clearStage10PreviewRestore(id);
    replacePreviewQuery(null);
    setClarificationAnswers({});
    setClarificationsConfirmed(false);
    setStage10BuildingParams({ floors_count: 1, has_basement: false, has_mansard: false });
    setStage10SelectedOptions({});
    setFile(null);
    setJobId(null);
    setPreview(null);
    setMappingPayload(null);
    setStage10ImportNotice(null);
    setStage10PendingBatchId(null);
    autoStartedKtpBatchRef.current = null;
    clarificationStartedRef.current = false;
    wasAllClarificationsAnsweredRef.current = false;
  }

  function selectEstimateType(nextTypeId: string | null) {
    const nextType = estimateTypeOptions.find((item) => item.id === nextTypeId) ?? null;
    if (!nextType || nextType.id !== restoredHierarchySnapshot?.estimate_type_id) {
      setRestoredHierarchySnapshot(null);
    }
    setEstimateTypeId(nextType?.id ?? null);
    setProjectVariantId(null);
    setEstimateKind(nextType ? (nextType.estimate_kind as EstimateKind) : null);
    resetClarificationState();
    if (nextType) {
      trackActivity("ESTIMATE_KIND_SELECTED", {
        projectId: id,
        entityType: "project",
        entityId: id,
        metadata: {
          estimate_kind: nextType.estimate_kind,
          estimate_type_id: nextType.id,
          kind_title: `${nextType.number}. ${nextType.title}`,
        },
      });
    }
  }

  function selectProjectVariant(nextVariantId: string | null) {
    setProjectVariantId(nextVariantId);
    resetClarificationState();
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

  function updateStage10BuildingParam<K extends keyof typeof stage10BuildingParams>(
    key: K,
    value: (typeof stage10BuildingParams)[K],
  ) {
    if (previewIdFromQuery) {
      restoredPreviewRef.current = previewIdFromQuery;
    }
    clearStage10PreviewRestore(id);
    replacePreviewQuery(null);
    setStage10BuildingParams((prev) => ({ ...prev, [key]: value }));
    if (key === "has_basement" && value === false) {
      setStage10SelectedOptions((prev) => {
        const next = { ...prev };
        for (const stageId of BASEMENT_BRANCH_STAGE_IDS) {
          delete next[stageId];
        }
        return next;
      });
    }
    setFile(null);
    setPreview(null);
    setMappingPayload(null);
  }

  async function selectStage10Option(stageId: string, optionId: string) {
    if (preview?.preview_backend === "db_stage10" && preview.preview_content_hash) {
      const previous = stage10SelectedOptions[stageId];
      setStage10SelectedOptions((current) => ({ ...current, [stageId]: optionId }));
      setStage10OptionsSaving(true);
      try {
        const updated = await estimates.updateDbStage10Preview(
          preview.preview_id,
          preview.preview_content_hash,
          preview.filename,
          preview.parser_profile || "auto",
          undefined,
          { [stageId]: optionId },
        );
        setPreview(updated);
        setStage10SelectedOptions(
          Object.fromEntries(
            Object.entries(updated.project_structure_options || {}).filter(([, value]) => typeof value === "string"),
          ) as Record<string, string>,
        );
      } catch (error: any) {
        setStage10SelectedOptions((current) => {
          const next = { ...current };
          if (previous) next[stageId] = previous;
          else delete next[stageId];
          return next;
        });
        alert(error?.message || "Не удалось сохранить вариант технологии");
      } finally {
        setStage10OptionsSaving(false);
      }
      return;
    }
    if (previewIdFromQuery) {
      restoredPreviewRef.current = previewIdFromQuery;
    }
    clearStage10PreviewRestore(id);
    replacePreviewQuery(null);
    setStage10SelectedOptions((prev) => ({ ...prev, [stageId]: optionId }));
    setFile(null);
    setPreview(null);
    setMappingPayload(null);
  }

  const handleKtpEstimate = useCallback(async (batchId: string) => {
    setKtpLoading("estimate");
    try {
      const { job_id, session_id } = await ktpEstimate.startSession(id, batchId, false, preserveEstimateStructure);
      trackActivity("KTP_ESTIMATE_SESSION_STARTED", {
        projectId: id,
        entityType: "ktp_estimate_session",
        entityId: session_id,
        metadata: { estimate_batch_id: batchId, job_id, preserve_estimate_structure: preserveEstimateStructure },
      });
      const suffix = job_id ? `?job=${job_id}` : "";
      router.replace(`/projects/${id}/ktp-estimate/${session_id}${suffix}`);
    } catch (e: any) {
      alert(e.message);
      setKtpLoading(null);
    }
  }, [id, preserveEstimateStructure, router]);

  useEffect(() => {
    const batchId = result?.estimate_batch_id;
    if (status !== "done" || !batchId || autoStartedKtpBatchRef.current === batchId) return;

    autoStartedKtpBatchRef.current = batchId;
    void handleKtpEstimate(batchId);
  }, [handleKtpEstimate, result?.estimate_batch_id, status]);

  useEffect(() => {
    if (
      fromKtpFlow
      || preview
      || activeStatus
      || mappingPayload
      || stage10PendingBatchId
      || ktpLoading
      || file
    ) {
      return;
    }

    let cancelled = false;
    const recoverCompletedStage10Import = async () => {
      try {
        const batches = await estimates.batches(id);
        if (cancelled) return;
        const batch = batchIdFromQuery
          ? batches.find((item) => item.id === batchIdFromQuery) ?? null
          : latestCompletedStage10Batch(batches);
        if (
          !batch
          || batch.project_variant_id !== DYNAMIC_FLOOR_VARIANT_ID
          || autoStartedKtpBatchRef.current === batch.id
          || !(
            batch.import_status === "completed"
            || batch.calculation_status === "calculated"
          )
          || (batch.estimates_count ?? 0) <= 0
        ) {
          return;
        }

        const session = await ktpEstimate.getSession(id, batch.id);
        if (cancelled) return;
        if (session) {
          autoStartedKtpBatchRef.current = batch.id;
          if (session.status === "stage1_pending" || session.status === "stage1_processing") {
            setStage10ImportNotice("Анализируем смету");
            await handleKtpEstimate(batch.id);
            return;
          }
          router.replace(ktpSessionHref(id, session));
          return;
        }

        autoStartedKtpBatchRef.current = batch.id;
        setStage10ImportNotice("Анализируем смету");
        await handleKtpEstimate(batch.id);
      } catch {
        // Recovery is best-effort; explicit upload controls remain available.
      }
    };

    void recoverCompletedStage10Import();
    return () => {
      cancelled = true;
    };
  }, [
    activeStatus,
    batchIdFromQuery,
    file,
    fromKtpFlow,
    handleKtpEstimate,
    id,
    ktpLoading,
    mappingPayload,
    preview,
    router,
    stage10PendingBatchId,
  ]);

  useEffect(() => {
    if (!stage10PendingBatchId || autoStartedKtpBatchRef.current === stage10PendingBatchId) return;

    let cancelled = false;
    const poll = async () => {
      try {
        const batches = await estimates.batches(id);
        if (cancelled) return;
        const batch = batches.find((item) => item.id === stage10PendingBatchId);
        if (!batch) return;
        if (batch.import_status === "completed" || batch.calculation_status === "calculated") {
          autoStartedKtpBatchRef.current = stage10PendingBatchId;
          setStage10PendingBatchId(null);
          setStage10ImportNotice("Анализируем смету");
          void handleKtpEstimate(stage10PendingBatchId);
        } else if (batch.import_status === "blocked" || batch.calculation_status === "blocked") {
          setStage10PendingBatchId(null);
          setStage10ImportNotice(
            batch.calculation_block_reason
              ? `Импорт остановлен: ${batch.calculation_block_reason}`
              : "Импорт остановлен. Требуется проверка сметы.",
          );
        }
      } catch {
        // Keep polling; transient auth/network failures are handled by api.ts.
      }
    };

    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [handleKtpEstimate, id, stage10PendingBatchId]);

  const importProgressTitle =
    status === "pending"
      ? "В очереди..."
      : result?._progress || "Обрабатываем смету...";
  const importProgressHint =
    status === "pending"
      ? "Ничего нажимать не нужно — страница сама начнёт обработку."
      : "Ничего нажимать не нужно — страница обновится автоматически. Большие сметы могут обрабатываться несколько минут.";

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
            Выберите тип и подтип объекта. Для кирпичных домов 2.7 задайте структуру здания и ветвления работ перед загрузкой.
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
        {hierarchyError && (
          <div style={{ padding: "12px 14px", borderRadius: 8, border: "1px solid rgba(239,68,68,.22)", background: "rgba(239,68,68,.06)", color: "var(--red)", fontSize: 12 }}>
            {hierarchyError}
          </div>
        )}
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
            value={estimateTypeId ?? ""}
            disabled={hierarchyLoading || !!hierarchyError}
            onChange={(e) => selectEstimateType(e.target.value || null)}
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
            <option value="">{hierarchyLoading ? "Загружаем типы..." : "Выберите тип объекта"}</option>
            {estimateTypeOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.number}. {option.title}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label
            htmlFor="project-variant"
            style={{
              display: "block",
              marginBottom: 8,
              fontSize: 14,
              fontWeight: 600,
            }}
          >
            2. Выберите подтип объекта
          </label>
          <select
            id="project-variant"
            value={projectVariantId ?? ""}
            disabled={!selectedEstimateType || !!hierarchyError}
            onChange={(e) => selectProjectVariant(e.target.value || null)}
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
            <option value="">{selectedEstimateType ? "Выберите подтип объекта" : "Сначала выберите тип объекта"}</option>
            {projectVariants.map((variant) => (
              <option key={variant.id} value={variant.id}>
                {variant.number}. {variant.title}
              </option>
            ))}
          </select>
        </div>

        <div>
          <div style={{ marginBottom: 8, fontSize: 14, fontWeight: 600 }}>
            3. Уточните исходные данные
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>
            {isDynamicFloorVariant
              ? "Для кирпичных домов задайте структуру здания и выберите ветки работ."
              : "Чекбоксы необязательны. Если отметить подходящие пункты, они помогут точнее разобрать смету."}
          </div>
        </div>
      </div>

      {isDynamicFloorVariant && selectedProjectVariant && !activeStatus && (
        <div style={{ marginBottom: 20, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>Структура кирпичного дома</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
              Эти параметры управляют поэтажной структурой 2.7 и рекомендованными работами.
            </div>
          </div>
          <div style={{ display: "grid", gap: 14, padding: 16 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
              <label style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 6, fontSize: 13, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={stage10BuildingParams.has_basement}
                  onChange={(event) => updateStage10BuildingParam("has_basement", event.target.checked)}
                />
                <span>Цоколь</span>
              </label>
              <label style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 6, fontSize: 13, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={stage10BuildingParams.has_mansard}
                  onChange={(event) => updateStage10BuildingParam("has_mansard", event.target.checked)}
                />
                <span>Мансарда</span>
              </label>
              <label style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                <span style={{ fontWeight: 600 }}>Этажность</span>
                <input
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  value={stage10BuildingParams.floors_count}
                  onChange={(event) => {
                    const next = Math.max(1, Math.min(100, Number.parseInt(event.target.value, 10) || 1));
                    updateStage10BuildingParam("floors_count", next);
                  }}
                  style={{ width: 86, padding: "8px 9px", border: "1px solid var(--border2)", borderRadius: 6, fontSize: 13 }}
                />
              </label>
            </div>

            {stage10RadioGroups.length > 0 && (
              <section style={{ display: "grid", gap: 12 }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>Ветвления работ</div>
                  <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
                    Для каждого этапа с вариантами выберите один способ выполнения.
                  </div>
                </div>
                {stage10RadioGroups.map((stage) => {
                  const stageId = String(stage.canonical_stage_id || "").trim();
                  const selectedOption = stage10SelectedOptions[stageId] || "";
                  return (
                    <section key={stageId} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 12 }}>
                      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10 }}>
                        {stage.number}. {stage.title}
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                        {stage.stage_options
                          .filter((option) => String(option.id || "").trim())
                          .map((option) => {
                            const optionId = String(option.id || "").trim();
                            const checked = selectedOption === optionId;
                            return (
                              <label
                                key={optionId}
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
                                  type="radio"
                                  name={`stage10-option-${stageId}`}
                                  checked={checked}
                                  disabled={stage10OptionsSaving || confirming}
                                  onChange={() => void selectStage10Option(stageId, optionId)}
                                />
                                <span>{option.title}</span>
                              </label>
                            );
                          })}
                      </div>
                      {!selectedOption && (
                        <div style={{ marginTop: 8, fontSize: 12, color: "var(--red)" }}>
                          Выберите один вариант.
                        </div>
                      )}
                    </section>
                  );
                })}
              </section>
            )}
          </div>
        </div>
      )}

      {activeClarification && selectedEstimateType && !clarificationsConfirmed && !activeStatus && (
        <div style={{ marginBottom: 20, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700 }}>{activeClarification.title}</div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
                Отмечено вопросов: {answeredCount} из {questionsCount}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setClarificationsConfirmed(true)}
              style={{
                padding: "9px 14px",
                background: "var(--blue-dark)",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                whiteSpace: "nowrap",
              }}
            >
              Свернуть уточнения
            </button>
          </div>

          <div style={{ display: "grid", gap: 16, padding: 16 }}>
            {activeClarification.sections.map((section) => (
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

      {activeClarification && selectedEstimateType && clarificationsConfirmed && !activeStatus && (
        <div style={{ marginBottom: 20, padding: "12px 14px", borderRadius: 8, border: "1px solid rgba(34,197,94,.25)", background: "rgba(34,197,94,.06)", display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
          <div style={{ fontSize: 12, color: "#166534" }}>
            Уточнения отмечены: {answeredCount} из {questionsCount}. Загрузка сметы доступна внизу.
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

      {!activeStatus && !mappingPayload && !preview && (
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text)", cursor: "pointer" }}>
            <input type="checkbox" checked={buildGantt} onChange={(e) => setBuildGantt(e.target.checked)} />
            Построить Гант после импорта
          </label>
        </div>
      )}

      {!activeStatus && !mappingPayload && !preview && (
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
            onChange={(e) => {
              handleDrop(e.target.files);
              e.currentTarget.value = "";
            }}
          />
          <div style={{ fontSize: 36, marginBottom: 10 }}>{file ? "📊" : canUpload ? "⬆" : "🔒"}</div>
          <div style={{ fontSize: 15, fontWeight: 500, marginBottom: 6 }}>
            {file ? file.name : canUpload ? "Перетащите смету сюда" : uploadDisabledTitle}
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>
            {file
              ? `${(file.size / 1024).toFixed(1)} KB · нажмите для замены`
              : canUpload
                ? "Поддерживаются .xlsx, .xls, .pdf · ГрандСмета, CourtDoc, PDF-сметы"
                : uploadDisabledHint}
          </div>
        </div>
      )}

      {file && !activeStatus && canUpload && !mappingPayload && !preview && stage10ImportNotice && (
        <div
          style={{
            marginTop: 16,
            width: "100%",
            padding: "11px 14px",
            border: "1px solid rgba(59,130,246,.22)",
            borderRadius: 6,
            background: "rgba(59,130,246,.06)",
            color: "var(--blue-dark)",
            fontSize: 14,
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 10,
          }}
        >
          <span>{stage10ImportNotice}</span>
          <span
            aria-hidden="true"
            style={{
              width: 16,
              height: 16,
              border: "2px solid rgba(29,78,216,.25)",
              borderTopColor: "var(--blue-dark)",
              borderRadius: "50%",
              animation: "ktp-spin .8s linear infinite",
              flex: "0 0 auto",
            }}
          />
        </div>
      )}

      {file && !activeStatus && canUpload && !mappingPayload && !preview && !stage10ImportNotice && (
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
          {uploading ? "Распознаём..." : "→ Показать работы"}
        </button>
      )}

      {preview && !activeStatus && !mappingPayload && (
        <EditablePreviewPanel
          preview={preview}
          confirming={confirming}
          complexMode={complexMode}
          preserveEstimateStructure={preserveEstimateStructure}
          onPreserveEstimateStructureChange={setPreserveEstimateStructure}
          onConfirm={handleConfirmImport}
          onCancel={handleCancelPreview}
        />
      )}

      {mappingPayload && estimateKind && estimateTypeId && !activeStatus && (
        <div style={{ marginTop: 18, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "0 16px" }}>
          <ColumnMapper
            payload={mappingPayload}
            projectId={id}
            startDate={startDate}
            workers={workers}
            estimateKind={estimateKind}
            estimateTypeId={estimateTypeId}
            projectVariantId={projectVariantId}
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

      {(activeStatus === "pending" || activeStatus === "processing") && (
        <div style={{ marginTop: 16, padding: "14px 16px", background: "rgba(59,130,246,.06)", border: "1px solid rgba(59,130,246,.2)", borderRadius: 6 }}>
          <div style={{ fontSize: 13, color: "var(--blue-dark)", fontWeight: 500 }}>
            ⏳ {importProgressTitle}
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>{importProgressHint}</div>
        </div>
      )}

      {activeStatus === "done" && result && (
        <div style={{ marginTop: 16, padding: "16px", background: "rgba(34,197,94,.06)", border: "1px solid rgba(34,197,94,.2)", borderRadius: 6 }}>
          <div style={{ color: "#15803d", fontWeight: 600, fontSize: 14, marginBottom: 10 }}>✓ Смета успешно обработана</div>
          <div style={{ display: "flex", gap: 20, fontSize: 12, color: "var(--muted)", flexWrap: "wrap" }}>
            {[
              ["Блок", result.estimate_batch_name],
              ["Тип", formatEstimateKind(result.estimate_kind ?? estimateKind)],
              ["Подтип", result.project_variant_title ?? selectedProjectVariant?.title ?? "—"],
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
              {ktpLoading === "estimate" ? "Анализируем смету..." : "КТП по смете"}
            </button>
          </div>
        </div>
      )}

      {activeStatus === "failed" && (
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

function sourceParentLines(row: Pick<PreviewRow, "section" | "section_title" | "section_description" | "source_parent">) {
  const title = (row.source_parent?.title ?? row.section_title ?? "").trim();
  const description = (row.source_parent?.description ?? row.section_description ?? "").trim();
  const fallback = (row.section ?? "").trim();
  const lines = [title, description].filter((value, index, arr) => value && arr.indexOf(value) === index);
  return lines.length ? lines : fallback ? [fallback] : [];
}

function EditablePreviewPanel({
  preview,
  confirming,
  complexMode,
  preserveEstimateStructure,
  onPreserveEstimateStructureChange,
  onConfirm,
  onCancel,
}: {
  preview: PreviewResult;
  confirming: boolean;
  complexMode: boolean;
  preserveEstimateStructure: boolean;
  onPreserveEstimateStructureChange: (value: boolean) => void;
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
              {["Тип", "Наименование", "Раздел", "Ед.", "Кол-во", "Сумма"].map((h) => (
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
                    <td style={{ padding: "6px 8px" }}>
                      {r.name}
                    </td>
                    <td style={{ padding: "6px 8px", color: "var(--muted)" }}>
                      {sourceParentLines(r).map((line) => (
                        <div key={line} style={{ marginTop: 2, color: "var(--muted)", fontSize: 11, lineHeight: 1.35 }}>
                          ↳ {line}
                        </div>
                      ))}
                      {sourceParentLines(r).length === 0 ? "—" : null}
                    </td>
                    <td style={{ padding: "6px 8px", color: "var(--muted)" }}>{r.unit ?? "—"}</td>
                    <td style={{ padding: "6px 8px", fontFamily: "var(--mono)" }}>{r.quantity ?? "—"}</td>
                    <td style={{ padding: "6px 8px", fontFamily: "var(--mono)" }}>{r.total_price != null ? fmtMoney(r.total_price) : "—"}</td>
                  </tr>
                  {(r.materials ?? []).map((m, j) => (
                    <tr key={`m${r.index}-${j}`} style={{ borderTop: "1px dashed var(--border)", background: "rgba(22,163,74,.04)" }}>
                      <td style={{ padding: "4px 8px", color: ITEM_TYPE_COLORS.material, fontSize: 11 }}>└ материал</td>
                      <td style={{ padding: "4px 8px", color: "var(--muted)" }}>{m.name}</td>
                      <td style={{ padding: "4px 8px" }} />
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
                <td style={{ padding: "4px 8px" }}>
                  <input value={a.name} onChange={(e) => updateAdded(i, { name: e.target.value })} placeholder="наименование"
                    style={{ width: "100%", minWidth: 160, fontSize: 12, padding: "3px 6px", border: "1px solid var(--border2)", borderRadius: 4 }} />
                </td>
                <td style={{ padding: "4px 8px" }}>
                  <input value={a.section ?? ""} onChange={(e) => updateAdded(i, { section: e.target.value })} placeholder="раздел"
                    style={{ width: 140, fontSize: 12, padding: "3px 6px", border: "1px solid var(--border2)", borderRadius: 4 }} />
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

      <label style={{ marginTop: 12, display: "flex", alignItems: "flex-start", gap: 8, fontSize: 12, color: "var(--text)", cursor: confirming ? "default" : "pointer" }}>
        <input
          type="checkbox"
          checked={preserveEstimateStructure}
          disabled={confirming}
          onChange={(e) => onPreserveEstimateStructureChange(e.target.checked)}
          style={{ marginTop: 2 }}
        />
        <span>
          <b>Оставить структуру сметы</b>
          <span style={{ display: "block", color: "var(--muted)", marginTop: 2 }}>
            Если выключено, шаг «Структура работ» будет сгруппирован по этапам JSON v6.
          </span>
        </span>
      </label>

      <div style={{ marginTop: 14, display: "flex", gap: 10, alignItems: "center" }}>
        <button
          onClick={() => onConfirm(buildEdits())}
          disabled={confirming}
          style={{ flex: 1, padding: "11px", background: "var(--blue-dark)", color: "#fff", border: "none", borderRadius: 6, fontSize: 14, fontWeight: 600, cursor: "pointer", opacity: confirming ? 0.7 : 1 }}
        >
          {confirming ? "Создаём задачу импорта..." : complexMode ? "→ Подтвердить типы и добавить в комплекс" : "→ Подтвердить типы и импортировать"}
        </button>
        <button
          onClick={onCancel}
          disabled={confirming}
          style={{ padding: "11px 16px", background: "var(--surface)", color: "var(--muted)", border: "1px solid var(--border2)", borderRadius: 6, fontSize: 14, cursor: "pointer" }}
        >
          Отмена
        </button>
      </div>
      {confirming && (
        <div style={{ marginTop: 8, fontSize: 11, color: "var(--muted)" }}>
          Ничего нажимать не нужно. После создания задачи появится статус обработки.
        </div>
      )}
      {changedCount > 0 && (
        <div style={{ marginTop: 8, fontSize: 11, color: "var(--muted)" }}>Правок к применению: {changedCount}</div>
      )}
    </div>
  );
}
