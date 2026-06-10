"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "next/navigation";

import { workTaxonomy } from "@/lib/api";
import type { WorkTaxonomySection, WorkTaxonomySubtype } from "@/lib/types";

const COLORS = {
  border: "#e2e8f0",
  bg: "#f8fafc",
  text: "#0f172a",
  muted: "#64748b",
  primary: "#0284c7",
  primaryBg: "#0284c715",
};

const LABEL_HINTS = {
  legacy: "Старый код из прежнего CSV/ФЕР-справочника. Нужен для сопоставления со старыми сметами и привычными кодами оператора.",
  strong: "Сильные термины: прямые признаки подтипа. При совпадении дают основной вес классификатору.",
  weak: "Слабые термины: вспомогательные признаки. Они уточняют классификацию, но сами по себе слабее сильных терминов.",
  pairs: "Пары действий: связки действие + объект, например монтаж + перегородка. Нужны для более точного выбора подтипа.",
};

const SECTION_TERM_LABELS: Record<string, string> = {
  strong_terms: "strong",
  action_terms: "action",
  object_terms: "object",
  material_terms: "material",
  weak_terms: "weak",
  document_terms: "document",
  unit_hints: "unit",
  negative_terms: "negative",
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

function pairToText(pair: string[] | undefined) {
  return (pair || []).filter(Boolean).join(" + ");
}

function TermGroup({ label, terms, title }: { label: string; terms: string[]; title?: string }) {
  const cleanTerms = terms.filter(Boolean);
  if (!cleanTerms.length) return null;

  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 6, flexWrap: "wrap" }}>
      <span title={title} style={{ minWidth: 58, paddingTop: 3, color: COLORS.muted, fontSize: 11, fontWeight: 650 }}>
        {label}
      </span>
      <span style={{ display: "flex", flexWrap: "wrap", gap: 4, minWidth: 0, flex: 1 }}>
        {cleanTerms.map((term, index) => (
          <span
            key={`${label}-${term}-${index}`}
            style={{
              padding: "2px 6px",
              borderRadius: 5,
              background: "#f1f5f9",
              color: COLORS.text,
              fontSize: 11,
              lineHeight: 1.25,
            }}
          >
            {term}
          </span>
        ))}
      </span>
    </div>
  );
}

