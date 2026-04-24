"use client";

import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { useParams } from "next/navigation";

import { foremanReports, reports } from "@/lib/api";
import { fmtDate } from "@/lib/dateUtils";
import type {
  ForemanTaskReportEntry,
  JournalEntry,
  MaterialDelayJournalEntry,
  ScheduleBaselineJournalEntry,
  WorkJournalEntry,
} from "@/lib/types";

type SortKey = "event_date" | "man_hours";
type SortDirection = "asc" | "desc";

const TABLE_COLUMNS = "minmax(0, 1fr) 180px 160px";

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

const SORTABLE_HEADER_BUTTON_RIGHT: CSSProperties = {
  ...SORTABLE_HEADER_BUTTON,
  width: "100%",
  justifyContent: "flex-end",
};

function formatReportDate(iso: string) {
  if (!iso) return "—";
  return `${fmtDate(iso)}.${new Date(iso).getFullYear()}`;
}

function formatLabor(value: number | null) {
  if (value == null) return "";
  return value.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

function WorkRow({ entry, striped }: { entry: WorkJournalEntry; striped: boolean }) {
  const showDetails =
    entry.work_done &&
    entry.work_done.trim() &&
    entry.work_done.trim() !== entry.task_name.trim();

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: TABLE_COLUMNS,
        gap: 0,
        background: striped ? "#f8fafc" : "var(--surface)",
      }}
    >
      <div style={{ padding: "14px 16px", minWidth: 0 }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 999, background: "rgba(59,130,246,.08)", color: "var(--blue-dark)", fontFamily: "var(--mono)" }}>
            work
          </span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>{entry.task_name}</span>
        </div>
        {showDetails && (
          <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.45 }}>
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
          fontWeight: 600,
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
          fontWeight: 600,
          display: "flex",
          alignItems: "center",
        }}
      >
        {formatReportDate(entry.report_date)}
      </div>
    </div>
  );
}

function DelayRow({ entry, striped }: { entry: MaterialDelayJournalEntry; striped: boolean }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: TABLE_COLUMNS,
        gap: 0,
        background: striped ? "#fffaf0" : "#fffdf7",
      }}
    >
      <div style={{ padding: "14px 16px", minWidth: 0 }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 999, background: "rgba(245,158,11,.14)", color: "#92400e", fontFamily: "var(--mono)" }}>
            delay
          </span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>{entry.material_name}</span>
        </div>
        <div style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.45 }}>
          {entry.reason}
        </div>
        <div style={{ marginTop: 4, fontSize: 11, color: "var(--muted)" }}>
          {entry.old_delivery_date ? `${formatReportDate(entry.old_delivery_date)} → ` : ""}
          {formatReportDate(entry.new_delivery_date)}
          {entry.days_shifted != null ? ` · сдвиг ${entry.days_shifted} дн.` : ""}
          {entry.reporter?.name ? ` · ${entry.reporter.name}` : ""}
        </div>
      </div>
      <div
        style={{
          padding: "14px 16px",
          fontSize: 12,
          color: "#92400e",
          fontFamily: "var(--mono)",
          fontWeight: 700,
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-end",
        }}
      >
        {entry.days_shifted != null ? `+${entry.days_shifted} дн.` : "перенос"}
      </div>
      <div
        style={{
          padding: "14px 16px",
          fontSize: 12,
          color: "var(--text)",
          fontFamily: "var(--mono)",
          fontWeight: 600,
          display: "flex",
          alignItems: "center",
        }}
      >
        {formatReportDate(entry.report_date)}
      </div>
    </div>
  );
}

function BaselineRow({ entry, striped }: { entry: ScheduleBaselineJournalEntry; striped: boolean }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: TABLE_COLUMNS,
        gap: 0,
        background: striped ? "#f8fafc" : "#fdfdff",
      }}
    >
      <div style={{ padding: "14px 16px", minWidth: 0 }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 10, padding: "2px 7px", borderRadius: 999, background: "rgba(15,23,42,.08)", color: "#0f172a", fontFamily: "var(--mono)" }}>
            baseline
          </span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>
            Просроченный график принят как текущий
          </span>
        </div>
        <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.45 }}>
          Неделя {entry.baseline_week}/{entry.baseline_year}
          {entry.created_by?.name ? ` · ${entry.created_by.name}` : ""}
          {entry.reason ? ` · ${entry.reason}` : ""}
        </div>
      </div>
      <div
        style={{
          padding: "14px 16px",
          fontSize: 12,
          color: "#0f172a",
          fontFamily: "var(--mono)",
          fontWeight: 700,
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-end",
        }}
      >
        W{entry.baseline_week}
      </div>
      <div
        style={{
          padding: "14px 16px",
          fontSize: 12,
          color: "var(--text)",
          fontFamily: "var(--mono)",
          fontWeight: 600,
          display: "flex",
          alignItems: "center",
        }}
      >
        {formatReportDate(entry.report_date)}
      </div>
    </div>
  );
}

