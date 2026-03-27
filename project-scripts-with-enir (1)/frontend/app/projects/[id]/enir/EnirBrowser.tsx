"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { enir as enirApi } from "@/lib/api";

interface Collection {
  id: number;
  code: string;
  title: string;
  description: string | null;
  issue: string | null;
  issue_title: string | null;
  source_file: string | null;
  source_format: string | null;
  sort_order: number;
  paragraph_count: number;
}

interface StructureRef {
  id: number;
  source_id: string | null;
  title: string;
}

interface ParaShort {
  id: number;
  collection_id: number;
  source_paragraph_id: string | null;
  code: string;
  title: string;
  unit: string | null;
  html_anchor: string | null;
  section: StructureRef | null;
  chapter: StructureRef | null;
  structure_title: string | null;
  is_technical: boolean;
}

interface NormValue {
  value_type: string;
  value_text: string | null;
  value_numeric: number | null;
}

interface NormCell {
  column_id: number;
  column_key: string;
  sort_order: number;
  header: string;
  label: string | null;
  values: NormValue[];
}

interface NormColumn {
  id: number;
  column_key: string;
  sort_order: number;
  header: string;
  label: string | null;
}

interface NormRow {
  id: number;
  source_row_id: string;
  source_row_num: number | null;
  sort_order: number;
  params: Record<string, unknown> | null;
  cells: NormCell[];
}

interface NormTable {
  id: number;
  source_table_id: string;
  sort_order: number;
  title: string | null;
  row_count: number | null;
  columns: NormColumn[];
  rows: NormRow[];
}

interface NoteItem {
  num: number;
  text: string;
  coefficient: number | null;
  pr_code: string | null;
  conditions: Record<string, unknown> | null;
  formula: string | null;
}

interface SourceNoteItem {
  sort_order: number;
  text: string;
  code: string | null;
  coefficient: number | null;
  conditions: Record<string, unknown> | null;
  formula: string | null;
}

interface TechnicalCoefficient {
  id: number;
  code: string;
  description: string;
  multiplier: number | null;
  conditions: Record<string, unknown> | null;
  formula: string | null;
  sort_order: number;
  scope: "collection" | "section" | "chapter" | "paragraph" | "paragraph_list";
  section: StructureRef | null;
  chapter: StructureRef | null;
  paragraph: { id: number; code: string; title: string } | null;
  applicable_paragraphs: { id: number; code: string; title: string }[];
}

interface ParaFull extends ParaShort {
  collection: {
    id: number;
    code: string;
    title: string;
    description: string | null;
    issue: string | null;
    issue_title: string | null;
    source_file: string | null;
    source_format: string | null;
  };
  work_compositions: { condition: string | null; operations: string[] }[];
  crew: { profession: string; grade: number | null; count: number }[];
  norms: {
    row_num: number | null;
    work_type: string | null;
    condition: string | null;
    thickness_mm: number | null;
    column_label: string | null;
    norm_time: number | null;
    price_rub: number | null;
  }[];
  notes: NoteItem[];
  technical_characteristics: { sort_order: number; raw_text: string }[];
  application_notes: { sort_order: number; text: string }[];
  refs: {
    sort_order: number;
    ref_type: string;
    link_text: string | null;
    href: string | null;
    abs_url: string | null;
    context_text: string | null;
    is_meganorm: boolean | null;
  }[];
  source_work_items: { sort_order: number; raw_text: string }[];
  source_crew_items: {
    sort_order: number;
    profession: string | null;
    grade: number | null;
    count: number | null;
    raw_text: string | null;
  }[];
  source_notes: SourceNoteItem[];
  norm_tables: NormTable[];
  technical_coefficients: TechnicalCoefficient[];
  has_legacy_norms: boolean;
  has_tabular_norms: boolean;
}

interface MultiplierHint {
  key: string;
  code: string;
  source: string;
  origin: string;
  explanation: string;
  multiplier: number | null;
  formula: string | null;
  conditions: Record<string, unknown> | null;
  text: string;
}

const TH: React.CSSProperties = {
  padding: "7px 10px",
  background: "#1e293b",
  color: "#94a3b8",
  fontSize: 10,
  fontFamily: "var(--mono)",
  textTransform: "uppercase",
  letterSpacing: ".05em",
  whiteSpace: "nowrap",
  borderRight: "1px solid #334155",
  fontWeight: 400,
};

const TD: React.CSSProperties = {
  padding: "6px 10px",
  fontSize: 12,
  borderBottom: "1px solid var(--border)",
  borderRight: "1px solid var(--border)",
  verticalAlign: "top",
};

const PANEL: React.CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 6,
};

const BADGE: React.CSSProperties = {
  fontSize: 10,
  color: "var(--muted)",
  border: "1px solid var(--border)",
  padding: "2px 6px",
  borderRadius: 999,
  background: "var(--bg)",
};

function formatJson(value: Record<string, unknown> | null | undefined) {
  if (!value || Object.keys(value).length === 0) return null;
  return JSON.stringify(value, null, 2);
}

function formatValue(value: NormValue) {
  if (value.value_text) return value.value_text;
  if (value.value_numeric != null) return String(value.value_numeric);
  return "—";
}

