"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

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

function Code({ children }: { children: string }) {
  return (
    <code style={{ fontSize: 11, color: COLORS.muted, fontFamily: "var(--mono, monospace)" }}>
      {children}
    </code>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span
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

export default function WorkTaxonomyPanel() {
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
        setSelectedSection(data[0]?.section_code ?? null);
      })
      .finally(() => setLoading(false));
  }, []);

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
          {sections.length} секций · {totalSubtypes} подтипов · JSON v3
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
                alignItems: "center",
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
                <Code>{section.section_code}</Code>
                <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 13 }}>
                  {section.section_name}
                </span>
              </span>
              <span style={{ color: COLORS.muted, fontSize: 12 }}>{section.subtypes_count}</span>
            </button>
          ))}
        </aside>

        <main style={{ padding: 16, overflow: "auto" }}>
          <input
            type="search"
            placeholder="Поиск по подтипу, canonical code или legacy-коду"
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
                    <div style={{ fontSize: 14, fontWeight: 650 }}>{subtype.work_subtype_name}</div>
                    <Code>{subtype.work_subtype_code}</Code>
                  </div>
                  {subtype.display_code ? <Chip>{subtype.display_code}</Chip> : null}
                </div>

                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {subtype.legacy_csv_codes.map((code) => (
                    <Chip key={code}>legacy {code}</Chip>
                  ))}
                  <Chip>strong {subtype.term_summary.strong_terms}</Chip>
                  <Chip>weak {subtype.term_summary.weak_terms}</Chip>
                  <Chip>pairs {subtype.term_summary.action_object_pairs}</Chip>
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
