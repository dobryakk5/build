"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { estimates, fer as ferApi } from "@/lib/api";
import { fmtMoney } from "@/lib/dateUtils";
import type { EstimateBatch, EstimateMaterial, EstimateRow, EstimateSummary, FerSearchResult, FerTableDetail, FerWordsCandidate } from "@/lib/types";
import { useJobPoller } from "@/lib/useJobPoller";

type ActFlagsPatch = {
  req_hidden_work_act?: boolean;
  req_intermediate_act?: boolean;
  req_ks2_ks3?: boolean;
};

type PopupState = {
  estimateId: string;
  top: number;
  left: number;
};

type FerTableInfo = {
  id: number;
  table_title: string;
  common_work_name: string | null;
  collection_id: number;
  collection_num: string;
  collection_name: string;
  section_id: number | null;
  section_title: string | null;
  subsection_id: number | null;
  subsection_title: string | null;
  ignored: boolean;
  effective_ignored: boolean;
};

const tableHeaders = [
  "Наименование работ",
  "Материалы",
  "Акты",
  "Тип работ ФЕР",
  "ФЕР слова",
  "Ед.",
  "Кол-во",
  "Цена за ед., ₽",
  "Сумма, ₽",
];

function fmtQuantity(value?: number | null) {
  return value == null ? "—" : value.toLocaleString("ru-RU");
}

function materialMeta(material: EstimateMaterial) {
  const parts: string[] = [];
  if (material.quantity != null) {
    parts.push(material.unit ? `${fmtQuantity(material.quantity)} ${material.unit}` : fmtQuantity(material.quantity));
  } else if (material.unit) {
    parts.push(material.unit);
  }
  if (material.total_price != null) {
    parts.push(`${fmtMoney(material.total_price)} ₽`);
  } else if (material.unit_price != null) {
    parts.push(`${fmtMoney(material.unit_price)} ₽/ед.`);
  }
  return parts.join(" · ");
}

function countSelectedActs(row: EstimateRow) {
  return [row.req_hidden_work_act, row.req_intermediate_act, row.req_ks2_ks3].filter(Boolean).length;
}

function FerIgnoreBadge({
  ignored,
  effectiveIgnored,
}: {
  ignored?: boolean;
  effectiveIgnored?: boolean;
}) {
  if (!effectiveIgnored) {
    return null;
  }

  return (
    <span
      style={{
        fontSize: 9,
        padding: "1px 5px",
        borderRadius: 999,
        background: ignored ? "#ef444416" : "#f59e0b16",
        color: ignored ? "#991b1b" : "#b45309",
        border: `1px solid ${ignored ? "#ef444435" : "#f59e0b35"}`,
        fontWeight: 700,
      }}
    >
      {ignored ? "ИГНОР" : "ИГНОР ПО РОДИТЕЛЮ"}
    </span>
  );
}

function ActsPopup({
  row,
  top,
  left,
  saving,
  onClose,
  onSave,
}: {
  row: EstimateRow;
  top: number;
  left: number;
  saving: boolean;
  onClose: () => void;
  onSave: (patch: ActFlagsPatch) => Promise<void>;
}) {
  const popupRef = useRef<HTMLDivElement | null>(null);
  const [draft, setDraft] = useState({
    req_hidden_work_act: Boolean(row.req_hidden_work_act),
    req_intermediate_act: Boolean(row.req_intermediate_act),
    req_ks2_ks3: Boolean(row.req_ks2_ks3),
  });

  useEffect(() => {
    setDraft({
      req_hidden_work_act: Boolean(row.req_hidden_work_act),
      req_intermediate_act: Boolean(row.req_intermediate_act),
      req_ks2_ks3: Boolean(row.req_ks2_ks3),
    });
  }, [row.id, row.req_hidden_work_act, row.req_intermediate_act, row.req_ks2_ks3]);

  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (!popupRef.current?.contains(event.target as Node)) {
        onClose();
      }
    };
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onEsc);
    };
  }, [onClose]);

  return (
    <div
      ref={popupRef}
      style={{
        position: "fixed",
        top,
        left,
        width: 280,
        zIndex: 40,
        background: "var(--surface)",
        border: "1px solid var(--border2)",
        boxShadow: "0 12px 30px rgba(15,23,42,.18)",
        borderRadius: 10,
        padding: 14,
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 10 }}>Отметки актов</div>
      <div style={{ display: "grid", gap: 10 }}>
        {([
          ["req_hidden_work_act", "Акты скрытых работ с приглашением технадзора"],
          ["req_intermediate_act", "Акты промежуточного выполнения работ"],
          ["req_ks2_ks3", "КС-2, КС-3 и исполнительная съемка по этапу"],
        ] as const).map(([key, label]) => (
          <label key={key} style={{ display: "flex", gap: 10, alignItems: "flex-start", fontSize: 12, lineHeight: 1.35 }}>
            <input type="checkbox" checked={draft[key]} onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.checked }))} />
            <span>{label}</span>
          </label>
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
        <button onClick={onClose} style={{ padding: "7px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", cursor: "pointer", fontSize: 12 }}>
          Закрыть
        </button>
        <button
          disabled={saving}
          onClick={() => onSave(draft)}
          style={{
            padding: "7px 12px",
            borderRadius: 8,
            border: "1px solid rgba(59,130,246,.18)",
            background: "rgba(59,130,246,.08)",
            color: "var(--blue-dark)",
            cursor: saving ? "default" : "pointer",
            opacity: saving ? 0.7 : 1,
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          {saving ? "Сохраняем..." : "Сохранить"}
        </button>
      </div>
    </div>
  );
}