function typeLabel(valueType: string) {
  if (valueType === "n_vr") return "Н.вр.";
  if (valueType === "rate") return "Расц.";
  return valueType;
}

function scopeLabel(scope: TechnicalCoefficient["scope"]) {
  if (scope === "collection") return "весь сборник";
  if (scope === "section") return "раздел";
  if (scope === "chapter") return "глава";
  if (scope === "paragraph") return "параграф";
  return "список параграфов";
}

function technicalCoefficientOrigin(detail: ParaFull, item: TechnicalCoefficient) {
  if (item.scope === "collection") {
    return `Техническая часть сборника ${detail.collection.code}`;
  }
  if (item.scope === "section") {
    return `Техническая часть раздела ${item.section?.source_id ?? "?"} ${item.section?.title ?? ""}`.trim();
  }
  if (item.scope === "chapter") {
    return `Техническая часть главы ${item.chapter?.source_id ?? "?"} ${item.chapter?.title ?? ""}`.trim();
  }
  if (item.scope === "paragraph" && item.paragraph) {
    return `Техническая часть параграфа ${item.paragraph.code}`;
  }
  if (item.scope === "paragraph_list") {
    return `Техническая часть для набора параграфов ${item.applicable_paragraphs.map((paragraph) => paragraph.code).join(", ")}`;
  }
  return "Техническая часть";
}

function technicalCoefficientExplanation(item: TechnicalCoefficient) {
  if (item.scope === "collection") {
    return "Коэффициент действует на весь сборник и попадает в этот параграф по принадлежности к сборнику.";
  }
  if (item.scope === "section") {
    return "Коэффициент действует на весь раздел, поэтому применим ко всем его параграфам.";
  }
  if (item.scope === "chapter") {
    return "Коэффициент действует на всю главу, поэтому применим ко всем её параграфам.";
  }
  if (item.scope === "paragraph") {
    return "Коэффициент привязан напрямую к этому параграфу.";
  }
  return "Коэффициент привязан к списку параграфов, в который входит текущий параграф.";
}

function isTextColumn(column: NormColumn) {
  const hay = `${column.column_key} ${column.header} ${column.label ?? ""}`.toLowerCase();
  return [
    "work",
    "вид",
    "тип",
    "condition",
    "услов",
    "name",
    "наимен",
    "description",
  ].some((part) => hay.includes(part));
}

function cellForColumn(row: NormRow, columnKey: string) {
  return row.cells.find((cell) => cell.column_key === columnKey) ?? null;
}

function valuePreview(cell: NormCell | null) {
  if (!cell || cell.values.length === 0) return "";
  if (cell.values.length === 1) return formatValue(cell.values[0]);
  return cell.values.map((value) => formatValue(value)).join(" / ");
}

function CellView({ cell, alignRight }: { cell: NormCell | null; alignRight: boolean }) {
  if (!cell || cell.values.length === 0) {
    return <span style={{ color: "var(--muted)" }}>—</span>;
  }
  if (cell.values.length === 1) {
    return <span>{formatValue(cell.values[0])}</span>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: alignRight ? "flex-end" : "flex-start" }}>
      {cell.values.map((value, index) => (
        <div key={`${value.value_type}-${index}`} style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
          <span style={{ fontSize: 9, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".04em" }}>
            {typeLabel(value.value_type)}
          </span>
          <span>{formatValue(value)}</span>
        </div>
      ))}
    </div>
  );
}

function MetaJson({ title, value }: { title: string; value: Record<string, unknown> | null | undefined }) {
  const text = formatJson(value);
  if (!text) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".06em" }}>
        {title}
      </div>
      <pre
        style={{
          margin: 0,
          padding: "8px 10px",
          borderRadius: 6,
          background: "var(--bg)",
          border: "1px solid var(--border)",
          fontSize: 11,
          lineHeight: 1.45,
          overflowX: "auto",
          fontFamily: "var(--mono)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {text}
      </pre>
    </div>
  );
}

function collectMultiplierHints(detail: ParaFull): MultiplierHint[] {
  const technical = detail.technical_coefficients.map((item) => ({
    key: `tc-${item.id}`,
    code: item.code,
    source: `ТЧ · ${scopeLabel(item.scope)}`,
    origin: technicalCoefficientOrigin(detail, item),
    explanation: technicalCoefficientExplanation(item),
    multiplier: item.multiplier,
    formula: item.formula,
    conditions: item.conditions,
    text: item.description,
  }));

  const notes = detail.notes
    .filter((item) => item.coefficient != null || item.formula || item.conditions)
    .map((item) => ({
      key: `note-${item.num}`,
      code: item.pr_code ?? `ПР-${item.num}`,
      source: "Примечание параграфа",
      origin: `Примечание ${item.num} параграфа ${detail.code}`,
      explanation: "Множитель взят из нормализованного примечания этого параграфа.",
      multiplier: item.coefficient,
      formula: item.formula,
      conditions: item.conditions,
      text: item.text,
    }));

  const sourceNotes = detail.source_notes
    .filter((item) => item.coefficient != null || item.formula || item.conditions)
    .map((item) => ({
      key: `source-note-${item.sort_order}`,
      code: item.code ?? `SRC-${item.sort_order}`,
      source: "Source note",
      origin: `Исходное примечание ${item.sort_order} параграфа ${detail.code}`,
      explanation: "Множитель взят из исходного текста примечаний, сохранённого рядом с нормализованным слоем.",
      multiplier: item.coefficient,
      formula: item.formula,
      conditions: item.conditions,
      text: item.text,
    }));

  return [...technical, ...notes, ...sourceNotes];
}

