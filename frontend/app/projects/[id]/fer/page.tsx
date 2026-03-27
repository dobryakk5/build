"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";

import { fer as ferApi } from "@/lib/api";
import type {
  FerBreadcrumbItem,
  FerBrowseItem,
  FerBrowseResponse,
  FerCollectionSummary,
  FerTableDetail,
  FerTableRow,
} from "@/lib/types";

const PANEL: CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 6,
};

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

function formatNumber(value: number | null | undefined, digits = 2) {
  return value == null ? "—" : value.toFixed(digits);
}

function crumbAccent(kind: FerBreadcrumbItem["kind"]) {
  if (kind === "collection") return "rgba(59,130,246,.12)";
  if (kind === "section") return "rgba(14,165,233,.1)";
  if (kind === "subsection") return "rgba(16,185,129,.1)";
  return "rgba(15,23,42,.06)";
}

function itemMeta(item: FerBrowseItem) {
  if (item.kind === "section") {
    const subsectionCount = item.subsection_count ?? 0;
    const tableCount = item.table_count ?? 0;
    return `${subsectionCount} подразделов • ${tableCount} таблиц`;
  }
  if (item.kind === "subsection") {
    return `${item.table_count ?? 0} таблиц`;
  }
  return `${item.row_count ?? 0} строк`;
}

function itemMarker(item: FerBrowseItem) {
  if (item.kind === "section") return "Раздел";
  if (item.kind === "subsection") return "Подраздел";
  return "Таблица";
}