const FOREMAN_STATUS_CONFIG: Record<string, { label: string; icon: string; color: string; bg: string }> = {
  done_as_planned: { label: "Выполнил по плану", icon: "✅", color: "#15803d", bg: "rgba(22,163,74,.10)" },
  done_not_as_planned: { label: "Выполнил не по плану", icon: "⚠️", color: "#92400e", bg: "rgba(217,119,6,.10)" },
  not_done: { label: "Не выполнил", icon: "❌", color: "#b91c1c", bg: "rgba(220,38,38,.10)" },
  pending: { label: "Ожидает ответа", icon: "🕐", color: "#6b7280", bg: "rgba(107,114,128,.10)" },
};

function ForemanReportRow({ entry, striped }: { entry: ForemanTaskReportEntry; striped: boolean }) {
  const cfg = FOREMAN_STATUS_CONFIG[entry.status] ?? FOREMAN_STATUS_CONFIG.pending;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: TABLE_COLUMNS,
        gap: 0,
        background: striped ? "#f9fafb" : "#ffffff",
      }}
    >
      <div style={{ padding: "14px 16px", minWidth: 0 }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span
            style={{
              fontSize: 10,
              padding: "2px 7px",
              borderRadius: 999,
              background: "rgba(99,102,241,.10)",
              color: "#4338ca",
              fontFamily: "var(--mono)",
            }}
          >
            прораб
          </span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>
            {entry.task_name ?? "—"}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              fontSize: 12,
              fontWeight: 600,
              padding: "3px 10px",
              borderRadius: 999,
              background: cfg.bg,
              color: cfg.color,
            }}
          >
            <span>{cfg.icon}</span>
            <span>{cfg.label}</span>
          </span>
          {entry.foreman_name && (
            <span style={{ fontSize: 11, color: "var(--muted)" }}>{entry.foreman_name}</span>
          )}
        </div>
        {entry.note && (
          <div style={{ marginTop: 5, fontSize: 12, color: "var(--muted)", lineHeight: 1.4 }}>
            {entry.note}
          </div>
        )}
      </div>
      <div style={{ padding: "14px 16px" }} />
      <div
        style={{
          padding: "14px 16px",
          fontSize: 12,
          color: "var(--text)",
          fontFamily: "var(--mono)",
          fontWeight: 600,
          display: "flex",
          alignItems: "center",
        }}
      >
        {formatReportDate(entry.report_date)}
      </div>
    </div>
  );
}

export default function JournalPage() {
  const { id } = useParams<{ id: string }>();
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("event_date");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  useEffect(() => {
    let cancelled = false;

    Promise.all([
      reports.journal(id),
      foremanReports.list(id).catch(() => [] as any[]),
    ])
      .then(([journalData, foremanData]) => {
        if (cancelled) return;

        const foremanEntries: ForemanTaskReportEntry[] = (foremanData as any[]).map((report) => ({
          entry_type: "foreman_report",
          id: report.id,
          report_date: report.report_date,
          event_date: report.responded_at ?? report.email_sent_at ?? `${report.report_date}T00:00:00`,
          status: report.status,
          status_label: report.status_label,
          note: report.note ?? null,
          task_id: report.task_id,
          task_name: report.task_name ?? null,
          foreman_id: report.foreman_id,
          foreman_name: report.foreman_name ?? null,
          email_sent_at: report.email_sent_at ?? null,
          responded_at: report.responded_at ?? null,
        }));

        setEntries([...journalData, ...foremanEntries]);
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

  const sortedEntries = useMemo(() => [...entries].sort((left, right) => {
    let comparison = 0;

    if (sortKey === "event_date") {
      comparison = new Date(left.event_date).getTime() - new Date(right.event_date).getTime();
    } else {
      const leftHours = left.entry_type === "work" ? (left.man_hours ?? Number.NEGATIVE_INFINITY) : Number.NEGATIVE_INFINITY;
      const rightHours = right.entry_type === "work" ? (right.man_hours ?? Number.NEGATIVE_INFINITY) : Number.NEGATIVE_INFINITY;
      comparison = leftHours - rightHours;
    }

    return sortDirection === "asc" ? comparison : -comparison;
  }), [entries, sortDirection, sortKey]);

  function renderSortLabel(title: string, key: SortKey) {
    const isActive = sortKey === key;
    const arrow = !isActive ? "↕" : sortDirection === "asc" ? "↑" : "↓";
    const buttonStyle = key === "man_hours" ? SORTABLE_HEADER_BUTTON_RIGHT : SORTABLE_HEADER_BUTTON;

    return (
      <button type="button" onClick={() => toggleSort(key)} style={buttonStyle}>
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
                fontWeight: 600,
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
                fontWeight: 600,
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
                fontWeight: 600,
              }}
            >
              {renderSortLabel("Дата", "event_date")}
            </div>
          </div>

          {sortedEntries.length === 0 ? (
            <div style={{ padding: 24, color: "var(--muted)" }}>В журнале пока нет записей.</div>
          ) : (
            sortedEntries.map((entry, index) => (
              <div key={entry.id} style={{ borderBottom: index === sortedEntries.length - 1 ? "none" : "1px solid var(--border)" }}>
                {entry.entry_type === "work" && <WorkRow entry={entry} striped={index % 2 === 1} />}
                {entry.entry_type === "material_delay" && <DelayRow entry={entry} striped={index % 2 === 1} />}
                {entry.entry_type === "schedule_baseline" && <BaselineRow entry={entry} striped={index % 2 === 1} />}
                {entry.entry_type === "foreman_report" && <ForemanReportRow entry={entry} striped={index % 2 === 1} />}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