export default function WorkTaxonomyPanel() {
  const searchParams = useSearchParams();
  const urlSection = searchParams.get("section");
  const urlSearch = searchParams.get("q") ?? "";
  const [sections, setSections] = useState<WorkTaxonomySection[]>([]);
  const [subtypes, setSubtypes] = useState<WorkTaxonomySubtype[]>([]);
  const [selectedSection, setSelectedSection] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    workTaxonomy
      .sections()
      .then((data) => {
        setSections(data);
        const urlSectionExists = urlSection && data.some((section) => section.section_code === urlSection);
        setSelectedSection(urlSectionExists ? urlSection : data[0]?.section_code ?? null);
      })
      .finally(() => setLoading(false));
  }, [urlSection]);

  useEffect(() => {
    setSearch(urlSearch);
  }, [urlSearch]);

  const reloadSubtypes = useCallback(() => {
    workTaxonomy
      .subtypes({
        section_code: selectedSection ?? undefined,
        q: search.trim() || undefined,
      })
      .then(setSubtypes)
      .catch((err) => console.error("Work taxonomy load failed", err));
  }, [selectedSection, search]);

  useEffect(() => {
    const t = setTimeout(reloadSubtypes, 180);
    return () => clearTimeout(t);
  }, [reloadSubtypes]);

  const totalSubtypes = useMemo(
    () => sections.reduce((sum, section) => sum + section.subtypes_count, 0),
    [sections],
  );

  if (loading) {
    return <div style={{ padding: 24, color: COLORS.muted }}>Загрузка справочника…</div>;
  }

  return (
    <div style={{ minHeight: "calc(100vh - 104px)", color: COLORS.text, fontFamily: "system-ui, sans-serif" }}>
      <div style={{ padding: "14px 16px", borderBottom: `1px solid ${COLORS.border}`, background: "white" }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>Справочник работ</h2>
        <div style={{ marginTop: 4, color: COLORS.muted, fontSize: 12 }}>
          {sections.length} секций · {totalSubtypes} подтипов · JSON v4
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "300px minmax(0, 1fr)", minHeight: "calc(100vh - 164px)" }}>
        <aside style={{ borderRight: `1px solid ${COLORS.border}`, background: "white", padding: 10 }}>
          {sections.map((section) => (
            <button
              key={section.section_code}
              type="button"
              onClick={() => setSelectedSection(section.section_code)}
              title={section.scope ?? ""}
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
                background: selectedSection === section.section_code ? COLORS.primaryBg : "transparent",
                color: selectedSection === section.section_code ? COLORS.primary : COLORS.text,
              }}
            >
              <span style={{ minWidth: 0 }}>
                <span style={{ display: "flex", alignItems: "flex-start", gap: 7, minWidth: 0 }}>
                  {section.taxonomy_code ? <Code>{section.taxonomy_code}</Code> : null}
                  <span style={{ display: "block", fontSize: 13, lineHeight: 1.25, whiteSpace: "normal", overflowWrap: "anywhere" }}>
                    {section.section_name}
                  </span>
                </span>
              </span>
              <span style={{ color: COLORS.muted, fontSize: 12 }}>{section.subtypes_count}</span>
            </button>
          ))}
        </aside>

        <main style={{ padding: 16, overflow: "auto" }}>
          <input
            type="search"
            placeholder="Поиск по названию, ID или старому коду"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            style={{
              width: "100%",
              maxWidth: 560,
              padding: "9px 11px",
              border: `1px solid ${COLORS.border}`,
              borderRadius: 6,
              fontSize: 13,
              marginBottom: 12,
            }}
          />

          <div style={{ display: "grid", gap: 8 }}>
            {subtypes.map((subtype) => (
              <article
                key={subtype.work_subtype_code}
                style={{
                  border: `1px solid ${COLORS.border}`,
                  borderRadius: 6,
                  background: "white",
                  padding: 12,
                  display: "grid",
                  gap: 8,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
                      {subtype.taxonomy_code ? <Code>{subtype.taxonomy_code}</Code> : null}
                      <span style={{ minWidth: 0, fontSize: 14, fontWeight: 650 }}>{subtype.work_subtype_name}</span>
                    </div>
                  </div>
                </div>

                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {subtype.legacy_csv_codes
                    .map((code) => (
                      <Chip key={code} title={LABEL_HINTS.legacy}>legacy {code}</Chip>
                    ))}
                  <Chip title={LABEL_HINTS.strong}>strong {subtype.term_summary.strong_terms}</Chip>
                  <Chip title={LABEL_HINTS.weak}>weak {subtype.term_summary.weak_terms}</Chip>
                  <Chip title={LABEL_HINTS.pairs}>pairs {subtype.term_summary.action_object_pairs}</Chip>
                </div>

                <div style={{ display: "grid", gap: 7 }}>
                  <div style={{ color: COLORS.muted, fontSize: 12, fontWeight: 650 }}>Слова первичного типа</div>
                  {Object.entries(SECTION_TERM_LABELS).map(([key, label]) => (
                    <TermGroup
                      key={key}
                      label={label}
                      terms={subtype.terms_json?.section?.[key as keyof NonNullable<WorkTaxonomySubtype["terms_json"]>["section"]] ?? []}
                      title={key === "negative_terms" ? "Отрицательные признаки: снижают вероятность выбора этого первичного типа." : undefined}
                    />
                  ))}
                </div>

                <div style={{ display: "grid", gap: 7 }}>
                  <div style={{ color: COLORS.muted, fontSize: 12, fontWeight: 650 }}>Слова подтипа</div>
                  <TermGroup label="strong" terms={subtype.terms_json?.subtype?.strong_terms ?? []} title={LABEL_HINTS.strong} />
                  <TermGroup label="weak" terms={subtype.terms_json?.subtype?.weak_terms ?? []} title={LABEL_HINTS.weak} />
                  <TermGroup
                    label="pairs"
                    terms={(subtype.terms_json?.subtype?.action_object_pairs ?? []).map(pairToText)}
                    title={LABEL_HINTS.pairs}
                  />
                </div>
              </article>
            ))}
            {!subtypes.length ? (
              <div style={{ color: COLORS.muted, padding: 18 }}>Подтипы не найдены.</div>
            ) : null}
          </div>
        </main>
      </div>
    </div>
  );
}