function HoverCard({
  label,
  count,
  items,
}: {
  label: string;
  count: number;
  items: MultiplierHint[];
}) {
  return (
    <div style={{ position: "relative", display: "inline-flex" }} className="enir-hover-card">
      <span
        style={{
          ...BADGE,
          cursor: "help",
          fontFamily: "var(--mono)",
          background: "rgba(59,130,246,.08)",
          borderColor: "rgba(59,130,246,.2)",
          color: "var(--blue-dark)",
        }}
      >
        {label}: {count}
      </span>
      <div
        style={{
          position: "absolute",
          left: 0,
          top: "calc(100% + 8px)",
          width: 420,
          maxWidth: "min(420px, calc(100vw - 48px))",
          background: "#0f172a",
          color: "#e2e8f0",
          border: "1px solid #334155",
          borderRadius: 8,
          padding: "10px 12px",
          boxShadow: "0 16px 40px rgba(15,23,42,.35)",
          zIndex: 20,
          opacity: 0,
          pointerEvents: "none",
          transform: "translateY(4px)",
          transition: "opacity .15s ease, transform .15s ease",
        }}
        className="enir-hover-card__popup"
      >
        <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".08em", color: "#94a3b8", marginBottom: 8 }}>
          Множители для состава работ
        </div>
        <div style={{ display: "grid", gap: 8, maxHeight: 320, overflowY: "auto" }}>
          {items.length === 0 && (
            <div style={{ fontSize: 12, color: "#cbd5e1", lineHeight: 1.5 }}>
              По текущему контексту расчёта активных множителей не найдено.
            </div>
          )}
          {items.map((item) => (
            <div
              key={item.key}
              style={{
                border: "1px solid #334155",
                borderRadius: 6,
                padding: "8px 9px",
                background: "rgba(15,23,42,.65)",
                display: "grid",
                gap: 6,
              }}
            >
              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                <span
                  style={{
                    fontFamily: "var(--mono)",
                    fontWeight: 700,
                    color: "#93c5fd",
                    background: "rgba(59,130,246,.12)",
                    padding: "2px 6px",
                    borderRadius: 4,
                  }}
                >
                  {item.code}
                </span>
                <span style={{ fontSize: 10, color: "#94a3b8" }}>{item.source}</span>
                {item.multiplier != null && (
                  <span style={{ fontFamily: "var(--mono)", color: "#fcd34d" }}>×{item.multiplier}</span>
                )}
              </div>
              <div style={{ fontSize: 10, color: "#94a3b8" }}>
                Откуда: {item.origin}
              </div>
              <div style={{ fontSize: 12, lineHeight: 1.45 }}>{item.text}</div>
              <div style={{ fontSize: 11, lineHeight: 1.45, color: "#cbd5e1" }}>
                Почему показан: {item.explanation}
              </div>
              {item.formula && (
                <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "#cbd5e1" }}>
                  formula: {item.formula}
                </div>
              )}
              {item.conditions && Object.keys(item.conditions).length > 0 && (
                <pre
                  style={{
                    margin: 0,
                    fontFamily: "var(--mono)",
                    fontSize: 10,
                    lineHeight: 1.4,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    color: "#cbd5e1",
                  }}
                >
                  {JSON.stringify(item.conditions, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function EnirBrowser() {
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionsLoad, setCollectionsLoad] = useState(true);
  const [activeCollection, setActiveCollection] = useState<Collection | null>(null);
  const [paragraphs, setParagraphs] = useState<ParaShort[]>([]);
  const [parasLoad, setParasLoad] = useState(false);
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<ParaFull | null>(null);
  const [detailLoad, setDetailLoad] = useState(false);
  const [globalSearch, setGlobalSearch] = useState("");
  const [globalResults, setGlobalResults] = useState<ParaShort[]>([]);
  const [globalSearchActive, setGlobalSearchActive] = useState(false);
  const debRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const globalDebRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadParagraphs = useCallback((collectionId: number, q?: string) => {
    setParasLoad(true);
    enirApi
      .paragraphs(collectionId, q)
      .then(setParagraphs)
      .finally(() => setParasLoad(false));
  }, []);

  useEffect(() => {
    enirApi
      .collections()
      .then((data) => {
        setCollections(data);
        if (data.length === 1) {
          setActiveCollection(data[0]);
          loadParagraphs(data[0].id);
        }
      })
      .finally(() => setCollectionsLoad(false));
  }, [loadParagraphs]);

  function selectCollection(coll: Collection) {
    setActiveCollection(coll);
    setDetail(null);
    setSearch("");
    setGlobalSearch("");
    setGlobalSearchActive(false);
    setGlobalResults([]);
    loadParagraphs(coll.id);
  }

  const handleSearch = useCallback(
    (value: string) => {
      setSearch(value);
      if (!activeCollection) return;
      if (debRef.current) clearTimeout(debRef.current);
      debRef.current = setTimeout(() => loadParagraphs(activeCollection.id, value || undefined), 300);
    },
    [activeCollection, loadParagraphs],
  );

  const handleGlobalSearch = useCallback((value: string) => {
    setGlobalSearch(value);
    if (globalDebRef.current) clearTimeout(globalDebRef.current);
    if (!value.trim()) {
      setGlobalSearchActive(false);
      setGlobalResults([]);
      return;
    }
    setGlobalSearchActive(true);
    globalDebRef.current = setTimeout(() => {
      enirApi.search(value).then(setGlobalResults);
    }, 300);
  }, []);

  function openParagraph(p: ParaShort) {
    setDetailLoad(true);
    setDetail(null);
    if (globalSearchActive) {
      const coll = collections.find((item) => item.id === p.collection_id) ?? null;
      if (coll) {
        setActiveCollection(coll);
        loadParagraphs(coll.id);
      }
    }
    enirApi
      .paragraph(p.id)
      .then(setDetail)
      .finally(() => setDetailLoad(false));
  }

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      <div
        style={{
          width: 340,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          borderRight: "1px solid var(--border)",
          background: "var(--hdr2)",
        }}
      >
        <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--border)" }}>
          <input
            value={globalSearch}
            onChange={(e) => handleGlobalSearch(e.target.value)}
            placeholder="Поиск по коду, названию, составу работ…"
            style={{
              width: "100%",
              boxSizing: "border-box",
              background: "var(--bg)",
              border: "1px solid var(--border)",
              borderRadius: 4,
              padding: "6px 10px",
              fontSize: 12,
              color: "var(--fg)",
              outline: "none",
            }}
          />
        </div>
        {globalSearchActive ? (
          <div style={{ flex: 1, overflowY: "auto" }}>
            <div
              style={{
                padding: "6px 12px",
                fontSize: 10,
                color: "var(--muted)",
                textTransform: "uppercase",
                letterSpacing: ".06em",
                borderBottom: "1px solid var(--border)",
                background: "rgba(59,130,246,.05)",
              }}
            >
              Результаты ({globalResults.length})
            </div>
            {globalResults.length === 0 ? (
              <div style={{ padding: 16, color: "var(--muted)", fontSize: 12, textAlign: "center" }}>
                Ничего не найдено
              </div>
            ) : (
              globalResults.map((paragraph) => (
                <ParaRow
                  key={paragraph.id}
                  para={paragraph}
                  isActive={detail?.id === paragraph.id}
                  collectionCode={collections.find((item) => item.id === paragraph.collection_id)?.code}
                  onClick={() => openParagraph(paragraph)}
                />
              ))
            )}
          </div>
        ) : (
          <>
            {!collectionsLoad && collections.length > 1 && (
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 4,
                  padding: "8px 12px",
                  borderBottom: "1px solid var(--border)",
                  background: "var(--bg)",
                }}
              >
                {collections.map((collection) => (
                  <button
                    key={collection.id}
                    onClick={() => selectCollection(collection)}
                    title={collection.title}
                    style={{
                      padding: "3px 8px",
                      border: "1px solid var(--border)",
                      borderRadius: 4,
                      fontSize: 11,
                      cursor: "pointer",
                      background: activeCollection?.id === collection.id ? "var(--blue)" : "transparent",
                      color: activeCollection?.id === collection.id ? "#fff" : "var(--muted)",
                      fontFamily: "var(--mono)",
                      fontWeight: 600,
                    }}
                  >
                    {collection.code}
                    <span style={{ fontSize: 9, opacity: 0.7, marginLeft: 4 }}>{collection.paragraph_count}</span>
                  </button>
                ))}
              </div>
            )}
            {activeCollection && (
              <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)" }}>
                <input
                  value={search}
                  onChange={(e) => handleSearch(e.target.value)}
                  placeholder={`Фильтр в ${activeCollection.code}: код, название, состав работ…`}
                  style={{
                    width: "100%",
                    boxSizing: "border-box",
                    background: "var(--bg)",
                    border: "1px solid var(--border)",
                    borderRadius: 4,
                    padding: "5px 9px",
                    fontSize: 12,
                    color: "var(--fg)",
                    outline: "none",
                  }}
                />
              </div>
            )}
            <div style={{ flex: 1, overflowY: "auto" }}>
              {collectionsLoad ? (
                <div style={{ padding: 20, color: "var(--muted)", fontSize: 12, textAlign: "center" }}>
                  Загрузка…
                </div>
              ) : !activeCollection ? (
                collections.map((collection) => (
                  <button
                    key={collection.id}
                    onClick={() => selectCollection(collection)}
                    style={{
                      display: "block",
                      width: "100%",
                      textAlign: "left",
                      padding: "12px 14px",
                      border: "none",
                      borderBottom: "1px solid var(--border)",
                      background: "transparent",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span
                        style={{
                          fontFamily: "var(--mono)",
                          fontWeight: 700,
                          fontSize: 13,
                          color: "var(--blue-dark)",
                          background: "rgba(59,130,246,.1)",
                          padding: "2px 7px",
                          borderRadius: 4,
                        }}
                      >
                        {collection.code}
                      </span>
                      <span style={{ fontSize: 12, color: "var(--fg)", flex: 1 }}>{collection.title}</span>
                      <span style={{ fontSize: 10, color: "var(--muted)", fontFamily: "var(--mono)" }}>
                        {collection.paragraph_count} §
                      </span>
                    </div>
                  </button>
                ))
              ) : parasLoad ? (
                <div style={{ padding: 20, color: "var(--muted)", fontSize: 12, textAlign: "center" }}>
                  Загрузка…
                </div>
              ) : paragraphs.length === 0 ? (
                <div style={{ padding: 20, color: "var(--muted)", fontSize: 12, textAlign: "center" }}>
                  Ничего не найдено
                </div>
              ) : (
                paragraphs.map((paragraph) => (
                  <ParaRow
                    key={paragraph.id}
                    para={paragraph}
                    isActive={detail?.id === paragraph.id}
                    onClick={() => openParagraph(paragraph)}
                  />
                ))
              )}
            </div>
          </>
        )}
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: 16 }}>
        {detailLoad && (
          <div style={{ padding: 40, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>
            Загрузка параграфа…
          </div>
        )}
        {!detailLoad && !detail && activeCollection && <CollectionView collection={activeCollection} />}
        {!detailLoad && !detail && !activeCollection && (
          <div style={{ padding: 48, textAlign: "center", color: "var(--muted)" }}>
            <div style={{ fontSize: 15, fontWeight: 500 }}>Выберите параграф</div>
            {collections.length > 0 && (
              <div style={{ fontSize: 13, marginTop: 6 }}>
                Доступно сборников: {collections.map((collection) => collection.code).join(", ")}
              </div>
            )}
          </div>
        )}
        {!detailLoad && detail && (
          <DetailView
            detail={detail}
            collectionTitle={collections.find((item) => item.id === detail.collection_id)?.title}
          />
        )}
      </div>
    </div>
  );
}

function ParaRow({
  para,
  isActive,
  onClick,
  collectionCode,
}: {
  para: ParaShort;
  isActive: boolean;
  onClick: () => void;
  collectionCode?: string;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        padding: "9px 12px",
        border: "none",
        borderBottom: "1px solid var(--border)",
        background: isActive ? "rgba(59,130,246,.12)" : "transparent",
        cursor: "pointer",
        borderLeft: isActive ? "3px solid var(--blue)" : "3px solid transparent",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        {collectionCode && (
          <span
            style={{
              fontSize: 9,
              fontFamily: "var(--mono)",
              color: "var(--muted)",
              background: "var(--border)",
              padding: "1px 5px",
              borderRadius: 3,
            }}
          >
            {collectionCode}
          </span>
        )}
        <span style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--blue-dark)", fontWeight: 700 }}>
          {para.code}
        </span>
        {para.is_technical && (
          <span style={{ ...BADGE, fontSize: 9, padding: "1px 5px" }}>
            TECH
          </span>
        )}
      </div>
      <div style={{ fontSize: 11, color: "var(--fg)", marginTop: 2, lineHeight: 1.4 }}>{para.title}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 4 }}>
        {para.structure_title && (
          <div style={{ fontSize: 10, color: "var(--muted)" }}>{para.structure_title}</div>
        )}
        {para.unit && <div style={{ fontSize: 10, color: "var(--muted)" }}>{para.unit}</div>}
      </div>
    </button>
  );
}

