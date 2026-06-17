"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "next/navigation";

import { workTaxonomy } from "@/lib/api";
import type { WorkEstimateType, WorkProjectHierarchy, WorkProjectVariant, WorkStage } from "@/lib/types";

const COLORS = {
  border: "#e2e8f0",
  bg: "#f8fafc",
  text: "#0f172a",
  muted: "#64748b",
  primary: "#0284c7",
  primaryBg: "#0284c715",
};

function Code({ children }: { children: string }) {
  return (
    <code
      style={{
        display: "inline-flex",
        alignItems: "center",
        flex: "0 0 auto",
        minWidth: 34,
        padding: "2px 6px",
        borderRadius: 5,
        border: `1px solid ${COLORS.border}`,
        background: COLORS.bg,
        fontSize: 11,
        lineHeight: 1.2,
        color: COLORS.muted,
        fontFamily: "var(--mono, monospace)",
      }}
    >
      {children}
    </code>
  );
}

function Chip({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 7px",
        borderRadius: 6,
        border: `1px solid ${COLORS.border}`,
        background: COLORS.bg,
        color: COLORS.muted,
        fontSize: 11,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

function formatDictionaryVersion(version: string | null | undefined) {
  if (!version) return "JSON v6.3.3";
  const match = version.match(/v(\d+(?:_\d+)*)/);
  if (!match) return version;
  return `JSON v${match[1].replaceAll("_", ".")}`;
}

function stageSearchText(stage: WorkStage) {
  return [
    stage.id,
    stage.number,
    stage.title,
    stage.stage_role,
    stage.section_id,
    stage.subtype_id,
    stage.primary_work_type,
    ...(stage.related_work_types ?? []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function optionTitle(number: string, title: string) {
  return number ? `${number}. ${title}` : title;
}

export default function WorkTaxonomyPanel() {
  const searchParams = useSearchParams();
  const urlSearch = searchParams.get("q") ?? "";
  const [hierarchy, setHierarchy] = useState<WorkProjectHierarchy | null>(null);
  const [selectedTypeId, setSelectedTypeId] = useState<string | null>(null);
  const [selectedVariantId, setSelectedVariantId] = useState<string | null>(null);
  const [search, setSearch] = useState(urlSearch);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSearch(urlSearch);
  }, [urlSearch]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    workTaxonomy
      .projectHierarchy({ include_stages: true })
      .then((data) => {
        if (cancelled) return;
        setHierarchy(data);
        const firstType = data.estimate_types[0] ?? null;
        setSelectedTypeId((current) => current ?? firstType?.id ?? null);
        setSelectedVariantId((current) => current ?? firstType?.project_variants[0]?.id ?? null);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || "Не удалось загрузить иерархию справочника");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const estimateTypes = hierarchy?.estimate_types ?? [];
  const selectedType = useMemo<WorkEstimateType | null>(
    () => estimateTypes.find((item) => item.id === selectedTypeId) ?? null,
    [estimateTypes, selectedTypeId],
  );
  const variants = selectedType?.project_variants ?? [];
  const selectedVariant = useMemo<WorkProjectVariant | null>(
    () => variants.find((item) => item.id === selectedVariantId) ?? null,
    [selectedVariantId, variants],
  );
  const stages = selectedVariant?.stages ?? [];
  const totalVariants = useMemo(
    () => estimateTypes.reduce((sum, type) => sum + type.project_variants.length, 0),
    [estimateTypes],
  );
  const totalStages = useMemo(
    () => estimateTypes.reduce(
      (sum, type) => sum + type.project_variants.reduce((variantSum, variant) => variantSum + variant.stages_count, 0),
      0,
    ),
    [estimateTypes],
  );
  const dictionaryLabel = formatDictionaryVersion(hierarchy?.dictionary_version);
  const filteredStages = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return stages;
    return stages.filter((stage) => stageSearchText(stage).includes(needle));
  }, [search, stages]);

  function selectType(type: WorkEstimateType) {
    setSelectedTypeId(type.id);
    setSelectedVariantId(type.project_variants[0]?.id ?? null);
  }

  if (loading) {
    return <div style={{ padding: 24, color: COLORS.muted }}>Загрузка справочника...</div>;
  }

  if (error) {
    return <div style={{ padding: 24, color: "#dc2626" }}>{error}</div>;
  }

  return (
    <div style={{ minHeight: "calc(100vh - 104px)", color: COLORS.text, fontFamily: "system-ui, sans-serif" }}>
      <div style={{ padding: "14px 16px", borderBottom: `1px solid ${COLORS.border}`, background: "white" }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>Справочник работ</h2>
        <div style={{ marginTop: 4, color: COLORS.muted, fontSize: 12 }}>
          {estimateTypes.length} типов · {totalVariants} вариантов · {totalStages} этапов · {dictionaryLabel}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "300px 360px minmax(0, 1fr)",
          minHeight: "calc(100vh - 164px)",
        }}
      >
        <aside style={{ borderRight: `1px solid ${COLORS.border}`, background: "white", padding: 10 }}>
          {estimateTypes.map((type) => (
            <button
              key={type.id}
              type="button"
              onClick={() => selectType(type)}
              style={{
                width: "100%",
                display: "grid",
                gridTemplateColumns: "minmax(0, 1fr) auto",
                gap: 8,
                alignItems: "start",
                textAlign: "left",
                padding: "8px 10px",
                marginBottom: 3,
                border: "none",
                borderRadius: 6,
                cursor: "pointer",
                background: selectedTypeId === type.id ? COLORS.primaryBg : "transparent",
                color: selectedTypeId === type.id ? COLORS.primary : COLORS.text,
              }}
            >
              <span style={{ minWidth: 0, display: "flex", alignItems: "flex-start", gap: 7 }}>
                <Code>{type.number}</Code>
                <span style={{ display: "block", fontSize: 13, lineHeight: 1.25, whiteSpace: "normal", overflowWrap: "anywhere" }}>
                  {type.title}
                </span>
              </span>
              <span style={{ color: COLORS.muted, fontSize: 12 }}>{type.project_variants.length}</span>
            </button>
          ))}
        </aside>

        <aside style={{ borderRight: `1px solid ${COLORS.border}`, background: "#fff", padding: 10 }}>
          <div style={{ padding: "6px 8px 10px", color: COLORS.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: ".06em" }}>
            Варианты объекта
          </div>
          {variants.map((variant) => (
            <button
              key={variant.id}
              type="button"
              onClick={() => setSelectedVariantId(variant.id)}
              title={variant.id}
              style={{
                width: "100%",
                display: "grid",
                gridTemplateColumns: "minmax(0, 1fr) auto",
                gap: 8,
                alignItems: "start",
                textAlign: "left",
                padding: "8px 10px",
                marginBottom: 3,
                border: "none",
                borderRadius: 6,
                cursor: "pointer",
                background: selectedVariantId === variant.id ? COLORS.primaryBg : "transparent",
                color: selectedVariantId === variant.id ? COLORS.primary : COLORS.text,
              }}
            >
              <span style={{ minWidth: 0, display: "flex", alignItems: "flex-start", gap: 7 }}>
                <Code>{variant.number}</Code>
                <span style={{ display: "block", fontSize: 13, lineHeight: 1.25, whiteSpace: "normal", overflowWrap: "anywhere" }}>
                  {variant.title}
                </span>
              </span>
              <span style={{ color: COLORS.muted, fontSize: 12 }}>{variant.stages_count}</span>
            </button>
          ))}
        </aside>

        <main style={{ padding: 16, overflow: "auto" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", marginBottom: 12 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
                {selectedVariant?.number ? <Code>{selectedVariant.number}</Code> : null}
                <h3 style={{ margin: 0, fontSize: 16, lineHeight: 1.25 }}>{selectedVariant?.title ?? "Вариант не выбран"}</h3>
              </div>
              <div style={{ color: COLORS.muted, fontSize: 12 }}>
                {selectedType ? optionTitle(selectedType.number, selectedType.title) : ""}
              </div>
            </div>
            <Chip>{filteredStages.length} из {stages.length} этапов</Chip>
          </div>

          <input
            type="search"
            placeholder="Поиск по этапам, section_id или subtype_id"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            style={{
              width: "100%",
              maxWidth: 620,
              padding: "9px 11px",
              border: `1px solid ${COLORS.border}`,
              borderRadius: 6,
              fontSize: 13,
              marginBottom: 12,
            }}
          />

          <div style={{ display: "grid", gap: 8 }}>
            {filteredStages.map((stage) => (
              <article
                key={stage.id}
                style={{
                  border: `1px solid ${COLORS.border}`,
                  borderRadius: 6,
                  background: "white",
                  padding: 12,
                  display: "grid",
                  gap: 8,
                }}
              >
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
                  <Code>{stage.number}</Code>
                  <span style={{ minWidth: 0, fontSize: 14, fontWeight: 650, lineHeight: 1.3 }}>{stage.title}</span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {stage.section_id ? <Chip>section {stage.section_id}</Chip> : null}
                  {stage.subtype_id ? <Chip>subtype {stage.subtype_id}</Chip> : null}
                  {stage.primary_work_type ? <Chip>primary {stage.primary_work_type}</Chip> : null}
                  {stage.stage_role ? <Chip>{stage.stage_role}</Chip> : null}
                  {stage.autofill_enabled ? <Chip>autofill</Chip> : null}
                </div>
                {stage.related_work_types.length ? (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                    {stage.related_work_types.map((workType) => (
                      <Chip key={workType}>related {workType}</Chip>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
            {!filteredStages.length ? (
              <div style={{ color: COLORS.muted, padding: 18 }}>Этапы не найдены.</div>
            ) : null}
          </div>
        </main>
      </div>
    </div>
  );
}
