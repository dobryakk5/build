"use client";

import { useEffect, useState } from "react";
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

function formatReportDate(iso: string) {
  if (!iso) return "—";
  return `${fmtDate(iso)}.${new Date(iso).getFullYear()}`;
}

function formatLabor(entry: JournalEntry) {
  if (entry.man_hours == null) return "—";
  return `${entry.man_hours.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} чел-ч`;
}

export default function JournalPage() {
  const { id } = useParams<{ id: string }>();
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  if (loading) {
    return <div style={{ padding: 24, color: "var(--muted)" }}>Загрузка журнала...</div>;
  }

  if (error) {
    return <div style={{ padding: 24, color: "#dc2626" }}>{error}</div>;
  }

  return (
    <div style={{ height: "100%", overflow: "auto", padding: 20, background: "#f8fafc" }}>
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
            gridTemplateColumns: "minmax(0, 1fr) 180px 140px",
            gap: 0,
            background: "#f8fafc",
            borderBottom: "1px solid var(--border)",
          }}
        >
          {["Название", "Трудозатраты", "Дата"].map((title) => (
            <div
              key={title}
              style={{
                padding: "12px 16px",
                fontSize: 10,
                color: "var(--muted)",
                textTransform: "uppercase",
                letterSpacing: ".08em",
                fontFamily: "var(--mono)",
              }}
            >
              {title}
            </div>
          ))}
        </div>

        {entries.length === 0 ? (
          <div style={{ padding: 24, color: "var(--muted)" }}>В журнале пока нет выполненных работ.</div>
        ) : (
          entries.map((entry, index) => {
            const showDetails =
              entry.work_done &&
              entry.work_done.trim() &&
              entry.work_done.trim() !== entry.task_name.trim();

            return (
              <div
                key={entry.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(0, 1fr) 180px 140px",
                  gap: 0,
                  borderBottom: index === entries.length - 1 ? "none" : "1px solid var(--border)",
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
                  }}
                >
                  {formatLabor(entry)}
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
  );
}