function DetailView({ detail, collectionTitle }: { detail: ParaFull; collectionTitle?: string }) {
  const multiplierHints = collectMultiplierHints(detail);
  const hasMultiplierBreakdown = multiplierHints.length > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 1040 }}>
      <style>{`
        .enir-hover-card:hover .enir-hover-card__popup,
        .enir-hover-card:focus-within .enir-hover-card__popup {
          opacity: 1;
          pointer-events: auto;
          transform: translateY(0);
        }
      `}</style>
      <div style={{ ...PANEL, padding: "14px 16px" }}>
        {collectionTitle && (
          <div
            style={{
              fontSize: 10,
              color: "var(--muted)",
              textTransform: "uppercase",
              letterSpacing: ".06em",
              marginBottom: 6,
            }}
          >
            {collectionTitle}
          </div>
        )}
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: 13,
              fontWeight: 700,
              color: "var(--blue-dark)",
              background: "rgba(59,130,246,.1)",
              padding: "2px 8px",
              borderRadius: 4,
            }}
          >
            {detail.code}
          </span>
          <span style={{ fontSize: 14, fontWeight: 600, flex: 1 }}>{detail.title}</span>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
          {detail.section && <span style={BADGE}>Раздел {detail.section.source_id}: {detail.section.title}</span>}
          {detail.chapter && <span style={BADGE}>Глава {detail.chapter.source_id}: {detail.chapter.title}</span>}
          {detail.source_paragraph_id && <span style={BADGE}>source: {detail.source_paragraph_id}</span>}
        </div>
        {detail.unit && (
          <div style={{ marginTop: 8, fontSize: 12, color: "var(--muted)" }}>
            Измеритель: <strong style={{ color: "var(--fg)" }}>{detail.unit}</strong>
          </div>
        )}
      </div>

      {detail.technical_coefficients.length > 0 && (
        <div style={PANEL}>
          <SecH>Технические коэффициенты</SecH>
          <div style={{ padding: "12px 16px", display: "grid", gap: 10 }}>
            {detail.technical_coefficients.map((item) => (
              <div
                key={item.id}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  background: "var(--bg)",
                  padding: "10px 12px",
                  display: "grid",
                  gap: 8,
                }}
              >
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  <span
                    style={{
                      fontFamily: "var(--mono)",
                      fontWeight: 700,
                      color: "var(--blue-dark)",
                      background: "rgba(59,130,246,.1)",
                      padding: "2px 7px",
                      borderRadius: 4,
                    }}
                  >
                    {item.code}
                  </span>
                  <span style={BADGE}>{scopeLabel(item.scope)}</span>
                  {item.multiplier != null && (
                    <span
                      style={{
                        fontFamily: "var(--mono)",
                        fontWeight: 700,
                        color: "#ca8a04",
                        background: "rgba(234,179,8,.15)",
                        padding: "2px 7px",
                        borderRadius: 4,
                      }}
                    >
                      ×{item.multiplier}
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 12, lineHeight: 1.5 }}>{item.description}</div>
                {item.formula && (
                  <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--muted)" }}>
                    formula: {item.formula}
                  </div>
                )}
                {item.applicable_paragraphs.length > 0 && (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {item.applicable_paragraphs.map((paragraph) => (
                      <span key={paragraph.id} style={BADGE}>
                        {paragraph.code}
                      </span>
                    ))}
                  </div>
                )}
                <MetaJson title="Conditions" value={item.conditions} />
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.work_compositions.length > 0 && (
        <div style={PANEL}>
          <SecH>Состав работ</SecH>
          <div style={{ padding: "0 16px 14px" }}>
            {detail.work_compositions.map((item, index) => (
              <div
                key={index}
                style={{
                  marginTop: index > 0 ? 12 : 8,
                  padding: hasMultiplierBreakdown ? "10px 12px" : undefined,
                  border: hasMultiplierBreakdown ? "1px solid var(--border)" : undefined,
                  borderRadius: hasMultiplierBreakdown ? 6 : undefined,
                  background: hasMultiplierBreakdown ? "var(--bg)" : undefined,
                }}
              >
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: item.condition ? 4 : 0 }}>
                  {item.condition && (
                    <div style={{ fontSize: 11, fontWeight: 600, color: "var(--blue-dark)" }}>
                      {item.condition}
                    </div>
                  )}
                  {hasMultiplierBreakdown && (
                    <HoverCard
                      label="множители и основания"
                      count={multiplierHints.length}
                      items={multiplierHints}
                    />
                  )}
                </div>
                {!item.condition && hasMultiplierBreakdown && (
                  <div style={{ marginBottom: 6, fontSize: 10, color: "var(--muted)" }}>
                    Наведи на бейдж, чтобы увидеть все ТЧ/ПР и условия применения, которые уже хранятся в БД для этого параграфа.
                  </div>
                )}
                <ol style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 3 }}>
                  {item.operations.map((operation, opIndex) => (
                    <li key={opIndex} style={{ fontSize: 12, lineHeight: 1.5 }}>
                      {operation}
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.crew.length > 0 && (
        <div style={PANEL}>
          <SecH>Состав звена</SecH>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                {["Профессия", "Разряд", "Кол-во"].map((header) => (
                  <th key={header} style={{ ...TH, textAlign: "left" }}>
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {detail.crew.map((item, index) => (
                <tr key={index} style={{ background: index % 2 ? "var(--stripe)" : "" }}>
                  <td style={TD}>{item.profession}</td>
                  <td style={{ ...TD, fontFamily: "var(--mono)" }}>{item.grade ?? "—"}</td>
                  <td style={{ ...TD, fontFamily: "var(--mono)" }}>{item.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail.norm_tables.length > 0 && (
        <div style={PANEL}>
          <SecH>Табличные нормы</SecH>
          <div style={{ paddingBottom: 12 }}>
            {detail.norm_tables.map((table, tableIndex) => (
              <div key={table.id} style={{ marginTop: tableIndex === 0 ? 0 : 12 }}>
                <div
                  style={{
                    padding: "8px 16px",
                    fontSize: 11,
                    fontWeight: 600,
                    color: "var(--blue-dark)",
                    background: "rgba(59,130,246,.06)",
                    borderTop: "1px solid var(--border)",
                    borderBottom: "1px solid var(--border)",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    flexWrap: "wrap",
                  }}
                >
                  <span>{table.title || `Таблица ${tableIndex + 1}`}</span>
                  <span style={{ fontSize: 10, color: "var(--muted)", fontFamily: "var(--mono)" }}>
                    {table.source_table_id}
                  </span>
                  {table.row_count != null && (
                    <span style={{ fontSize: 10, color: "var(--muted)", fontFamily: "var(--mono)" }}>
                      {table.row_count} строк
                    </span>
                  )}
                </div>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                    <thead>
                      <tr>
                        {table.columns.map((column, colIndex) => {
                          const textColumn = isTextColumn(column);
                          return (
                            <th
                              key={column.id}
                              style={{
                                ...TH,
                                textAlign: textColumn ? "left" : "right",
                                minWidth: colIndex === 0 ? 220 : 120,
                                borderRight: colIndex === table.columns.length - 1 ? "none" : TH.borderRight,
                              }}
                              title={column.header || column.label || column.column_key}
                            >
                              {column.label || column.header || column.column_key}
                            </th>
                          );
                        })}
                      </tr>
                    </thead>
                    <tbody>
                      {table.rows.map((row, rowIndex) => (
                        <tr key={row.id} style={{ background: rowIndex % 2 ? "var(--stripe)" : "" }}>
                          {table.columns.map((column, colIndex) => {
                            const cell = cellForColumn(row, column.column_key);
                            const textColumn = isTextColumn(column);
                            return (
                              <td
                                key={`${row.id}-${column.id}`}
                                style={{
                                  ...TD,
                                  textAlign: textColumn ? "left" : "right",
                                  fontFamily: textColumn ? undefined : "var(--mono)",
                                  color: valuePreview(cell) ? "var(--fg)" : "var(--muted)",
                                  borderRight: colIndex === table.columns.length - 1 ? "none" : TD.borderRight,
                                }}
                              >
                                {colIndex === 0 && (
                                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4, flexWrap: "wrap" }}>
                                    {row.source_row_num != null && <span style={BADGE}>#{row.source_row_num}</span>}
                                    {row.source_row_id && (
                                      <span style={{ ...BADGE, fontFamily: "var(--mono)" }}>{row.source_row_id}</span>
                                    )}
                                  </div>
                                )}
                                <CellView cell={cell} alignRight={!textColumn} />
                                {colIndex === 0 && row.params && (
                                  <div style={{ marginTop: 8 }}>
                                    <MetaJson title="Params" value={row.params} />
                                  </div>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.has_legacy_norms && detail.norms.length > 0 && (
        <div style={PANEL}>
          <SecH>Legacy нормы</SecH>
          <div style={{ padding: "12px 16px", display: "grid", gap: 8 }}>
            {detail.norms.map((item, index) => (
              <div
                key={`${item.row_num}-${index}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
                  gap: 8,
                  padding: "10px 12px",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  background: "var(--bg)",
                }}
              >
                <div><strong>Строка:</strong> {item.row_num ?? "—"}</div>
                <div><strong>Вид:</strong> {item.work_type ?? "—"}</div>
                <div><strong>Условие:</strong> {item.condition ?? "—"}</div>
                <div><strong>Толщина:</strong> {item.thickness_mm ?? "—"}</div>
                <div><strong>Н.вр.:</strong> {item.norm_time ?? "—"}</div>
                <div><strong>Расц.:</strong> {item.price_rub ?? "—"}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.notes.length > 0 && (
        <div style={PANEL}>
          <SecH>Примечания</SecH>
          <div style={{ padding: "0 16px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
            {detail.notes.map((item) => (
              <div
                key={item.num}
                style={{
                  fontSize: 12,
                  lineHeight: 1.5,
                  display: "grid",
                  gap: 8,
                  padding: "10px 12px",
                  background: item.coefficient != null ? "rgba(234,179,8,.07)" : "transparent",
                  border: item.coefficient != null ? "1px solid rgba(234,179,8,.2)" : "1px solid var(--border)",
                  borderRadius: 6,
                }}
              >
                <div style={{ display: "flex", gap: 8, alignItems: "flex-start", flexWrap: "wrap" }}>
                  <span style={{ fontFamily: "var(--mono)", fontWeight: 700, fontSize: 10, color: "var(--muted)" }}>
                    {item.num}.
                  </span>
                  {item.pr_code && <span style={BADGE}>{item.pr_code}</span>}
                  {item.coefficient != null && (
                    <span
                      style={{
                        fontFamily: "var(--mono)",
                        fontWeight: 700,
                        fontSize: 11,
                        color: "#ca8a04",
                        background: "rgba(234,179,8,.15)",
                        padding: "1px 6px",
                        borderRadius: 3,
                      }}
                    >
                      ×{item.coefficient}
                    </span>
                  )}
                </div>
                <div>{item.text}</div>
                {item.formula && (
                  <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--muted)" }}>
                    formula: {item.formula}
                  </div>
                )}
                <MetaJson title="Conditions" value={item.conditions} />
              </div>
            ))}
          </div>
        </div>
      )}

      {(detail.application_notes.length > 0 || detail.technical_characteristics.length > 0 || detail.refs.length > 0) && (
        <div style={PANEL}>
          <SecH>Дополнительно</SecH>
          <div style={{ padding: "12px 16px", display: "grid", gap: 14 }}>
            {detail.technical_characteristics.length > 0 && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--blue-dark)", marginBottom: 6 }}>
                  Технические характеристики
                </div>
                <div style={{ display: "grid", gap: 6 }}>
                  {detail.technical_characteristics.map((item) => (
                    <div key={item.sort_order} style={{ padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)", fontSize: 12, lineHeight: 1.5 }}>
                      {item.raw_text}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {detail.application_notes.length > 0 && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--blue-dark)", marginBottom: 6 }}>
                  Применение
                </div>
                <div style={{ display: "grid", gap: 6 }}>
                  {detail.application_notes.map((item) => (
                    <div key={item.sort_order} style={{ padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)", fontSize: 12, lineHeight: 1.5 }}>
                      {item.text}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {detail.refs.length > 0 && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--blue-dark)", marginBottom: 6 }}>
                  Ссылки
                </div>
                <div style={{ display: "grid", gap: 6 }}>
                  {detail.refs.map((item) => (
                    <div key={`${item.sort_order}-${item.href ?? item.link_text ?? ""}`} style={{ padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)", fontSize: 12, lineHeight: 1.5 }}>
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: item.context_text ? 4 : 0 }}>
                        <span style={BADGE}>{item.ref_type}</span>
                        {item.link_text && <span>{item.link_text}</span>}
                        {item.abs_url && (
                          <a href={item.abs_url} target="_blank" rel="noreferrer" style={{ color: "var(--blue-dark)" }}>
                            {item.abs_url}
                          </a>
                        )}
                      </div>
                      {item.context_text && <div style={{ color: "var(--muted)" }}>{item.context_text}</div>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {(detail.source_work_items.length > 0 || detail.source_crew_items.length > 0 || detail.source_notes.length > 0) && (
        <div style={PANEL}>
          <SecH>Исходные данные</SecH>
          <div style={{ padding: "12px 16px", display: "grid", gap: 14 }}>
            {detail.source_work_items.length > 0 && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--blue-dark)", marginBottom: 6 }}>
                  Source work items
                </div>
                <div style={{ display: "grid", gap: 6 }}>
                  {detail.source_work_items.map((item) => (
                    <div key={item.sort_order} style={{ padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)", fontSize: 12, lineHeight: 1.5 }}>
                      {item.raw_text}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {detail.source_crew_items.length > 0 && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--blue-dark)", marginBottom: 6 }}>
                  Source crew items
                </div>
                <div style={{ display: "grid", gap: 6 }}>
                  {detail.source_crew_items.map((item) => (
                    <div key={item.sort_order} style={{ padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)", fontSize: 12, lineHeight: 1.5 }}>
                      {item.raw_text || `${item.profession ?? "—"} · ${item.grade ?? "—"} · ${item.count ?? "—"}`}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {detail.source_notes.length > 0 && (
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "var(--blue-dark)", marginBottom: 6 }}>
                  Source notes
                </div>
                <div style={{ display: "grid", gap: 8 }}>
                  {detail.source_notes.map((item) => (
                    <div key={`${item.sort_order}-${item.code ?? "note"}`} style={{ padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)", display: "grid", gap: 8 }}>
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        {item.code && <span style={BADGE}>{item.code}</span>}
                        {item.coefficient != null && (
                          <span style={{ ...BADGE, fontFamily: "var(--mono)" }}>×{item.coefficient}</span>
                        )}
                      </div>
                      <div style={{ fontSize: 12, lineHeight: 1.5 }}>{item.text}</div>
                      {item.formula && (
                        <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--muted)" }}>
                          formula: {item.formula}
                        </div>
                      )}
                      <MetaJson title="Conditions" value={item.conditions} />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function CollectionView({ collection }: { collection: Collection }) {
  const meta = [
    { label: "Выпуск", value: collection.issue || "—" },
    { label: "Заголовок выпуска", value: collection.issue_title || "—" },
    { label: "Файл", value: collection.source_file || "—" },
    { label: "Формат", value: collection.source_format || "—" },
    { label: "Параграфов", value: String(collection.paragraph_count) },
    { label: "Порядок", value: String(collection.sort_order) },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 920 }}>
      <div style={{ ...PANEL, padding: "16px 18px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: 13,
              fontWeight: 700,
              color: "var(--blue-dark)",
              background: "rgba(59,130,246,.1)",
              padding: "3px 8px",
              borderRadius: 4,
            }}
          >
            {collection.code}
          </span>
          <span style={{ fontSize: 16, fontWeight: 600 }}>{collection.title}</span>
        </div>

        {collection.description && (
          <div style={{ fontSize: 13, lineHeight: 1.6, color: "var(--fg)", marginBottom: 12 }}>
            {collection.description}
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
          {meta.map((item) => (
            <div key={item.label} style={{ padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 6, background: "var(--bg)" }}>
              <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 4 }}>
                {item.label}
              </div>
              <div style={{ fontSize: 12, lineHeight: 1.45, color: "var(--fg)" }}>{item.value}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SecH({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        padding: "8px 16px",
        borderBottom: "1px solid var(--border)",
        fontSize: 11,
        fontWeight: 600,
        color: "var(--muted)",
        textTransform: "uppercase",
        letterSpacing: ".06em",
      }}
    >
      {children}
    </div>
  );
}
