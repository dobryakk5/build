// frontend/components/ColumnMapper.tsx
"use client";

import { useState } from "react";

// ─── типы ────────────────────────────────────────────────────────────────────

export interface MappingPayload {
  needs_mapping: true;
  filename:      string;
  sheet:         string;
  preview_rows:  string[][];
  col_count:     number;
  tmp_path:      string;
}

interface Props {
  payload:    MappingPayload;
  projectId:  string;
  startDate:  string;
  workers:    number;
  onConfirm:  (jobId: string) => void;
  onCancel:   () => void;
}

// ─── константы ───────────────────────────────────────────────────────────────

const FIELDS = [
  { key: "skip",        label: "— не импортировать" },
  { key: "work_name",   label: "Наименование" },
  { key: "unit",        label: "Ед. измерения" },
  { key: "quantity",    label: "Количество" },
  { key: "unit_price",  label: "Цена за ед." },
  { key: "total_price", label: "Сумма" },
] as const;

type FieldKey = typeof FIELDS[number]["key"];

function fieldLabel(key: FieldKey) {
  return FIELDS.find(f => f.key === key)?.label ?? key;
}

// ─── компонент ───────────────────────────────────────────────────────────────

export default function ColumnMapper({
  payload,
  projectId,
  startDate,
  workers,
  onConfirm,
  onCancel,
}: Props) {
  const { filename, sheet, preview_rows, col_count, tmp_path } = payload;

  // Начальный маппинг: пытаемся угадать по кол-ву колонок
  const defaultMapping = (): FieldKey[] => {
    const defaults: FieldKey[] = ["work_name", "unit", "quantity", "unit_price", "total_price"];
    const result: FieldKey[] = Array(col_count).fill("skip" as FieldKey);
    defaults.slice(0, col_count).forEach((f, i) => { result[i] = f; });
    return result;
  };

  const [mapping, setMapping]   = useState<FieldKey[]>(defaultMapping);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);

  // ── маппинг ──────────────────────────────────────────────────────────────

  function setCol(idx: number, value: FieldKey) {
    setMapping(prev => {
      const next = [...prev];
      // Если эта роль уже занята другой колонкой — сбрасываем её
      if (value !== "skip") {
        const existing = next.indexOf(value);
        if (existing !== -1 && existing !== idx) next[existing] = "skip";
      }
      next[idx] = value;
      return next;
    });
  }

  const workMapped = mapping.includes("work_name");

  // ── подтверждение ─────────────────────────────────────────────────────────

  async function confirm() {
    if (!workMapped) {
      setError("Назначьте колонку «Наименование» перед импортом.");
      return;
    }

    // col_mapping: {col_0based: field_key} — только не-skip колонки
    const col_mapping: Record<number, string> = {};
    mapping.forEach((f, i) => { if (f !== "skip") col_mapping[i] = f; });

    setLoading(true);
    setError(null);

    try {
      const token = localStorage.getItem("access_token");
      const res = await fetch(`/api/projects/${projectId}/estimates/upload/confirm-mapping`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          tmp_path,
          sheet,
          col_mapping,
          start_date: startDate,
          workers,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err?.detail ?? `HTTP ${res.status}`);
      }

      const job = await res.json();
      onConfirm(job.id);
    } catch (e: any) {
      setError(e.message ?? "Ошибка при отправке");
    } finally {
      setLoading(false);
    }
  }

  // ── render ────────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: "1.25rem 0" }}>
      {/* Заголовок */}
      <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 4 }}>
        {filename} — лист «{sheet}»
      </p>
      <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginBottom: 12 }}>
        Не удалось автоматически определить колонки. Назначьте роль каждой:
      </p>

      {/* Таблица */}
      <div style={{ overflowX: "auto", marginBottom: "1.5rem" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr>
              {mapping.map((role, i) => (
                <th
                  key={i}
                  style={{
                    padding: 0,
                    border: "0.5px solid var(--color-border-tertiary)",
                    background: "var(--color-background-secondary)",
                  }}
                >
                  <select
                    value={role}
                    onChange={e => setCol(i, e.target.value as FieldKey)}
                    style={{
                      width: "100%",
                      border: "none",
                      background: "transparent",
                      fontSize: 12,
                      fontWeight: 500,
                      color: role === "skip" ? "var(--color-text-tertiary)" : "#0F6E56",
                      padding: "8px 10px",
                      outline: "none",
                      cursor: "pointer",
                    }}
                  >
                    {FIELDS.map(f => (
                      <option key={f.key} value={f.key}>{f.label}</option>
                    ))}
                  </select>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview_rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    style={{
                      border: "0.5px solid var(--color-border-tertiary)",
                      padding: "6px 10px",
                      color: mapping[ci] === "skip"
                        ? "var(--color-text-tertiary)"
                        : "var(--color-text-primary)",
                      textDecoration: mapping[ci] === "skip" ? "line-through" : "none",
                    }}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Действия */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button
          onClick={confirm}
          disabled={loading || !workMapped}
          style={{
            fontSize: 13,
            padding: "8px 20px",
            borderRadius: "var(--border-radius-md)",
            border: "0.5px solid var(--color-border-secondary)",
            background: "var(--color-background-primary)",
            color: "var(--color-text-primary)",
            cursor: loading || !workMapped ? "not-allowed" : "pointer",
            opacity: !workMapped ? 0.5 : 1,
          }}
        >
          {loading ? "Импорт..." : "Подтвердить и импортировать"}
        </button>

        <button
          onClick={onCancel}
          style={{
            fontSize: 13,
            padding: "8px 16px",
            borderRadius: "var(--border-radius-md)",
            border: "none",
            background: "transparent",
            color: "var(--color-text-secondary)",
            cursor: "pointer",
          }}
        >
          Отмена
        </button>

        {!workMapped && (
          <span style={{
            fontSize: 11,
            padding: "2px 8px",
            borderRadius: "var(--border-radius-md)",
            background: "var(--color-background-warning)",
            color: "var(--color-text-warning)",
          }}>
            назначьте колонку «Наименование»
          </span>
        )}

        {error && (
          <span style={{ fontSize: 12, color: "var(--color-text-danger)" }}>{error}</span>
        )}
      </div>
    </div>
  );
}