export default function FerPage() {
  const [collections, setCollections] = useState<FerCollectionSummary[]>([]);
  const [collectionsLoad, setCollectionsLoad] = useState(true);
  const [browse, setBrowse] = useState<FerBrowseResponse | null>(null);
  const [browseLoad, setBrowseLoad] = useState(false);
  const [detail, setDetail] = useState<FerTableDetail | null>(null);
  const [detailLoad, setDetailLoad] = useState(false);

  useEffect(() => {
    ferApi.collections()
      .then(setCollections)
      .finally(() => setCollectionsLoad(false));
  }, []);

  function openCollections() {
    setBrowse(null);
    setDetail(null);
  }

  function openLevel(params: { collectionId: number; sectionId?: number; subsectionId?: number }) {
    setBrowseLoad(true);
    setDetail(null);
    ferApi.browse(params)
      .then(setBrowse)
      .finally(() => setBrowseLoad(false));
  }

  function openCollection(collection: FerCollectionSummary) {
    openLevel({ collectionId: collection.id });
  }

  function openItem(item: FerBrowseItem) {
    if (!browse) {
      return;
    }

    if (item.kind === "section") {
      openLevel({ collectionId: browse.collection.id, sectionId: item.id });
      return;
    }
    if (item.kind === "subsection") {
      if (!browse.section) {
        return;
      }
      openLevel({
        collectionId: browse.collection.id,
        sectionId: browse.section.id,
        subsectionId: item.id,
      });
      return;
    }

    setDetailLoad(true);
    ferApi.table(item.id)
      .then(setDetail)
      .finally(() => setDetailLoad(false));
  }

  function openBreadcrumb(crumb: FerBreadcrumbItem) {
    if (!browse) {
      return;
    }

    if (crumb.kind === "collection") {
      openLevel({ collectionId: browse.collection.id });
      return;
    }
    if (crumb.kind === "section") {
      openLevel({ collectionId: browse.collection.id, sectionId: crumb.id });
      return;
    }
    if (crumb.kind === "subsection" && browse.section) {
      openLevel({
        collectionId: browse.collection.id,
        sectionId: browse.section.id,
        subsectionId: crumb.id,
      });
    }
  }

  return (
    <div style={{ height: "100%", overflow: "auto", padding: 16 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 1200 }}>
        <div
          style={{
            ...PANEL,
            padding: "12px 14px",
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div>
              <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".08em" }}>
                Справочник
              </div>
              <div style={{ fontSize: 14, fontWeight: 700 }}>ФЕР</div>
            </div>
            {browse && (
              <button
                onClick={openCollections}
                style={{
                  border: "1px solid var(--border)",
                  background: "transparent",
                  borderRadius: 4,
                  cursor: "pointer",
                  fontSize: 11,
                  color: "var(--muted)",
                  padding: "5px 8px",
                }}
              >
                Все сборники
              </button>
            )}
          </div>

          {detail ? (
            <Breadcrumbs items={detail.breadcrumb} onClick={openBreadcrumb} />
          ) : browse ? (
            <Breadcrumbs items={browse.breadcrumb} onClick={openBreadcrumb} />
          ) : null}
        </div>

        {detailLoad ? (
          <EmptyPanel label="Загрузка таблицы ФЕР…" />
        ) : detail ? (
          <FerDetail detail={detail} />
        ) : (
          <div style={PANEL}>
            {collectionsLoad ? (
              <EmptyState label="Загружаю структуру ФЕР…" />
            ) : !browse ? (
              collections.length === 0 ? (
                <EmptyState label="В базе пока нет сборников ФЕР" />
              ) : (
                collections.map((collection) => (
                  <button
                    key={collection.id}
                    onClick={() => openCollection(collection)}
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
                        {collection.num}
                      </span>
                      <span style={{ fontSize: 12, color: "var(--text)", flex: 1 }}>{collection.name}</span>
                    </div>
                    <div style={{ marginTop: 5, fontSize: 11, color: "var(--muted)" }}>
                      {collection.sections_count} разделов • {collection.subsections_count} подразделов • {collection.total_tables_count} таблиц
                    </div>
                  </button>
                ))
              )
            ) : browseLoad ? (
              <EmptyState label="Загружаю вложенный список…" />
            ) : browse.items.length === 0 ? (
              <EmptyState label="На этом уровне пока нет элементов" />
            ) : (
              browse.items.map((item) => (
                <button
                  key={`${item.kind}-${item.id}`}
                  onClick={() => openItem(item)}
                  style={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    padding: "11px 14px",
                    border: "none",
                    borderBottom: "1px solid var(--border)",
                    background: "transparent",
                    cursor: "pointer",
                  }}
                >
                  {item.kind === "table" ? (
                    <div
                      style={{
                        display: "flex",
                        alignItems: "baseline",
                        gap: 12,
                      }}
                    >
                      <div
                        style={{
                          flex: 1,
                          minWidth: 0,
                          fontSize: 12,
                          lineHeight: 1.4,
                          color: "var(--text)",
                        }}
                      >
                        {item.title}
                      </div>
                      <div
                        style={{
                          flexShrink: 0,
                          fontSize: 11,
                          color: "var(--muted)",
                          fontFamily: "var(--mono)",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {item.row_count ?? 0} строк
                      </div>
                    </div>
                  ) : (
                    <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                      <span
                        style={{
                          marginTop: 1,
                          fontSize: 9,
                          fontFamily: "var(--mono)",
                          color: "var(--muted)",
                          background: "var(--bg)",
                          border: "1px solid var(--border)",
                          borderRadius: 999,
                          padding: "2px 6px",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {itemMarker(item)}
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, lineHeight: 1.45, color: "var(--text)" }}>{item.title}</div>
                        <div style={{ marginTop: 4, fontSize: 11, color: "var(--muted)" }}>{itemMeta(item)}</div>
                      </div>
                    </div>
                  )}
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Breadcrumbs({
  items,
  onClick,
}: {
  items: FerBreadcrumbItem[];
  onClick?: (item: FerBreadcrumbItem) => void;
}) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
      {items.map((item, index) => {
        const isLast = index === items.length - 1;
        const clickable = !isLast && onClick;
        return (
          <button
            key={`${item.kind}-${item.id}`}
            onClick={clickable ? () => onClick(item) : undefined}
            style={{
              border: "1px solid var(--border)",
              background: crumbAccent(item.kind),
              borderRadius: 999,
              padding: "4px 9px",
              fontSize: 11,
              color: "var(--text)",
              cursor: clickable ? "pointer" : "default",
            }}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return (
    <div style={{ padding: 22, color: "var(--muted)", fontSize: 12, textAlign: "center" }}>
      {label}
    </div>
  );
}

function EmptyPanel({ label, hint }: { label: string; hint?: string }) {
  return (
    <div style={{ padding: 48, textAlign: "center", color: "var(--muted)" }}>
      <div style={{ fontSize: 36, marginBottom: 12 }}>🧾</div>
      <div style={{ fontSize: 15, fontWeight: 500 }}>{label}</div>
      {hint && <div style={{ fontSize: 13, marginTop: 6 }}>{hint}</div>}
    </div>
  );
}

function FerDetail({
  detail,
}: {
  detail: FerTableDetail;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 1200 }}>
      <div style={{ ...PANEL, padding: "14px 16px" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
          <span
            style={{
              fontSize: 10,
              color: "var(--muted)",
              textTransform: "uppercase",
              letterSpacing: ".06em",
            }}
          >
            ФЕР {detail.collection.num}
          </span>
          <span style={{ fontSize: 15, fontWeight: 700 }}>{detail.table_title}</span>
        </div>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 8, fontSize: 12, color: "var(--muted)" }}>
          <span>Строк: <strong style={{ color: "var(--text)" }}>{detail.row_count}</strong></span>
          {detail.common_work_name && (
            <span>Общее наименование: <strong style={{ color: "var(--text)" }}>{detail.common_work_name}</strong></span>
          )}
        </div>
      </div>

      <div style={PANEL}>
        <div style={{ padding: "12px 16px 0", fontSize: 13, fontWeight: 600 }}>Строки таблицы</div>
        {detail.rows.length === 0 ? (
          <EmptyState label="В этой таблице нет строк" />
        ) : (
          <div style={{ overflowX: "auto", marginTop: 10 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 760 }}>
              <thead>
                <tr>
                  <th style={{ ...TH, width: 70 }}>№</th>
                  <th style={{ ...TH, minWidth: 360 }}>Уточнение</th>
                  <th style={{ ...TH, width: 120 }}>Чел.-ч</th>
                  <th style={{ ...TH, width: 120, borderRight: "none" }}>Маш.-ч</th>
                </tr>
              </thead>
              <tbody>
                {detail.rows.map((row, index) => (
                  <FerRowView key={row.id} row={row} index={index} commonWorkName={detail.common_work_name} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function FerRowView({
  row,
  index,
  commonWorkName,
}: {
  row: FerTableRow;
  index: number;
  commonWorkName: string | null;
}) {
  const prefix = commonWorkName?.trim() ?? "";
  const suffix = row.clarification?.trim() ?? "";

  return (
    <tr>
      <td style={{ ...TD, fontFamily: "var(--mono)", color: "var(--blue-dark)" }}>{index + 1}</td>
      <td style={{ ...TD, lineHeight: 1.45 }}>
        {prefix || suffix ? (
          <>
            {prefix && (
              <span style={{ color: "var(--muted)" }}>
                {prefix}
                {suffix ? " " : ""}
              </span>
            )}
            {suffix && <span>{suffix}</span>}
          </>
        ) : "—"}
      </td>
      <td style={{ ...TD, fontFamily: "var(--mono)" }}>{formatNumber(row.h_hour)}</td>
      <td style={{ ...TD, borderRight: "none", fontFamily: "var(--mono)" }}>{formatNumber(row.m_hour)}</td>
    </tr>
  );
}