function ActsCell({
  row,
  onOpen,
}: {
  row: EstimateRow;
  onOpen: (event: ReactMouseEvent<HTMLButtonElement>, row: EstimateRow) => void;
}) {
  const count = countSelectedActs(row);
  return (
    <button
      type="button"
      onClick={(event) => onOpen(event, row)}
      style={{
        padding: "6px 10px",
        borderRadius: 999,
        border: count > 0 ? "1px solid rgba(59,130,246,.22)" : "1px solid var(--border)",
        background: count > 0 ? "rgba(59,130,246,.08)" : "var(--surface)",
        color: count > 0 ? "var(--blue-dark)" : "var(--muted)",
        cursor: "pointer",
        fontSize: 11,
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      {count > 0 ? `Акты ${count}/3` : "Акты"}
    </button>
  );
}

function FerSearchModal({
  row,
  onClose,
  onSelect,
}: {
  row: EstimateRow;
  onClose: () => void;
  onSelect: (result: FerSearchResult | null) => Promise<void>;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<FerSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    if (debounce.current) {
      clearTimeout(debounce.current);
    }
    debounce.current = setTimeout(async () => {
      setSearching(true);
      try {
        const data = await ferApi.search(q.trim(), 40);
        setResults(data as FerSearchResult[]);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 320);
    return () => {
      if (debounce.current) {
        clearTimeout(debounce.current);
      }
    };
  }, [q]);

  useEffect(() => {
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [onClose]);

  async function pick(result: FerSearchResult | null) {
    if (result?.effective_ignored) {
      return;
    }
    setSaving(true);
    try {
      await onSelect(result);
    } finally {
      setSaving(false);
    }
  }

  const breadcrumb = (result: FerSearchResult) =>
    [`Сб. ${result.collection.num}`, result.section?.title, result.subsection?.title].filter(Boolean).join(" › ");

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,.55)",
        zIndex: 100,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        style={{
          width: 700,
          maxHeight: "82vh",
          background: "var(--surface)",
          borderRadius: 12,
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 24px 64px rgba(0,0,0,.28)",
          overflow: "hidden",
        }}
      >
        <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 3 }}>Маппинг ФЕР</div>
            <div style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.4 }}>
              Работа: <strong style={{ color: "var(--text)" }}>{row.work_name}</strong>
            </div>
            {row.fer_work_type && (
              <div style={{ marginTop: 4, fontSize: 11, color: "var(--muted)" }}>
                Текущий тип: <span style={{ color: "var(--blue-dark)", fontWeight: 500 }}>{row.fer_work_type}</span>
              </div>
            )}
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--muted)", fontSize: 18, lineHeight: 1 }}>
            ✕
          </button>
        </div>

        <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border)" }}>
          <input
            autoFocus
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Поиск по названию работы, разделу, сборнику ФЕР..."
            style={{
              width: "100%",
              padding: "9px 14px",
              boxSizing: "border-box",
              border: "1px solid var(--border2)",
              borderRadius: 7,
              fontSize: 13,
              outline: "none",
              background: "var(--bg)",
            }}
          />
        </div>

        <div style={{ flex: 1, overflowY: "auto" }}>
          {searching && <div style={{ padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>Поиск...</div>}
          {!searching && q.length >= 2 && results.length === 0 && <div style={{ padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>Ничего не найдено</div>}
          {!searching && q.length < 2 && <div style={{ padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>Введите минимум 2 символа</div>}

          {results.map((result) => (
            <div
              key={result.table_id}
              onClick={() => !saving && !result.effective_ignored && pick(result)}
              style={{
                padding: "12px 20px",
                borderBottom: "1px solid var(--border)",
                cursor: saving || result.effective_ignored ? "default" : "pointer",
                transition: "background .1s",
                opacity: result.effective_ignored ? 0.5 : 1,
                background: result.effective_ignored ? "rgba(148,163,184,.06)" : "transparent",
              }}
              onMouseEnter={(event) => {
                if (!result.effective_ignored) {
                  event.currentTarget.style.background = "rgba(59,130,246,.05)";
                }
              }}
              onMouseLeave={(event) => {
                event.currentTarget.style.background = result.effective_ignored ? "rgba(148,163,184,.06)" : "transparent";
              }}
            >
              <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 4, fontFamily: "var(--mono)" }}>{breadcrumb(result)}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: result.common_work_name ? 3 : 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{result.table_title}</div>
                <FerIgnoreBadge ignored={result.ignored} effectiveIgnored={result.effective_ignored} />
              </div>
              {result.common_work_name && <div style={{ fontSize: 12, color: "var(--muted)" }}>{result.common_work_name}</div>}
              <div style={{ marginTop: 4, display: "flex", gap: 10, fontSize: 10, color: "var(--muted)" }}>
                <span style={{ fontFamily: "var(--mono)" }}>{result.row_count} строк</span>
                {result.table_url && <span style={{ fontFamily: "var(--mono)", color: "var(--blue)" }}>{result.table_url}</span>}
                {result.matched_text && result.match_scope !== "table_title" && <span>совпадение: «{result.matched_text}»</span>}
              </div>
              {result.effective_ignored && (
                <div style={{ marginTop: 6, fontSize: 10, color: "#b45309" }}>
                  Таблица помечена как игнорируемая и недоступна для назначения.
                </div>
              )}
            </div>
          ))}
        </div>

        {row.fer_table_id && (
          <div style={{ padding: "10px 20px", borderTop: "1px solid var(--border)", background: "#fef9f9" }}>
            <button
              onClick={() => !saving && pick(null)}
              disabled={saving}
              style={{
                background: "none",
                border: "1px solid #ef444440",
                borderRadius: 6,
                padding: "6px 14px",
                color: "#ef4444",
                cursor: saving ? "not-allowed" : "pointer",
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              Сбросить маппинг ФЕР
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function FerCell({
  row,
  onOpenModal,
}: {
  row: EstimateRow;
  onOpenModal: (row: EstimateRow) => void;
}) {
  const [tableInfo, setTableInfo] = useState<FerTableInfo | null>(null);
  const [hovered, setHovered] = useState(false);
  const [tooltipPos, setTooltipPos] = useState({ top: 0, left: 0 });
  const cellRef = useRef<HTMLTableCellElement>(null);
  const fetchedId = useRef<number | null>(null);

  async function onHover() {
    setHovered(true);
    if (row.fer_table_id && fetchedId.current !== row.fer_table_id) {
      try {
        const data = await ferApi.table(row.fer_table_id);
        const detail = data as FerTableDetail & {
          collection_id?: number;
          collection_num?: string;
          collection_name?: string;
          section_id?: number | null;
          section_title?: string | null;
          subsection_id?: number | null;
          subsection_title?: string | null;
        };
        setTableInfo({
          id: detail.id,
          table_title: detail.table_title,
          common_work_name: detail.common_work_name,
          collection_id: detail.collection?.id ?? detail.collection_id ?? 0,
          collection_num: detail.collection?.num ?? detail.collection_num ?? "",
          collection_name: detail.collection?.name ?? detail.collection_name ?? "",
          section_id: detail.section?.id ?? detail.section_id ?? null,
          section_title: detail.section?.title ?? detail.section_title ?? null,
          subsection_id: detail.subsection?.id ?? detail.subsection_id ?? null,
          subsection_title: detail.subsection?.title ?? detail.subsection_title ?? null,
          ignored: detail.ignored ?? false,
          effective_ignored: detail.effective_ignored ?? false,
        });
        fetchedId.current = row.fer_table_id;
      } catch {}
    }
    if (cellRef.current) {
      const rect = cellRef.current.getBoundingClientRect();
      setTooltipPos({ top: rect.bottom + 6, left: Math.min(rect.left, window.innerWidth - 340) });
    }
  }

  const isManual = row.fer_table_id && (row.fer_match_score ?? 0) >= 1.0;
  const isLow = row.fer_table_id && (row.fer_match_score ?? 0) < 0.45;

  return (
    <td
      ref={cellRef}
      onMouseEnter={onHover}
      onMouseLeave={() => setHovered(false)}
      onClick={() => onOpenModal(row)}
      style={{
        padding: "8px 12px",
        borderBottom: "1px solid var(--border)",
        cursor: "pointer",
        position: "relative",
        background: !row.fer_table_id ? "rgba(239,68,68,.03)" : isLow ? "rgba(245,158,11,.05)" : "transparent",
      }}
    >
      {row.fer_work_type ? (
        <>
          <div style={{ fontSize: 12, lineHeight: 1.4, maxWidth: 200 }}>{row.fer_work_type}</div>
          <div style={{ marginTop: 3, display: "flex", gap: 6, alignItems: "center" }}>
            {isManual ? (
              <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: "#22c55e18", color: "#16a34a", border: "1px solid #22c55e30", fontWeight: 700 }}>
                ✎ РУЧНОЙ
              </span>
            ) : (
              <span style={{ fontSize: 9, color: "var(--muted)", fontFamily: "var(--mono)" }}>score {(row.fer_match_score ?? 0).toFixed(2)}</span>
            )}
            {tableInfo?.effective_ignored && <FerIgnoreBadge ignored={tableInfo.ignored} effectiveIgnored={tableInfo.effective_ignored} />}
            {row.fer_table_id && <span style={{ fontSize: 9, color: "var(--muted)", fontFamily: "var(--mono)" }}>#{row.fer_table_id}</span>}
          </div>
        </>
      ) : (
        <span style={{ fontSize: 11, color: "#ef4444", fontStyle: "italic", display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 13 }}>＋</span> Назначить ФЕР
        </span>
      )}

      {hovered && row.fer_table_id && tableInfo && (
        <div
          style={{
            position: "fixed",
            top: tooltipPos.top,
            left: tooltipPos.left,
            zIndex: 60,
            width: 320,
            background: "#0f172a",
            borderRadius: 8,
            padding: "12px 14px",
            boxShadow: "0 12px 32px rgba(0,0,0,.35)",
            pointerEvents: "none",
          }}
        >
          <div style={{ fontSize: 10, color: "#64748b", marginBottom: 8, lineHeight: 1.6 }}>
            {[`Сборник ${tableInfo.collection_num}. ${tableInfo.collection_name}`, tableInfo.section_title, tableInfo.subsection_title]
              .filter(Boolean)
              .map((item, index, items) => (
                <span key={index}>
                  <span style={{ color: index === items.length - 1 ? "#94a3b8" : "#64748b" }}>{item}</span>
                  {index < items.length - 1 && <span style={{ color: "#334155" }}> › </span>}
                </span>
              ))}
          </div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#e2e8f0", marginBottom: tableInfo.common_work_name ? 4 : 0 }}>{tableInfo.table_title}</div>
          {tableInfo.effective_ignored && (
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: tableInfo.common_work_name ? 4 : 0 }}>
              <FerIgnoreBadge ignored={tableInfo.ignored} effectiveIgnored={tableInfo.effective_ignored} />
            </div>
          )}
          {tableInfo.common_work_name && <div style={{ fontSize: 11, color: "#94a3b8" }}>{tableInfo.common_work_name}</div>}
          <div style={{ marginTop: 8, fontSize: 10, color: "#475569" }}>Нажмите для изменения маппинга</div>
        </div>
      )}
    </td>
  );
}

function FerWordsCell({
  row,
  onOpenModal,
}: {
  row: EstimateRow;
  onOpenModal: (row: EstimateRow) => void;
}) {
  const matchedCount = row.fer_words_match_count ?? 0;

  return (
    <td
      onClick={() => onOpenModal(row)}
      style={{
        padding: "8px 12px",
        borderBottom: "1px solid var(--border)",
        cursor: "pointer",
        background: row.fer_words_entry_id ? "rgba(16,185,129,.05)" : "rgba(245,158,11,.05)",
      }}
    >
      {row.fer_words_entry_id ? (
        <>
          <div style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--blue-dark)", fontWeight: 700 }}>{row.fer_words_code}</div>
          <div style={{ marginTop: 3, fontSize: 12, lineHeight: 1.35, maxWidth: 240 }}>{row.fer_words_name}</div>
          <div style={{ marginTop: 4, display: "flex", gap: 8, flexWrap: "wrap", fontSize: 10, color: "var(--muted)", fontFamily: "var(--mono)" }}>
            <span>совпало {matchedCount}</span>
            <span>чел {fmtQuantity(row.fer_words_human_hours)}</span>
            <span>маш {fmtQuantity(row.fer_words_machine_hours)}</span>
          </div>
        </>
      ) : (
        <span style={{ fontSize: 11, color: "#b45309", fontStyle: "italic", display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ fontSize: 13 }}>＋</span> Выбрать ФЕР слова
        </span>
      )}
    </td>
  );
}

function FerWordsReviewModal({
  projectId,
  row,
  reviewIndex,
  reviewTotal,
  onClose,
  onApply,
  onSkip,
}: {
  projectId: string;
  row: EstimateRow;
  reviewIndex?: number;
  reviewTotal?: number;
  onClose: () => void;
  onApply: (row: EstimateRow, candidate: FerWordsCandidate | null) => Promise<void>;
  onSkip?: () => void;
}) {
  const [candidates, setCandidates] = useState<FerWordsCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(row.fer_words_entry_id ?? null);

  useEffect(() => {
    setSelectedId(row.fer_words_entry_id ?? null);
    setLoading(true);
    estimates.ferWordsCandidates(projectId, row.id, 5)
      .then((data) => setCandidates(data))
      .catch(() => setCandidates([]))
      .finally(() => setLoading(false));
  }, [projectId, row.id, row.fer_words_entry_id]);

  useEffect(() => {
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) {
        onClose();
      }
    };
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [onClose, saving]);

  async function submit(candidate: FerWordsCandidate | null) {
    setSaving(true);
    try {
      await onApply(row, candidate);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,.55)",
        zIndex: 120,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget && !saving) {
          onClose();
        }
      }}
    >
      <div
        style={{
          width: 760,
          maxHeight: "86vh",
          background: "var(--surface)",
          borderRadius: 12,
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 24px 64px rgba(0,0,0,.28)",
          overflow: "hidden",
        }}
      >
        <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", gap: 16 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>ФЕР слова</div>
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.45 }}>
              Строка сметы: <strong style={{ color: "var(--text)" }}>{row.work_name}</strong>
            </div>
            {reviewTotal != null && reviewTotal > 0 && (
              <div style={{ marginTop: 6, fontSize: 11, color: "#b45309" }}>
                Требуется подтверждение: {reviewIndex ?? 1} из {reviewTotal}
              </div>
            )}
          </div>
          <button onClick={onClose} disabled={saving} style={{ background: "none", border: "none", cursor: saving ? "default" : "pointer", color: "var(--muted)", fontSize: 18, lineHeight: 1 }}>
            ✕
          </button>
        </div>

        <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border)", fontSize: 11, color: "var(--muted)" }}>
          Выберите строку из загруженной таблицы `ФЕР слова`. Совпадение считается по словам и похожим формулировкам.
        </div>

        <div style={{ flex: 1, overflowY: "auto" }}>
          {loading ? (
            <div style={{ padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>Подбираю варианты...</div>
          ) : candidates.length === 0 ? (
            <div style={{ padding: 24, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>Подходящих строк в таблице не найдено</div>
          ) : (
            candidates.map((candidate) => {
              const active = selectedId === candidate.entry_id;
              return (
                <label
                  key={candidate.entry_id}
                  style={{
                    display: "block",
                    padding: "12px 20px",
                    borderBottom: "1px solid var(--border)",
                    cursor: "pointer",
                    background: active ? "rgba(16,185,129,.06)" : "transparent",
                  }}
                >
                  <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                    <input
                      type="radio"
                      name="fer-words-candidate"
                      checked={active}
                      onChange={() => setSelectedId(candidate.entry_id)}
                      style={{ marginTop: 3 }}
                    />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                        <span style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--blue-dark)", fontWeight: 700 }}>{candidate.fer_code}</span>
                        <span style={{ fontSize: 10, color: "var(--muted)", fontFamily: "var(--mono)" }}>
                          {`совпало ${candidate.matched_tokens} — ${candidate.matched_words.join(", ")}`}
                        </span>
                      </div>
                      <div style={{ marginTop: 5, fontSize: 12, lineHeight: 1.45 }}>{candidate.display_name}</div>
                      <div style={{ marginTop: 6, display: "flex", gap: 10, flexWrap: "wrap", fontSize: 10, color: "var(--muted)", fontFamily: "var(--mono)" }}>
                        <span>чел {fmtQuantity(candidate.human_hours)}</span>
                        <span>маш {fmtQuantity(candidate.machine_hours)}</span>
                        <span>score {(candidate.average_ratio * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                  </div>
                </label>
              );
            })
          )}
        </div>

        <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border)", display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {onSkip && (
              <button
                onClick={onSkip}
                disabled={saving}
                style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", cursor: saving ? "default" : "pointer", fontSize: 12 }}
              >
                Пропустить
              </button>
            )}
            {row.fer_words_entry_id && (
              <button
                onClick={() => submit(null)}
                disabled={saving}
                style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #ef444430", background: "#fef2f2", color: "#b91c1c", cursor: saving ? "default" : "pointer", fontSize: 12, fontWeight: 600 }}
              >
                Сбросить
              </button>
            )}
          </div>
          <button
            onClick={() => submit(candidates.find((candidate) => candidate.entry_id === selectedId) ?? null)}
            disabled={saving || (!selectedId && !row.fer_words_entry_id)}
            style={{
              padding: "8px 14px",
              borderRadius: 8,
              border: "1px solid rgba(16,185,129,.22)",
              background: "rgba(16,185,129,.08)",
              color: "#047857",
              cursor: saving ? "default" : "pointer",
              fontSize: 12,
              fontWeight: 700,
              opacity: saving ? 0.7 : 1,
            }}
          >
            {saving ? "Сохраняем..." : "Применить"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function EstimatePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const batchFromUrl = searchParams.get("batch");

  const [rows, setRows] = useState<EstimateRow[]>([]);
  const [summary, setSummary] = useState<EstimateSummary | null>(null);
  const [batches, setBatches] = useState<EstimateBatch[]>([]);
  const [activeBatchId, setActiveBatchId] = useState<string | null>(batchFromUrl);
  const [loading, setLoading] = useState(true);
  const [matchJobId, setMatchJobId] = useState<string | null>(null);
  const [runningBatchId, setRunningBatchId] = useState<string | null>(null);
  const [matchWordsJobId, setMatchWordsJobId] = useState<string | null>(null);
  const [runningWordsBatchId, setRunningWordsBatchId] = useState<string | null>(null);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const [popup, setPopup] = useState<PopupState | null>(null);
  const [savingActsId, setSavingActsId] = useState<string | null>(null);
  const [ferModalRow, setFerModalRow] = useState<EstimateRow | null>(null);
  const [ferWordsModalRow, setFerWordsModalRow] = useState<EstimateRow | null>(null);
  const [ferWordsReviewQueue, setFerWordsReviewQueue] = useState<string[]>([]);
  const [ferWordsReviewIndex, setFerWordsReviewIndex] = useState(0);

  const { job: matchJob, loading: matching } = useJobPoller(matchJobId);
  const { job: matchWordsJob, loading: matchingWords } = useJobPoller(matchWordsJobId);

  const loadBatches = useCallback(async () => {
    setBatchError(null);
    const data = await estimates.batches(id);
    setBatches(data);
    const latestBatch = data.length ? data[data.length - 1]?.id : null;
    const nextBatch = batchFromUrl ?? latestBatch ?? null;
    setActiveBatchId(nextBatch);
  }, [batchFromUrl, id]);

  const loadEstimateData = useCallback(
    async (batchId: string) => {
      setEstimateError(null);
      const [nextRows, nextSummary] = await Promise.all([estimates.list(id, batchId), estimates.summary(id, batchId)]);
      setRows(nextRows);
      setSummary(nextSummary);
    },
    [id],
  );

  useEffect(() => {
    loadBatches().catch(() => {
      setBatches([]);
      setActiveBatchId(batchFromUrl ?? null);
      setBatchError("Не удалось загрузить блоки сметы.");
      setLoading(false);
    });
  }, [batchFromUrl, loadBatches]);

  useEffect(() => {
    if (!activeBatchId) {
      setRows([]);
      setSummary(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    loadEstimateData(activeBatchId)
      .catch((error) => {
        setRows([]);
        setSummary(null);
        setEstimateError(error instanceof Error ? error.message : "Ошибка");
      })
      .finally(() => setLoading(false));
  }, [activeBatchId, loadEstimateData]);

  useEffect(() => {
    if (matchJob?.status === "done" && activeBatchId) {
      loadBatches().catch(() => {});
      loadEstimateData(activeBatchId).catch(() => {});
      setRunningBatchId(null);
    }
    if (matchJob?.status === "failed") {
      setRunningBatchId(null);
    }
  }, [activeBatchId, loadBatches, loadEstimateData, matchJob?.status]);

  useEffect(() => {
    if (matchWordsJob?.status === "done" && activeBatchId) {
      loadBatches().catch(() => {});
      loadEstimateData(activeBatchId).catch(() => {});
      setRunningWordsBatchId(null);
      const reviewIds = matchWordsJob.result?.review_estimate_ids ?? [];
      if (reviewIds.length) {
        setFerWordsReviewQueue(reviewIds);
        setFerWordsReviewIndex(0);
      } else {
        setFerWordsReviewQueue([]);
        setFerWordsReviewIndex(0);
      }
    }
    if (matchWordsJob?.status === "failed") {
      setRunningWordsBatchId(null);
    }
  }, [activeBatchId, loadBatches, loadEstimateData, matchWordsJob?.result?.review_estimate_ids, matchWordsJob?.status]);

  useEffect(() => {
    if (!ferWordsReviewQueue.length) {
      return;
    }
    const currentRowId = ferWordsReviewQueue[ferWordsReviewIndex];
    if (!currentRowId) {
      setFerWordsReviewQueue([]);
      setFerWordsReviewIndex(0);
      return;
    }
    const nextRow = rows.find((row) => row.id === currentRowId) ?? null;
    if (nextRow) {
      setFerWordsModalRow(nextRow);
    }
  }, [ferWordsReviewIndex, ferWordsReviewQueue, rows]);

  const selectBatch = (batchId: string) => {
    setActiveBatchId(batchId);
    setPopup(null);
    setFerWordsModalRow(null);
    setFerWordsReviewQueue([]);
    setFerWordsReviewIndex(0);
    router.replace(`/projects/${id}/estimate?batch=${batchId}`);
  };

  const activeBatch = batches.find((batch) => batch.id === activeBatchId) ?? null;

  const handleMatchFer = async (batchId: string) => {
    try {
      setRunningBatchId(batchId);
      const result = await estimates.matchFer(id, batchId);
      setMatchJobId(result.job_id);
    } catch (error: any) {
      setRunningBatchId(null);
      alert(error.message);
    }
  };

  const handleMatchFerWords = async (batchId: string) => {
    try {
      setRunningWordsBatchId(batchId);
      setFerWordsReviewQueue([]);
      setFerWordsReviewIndex(0);
      const result = await estimates.matchFerWords(id, batchId);
      setMatchWordsJobId(result.job_id);
    } catch (error: any) {
      setRunningWordsBatchId(null);
      alert(error.message);
    }
  };

  const handleOpenActs = (event: ReactMouseEvent<HTMLButtonElement>, row: EstimateRow) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setPopup({ estimateId: row.id, top: rect.bottom + 8, left: Math.max(12, rect.left - 120) });
  };

  const handleActsUpdate = async (estimateId: string, patch: ActFlagsPatch) => {
    try {
      setSavingActsId(estimateId);
      const result = await estimates.updateActs(id, estimateId, patch);
      setRows((current) => current.map((row) => (row.id === estimateId ? { ...row, ...result } : row)));
      setPopup(null);
    } catch (error: any) {
      alert(error.message);
    } finally {
      setSavingActsId(null);
    }
  };

  const handleFerSelect = async (selectedRow: EstimateRow, ferResult: FerSearchResult | null) => {
    const patch = ferResult ? { fer_table_id: ferResult.table_id } : { fer_table_id: null };

    try {
      const result = await estimates.updateFer(id, selectedRow.id, patch);
      setRows((current) =>
        current.map((row) =>
          row.id === selectedRow.id
            ? {
                ...row,
                fer_table_id: result.fer_table_id,
                fer_work_type: result.fer_work_type,
                fer_match_score: result.fer_match_score,
              }
            : row,
        ),
      );
      loadBatches().catch(() => {});
    } catch (error: any) {
      alert(error.message);
    } finally {
      setFerModalRow(null);
    }
  };

  const handleFerWordsSelect = async (selectedRow: EstimateRow, candidate: FerWordsCandidate | null) => {
    const patch = candidate ? { entry_id: candidate.entry_id } : { entry_id: null };

    try {
      const result = await estimates.updateFerWords(id, selectedRow.id, patch);
      setRows((current) =>
        current.map((row) =>
          row.id === selectedRow.id
            ? {
                ...row,
                fer_words_entry_id: result.fer_words_entry_id,
                fer_words_code: result.fer_words_code,
                fer_words_name: result.fer_words_name,
                fer_words_human_hours: result.fer_words_human_hours,
                fer_words_machine_hours: result.fer_words_machine_hours,
                fer_words_match_score: result.fer_words_match_score,
                fer_words_match_count: result.fer_words_match_count,
              }
            : row,
        ),
      );
      loadBatches().catch(() => {});

      if (ferWordsReviewQueue.length) {
        if (ferWordsReviewIndex + 1 < ferWordsReviewQueue.length) {
          setFerWordsReviewIndex((current) => current + 1);
        } else {
          setFerWordsReviewQueue([]);
          setFerWordsReviewIndex(0);
          setFerWordsModalRow(null);
        }
      } else {
        setFerWordsModalRow(null);
      }
    } catch (error: any) {
      alert(error.message);
    }
  };

  const handleSkipFerWordsReview = () => {
    if (ferWordsReviewIndex + 1 < ferWordsReviewQueue.length) {
      setFerWordsReviewIndex((current) => current + 1);
      return;
    }
    setFerWordsReviewQueue([]);
    setFerWordsReviewIndex(0);
    setFerWordsModalRow(null);
  };

  if (loading) {
    return <div style={{ padding: 24, color: "var(--muted)" }}>Загрузка сметы...</div>;
  }

  if (batchError) {
    return (
      <div style={{ padding: 48, textAlign: "center", color: "var(--red)" }}>
        <div style={{ fontSize: 15, fontWeight: 600 }}>Ошибка загрузки сметы</div>
        <div style={{ fontSize: 13, marginTop: 8 }}>{batchError}</div>
      </div>
    );
  }

  if (!batches.length) {
    return (
      <div style={{ padding: 48, textAlign: "center", color: "var(--muted)" }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>📋</div>
        <div style={{ fontSize: 15, fontWeight: 500 }}>Смета ещё не загружена</div>
        <div style={{ fontSize: 13, marginTop: 6 }}>Перейдите на вкладку «Загрузка»</div>
      </div>
    );
  }

  if (!rows.length) {
    return (
      <div style={{ padding: 16 }}>
        <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
          {batches.map((batch) => (
            <button
              key={batch.id}
              onClick={() => selectBatch(batch.id)}
              style={{
                padding: "8px 12px",
                borderRadius: 999,
                border: activeBatchId === batch.id ? "1px solid var(--blue)" : "1px solid var(--border)",
                background: activeBatchId === batch.id ? "rgba(59,130,246,.08)" : "var(--surface)",
                cursor: "pointer",
                fontSize: 12,
              }}
            >
              {batch.name}
            </button>
          ))}
        </div>
        <div style={{ padding: 48, textAlign: "center", color: estimateError ? "var(--red)" : "var(--muted)" }}>{estimateError ?? "В выбранном блоке нет строк сметы."}</div>
      </div>
    );
  }

  const sections: Record<string, EstimateRow[]> = {};
  for (const row of rows) {
    const section = row.section ?? "Без раздела";
    (sections[section] ??= []).push(row);
  }

  const matchStatus = matchJob?.status;
  const popupRow = popup ? rows.find((row) => row.id === popup.estimateId) ?? null : null;

  return (
    <div style={{ padding: 16, height: "100%", overflow: "auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, marginBottom: 16, flexWrap: "wrap" }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {batches.map((batch) => (
            <button
              key={batch.id}
              onClick={() => selectBatch(batch.id)}
              style={{
                padding: "8px 12px",
                borderRadius: 999,
                border: activeBatchId === batch.id ? "1px solid var(--blue)" : "1px solid var(--border)",
                background: activeBatchId === batch.id ? "rgba(59,130,246,.08)" : "var(--surface)",
                cursor: "pointer",
                fontSize: 12,
                fontWeight: activeBatchId === batch.id ? 600 : 500,
              }}
            >
              {batch.name}
            </button>
          ))}
        </div>
        {activeBatch && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              onClick={() => handleMatchFer(activeBatch.id)}
              disabled={matching}
              style={{
                padding: "8px 14px",
                borderRadius: 8,
                border: "1px solid var(--border2)",
                background: matching && runningBatchId === activeBatch.id ? "rgba(59,130,246,.08)" : "var(--surface)",
                cursor: matching ? "default" : "pointer",
                fontSize: 12,
                fontWeight: 600,
                opacity: matching ? 0.7 : 1,
                whiteSpace: "nowrap",
              }}
            >
              {matching && runningBatchId === activeBatch.id ? "Векторно сопоставляем с ФЕР..." : "Векторно сопоставить с ФЕР"}
            </button>
            <button
              onClick={() => handleMatchFerWords(activeBatch.id)}
              disabled={matchingWords}
              style={{
                padding: "8px 14px",
                borderRadius: 8,
                border: "1px solid rgba(16,185,129,.24)",
                background: matchingWords && runningWordsBatchId === activeBatch.id ? "rgba(16,185,129,.08)" : "rgba(16,185,129,.04)",
                cursor: matchingWords ? "default" : "pointer",
                fontSize: 12,
                fontWeight: 700,
                opacity: matchingWords ? 0.7 : 1,
                whiteSpace: "nowrap",
                color: "#047857",
              }}
            >
              {matchingWords && runningWordsBatchId === activeBatch.id ? "Сопоставляем по ФЕР слова..." : "ФЕР слова"}
            </button>
          </div>
        )}
      </div>

      {activeBatch && (
        <div style={{ marginBottom: 12, fontSize: 12, color: "var(--muted)" }}>
          ФЕР размечено: <b style={{ color: "var(--text)" }}>{activeBatch.fer_matched_count}</b> из <b style={{ color: "var(--text)" }}>{activeBatch.estimates_count}</b>
          <span style={{ marginLeft: 10, color: "var(--muted)" }}>· ФЕР слова: <b style={{ color: "var(--text)" }}>{activeBatch.fer_words_matched_count}</b></span>
          <span style={{ marginLeft: 10, color: "var(--muted)" }}>· кликните на ячейку ФЕР или ФЕР слова для ручного выбора</span>
        </div>
      )}

      {matchStatus === "processing" && (
        <div style={{ marginBottom: 16, padding: "12px 14px", borderRadius: 8, background: "rgba(59,130,246,.06)", border: "1px solid rgba(59,130,246,.16)", fontSize: 12, color: "var(--blue-dark)" }}>
          Векторное сопоставление сметы с ФЕР выполняется.
        </div>
      )}
      {matchStatus === "done" && matchJob?.result && (
        <div style={{ marginBottom: 16, padding: "12px 14px", borderRadius: 8, background: "rgba(34,197,94,.06)", border: "1px solid rgba(34,197,94,.18)", fontSize: 12, color: "#166534" }}>
          Сопоставление завершено: найден тип ФЕР для {matchJob.result.matched_rows_count ?? 0} строк
          {typeof matchJob.result.low_confidence_count === "number" ? `, из них ${matchJob.result.low_confidence_count} с низкой уверенностью.` : "."}
        </div>
      )}
      {matchStatus === "failed" && (
        <div style={{ marginBottom: 16, padding: "12px 14px", borderRadius: 8, background: "rgba(239,68,68,.06)", border: "1px solid rgba(239,68,68,.18)", fontSize: 12, color: "var(--red)" }}>
          Не удалось выполнить сопоставление с ФЕР: {matchJob?.result?.error ?? "неизвестная ошибка"}.
        </div>
      )}

      {matchWordsJob?.status === "processing" && (
        <div style={{ marginBottom: 16, padding: "12px 14px", borderRadius: 8, background: "rgba(16,185,129,.06)", border: "1px solid rgba(16,185,129,.18)", fontSize: 12, color: "#047857" }}>
          Идёт сопоставление по таблице ФЕР слова.
        </div>
      )}
      {matchWordsJob?.status === "done" && matchWordsJob.result && (
        <div style={{ marginBottom: 16, padding: "12px 14px", borderRadius: 8, background: "rgba(16,185,129,.06)", border: "1px solid rgba(16,185,129,.18)", fontSize: 12, color: "#047857" }}>
          ФЕР слова: автоматически сопоставлено {matchWordsJob.result.matched_rows_count ?? 0} строк
          {typeof matchWordsJob.result.review_rows_count === "number" && matchWordsJob.result.review_rows_count > 0
            ? `, ещё ${matchWordsJob.result.review_rows_count} требуют ручного выбора.`
            : "."}
        </div>
      )}
      {matchWordsJob?.status === "failed" && (
        <div style={{ marginBottom: 16, padding: "12px 14px", borderRadius: 8, background: "rgba(239,68,68,.06)", border: "1px solid rgba(239,68,68,.18)", fontSize: 12, color: "var(--red)" }}>
          Не удалось выполнить сопоставление по ФЕР слова: {matchWordsJob?.result?.error ?? "неизвестная ошибка"}.
        </div>
      )}

      {summary && (
        <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, padding: "12px 16px" }}>
            <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 4 }}>Итого по блоку</div>
            <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "var(--mono)", color: "var(--blue-dark)" }}>{fmtMoney(summary.total)} ₽</div>
          </div>
          {summary.sections?.map((section) => (
            <div key={section.name} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, padding: "12px 16px" }}>
              <div style={{ fontSize: 10, color: "var(--muted)", marginBottom: 4 }}>{section.name}</div>
              <div style={{ fontSize: 14, fontWeight: 600, fontFamily: "var(--mono)" }}>{fmtMoney(section.subtotal)} ₽</div>
              <div style={{ fontSize: 10, color: "var(--muted)" }}>{section.items} позиций</div>
            </div>
          ))}
        </div>
      )}

      <div style={{ position: "relative", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "#1e293b" }}>
              {tableHeaders.map((header) => (
                <th
                  key={header}
                  style={{
                    padding: "9px 12px",
                    textAlign: ["Наименование работ", "Материалы", "Тип работ ФЕР", "ФЕР слова"].includes(header) ? "left" : "right",
                    fontSize: 10,
                    color: "#94a3b8",
                    textTransform: "uppercase",
                    letterSpacing: ".06em",
                    fontFamily: "var(--mono)",
                    fontWeight: 400,
                    borderRight: "1px solid #334155",
                    whiteSpace: "nowrap",
                  }}
                >
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(sections).map(([sectionName, sectionRows]) => [
              <tr key={`s-${sectionName}`}>
                <td colSpan={8} style={{ padding: "8px 12px", fontWeight: 600, fontSize: 11, background: "rgba(59,130,246,.06)", color: "var(--blue-dark)", letterSpacing: ".03em" }}>
                  {sectionName}
                </td>
                <td style={{ padding: "8px 12px", textAlign: "right", fontFamily: "var(--mono)", fontSize: 11, background: "rgba(59,130,246,.06)", fontWeight: 600 }}>
                  {fmtMoney(sectionRows.reduce((sum, row) => sum + (row.total_price ?? 0), 0))}
                </td>
              </tr>,
              ...sectionRows.map((row, index) => (
                <tr key={row.id} style={{ background: index % 2 ? "var(--stripe)" : "" }}>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)" }}>{row.work_name}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", verticalAlign: "top" }}>
                    {row.materials?.length ? (
                      <div style={{ display: "grid", gap: 4 }}>
                        {row.materials.map((material, materialIndex) => (
                          <div key={`${row.id}-m-${materialIndex}`}>
                            <div>{material.name}</div>
                            {materialMeta(material) && <div style={{ marginTop: 2, fontSize: 10, color: "var(--muted)", fontFamily: "var(--mono)" }}>{materialMeta(material)}</div>}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <span style={{ color: "var(--muted)" }}>—</span>
                    )}
                  </td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right" }}>
                    <ActsCell row={row} onOpen={handleOpenActs} />
                  </td>
                  <FerCell row={row} onOpenModal={setFerModalRow} />
                  <FerWordsCell row={row} onOpenModal={setFerWordsModalRow} />
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", color: "var(--muted)", fontFamily: "var(--mono)" }}>{row.unit}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)" }}>{fmtQuantity(row.quantity)}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)" }}>{fmtMoney(row.unit_price ?? 0)}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)", fontWeight: 500 }}>{fmtMoney(row.total_price ?? 0)}</td>
                </tr>
              )),
            ])}
            <tr style={{ background: "#f1f5f9", fontWeight: 700 }}>
              <td colSpan={8} style={{ padding: "10px 12px", textAlign: "right", fontSize: 11, color: "var(--muted)", letterSpacing: ".06em" }}>
                ИТОГО
              </td>
              <td style={{ padding: "10px 12px", textAlign: "right", fontFamily: "var(--mono)", fontSize: 15, color: "var(--blue-dark)" }}>
                {fmtMoney(summary?.total ?? rows.reduce((sum, row) => sum + (row.total_price ?? 0), 0))} ₽
              </td>
            </tr>
          </tbody>
        </table>

        {popup && popupRow && (
          <ActsPopup
            row={popupRow}
            top={popup.top}
            left={popup.left}
            saving={savingActsId === popupRow.id}
            onClose={() => setPopup(null)}
            onSave={(patch) => handleActsUpdate(popupRow.id, patch)}
          />
        )}
      </div>

      {ferModalRow && <FerSearchModal row={ferModalRow} onClose={() => setFerModalRow(null)} onSelect={(result) => handleFerSelect(ferModalRow, result)} />}
      {ferWordsModalRow && (
        <FerWordsReviewModal
          projectId={id}
          row={ferWordsModalRow}
          reviewIndex={ferWordsReviewQueue.length ? ferWordsReviewIndex + 1 : undefined}
          reviewTotal={ferWordsReviewQueue.length || undefined}
          onClose={() => {
            setFerWordsModalRow(null);
            setFerWordsReviewQueue([]);
            setFerWordsReviewIndex(0);
          }}
          onApply={handleFerWordsSelect}
          onSkip={ferWordsReviewQueue.length ? handleSkipFerWordsReview : undefined}
        />
      )}
    </div>
  );
}
