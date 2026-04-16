"use client";

import { useCallback, useEffect, useState } from "react";

import { admin as adminApi, ApiError } from "@/lib/api";
import type { FerKnowledgeImportJobStatus, FerKnowledgeImportResponse } from "@/lib/types";

function fmtDateTime(value?: string | null) {
  if (!value) {
    return "—";
  }
  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusTone(status: FerKnowledgeImportJobStatus["status"]) {
  if (status === "done") {
    return { color: "#15803d", bg: "#16a34a16", border: "#16a34a33", label: "Готово" };
  }
  if (status === "failed") {
    return { color: "#b91c1c", bg: "#ef444416", border: "#ef444433", label: "Ошибка" };
  }
  if (status === "processing") {
    return { color: "#b45309", bg: "#f59e0b16", border: "#f59e0b33", label: "Embedding..." };
  }
  return { color: "#475569", bg: "#64748b14", border: "#64748b2d", label: "В очереди" };
}

export default function AdminFerKnowledgePanel() {
  const [batchId, setBatchId] = useState("");
  const [imports, setImports] = useState<FerKnowledgeImportJobStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FerKnowledgeImportResponse | null>(null);

  const loadImports = useCallback(async () => {
    const response = await adminApi.listFerKnowledgeImports(10);
    setImports(response.items);
  }, []);

  useEffect(() => {
    setLoading(true);
    loadImports()
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Не удалось загрузить историю импортов");
      })
      .finally(() => setLoading(false));
  }, [loadImports]);

  useEffect(() => {
    const timer = setInterval(() => {
      loadImports().catch(() => undefined);
    }, 4000);
    return () => clearInterval(timer);
  }, [loadImports]);

  const submit = useCallback(async () => {
    const cleaned = batchId.trim();
    if (!cleaned) {
      setError("Укажите ID батча");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const response = await adminApi.importFerKnowledge(cleaned);
      setResult(response);
      setBatchId("");
      await loadImports();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Импорт не запустился");
      }
    } finally {
      setSubmitting(false);
    }
  }, [batchId, loadImports]);

  return (
    <div style={{ borderBottom: "1px solid var(--border)" }}>
      <div style={{ padding: "18px 20px", background: "#f8fafc", borderBottom: "1px solid var(--border)" }}>
        <div style={{ fontSize: 12, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 8 }}>
          FER / База знаний
        </div>
        <div style={{ fontSize: 20, fontWeight: 700, color: "var(--text)", marginBottom: 8 }}>
          Импорт эталонной сметы
        </div>
        <div style={{ fontSize: 13, color: "var(--muted)", maxWidth: 760, lineHeight: 1.5 }}>
          Импортирует все уже сопоставленные строки выбранного батча в эталонные пары. Для новых смет поиск сначала проверяет эту базу знаний и только потом идёт в обычный hybrid search.
        </div>
      </div>

      <div style={{ padding: 20, borderBottom: "1px solid var(--border)" }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <input
            value={batchId}
            onChange={(event) => setBatchId(event.target.value)}
            placeholder="ID батча"
            style={{
              width: 280,
              padding: "10px 12px",
              border: "1px solid var(--border2)",
              borderRadius: 8,
              fontSize: 14,
              outline: "none",
              background: "var(--surface)",
              fontFamily: "var(--mono)",
            }}
          />
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            style={{
              padding: "10px 16px",
              borderRadius: 8,
              border: "none",
              background: submitting ? "#94a3b8" : "var(--blue-dark)",
              color: "#fff",
              fontWeight: 600,
              cursor: submitting ? "default" : "pointer",
            }}
          >
            {submitting ? "Импорт..." : "Импортировать"}
          </button>
        </div>

        {error && (
          <div style={{ marginTop: 12, color: "#b91c1c", fontSize: 12 }}>
            {error}
          </div>
        )}

        {result && (
          <div
            style={{
              marginTop: 14,
              padding: "12px 14px",
              borderRadius: 10,
              border: "1px solid var(--border)",
              background: "#f8fafc",
              fontSize: 13,
              color: "var(--text)",
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 4 }}>
              Батч {result.batch_id}
            </div>
            <div>
              Совпавших строк: <strong>{result.total_matched_rows}</strong>, импортировано: <strong>{result.imported_count}</strong>, пропущено дублей: <strong>{result.skipped_duplicates}</strong>.
            </div>
            {result.reason === "no_matched_rows" && (
              <div style={{ marginTop: 4, color: "var(--muted)" }}>
                В батче нет строк с заполненным `fer_table_id`.
              </div>
            )}
            {result.status === "already_imported" && (
              <div style={{ marginTop: 4, color: "var(--muted)" }}>
                Новых примеров не появилось: все пары уже были в базе знаний.
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{ padding: 20 }}>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, color: "var(--text)" }}>
          Последние импорты
        </div>

        {loading ? (
          <div style={{ color: "var(--muted)", fontSize: 13 }}>Загрузка истории...</div>
        ) : imports.length === 0 ? (
          <div style={{ color: "var(--muted)", fontSize: 13 }}>Импортов пока не было.</div>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {imports.map((item) => {
              const tone = statusTone(item.status);
              return (
                <div
                  key={item.job_id}
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: 10,
                    padding: "12px 14px",
                    background: "var(--surface)",
                    display: "grid",
                    gridTemplateColumns: "1fr auto",
                    gap: 12,
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                      <span style={{ fontWeight: 600, color: "var(--text)" }}>
                        batch {item.batch_id}
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          padding: "2px 8px",
                          borderRadius: 999,
                          color: tone.color,
                          background: tone.bg,
                          border: `1px solid ${tone.border}`,
                        }}
                      >
                        {tone.label}
                      </span>
                    </div>
                    <div style={{ marginTop: 6, fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
                      {item.imported_count} строк импортировано, {item.embedded}/{item.total} с embedding, дублей пропущено {item.skipped_duplicates}. Запуск: {fmtDateTime(item.created_at)}
                    </div>
                    {item.error && (
                      <div style={{ marginTop: 4, fontSize: 12, color: "#b91c1c" }}>
                        {item.error}
                      </div>
                    )}
                  </div>

                  <div style={{ textAlign: "right", fontSize: 12, color: "var(--muted)", fontFamily: "var(--mono)" }}>
                    {item.failed_rows > 0 ? `errors ${item.failed_rows}` : `job ${item.job_id.slice(0, 8)}`}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
