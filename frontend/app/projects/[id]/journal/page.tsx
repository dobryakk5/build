"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { useParams } from "next/navigation";
import { reports } from "@/lib/api";
import { fmtDate } from "@/lib/dateUtils";

type JournalEntry = {
  id: string;
  report_id: string | null;
  task_id: string;
  task_name: string;
  work_done: string;
  man_hours: number | null;
  workers_count: number | null;
  volume_done: number | null;
  volume_unit: string | null;
  report_date: string;
};

type SortKey = "report_date" | "man_hours";
type SortDirection = "asc" | "desc";

const TABLE_COLUMNS = "minmax(0, 1fr) 180px 140px";

const SORTABLE_HEADER_BUTTON: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: 0,
  border: "none",
  background: "transparent",
  color: "inherit",
  font: "inherit",
  textTransform: "inherit",
  letterSpacing: "inherit",
  cursor: "pointer",
};

function formatReportDate(iso: string) {
  if (!iso) return "—";
  return `${fmtDate(iso)}.${new Date(iso).getFullYear()}`;
}

function formatLabor(value: number | null) {
  if (value == null) return "";
  return value.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

export default function JournalPage() {
  const { id } = useParams<{ id: string }>();
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("report_date");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  useEffect(() => {
    let cancelled = false;

    reports.journal(id)
      .then((data) => {
        if (cancelled) return;
        setEntries(data);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || "Не удалось загрузить журнал");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  function toggleSort(nextKey: SortKey) {
    if (nextKey === sortKey) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }

    setSortKey(nextKey);
    setSortDirection("desc");
  }

  const sortedEntries = [...entries].sort((left, right) => {
    let comparison = 0;

    if (sortKey === "report_date") {
      comparison = new Date(left.report_date).getTime() - new Date(right.report_date).getTime();
    } else {
      const leftHours = left.man_hours ?? Number.NEGATIVE_INFINITY;
      const rightHours = right.man_hours ?? Number.NEGATIVE_INFINITY;
      comparison = leftHours - rightHours;
    }

    return sortDirection === "asc" ? comparison : -comparison;
  });

  function renderSortLabel(title: string, key: SortKey) {
    const isActive = sortKey === key;
    const arrow = !isActive ? "↕" : sortDirection === "asc" ? "↑" : "↓";

    return (
      <button type="button" onClick={() => toggleSort(key)} style={SORTABLE_HEADER_BUTTON}>
        <span>{title}</span>
        <span aria-hidden="true" style={{ fontSize: 11, lineHeight: 1 }}>
          {arrow}
        </span>
      </button>
    );
  }

  if (loading) {
    return <div style={{ padding: 24, color: "var(--muted)" }}>Загрузка журнала...</div>;
  }

  if (error) {
    return <div style={{ padding: 24, color: "#dc2626" }}>{error}</div>;
  }

  return (
    <div style={{ height: "100%", overflow: "auto", padding: 20, background: "#f8fafc" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 1200 }}>
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 10,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: TABLE_COLUMNS,
              gap: 0,
              background: "#f8fafc",
              borderBottom: "1px solid var(--border)",
            }}
          >
            <div
              style={{
                padding: "12px 16px",
                fontSize: 10,
                color: "var(--muted)",
                textTransform: "uppercase",
                letterSpacing: ".08em",
                fontFamily: "var(--mono)",
              }}
            >
              Название
            </div>
            <div
              style={{
                padding: "12px 16px",
                fontSize: 10,
                color: "var(--muted)",
                textTransform: "uppercase",
                letterSpacing: ".08em",
                fontFamily: "var(--mono)",
              }}
            >
              {renderSortLabel("чел. часов", "man_hours")}
            </div>
            <div
              style={{
                padding: "12px 16px",
                fontSize: 10,
                color: "var(--muted)",
                textTransform: "uppercase",
                letterSpacing: ".08em",
                fontFamily: "var(--mono)",
              }}
            >
              {renderSortLabel("Дата", "report_date")}
            </div>
          </div>

          {sortedEntries.length === 0 ? (
            <div style={{ padding: 24, color: "var(--muted)" }}>В журнале пока нет выполненных работ.</div>
          ) : (
            sortedEntries.map((entry, index) => {
              const showDetails =
                entry.work_done &&
                entry.work_done.trim() &&
                entry.work_done.trim() !== entry.task_name.trim();

              return (
                <div
                  key={entry.id}
                  style={{
                    display: "grid",
                    gridTemplateColumns: TABLE_COLUMNS,
                    gap: 0,
                    borderBottom: index === sortedEntries.length - 1 ? "none" : "1px solid var(--border)",
                    background: index % 2 ? "#f8fafc" : "var(--surface)",
                  }}
                >
                  <div style={{ padding: "14px 16px", minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 13,
                        fontWeight: 600,
                        color: "var(--text)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {entry.task_name}
                    </div>
                    {showDetails && (
                      <div style={{ marginTop: 4, fontSize: 12, color: "var(--muted)", lineHeight: 1.45 }}>
                        {entry.work_done}
                      </div>
                    )}
                  </div>

                  <div
                    style={{
                      padding: "14px 16px",
                      fontSize: 12,
                      color: "var(--text)",
                      fontFamily: "var(--mono)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "flex-end",
                    }}
                  >
                    {formatLabor(entry.man_hours)}
                  </div>

                  <div
                    style={{
                      padding: "14px 16px",
                      fontSize: 12,
                      color: "var(--text)",
                      fontFamily: "var(--mono)",
                      display: "flex",
                      alignItems: "center",
                    }}
                  >
                    {formatReportDate(entry.report_date)}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
