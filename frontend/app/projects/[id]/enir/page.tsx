"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

import { enir as enirApi } from "@/lib/api";
import type {
  EnirCollectionSummary,
  EnirNorm,
  EnirNormCellValue,
  EnirNormTable,
  EnirParagraphFull,
  EnirParagraphShort,
} from "@/lib/types";

function groupNorms(norms: EnirNorm[]) {
  const byType: Record<string, Record<string, EnirNorm[]>> = {};
  for (const norm of norms) {
    const workType = norm.work_type ?? "(без типа)";
    const rowKey = String(norm.row_num ?? "__null__");
    (byType[workType] ??= {})[rowKey] ??= [];
    byType[workType][rowKey].push(norm);
  }
  return byType;
}

function formatNumber(value: number | null | undefined, digits = 2) {
  return value == null ? "—" : value.toFixed(digits);
}

function paragraphDisplayLabel(
  paragraph: Pick<EnirParagraphShort, "code" | "structure_title" | "chapter" | "section" | "is_technical">
) {
  if (!paragraph.is_technical) {
    return paragraph.code;
  }
  return paragraph.structure_title ?? paragraph.chapter?.title ?? paragraph.section?.title ?? paragraph.code;
}

function renderCellValues(values: EnirNormCellValue[]) {
  if (values.length === 0) {
    return <span style={{ color: "var(--muted)" }}>—</span>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {values.map((value, index) => (
        <span
          key={`${value.value_type}-${index}-${value.value_text}`}
          style={{
            fontFamily: "var(--mono)",
            color: value.value_type === "price_cell" ? "var(--blue-dark)" : "var(--text)",
            fontWeight: value.value_type === "price_cell" ? 600 : 400,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {value.value_text || "—"}
        </span>
      ))}
    </div>
  );
}

const TH: CSSProperties = {
  padding: "7px 10px",
  background: "#f8fafc",
  color: "var(--muted)",
  fontSize: 10,
  fontFamily: "var(--mono)",
  textTransform: "uppercase",
  letterSpacing: ".05em",
  whiteSpace: "nowrap",
  borderRight: "1px solid var(--border)",
  fontWeight: 400,
};

const TD: CSSProperties = {
  padding: "6px 10px",
  fontSize: 12,
  borderBottom: "1px solid var(--border)",
  borderRight: "1px solid var(--border)",
  verticalAlign: "top",
};

const PANEL: CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 6,
};

export default function EnirPage() {
  const [collections, setCollections] = useState<EnirCollectionSummary[]>([]);
  const [collectionsLoad, setCollectionsLoad] = useState(true);
  const [activeCollection, setActiveCollection] = useState<EnirCollectionSummary | null>(null);

  const [paragraphs, setParagraphs] = useState<EnirParagraphShort[]>([]);
  const [parasLoad, setParasLoad] = useState(false);
  const [search, setSearch] = useState("");
  const debRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [detail, setDetail] = useState<EnirParagraphFull | null>(null);
  const [detailLoad, setDetailLoad] = useState(false);

  const [globalSearch, setGlobalSearch] = useState("");
  const [globalResults, setGlobalResults] = useState<EnirParagraphShort[]>([]);
  const [globalSearchActive, setGlobalSearchActive] = useState(false);
  const globalDebRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    enirApi.collections()
      .then((data) => {
        setCollections(data);
        if (data.length === 1) {
          selectCollection(data[0]);
        }
      })
      .finally(() => setCollectionsLoad(false));
  }, []);

  function selectCollection(collection: EnirCollectionSummary) {
    setActiveCollection(collection);
    setDetail(null);
    setSearch("");
    setGlobalSearch("");
    setGlobalSearchActive(false);
    setParasLoad(true);
    enirApi.paragraphs(collection.id)
      .then(setParagraphs)
      .finally(() => setParasLoad(false));
  }

  const handleSearch = useCallback((value: string) => {
    setSearch(value);
    if (!activeCollection) {
      return;
    }
    if (debRef.current) {
      clearTimeout(debRef.current);
    }
    debRef.current = setTimeout(() => {
      setParasLoad(true);
      enirApi.paragraphs(activeCollection.id, value || undefined)
        .then(setParagraphs)
        .finally(() => setParasLoad(false));
    }, 300);
  }, [activeCollection]);

  const handleGlobalSearch = useCallback((value: string) => {
    setGlobalSearch(value);
    if (globalDebRef.current) {
      clearTimeout(globalDebRef.current);
    }
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

  function openParagraph(paragraph: EnirParagraphShort) {
    setDetailLoad(true);
    setDetail(null);
    enirApi.paragraph(paragraph.id)
      .then(setDetail)
      .finally(() => setDetailLoad(false));

    if (globalSearchActive) {
      const collection = collections.find((item) => item.id === paragraph.collection_id);
      if (collection) {
        setActiveCollection(collection);
      }
    }
  }

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      <div
        style={{
          width: 320,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          borderRight: "1px solid var(--border)",
          background: "var(--surface)",
        }}
      >
        <div
          style={{
            padding: "10px 12px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <input
            value={globalSearch}
            onChange={(e) => handleGlobalSearch(e.target.value)}
            placeholder="🔍 Поиск по всем сборникам…"
            style={{
              width: "100%",
              boxSizing: "border-box",
              background: "var(--bg)",
              border: "1px solid var(--border)",
              borderRadius: 4,
              padding: "6px 10px",
              fontSize: 12,
              color: "var(--text)",
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
              Результаты поиска ({globalResults.length})
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
                    title={collection.title}
                  >
                    {collection.code}
                    <span style={{ fontSize: 9, opacity: 0.7, marginLeft: 4 }}>
                      {collection.paragraph_count}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {activeCollection && (
              <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)" }}>
                <input
                  value={search}
                  onChange={(e) => handleSearch(e.target.value)}
                  placeholder={`Фильтр в ${activeCollection.code}…`}
                  style={{
                    width: "100%",
                    boxSizing: "border-box",
                    background: "var(--bg)",
                    border: "1px solid var(--border)",
                    borderRadius: 4,
                    padding: "5px 9px",
                    fontSize: 12,
                    color: "var(--text)",
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
                collections.length === 0 ? (
                  <div style={{ padding: 20, color: "var(--muted)", fontSize: 12, textAlign: "center" }}>
                    В базе пока нет сборников ЕНИР
                  </div>
                ) : (
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
                        <span style={{ fontSize: 12, color: "var(--text)", flex: 1 }}>{collection.title}</span>
                        <span style={{ fontSize: 10, color: "var(--muted)", fontFamily: "var(--mono)" }}>
                          {collection.paragraph_count} §
                        </span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4, paddingLeft: 2 }}>
                        {collection.description && (
                          <span style={{ fontSize: 11, color: "var(--muted)" }}>{collection.description}</span>
                        )}
                        {collection.issue && (
                          <span style={{ fontSize: 11, color: "var(--muted)" }}>
                            {collection.issue}
                          </span>
                        )}
                      </div>
                    </button>
                  ))
                )
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
        {!detailLoad && !detail && (
          <div style={{ padding: 48, textAlign: "center", color: "var(--muted)" }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>📖</div>
            <div style={{ fontSize: 15, fontWeight: 500 }}>Выберите параграф</div>
            {collections.length > 0 && (
              <div style={{ fontSize: 13, marginTop: 6 }}>
                Доступно сборников: {collections.map((collection) => collection.code).join(", ")}
              </div>
            )}
          </div>
        )}
        {!detailLoad && detail && <DetailView detail={detail} />}
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
  para: EnirParagraphShort;
  isActive: boolean;
  onClick: () => void;
  collectionCode?: string;
}) {
  const codeLabel = paragraphDisplayLabel(para);
  const showStructureLabel = para.is_technical && codeLabel !== para.code;

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
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
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
        <span
          style={{
            fontSize: 11,
            fontFamily: showStructureLabel ? "var(--sans)" : "var(--mono)",
            color: showStructureLabel ? "var(--muted)" : "var(--blue-dark)",
            fontWeight: showStructureLabel ? 600 : 700,
            whiteSpace: "normal",
            lineHeight: 1.35,
          }}
        >
          {codeLabel}
        </span>
        {para.source_paragraph_id && para.source_paragraph_id !== para.code && (
          <span style={{ fontSize: 9, color: "var(--muted)", fontFamily: "var(--mono)" }}>
            {para.source_paragraph_id}
          </span>
        )}
      </div>
      <div style={{ fontSize: 11, color: "var(--text)", marginTop: 2, lineHeight: 1.4 }}>{para.title}</div>
      {para.unit && (
        <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 2 }}>{para.unit}</div>
      )}
    </button>
  );
}

function DetailView({ detail }: { detail: EnirParagraphFull }) {
  const normGroups = groupNorms(detail.norms);
  const multiType = Object.keys(normGroups).length > 1;
  const codeLabel = paragraphDisplayLabel(detail);
  const showStructureLabel = detail.is_technical && codeLabel !== detail.code;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 1100 }}>
      <div style={{ ...PANEL, padding: "14px 16px" }}>
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <div
            style={{
              fontSize: 10,
              color: "var(--muted)",
              textTransform: "uppercase",
              letterSpacing: ".06em",
            }}
          >
            {detail.collection.issue_title || detail.collection.title}
          </div>
          {detail.collection.issue && (
            <span
              style={{
                fontSize: 9,
                color: "var(--muted)",
                fontFamily: "var(--mono)",
                border: "1px solid var(--border)",
                padding: "1px 5px",
                borderRadius: 999,
              }}
            >
              {detail.collection.issue}
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <span
            style={{
              fontFamily: showStructureLabel ? "var(--sans)" : "var(--mono)",
              fontSize: showStructureLabel ? 12 : 13,
              fontWeight: 700,
              color: showStructureLabel ? "var(--muted)" : "var(--blue-dark)",
              background: showStructureLabel ? "transparent" : "rgba(59,130,246,.1)",
              padding: showStructureLabel ? 0 : "2px 8px",
              borderRadius: 4,
              whiteSpace: "normal",
              lineHeight: 1.35,
            }}
          >
            {codeLabel}
          </span>
          <span style={{ fontSize: 14, fontWeight: 600, flex: 1 }}>{detail.title}</span>
        </div>
        {detail.collection.issue_title && detail.collection.issue_title !== detail.collection.title && (
          <div style={{ marginTop: 6, fontSize: 12, color: "var(--muted)" }}>
            Сборник: <strong style={{ color: "var(--text)" }}>{detail.collection.title}</strong>
          </div>
        )}
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 8 }}>
          {detail.unit && (
            <div style={{ fontSize: 12, color: "var(--muted)" }}>
              Измеритель: <strong style={{ color: "var(--text)" }}>{detail.unit}</strong>
            </div>
          )}
          {detail.source_paragraph_id && detail.source_paragraph_id !== detail.code && (
            <div style={{ fontSize: 12, color: "var(--muted)" }}>
              Source ID: <strong style={{ color: "var(--text)", fontFamily: "var(--mono)" }}>{detail.source_paragraph_id}</strong>
            </div>
          )}
        </div>
      </div>

      {detail.application_notes.length > 0 && (
        <div style={PANEL}>
          <SecHeader>Примечания по применению</SecHeader>
          <div style={{ padding: "0 16px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
            {detail.application_notes.map((note) => (
              <div
                key={`${note.sort_order}-${note.text}`}
                style={{
                  marginTop: 8,
                  padding: "8px 10px",
                  border: "1px solid var(--border)",
                  borderRadius: 4,
                  fontSize: 12,
                  lineHeight: 1.5,
                }}
              >
                {note.text}
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.technical_characteristics.length > 0 && (
        <div style={PANEL}>
          <SecHeader>Технические характеристики</SecHeader>
          <div style={{ padding: "0 16px 14px", display: "flex", flexDirection: "column", gap: 10 }}>
            {detail.technical_characteristics.map((item) => (
              <pre
                key={`${item.sort_order}-${item.raw_text.slice(0, 24)}`}
                style={{
                  margin: 0,
                  marginTop: 8,
                  padding: "10px 12px",
                  borderRadius: 4,
                  background: "var(--bg)",
                  border: "1px solid var(--border)",
                  color: "var(--text)",
                  fontSize: 11,
                  lineHeight: 1.5,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  fontFamily: "var(--mono)",
                }}
              >
                {item.raw_text}
              </pre>
            ))}
          </div>
        </div>
      )}

      {detail.work_compositions.length > 0 && (
        <div style={PANEL}>
          <SecHeader>Состав работ</SecHeader>
          <div style={{ padding: "0 16px 14px" }}>
            {detail.work_compositions.map((workComposition, index) => (
              <div key={`${workComposition.condition ?? "no-condition"}-${index}`} style={{ marginTop: index > 0 ? 12 : 8 }}>
                {workComposition.condition && (
                  <div style={{ fontSize: 11, fontWeight: 600, color: "var(--blue-dark)", marginBottom: 4 }}>
                    {workComposition.condition}
                  </div>
                )}
                <ol style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 3 }}>
                  {workComposition.operations.map((operation, operationIndex) => (
                    <li key={`${operationIndex}-${operation}`} style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.5 }}>
                      {operation}
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        </div>
      )}

      {detail.work_compositions.length === 0 && detail.source_work_items.length > 0 && (
        <div style={PANEL}>
          <SecHeader>Исходные блоки состава работ</SecHeader>
          <div style={{ padding: "0 16px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
            {detail.source_work_items.map((item) => (
              <pre
                key={`${item.sort_order}-${item.raw_text.slice(0, 24)}`}
                style={{
                  margin: 0,
                  marginTop: 8,
                  padding: "10px 12px",
                  borderRadius: 4,
                  background: "var(--bg)",
                  border: "1px solid var(--border)",
                  color: "var(--text)",
                  fontSize: 11,
                  lineHeight: 1.5,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  fontFamily: "var(--mono)",
                }}
              >
                {item.raw_text}
              </pre>
            ))}
          </div>
        </div>
      )}

      {detail.crew.length > 0 && (
        <div style={PANEL}>
          <SecHeader>Состав звена</SecHeader>
          <div style={{ overflowX: "auto" }}>
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
                {detail.crew.map((member, index) => (
                  <tr key={`${member.profession}-${index}`} style={{ background: index % 2 ? "var(--stripe)" : "" }}>
                    <td style={TD}>{member.profession}</td>
                    <td style={{ ...TD, fontFamily: "var(--mono)" }}>{member.grade ?? "—"}</td>
                    <td style={{ ...TD, fontFamily: "var(--mono)" }}>{member.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {detail.norm_tables.length > 0 && (
        <div style={PANEL}>
          <SecHeader>Табличные нормы</SecHeader>
          <div style={{ padding: "0 16px 14px", display: "flex", flexDirection: "column", gap: 14 }}>
            {detail.norm_tables.map((table, index) => (
              <NormTableView
                key={table.source_table_id}
                table={table}
                caption={table.title || `Таблица ${index + 1}`}
              />
            ))}
          </div>
        </div>
      )}

      {detail.norms.length > 0 && (
        <div style={PANEL}>
          <SecHeader>{detail.norm_tables.length > 0 ? "Плоские нормы" : "Нормы времени и расценки"}</SecHeader>
          {Object.entries(normGroups).map(([workType, byRowNum]) => (
            <div key={workType}>
              {multiType && (
                <div
                  style={{
                    padding: "6px 16px",
                    fontSize: 11,
                    fontWeight: 600,
                    color: "var(--blue-dark)",
                    background: "rgba(59,130,246,.06)",
                    borderTop: "1px solid var(--border)",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  {workType}
                </div>
              )}
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr>
                      <th style={{ ...TH, textAlign: "right", minWidth: 60 }}>Строка</th>
                      <th style={{ ...TH, textAlign: "left", minWidth: 220 }}>Условия</th>
                      <th style={{ ...TH, textAlign: "right" }}>Толщина, мм</th>
                      <th style={{ ...TH, textAlign: "center" }}>Стб.</th>
                      <th style={{ ...TH, textAlign: "right" }}>Н.вр., чел-ч</th>
                      <th style={{ ...TH, textAlign: "right", borderRight: "none" }}>Расц., руб.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(byRowNum).flatMap(([rowKey, norms]) =>
                      norms.map((norm, index) => (
                        <tr key={`${rowKey}-${index}`} style={{ background: index % 2 ? "var(--stripe)" : "" }}>
                          {index === 0 ? (
                            <>
                              <td
                                style={{
                                  ...TD,
                                  textAlign: "right",
                                  fontFamily: "var(--mono)",
                                  color: "var(--muted)",
                                }}
                                rowSpan={norms.length}
                              >
                                {norm.row_num ?? "—"}
                              </td>
                              <td style={{ ...TD, verticalAlign: "top" }} rowSpan={norms.length}>
                                {norm.condition ?? "—"}
                              </td>
                            </>
                          ) : null}
                          <td
                            style={{
                              ...TD,
                              textAlign: "right",
                              fontFamily: "var(--mono)",
                              color: "var(--muted)",
                            }}
                          >
                            {norm.thickness_mm ?? "—"}
                          </td>
                          <td
                            style={{
                              ...TD,
                              textAlign: "center",
                              fontFamily: "var(--mono)",
                              color: "var(--muted)",
                            }}
                          >
                            {norm.column_label ?? ""}
                          </td>
                          <td
                            style={{
                              ...TD,
                              textAlign: "right",
                              fontFamily: "var(--mono)",
                              fontWeight: 500,
                            }}
                          >
                            {formatNumber(norm.norm_time)}
                          </td>
                          <td
                            style={{
                              ...TD,
                              textAlign: "right",
                              fontFamily: "var(--mono)",
                              color: "var(--blue-dark)",
                              fontWeight: 600,
                              borderRight: "none",
                            }}
                          >
                            {formatNumber(norm.price_rub)}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}

      {detail.notes.length > 0 && (
        <div style={PANEL}>
          <SecHeader>Примечания</SecHeader>
          <div style={{ padding: "0 16px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
            {detail.notes.map((note) => (
              <div
                key={`${note.num}-${note.text.slice(0, 24)}`}
                style={{
                  fontSize: 12,
                  lineHeight: 1.5,
                  display: "flex",
                  gap: 8,
                  padding: "8px 10px",
                  background: note.coefficient ? "rgba(234,179,8,.07)" : "transparent",
                  border: note.coefficient ? "1px solid rgba(234,179,8,.2)" : "1px solid transparent",
                  borderRadius: 4,
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--mono)",
                    fontWeight: 700,
                    fontSize: 10,
                    color: "var(--muted)",
                    minWidth: 18,
                  }}
                >
                  {note.num}.
                </span>
                <span style={{ flex: 1 }}>{note.text}</span>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, flexShrink: 0 }}>
                  {note.coefficient != null && (
                    <span
                      style={{
                        fontFamily: "var(--mono)",
                        fontWeight: 700,
                        fontSize: 11,
                        color: "#ca8a04",
                        background: "rgba(234,179,8,.15)",
                        padding: "1px 6px",
                        borderRadius: 3,
                        whiteSpace: "nowrap",
                      }}
                    >
                      ×{note.coefficient}
                    </span>
                  )}
                  {note.pr_code && (
                    <span
                      style={{
                        fontFamily: "var(--mono)",
                        fontSize: 9,
                        color: "var(--muted)",
                        border: "1px solid var(--border)",
                        padding: "1px 5px",
                        borderRadius: 3,
                      }}
                    >
                      {note.pr_code}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function NormTableView({ table, caption }: { table: EnirNormTable; caption: string }) {
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>{caption}</div>
        {table.row_count != null && (
          <span style={{ fontSize: 10, color: "var(--muted)" }}>строк: {table.row_count}</span>
        )}
      </div>

      <div style={{ overflowX: "auto", border: "1px solid var(--border)", borderRadius: 6 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              <th style={{ ...TH, textAlign: "right", minWidth: 70 }}>№</th>
              {table.columns.map((column) => (
                <th key={column.column_key} style={{ ...TH, textAlign: "left", minWidth: 140 }}>
                  <div>{column.header}</div>
                  {column.label && (
                    <div style={{ fontSize: 9, color: "#64748b", marginTop: 2, fontFamily: "var(--mono)" }}>
                      {column.label}
                    </div>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, index) => (
              <tr key={row.source_row_id} style={{ background: index % 2 ? "var(--stripe)" : "" }}>
                <td style={{ ...TD, textAlign: "right", fontFamily: "var(--mono)", color: "var(--muted)" }}>
                  {row.source_row_num ?? "—"}
                </td>
                {row.cells.map((cell) => (
                  <td key={`${row.source_row_id}-${cell.column_key}`} style={TD}>
                    {renderCellValues(cell.values)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SecHeader({ children }: { children: ReactNode }) {
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
