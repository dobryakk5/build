"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { estimates, fer as ferApi } from "@/lib/api";
import { fmtMoney } from "@/lib/dateUtils";
import type {
  EstimateBatch,
  EstimateMaterial,
  EstimateRow,
  EstimateSummary,
  FerGroupOptionCollection,
  FerSearchResult,
  FerTableDetail,
} from "@/lib/types";
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

type GroupCandidatesModalState = {
  sectionKey: string;
};

type GroupManualModalState = {
  sectionKey: string;
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

type FerHoursInfo = {
  humanHours: number | null;
  loading?: boolean;
};

const tableHeaders = [
  "Наименование работ",
  "Ед.",
  "Кол-во",
  "Цена за ед., ₽",
  "Сумма, ₽",
  "Материалы",
  "Акты",
  "Тип работ ФЕР",
  "Номер ФЕР",
  "Нормочасы ФЕР",
  "Множитель",
  "Расчет",
  "Человеко-дни",
  "ИИ",
];

function fmtQuantity(value?: number | null) {
  return value == null ? "—" : value.toLocaleString("ru-RU");
}

function fmtFerHours(value?: number | null) {
  return value == null
    ? "—"
    : value.toLocaleString("ru-RU", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 3,
      });
}

function sumFerHours(rows: FerTableDetail["rows"]) {
  let total = 0;
  let hasValue = false;
  for (const row of rows) {
    const value = row.h_hour;
    if (value != null) {
      total += value;
      hasValue = true;
    }
  }
  return hasValue ? total : null;
}

function calcNormHours(row: EstimateRow, ferHours?: FerHoursInfo) {
  if (row.quantity == null || ferHours?.humanHours == null) {
    return null;
  }
  return row.quantity * ferHours.humanHours * (row.fer_multiplier ?? 1);
}

function calcPersonDays(row: EstimateRow, ferHours: FerHoursInfo | undefined, hoursPerDay: number, workersCount: number) {
  const normHours = calcNormHours(row, ferHours);
  if (normHours == null || hoursPerDay <= 0 || workersCount <= 0) {
    return null;
  }
  return normHours / hoursPerDay / workersCount;
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
  const scope = useMemo(() => {
    if (row.fer_group_is_ambiguous || !row.fer_group_kind) return null;
    if (row.fer_group_kind === "section" && row.fer_group_ref_id != null) {
      return {
        sectionId: row.fer_group_ref_id,
        label: `Поиск внутри раздела ФЕР: ${row.fer_group_title ?? "—"}`,
      };
    }
    if (row.fer_group_kind === "collection" && row.fer_group_collection_id != null) {
      return {
        collectionId: row.fer_group_collection_id,
        label: `Поиск внутри сборника ФЕР: Сборник ${row.fer_group_collection_num ?? ""}. ${row.fer_group_collection_name ?? row.fer_group_title ?? "—"}`.trim(),
      };
    }
    return null;
  }, [
    row.fer_group_is_ambiguous,
    row.fer_group_kind,
    row.fer_group_ref_id,
    row.fer_group_collection_id,
    row.fer_group_collection_num,
    row.fer_group_collection_name,
    row.fer_group_title,
  ]);

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
        const data = await ferApi.search(q.trim(), 40, scope ?? undefined);
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
  }, [q, scope]);

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
          {scope?.label && (
            <div style={{ marginBottom: 8, fontSize: 11, color: "var(--blue-dark)" }}>
              {scope.label}
            </div>
          )}
          <input
            autoFocus
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder={scope ? "Поиск внутри заданного раздела или сборника ФЕР..." : "Поиск по названию работы, разделу, сборнику ФЕР..."}
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

function FerNumberCell({
  tableId,
  onOpen,
}: {
  tableId?: number | null;
  onOpen: (tableId: number) => void;
}) {
  return (
    <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)" }}>
      {tableId ? (
        <button
          type="button"
          onClick={() => onOpen(tableId)}
          title="Открыть таблицу в справочнике ФЕР"
          style={{
            border: "none",
            background: "transparent",
            padding: 0,
            margin: 0,
            color: "var(--blue-dark)",
            cursor: "pointer",
            font: "inherit",
            textDecoration: "underline",
          }}
        >
          #{tableId}
        </button>
      ) : (
        <span style={{ color: "var(--muted)" }}>—</span>
      )}
    </td>
  );
}

function FerHoursCell({
  tableId,
  hours,
}: {
  tableId?: number | null;
  hours?: FerHoursInfo;
}) {
  const value = tableId ? hours?.humanHours : null;
  return (
    <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)" }}>
      {tableId && hours?.loading ? (
        <span style={{ color: "var(--muted)" }}>...</span>
      ) : (
        fmtFerHours(value)
      )}
    </td>
  );
}

function CalculatedNormHoursCell({
  row,
  hours,
}: {
  row: EstimateRow;
  hours?: FerHoursInfo;
}) {
  return (
    <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)", fontWeight: 600 }}>
      {hours?.loading ? <span style={{ color: "var(--muted)" }}>...</span> : fmtFerHours(calcNormHours(row, hours))}
    </td>
  );
}

function PersonDaysCell({
  row,
  hours,
  hoursPerDay,
  workersCount,
}: {
  row: EstimateRow;
  hours?: FerHoursInfo;
  hoursPerDay: number;
  workersCount: number;
}) {
  return (
    <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)", fontWeight: 600 }}>
      {hours?.loading ? <span style={{ color: "var(--muted)" }}>...</span> : fmtFerHours(calcPersonDays(row, hours, hoursPerDay, workersCount))}
    </td>
  );
}

function FerMultiplierCell({
  row,
  onChange,
}: {
  row: EstimateRow;
  onChange: (row: EstimateRow, nextMultiplier: number) => Promise<void>;
}) {
  const value = row.fer_multiplier ?? 1;
  const update = (delta: number) => {
    const next = Math.max(0, Math.round((value + delta) * 10) / 10);
    if (next !== value) {
      onChange(row, next);
    }
  };

  return (
    <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)" }}>
      <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <button
          type="button"
          onClick={() => update(-0.1)}
          disabled={value <= 0}
          aria-label="Уменьшить множитель ФЕР"
          style={{
            width: 22,
            height: 22,
            borderRadius: 4,
            border: "1px solid var(--border)",
            background: "var(--surface)",
            color: value <= 0 ? "var(--muted)" : "var(--text)",
            cursor: value <= 0 ? "default" : "pointer",
            padding: 0,
            lineHeight: "20px",
          }}
        >
          -
        </button>
        <span style={{ minWidth: 34, textAlign: "center", color: "var(--text)" }}>
          {value.toFixed(1)}
        </span>
        <button
          type="button"
          onClick={() => update(0.1)}
          aria-label="Увеличить множитель ФЕР"
          style={{
            width: 22,
            height: 22,
            borderRadius: 4,
            border: "1px solid var(--border)",
            background: "var(--surface)",
            color: "var(--text)",
            cursor: "pointer",
            padding: 0,
            lineHeight: "20px",
          }}
        >
          +
        </button>
      </div>
    </td>
  );
}

function AIVectorCell({
  row,
  running,
  onRun,
}: {
  row: EstimateRow;
  running: boolean;
  onRun: (row: EstimateRow) => Promise<void>;
}) {
  return (
    <td
      style={{
        padding: "8px 12px",
        borderBottom: "1px solid var(--border)",
        textAlign: "left",
      }}
    >
      <button
        type="button"
        onClick={() => onRun(row)}
        disabled={running}
        style={{
          border: "none",
          background: "transparent",
          padding: 0,
          margin: 0,
          color: running ? "var(--muted)" : "var(--blue-dark)",
          cursor: running ? "default" : "pointer",
          fontSize: 12,
          fontWeight: 700,
          textDecoration: "underline",
          opacity: running ? 0.7 : 1,
        }}
      >
        {running ? "ИИ..." : "ИИ"}
      </button>
    </td>
  );
}

function SectionGroupAiControls({
  representativeRow,
  running,
  onRun,
  onOpenCandidates,
}: {
  representativeRow: EstimateRow;
  running: boolean;
  onRun: (row: EstimateRow) => Promise<void>;
  onOpenCandidates: (row: EstimateRow) => void;
}) {
  const hasSection = Boolean(representativeRow.section?.trim());

  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={() => onRun(representativeRow)}
          disabled={running || !hasSection}
          title={hasSection ? "Определить раздел или сборник ФЕР по группе работ" : "У группы нет названия"}
          style={{
            border: "none",
            background: "transparent",
            padding: 0,
            margin: 0,
            color: running ? "var(--muted)" : hasSection ? "var(--blue-dark)" : "var(--muted)",
            cursor: running || !hasSection ? "default" : "pointer",
            fontSize: 11,
            fontWeight: 700,
            textDecoration: "underline",
            opacity: running || !hasSection ? 0.7 : 1,
            width: "fit-content",
          }}
        >
          {running ? "ИИ раздел..." : "ИИ раздел"}
        </button>
      </div>

      {representativeRow.fer_group_is_ambiguous && representativeRow.fer_group_candidates?.length ? (
        <button
          type="button"
          onClick={() => onOpenCandidates(representativeRow)}
          style={{
            border: "none",
            background: "transparent",
            padding: 0,
            margin: 0,
            color: "var(--muted)",
            cursor: "pointer",
            fontSize: 11,
            fontWeight: 600,
            textDecoration: "underline",
            width: "fit-content",
          }}
        >
          Выбрать вариант
        </button>
      ) : null}
    </div>
  );
}

function GroupFerCell({
  row,
  onOpenManual,
}: {
  row: EstimateRow;
  onOpenManual: (row: EstimateRow) => void;
}) {
  const hasSection = Boolean(row.section?.trim());

  if (!row.fer_group_kind || !row.fer_group_title) {
    return hasSection ? (
      <button
        type="button"
        onClick={() => onOpenManual(row)}
        style={{
          border: "none",
          background: "transparent",
          padding: 0,
          margin: 0,
          textAlign: "left",
          color: "var(--blue-dark)",
          cursor: "pointer",
          fontSize: 11,
          lineHeight: 1.35,
          textDecoration: "underline",
          width: "fit-content",
        }}
      >
        Выбрать
      </button>
    ) : (
      <span style={{ color: "var(--muted)" }}>—</span>
    );
  }

  const score = typeof row.fer_group_match_score === "number" ? row.fer_group_match_score.toFixed(2) : null;
  const isSection = row.fer_group_kind === "section";

  return (
    <div style={{ display: "grid", gap: 3, color: row.fer_group_is_ambiguous ? "var(--muted)" : "var(--text)" }}>
      <button
        type="button"
        onClick={() => onOpenManual(row)}
        style={{
          border: "none",
          background: "transparent",
          padding: 0,
          margin: 0,
          textAlign: "left",
          color: "var(--blue-dark)",
          cursor: "pointer",
          fontSize: 11,
          lineHeight: 1.35,
          textDecoration: "underline",
          width: "fit-content",
        }}
      >
        Выбрать
      </button>
      <button
        type="button"
        onClick={() => onOpenManual(row)}
        style={{
          border: "none",
          background: "transparent",
          padding: 0,
          margin: 0,
          textAlign: "left",
          color: row.fer_group_is_ambiguous ? "var(--muted)" : "var(--text)",
          cursor: "pointer",
          fontSize: 11,
          lineHeight: 1.35,
          textDecoration: "underline",
          width: "fit-content",
        }}
      >
        {row.fer_group_title}
      </button>
      {row.fer_group_collection_num && row.fer_group_collection_name && (
        <div style={{ fontSize: 10, color: "var(--muted)", lineHeight: 1.35 }}>
          {isSection
            ? `Сборник ${row.fer_group_collection_num}. ${row.fer_group_collection_name}${score ? ` · score ${score}` : ""}`
            : score ? `score ${score}` : null}
        </div>
      )}
      {row.fer_group_is_ambiguous && (
        <div style={{ fontSize: 10, color: "var(--muted)", lineHeight: 1.35 }}>
          Требуется выбор оператора
        </div>
      )}
    </div>
  );
}

function GroupManualModal({
  sectionName,
  representativeRow,
  collections,
  loading,
  saving,
  error,
  onClose,
  onSave,
}: {
  sectionName: string;
  representativeRow: EstimateRow;
  collections: FerGroupOptionCollection[];
  loading: boolean;
  saving: boolean;
  error: string | null;
  onClose: () => void;
  onSave: (row: EstimateRow, kind: "section" | "collection", refId: number) => Promise<void>;
}) {
  const [activeCollectionId, setActiveCollectionId] = useState<number | null>(null);
  const [selectedValue, setSelectedValue] = useState<string>("");

  useEffect(() => {
    const fallbackCollectionId = collections[0]?.id ?? null;
    const currentCollectionId = representativeRow.fer_group_collection_id ?? fallbackCollectionId;
    setActiveCollectionId(currentCollectionId);
    if (representativeRow.fer_group_kind && representativeRow.fer_group_ref_id != null) {
      setSelectedValue(`${representativeRow.fer_group_kind}:${representativeRow.fer_group_ref_id}`);
    } else if (fallbackCollectionId != null) {
      setSelectedValue(`collection:${fallbackCollectionId}`);
    } else {
      setSelectedValue("");
    }
  }, [collections, representativeRow.fer_group_collection_id, representativeRow.fer_group_kind, representativeRow.fer_group_ref_id]);

  useEffect(() => {
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [onClose]);

  const activeCollection =
    collections.find((collection) => collection.id === activeCollectionId) ??
    collections[0] ??
    null;

  useEffect(() => {
    if (!activeCollection) {
      return;
    }
    if (selectedValue === `collection:${activeCollection.id}`) {
      return;
    }
    if (selectedValue.startsWith("section:")) {
      const sectionId = Number(selectedValue.split(":")[1]);
      if (activeCollection.sections.some((section) => section.id === sectionId)) {
        return;
      }
    }
    setSelectedValue(`collection:${activeCollection.id}`);
  }, [activeCollection, selectedValue]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,.55)",
        zIndex: 110,
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
          width: 860,
          maxWidth: "calc(100vw - 32px)",
          maxHeight: "80vh",
          background: "var(--surface)",
          borderRadius: 12,
          boxShadow: "0 24px 64px rgba(0,0,0,.28)",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>Ручной выбор ФЕР группы</div>
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.4 }}>
              Группа работ: <strong style={{ color: "var(--text)" }}>{sectionName}</strong>
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--muted)", fontSize: 18, lineHeight: 1 }}>
            ✕
          </button>
        </div>

        {loading ? (
          <div style={{ padding: 24, color: "var(--muted)", fontSize: 13 }}>Загружаем доступные сборники и разделы ФЕР...</div>
        ) : error ? (
          <div style={{ padding: 24, color: "var(--red)", fontSize: 13 }}>{error}</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "280px minmax(0, 1fr)", minHeight: 320, maxHeight: "calc(80vh - 120px)" }}>
            <div style={{ borderRight: "1px solid var(--border)", overflowY: "auto", padding: 12, display: "grid", gap: 8 }}>
              {collections.map((collection) => {
                const active = collection.id === activeCollectionId;
                return (
                  <button
                    key={collection.id}
                    type="button"
                    onClick={() => setActiveCollectionId(collection.id)}
                    style={{
                      textAlign: "left",
                      padding: "10px 12px",
                      borderRadius: 8,
                      border: active ? "1px solid rgba(59,130,246,.24)" : "1px solid var(--border)",
                      background: active ? "rgba(59,130,246,.06)" : "var(--surface)",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ fontSize: 12, fontWeight: 600 }}>{`Сборник ${collection.num}. ${collection.name}`}</div>
                    <div style={{ marginTop: 4, fontSize: 10, color: "var(--muted)" }}>{collection.sections.length} разделов</div>
                  </button>
                );
              })}
            </div>

            <div style={{ overflowY: "auto", padding: 16, display: "grid", gap: 10 }}>
              {activeCollection ? (
                <>
                  <label
                    style={{
                      display: "grid",
                      gap: 4,
                      padding: "10px 12px",
                      border: selectedValue === `collection:${activeCollection.id}` ? "1px solid rgba(59,130,246,.28)" : "1px solid var(--border)",
                      background: selectedValue === `collection:${activeCollection.id}` ? "rgba(59,130,246,.05)" : "var(--surface)",
                      borderRadius: 8,
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                      <input
                        type="radio"
                        name="manual-fer-group"
                        checked={selectedValue === `collection:${activeCollection.id}`}
                        onChange={() => setSelectedValue(`collection:${activeCollection.id}`)}
                        style={{ marginTop: 2 }}
                      />
                      <div>
                        <div style={{ fontSize: 12, fontWeight: 600 }}>{`Сборник ${activeCollection.num}. ${activeCollection.name}`}</div>
                        <div style={{ marginTop: 3, fontSize: 10, color: "var(--muted)" }}>Назначить весь сборник</div>
                      </div>
                    </div>
                  </label>

                  {activeCollection.sections.map((section) => (
                    <label
                      key={section.id}
                      style={{
                        display: "grid",
                        gap: 4,
                        padding: "10px 12px",
                        border: selectedValue === `section:${section.id}` ? "1px solid rgba(59,130,246,.28)" : "1px solid var(--border)",
                        background: selectedValue === `section:${section.id}` ? "rgba(59,130,246,.05)" : "var(--surface)",
                        borderRadius: 8,
                        cursor: "pointer",
                      }}
                    >
                      <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                        <input
                          type="radio"
                          name="manual-fer-group"
                          checked={selectedValue === `section:${section.id}`}
                          onChange={() => setSelectedValue(`section:${section.id}`)}
                          style={{ marginTop: 2 }}
                        />
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.35 }}>{section.title}</div>
                          <div style={{ marginTop: 3, fontSize: 10, color: "var(--muted)" }}>{`Сборник ${activeCollection.num}. ${activeCollection.name}`}</div>
                        </div>
                      </div>
                    </label>
                  ))}
                </>
              ) : (
                <div style={{ color: "var(--muted)", fontSize: 13 }}>Нет доступных вариантов ФЕР для этой группы.</div>
              )}
            </div>
          </div>
        )}

        <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border)", display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button
            type="button"
            onClick={onClose}
            style={{ padding: "7px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", cursor: "pointer", fontSize: 12 }}
          >
            Закрыть
          </button>
          <button
            type="button"
            disabled={loading || saving || !selectedValue}
            onClick={() => {
              const [kind, refId] = selectedValue.split(":");
              if (!kind || !refId) {
                return;
              }
              onSave(representativeRow, kind as "section" | "collection", Number(refId));
            }}
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
    </div>
  );
}

function GroupCandidatesModal({
  sectionName,
  representativeRow,
  saving,
  onClose,
  onConfirm,
}: {
  sectionName: string;
  representativeRow: EstimateRow;
  saving: boolean;
  onClose: () => void;
  onConfirm: (row: EstimateRow, kind: "section" | "collection", refId: number) => Promise<void>;
}) {
  const [selectedCandidate, setSelectedCandidate] = useState<string>("");

  useEffect(() => {
    const firstCandidate = representativeRow.fer_group_candidates?.[0];
    setSelectedCandidate(firstCandidate ? `${firstCandidate.kind}:${firstCandidate.ref_id}` : "");
  }, [representativeRow.id, representativeRow.fer_group_candidates]);

  useEffect(() => {
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [onClose]);

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
          width: 640,
          maxWidth: "calc(100vw - 32px)",
          background: "var(--surface)",
          borderRadius: 12,
          boxShadow: "0 24px 64px rgba(0,0,0,.28)",
          overflow: "hidden",
        }}
      >
        <div style={{ padding: "14px 20px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>Выбор ФЕР сборника</div>
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.4 }}>
              Группа работ: <strong style={{ color: "var(--text)" }}>{sectionName}</strong>
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--muted)", fontSize: 18, lineHeight: 1 }}>
            ✕
          </button>
        </div>

        <div style={{ padding: 20, display: "grid", gap: 10 }}>
          {representativeRow.fer_group_candidates?.map((candidate) => {
            const value = `${candidate.kind}:${candidate.ref_id}`;
            const checked = selectedCandidate === value;
            return (
              <label
                key={value}
                style={{
                  display: "grid",
                  gap: 4,
                  padding: "10px 12px",
                  border: checked ? "1px solid rgba(59,130,246,.28)" : "1px solid var(--border)",
                  background: checked ? "rgba(59,130,246,.05)" : "var(--surface)",
                  borderRadius: 8,
                  cursor: "pointer",
                }}
              >
                <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                  <input
                    type="radio"
                    name="fer-group-candidate"
                    checked={checked}
                    onChange={() => setSelectedCandidate(value)}
                    style={{ marginTop: 2 }}
                  />
                  <div style={{ display: "grid", gap: 3 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.35 }}>{candidate.title}</div>
                    {candidate.collection_num && candidate.collection_name && (
                      <div style={{ fontSize: 11, color: "var(--muted)" }}>
                        Сборник {candidate.collection_num}. {candidate.collection_name}
                      </div>
                    )}
                    <div style={{ fontSize: 10, color: "var(--muted)", fontFamily: "var(--mono)" }}>
                      score {candidate.score.toFixed(2)}
                    </div>
                  </div>
                </div>
              </label>
            );
          })}
        </div>

        <div style={{ padding: "12px 20px", borderTop: "1px solid var(--border)", display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button
            type="button"
            onClick={onClose}
            style={{ padding: "7px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", cursor: "pointer", fontSize: 12 }}
          >
            Закрыть
          </button>
          <button
            type="button"
            disabled={saving || !selectedCandidate}
            onClick={() => {
              const [kind, refId] = selectedCandidate.split(":");
              if (!kind || !refId) {
                return;
              }
              onConfirm(representativeRow, kind as "section" | "collection", Number(refId));
            }}
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
            {saving ? "Подтверждаем..." : "Подтвердить"}
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
  const [batchError, setBatchError] = useState<string | null>(null);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const [popup, setPopup] = useState<PopupState | null>(null);
  const [savingActsId, setSavingActsId] = useState<string | null>(null);
  const [ferModalRow, setFerModalRow] = useState<EstimateRow | null>(null);
  const [ferHoursByTableId, setFerHoursByTableId] = useState<Record<number, FerHoursInfo>>({});
  const [runningAiRowId, setRunningAiRowId] = useState<string | null>(null);
  const [runningGroupSectionKey, setRunningGroupSectionKey] = useState<string | null>(null);
  const [confirmingGroupSectionKey, setConfirmingGroupSectionKey] = useState<string | null>(null);
  const [groupCandidatesModal, setGroupCandidatesModal] = useState<GroupCandidatesModalState | null>(null);
  const [groupManualModal, setGroupManualModal] = useState<GroupManualModalState | null>(null);
  const [groupManualOptions, setGroupManualOptions] = useState<FerGroupOptionCollection[]>([]);
  const [groupManualLoading, setGroupManualLoading] = useState(false);
  const [groupManualError, setGroupManualError] = useState<string | null>(null);
  const [workersDraft, setWorkersDraft] = useState("1");
  const [hoursPerDay, setHoursPerDay] = useState(8);
  const [savingWorkers, setSavingWorkers] = useState(false);
  const [buildingGanttBatchId, setBuildingGanttBatchId] = useState<string | null>(null);
  const multiplierRequestSeq = useRef<Record<string, number>>({});

  const { job: matchJob, loading: matching } = useJobPoller(matchJobId);

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
    const tableIds = Array.from(
      new Set(rows.map((row) => row.fer_table_id).filter((tableId): tableId is number => tableId != null)),
    ).filter((tableId) => ferHoursByTableId[tableId] == null);

    if (!tableIds.length) {
      return;
    }

    setFerHoursByTableId((current) => {
      const next = { ...current };
      for (const tableId of tableIds) {
        next[tableId] = { humanHours: null, loading: true };
      }
      return next;
    });

    for (const tableId of tableIds) {
      ferApi
        .table(tableId)
        .then((detail) => {
          setFerHoursByTableId((current) => ({
            ...current,
            [tableId]: {
              humanHours: sumFerHours(detail.rows),
            },
          }));
        })
        .catch(() => {
          setFerHoursByTableId((current) => ({
            ...current,
            [tableId]: { humanHours: null },
          }));
        });
    }
  }, [ferHoursByTableId, rows]);

  const selectBatch = (batchId: string) => {
    setActiveBatchId(batchId);
    setPopup(null);
    setGroupCandidatesModal(null);
    setGroupManualModal(null);
    router.replace(`/projects/${id}/estimate?batch=${batchId}`);
  };

  const openFerReference = (tableId: number) => {
    router.push(`/projects/${id}/fer?table=${tableId}`);
  };

  const activeBatch = batches.find((batch) => batch.id === activeBatchId) ?? null;

  useEffect(() => {
    setWorkersDraft(String(activeBatch?.workers_count ?? 1));
  }, [activeBatch?.id, activeBatch?.workers_count]);

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

  const handleBuildGantt = async (batch: EstimateBatch) => {
    try {
      setBuildingGanttBatchId(batch.id);
      const result = await estimates.buildGantt(id, batch.id, batch.start_date);
      setBatches((current) =>
        current.map((item) =>
          item.id === batch.id
            ? {
                ...item,
                start_date: result.start_date,
                gantt_tasks_count: result.gantt_tasks_count,
              }
            : item,
        ),
      );
    } catch (error: any) {
      alert(error.message);
    } finally {
      setBuildingGanttBatchId(null);
    }
  };

  const handleSaveWorkers = async () => {
    if (!activeBatch) return;

    const nextWorkers = Number(workersDraft);
    if (!Number.isInteger(nextWorkers) || nextWorkers < 1 || nextWorkers > 500) {
      alert("Введите целое число рабочих от 1 до 500.");
      return;
    }

    try {
      setSavingWorkers(true);
      const result = await estimates.updateBatchWorkers(id, activeBatch.id, nextWorkers);
      setBatches((current) =>
        current.map((batch) =>
          batch.id === activeBatch.id
            ? {
                ...batch,
                workers_count: result.workers_count,
              }
            : batch,
        ),
      );
      setWorkersDraft(String(result.workers_count));
    } catch (error: any) {
      alert(error.message);
    } finally {
      setSavingWorkers(false);
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

  const handleFerMultiplierChange = async (selectedRow: EstimateRow, nextMultiplier: number) => {
    const previousMultiplier = selectedRow.fer_multiplier ?? 1;
    const requestSeq = (multiplierRequestSeq.current[selectedRow.id] ?? 0) + 1;
    multiplierRequestSeq.current[selectedRow.id] = requestSeq;

    setRows((current) =>
      current.map((row) =>
        row.id === selectedRow.id
          ? {
              ...row,
              fer_multiplier: nextMultiplier,
            }
          : row,
      ),
    );

    try {
      const result = await estimates.updateFerMultiplier(id, selectedRow.id, nextMultiplier);
      if (multiplierRequestSeq.current[selectedRow.id] === requestSeq) {
        setRows((current) =>
          current.map((row) =>
            row.id === selectedRow.id
              ? {
                  ...row,
                  fer_multiplier: result.fer_multiplier,
                }
              : row,
          ),
        );
      }
    } catch (error: any) {
      if (multiplierRequestSeq.current[selectedRow.id] === requestSeq) {
        setRows((current) =>
          current.map((row) =>
            row.id === selectedRow.id
              ? {
                  ...row,
                  fer_multiplier: previousMultiplier,
                }
              : row,
          ),
        );
        alert(error.message);
      }
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

  const handleAIVectorMatch = async (selectedRow: EstimateRow) => {
    try {
      setRunningAiRowId(selectedRow.id);
      const result = await estimates.matchFerVectorRow(id, selectedRow.id);
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
      setRunningAiRowId(null);
    }
  };

  const applyGroupMatchResult = (sectionName: string | null | undefined, result: any) => {
    setRows((current) =>
      current.map((row) =>
        (row.section ?? "Без раздела") === (sectionName ?? "Без раздела")
          ? {
              ...row,
              fer_group_kind: result.fer_group_kind,
              fer_group_ref_id: result.fer_group_ref_id,
              fer_group_title: result.fer_group_title,
              fer_group_collection_id: result.fer_group_collection_id,
              fer_group_collection_num: result.fer_group_collection_num,
              fer_group_collection_name: result.fer_group_collection_name,
              fer_group_match_score: result.fer_group_match_score,
              fer_group_is_ambiguous: Boolean(result.fer_group_is_ambiguous),
              fer_group_candidates: result.fer_group_candidates,
            }
          : row,
      ),
    );
  };

  const handleAIGroupMatch = async (selectedRow: EstimateRow) => {
    const sectionKey = selectedRow.section ?? "Без раздела";
    try {
      setRunningGroupSectionKey(sectionKey);
      const result = await estimates.matchFerGroupVectorRow(id, selectedRow.id);
      applyGroupMatchResult(selectedRow.section, result);
      if (result.fer_group_is_ambiguous && result.fer_group_candidates?.length) {
        setGroupCandidatesModal({ sectionKey });
      } else {
        setGroupCandidatesModal(null);
      }
    } catch (error: any) {
      alert(error.message);
    } finally {
      setRunningGroupSectionKey(null);
    }
  };

  const handleConfirmGroup = async (
    selectedRow: EstimateRow,
    kind: "section" | "collection",
    refId: number,
  ) => {
    const sectionKey = selectedRow.section ?? "Без раздела";
    try {
      setConfirmingGroupSectionKey(sectionKey);
      const result = await estimates.confirmFerGroup(id, selectedRow.id, { kind, ref_id: refId });
      applyGroupMatchResult(selectedRow.section, result);
      setGroupCandidatesModal(null);
    } catch (error: any) {
      alert(error.message);
    } finally {
      setConfirmingGroupSectionKey(null);
    }
  };

  const openManualGroupModal = async (selectedRow: EstimateRow) => {
    const sectionKey = selectedRow.section ?? "Без раздела";
    setGroupManualModal({ sectionKey });
    setGroupManualLoading(true);
    setGroupManualError(null);
    try {
      const result = await estimates.ferGroupOptions(id, selectedRow.id);
      setGroupManualOptions(result.collections ?? []);
    } catch (error: any) {
      setGroupManualOptions([]);
      setGroupManualError(error.message ?? "Не удалось загрузить варианты ФЕР.");
    } finally {
      setGroupManualLoading(false);
    }
  };

  const handleManualGroupSave = async (
    selectedRow: EstimateRow,
    kind: "section" | "collection",
    refId: number,
  ) => {
    const sectionKey = selectedRow.section ?? "Без раздела";
    try {
      setConfirmingGroupSectionKey(sectionKey);
      const result = await estimates.updateFerGroupManual(id, selectedRow.id, { kind, ref_id: refId });
      applyGroupMatchResult(selectedRow.section, result);
      setGroupManualModal(null);
    } catch (error: any) {
      alert(error.message);
    } finally {
      setConfirmingGroupSectionKey(null);
    }
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
  const groupCandidatesRow = groupCandidatesModal ? sections[groupCandidatesModal.sectionKey]?.[0] ?? null : null;
  const groupManualRow = groupManualModal ? sections[groupManualModal.sectionKey]?.[0] ?? null : null;
  const activeBatchWorkers = activeBatch?.workers_count ?? 1;
  const workersDraftNumber = Number(workersDraft);
  const workersChanged = Number.isInteger(workersDraftNumber) && workersDraftNumber !== activeBatchWorkers;
  const calculationWorkers = Number.isInteger(workersDraftNumber) && workersDraftNumber > 0 ? workersDraftNumber : activeBatchWorkers;

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
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
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
              onClick={() => handleBuildGantt(activeBatch)}
              disabled={buildingGanttBatchId === activeBatch.id}
              style={{
                padding: "8px 14px",
                borderRadius: 8,
                border: "1px solid rgba(59,130,246,.22)",
                background: "var(--blue-dark)",
                color: "#fff",
                cursor: buildingGanttBatchId === activeBatch.id ? "default" : "pointer",
                fontSize: 12,
                fontWeight: 700,
                opacity: buildingGanttBatchId === activeBatch.id ? 0.7 : 1,
                whiteSpace: "nowrap",
              }}
            >
              {buildingGanttBatchId === activeBatch.id
                ? "Строим Гант..."
                : activeBatch.gantt_tasks_count > 0
                  ? "Перестроить Гант"
                  : "Построить Гант"}
            </button>
          </div>
        )}
      </div>

      {activeBatch && (
        <div style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", fontSize: 12, color: "var(--muted)" }}>
          <div>
            ФЕР размечено: <b style={{ color: "var(--text)" }}>{activeBatch.fer_matched_count}</b> из <b style={{ color: "var(--text)" }}>{activeBatch.estimates_count}</b>
            <span style={{ marginLeft: 10 }}>
              · Гант: <b style={{ color: "var(--text)" }}>{activeBatch.gantt_tasks_count}</b> задач
            </span>
            <span style={{ marginLeft: 10, color: "var(--muted)" }}>· кнопка ИИ в строке запускает векторную сверку по этой работе</span>
          </div>
          <label style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 8, color: "var(--text)", fontWeight: 600 }}>
            Рабочих:
            <input
              type="number"
              min={1}
              max={500}
              step={1}
              value={workersDraft}
              onChange={(event) => setWorkersDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && workersChanged && !savingWorkers) {
                  handleSaveWorkers();
                }
              }}
              style={{
                width: 82,
                padding: "6px 8px",
                borderRadius: 7,
                border: "1px solid var(--border2)",
                background: "var(--surface)",
                fontSize: 12,
                fontFamily: "var(--mono)",
              }}
            />
          </label>
          <button
            type="button"
            disabled={savingWorkers || !workersChanged}
            onClick={handleSaveWorkers}
            style={{
              padding: "6px 10px",
              borderRadius: 7,
              border: "1px solid rgba(59,130,246,.18)",
              background: workersChanged ? "rgba(59,130,246,.08)" : "var(--surface)",
              color: workersChanged ? "var(--blue-dark)" : "var(--muted)",
              cursor: savingWorkers || !workersChanged ? "default" : "pointer",
              opacity: savingWorkers ? 0.7 : 1,
              fontSize: 12,
              fontWeight: 600,
            }}
          >
            {savingWorkers ? "Сохраняем..." : "Сохранить"}
          </button>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "var(--text)", fontWeight: 600 }}>
            Часов/день:
            <select
              value={hoursPerDay}
              onChange={(event) => setHoursPerDay(Number(event.target.value))}
              style={{
                padding: "6px 8px",
                borderRadius: 7,
                border: "1px solid var(--border2)",
                background: "var(--surface)",
                fontSize: 12,
                fontFamily: "var(--mono)",
              }}
            >
              {[8, 9, 10].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
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
          {matchJob.result.strategy ? ` Стратегия: ${matchJob.result.strategy}.` : ""}
          {typeof matchJob.result.normalized_rows_count === "number" ? ` Нормализовано: ${matchJob.result.normalized_rows_count}.` : ""}
          {typeof matchJob.result.reranked_rows_count === "number" ? ` Rerank: ${matchJob.result.reranked_rows_count}.` : ""}
          {typeof matchJob.result.rerank_corrected_count === "number" ? ` Исправлено rerank: ${matchJob.result.rerank_corrected_count}.` : ""}
          {typeof matchJob.result.fallback_rows_count === "number" ? ` Fallback: ${matchJob.result.fallback_rows_count}.` : ""}
        </div>
      )}
      {matchStatus === "failed" && (
        <div style={{ marginBottom: 16, padding: "12px 14px", borderRadius: 8, background: "rgba(239,68,68,.06)", border: "1px solid rgba(239,68,68,.18)", fontSize: 12, color: "var(--red)" }}>
          Не удалось выполнить сопоставление с ФЕР: {matchJob?.result?.error ?? "неизвестная ошибка"}.
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

      <div style={{ position: "relative", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, overflowX: "auto", overflowY: "hidden" }}>
        <table style={{ width: "max-content", minWidth: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "#1e293b" }}>
              {tableHeaders.map((header) => (
                <th
                  key={header}
                  style={{
                    padding: "9px 12px",
                    textAlign: ["Наименование работ", "Материалы", "Тип работ ФЕР", "ИИ"].includes(header) ? "left" : "right",
                    width: header === "Наименование работ" ? "1%" : undefined,
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
                <td
                  style={{
                    padding: "8px 12px",
                    fontWeight: 700,
                    fontSize: 11,
                    width: "1%",
                    whiteSpace: "nowrap",
                    background: "rgba(59,130,246,.06)",
                    color: "var(--blue-dark)",
                    letterSpacing: ".03em",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  {sectionName}
                </td>
                <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", background: "rgba(59,130,246,.06)", textAlign: "right", color: "var(--muted)", fontFamily: "var(--mono)" }}>—</td>
                <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", background: "rgba(59,130,246,.06)", textAlign: "right", color: "var(--muted)", fontFamily: "var(--mono)" }}>—</td>
                <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", background: "rgba(59,130,246,.06)", textAlign: "right", color: "var(--muted)", fontFamily: "var(--mono)" }}>—</td>
                <td
                  style={{
                    padding: "8px 12px",
                    textAlign: "right",
                    fontFamily: "var(--mono)",
                    fontSize: 11,
                    background: "rgba(59,130,246,.06)",
                    fontWeight: 600,
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  {fmtMoney(sectionRows.reduce((sum, row) => sum + (row.total_price ?? 0), 0))}
                </td>
                <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", background: "rgba(59,130,246,.06)", color: "var(--muted)" }}>—</td>
                <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", background: "rgba(59,130,246,.06)", textAlign: "right", color: "var(--muted)" }}>—</td>
                <td
                  style={{
                    padding: "8px 12px",
                    borderBottom: "1px solid var(--border)",
                    background: "rgba(59,130,246,.06)",
                    verticalAlign: "top",
                  }}
                >
                  <GroupFerCell row={sectionRows[0]} onOpenManual={openManualGroupModal} />
                </td>
                <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", background: "rgba(59,130,246,.06)", textAlign: "right", color: "var(--muted)", fontFamily: "var(--mono)" }}>—</td>
                <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", background: "rgba(59,130,246,.06)", textAlign: "right", color: "var(--muted)", fontFamily: "var(--mono)" }}>—</td>
                <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", background: "rgba(59,130,246,.06)", textAlign: "right", color: "var(--muted)", fontFamily: "var(--mono)" }}>—</td>
                <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", background: "rgba(59,130,246,.06)", textAlign: "right", color: "var(--muted)", fontFamily: "var(--mono)" }}>—</td>
                <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", background: "rgba(59,130,246,.06)", textAlign: "right", color: "var(--muted)", fontFamily: "var(--mono)" }}>—</td>
                <td
                  style={{
                    padding: "8px 12px",
                    borderBottom: "1px solid var(--border)",
                    background: "rgba(59,130,246,.06)",
                    verticalAlign: "top",
                  }}
                >
                  <SectionGroupAiControls
                    representativeRow={sectionRows[0]}
                    running={runningGroupSectionKey === sectionName}
                    onRun={handleAIGroupMatch}
                    onOpenCandidates={(row) => setGroupCandidatesModal({ sectionKey: row.section ?? "Без раздела" })}
                  />
                </td>
              </tr>,
              ...sectionRows.map((row, index) => (
                <tr key={row.id} style={{ background: index % 2 ? "var(--stripe)" : "" }}>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", width: "1%", whiteSpace: "nowrap" }}>{row.work_name}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", color: "var(--muted)", fontFamily: "var(--mono)" }}>{row.unit}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)" }}>{fmtQuantity(row.quantity)}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)" }}>{fmtMoney(row.unit_price ?? 0)}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)", fontWeight: 500 }}>{fmtMoney(row.total_price ?? 0)}</td>
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
                  <FerNumberCell tableId={row.fer_table_id} onOpen={openFerReference} />
                  <FerHoursCell tableId={row.fer_table_id} hours={row.fer_table_id ? ferHoursByTableId[row.fer_table_id] : undefined} />
                  <FerMultiplierCell row={row} onChange={handleFerMultiplierChange} />
                  <CalculatedNormHoursCell row={row} hours={row.fer_table_id ? ferHoursByTableId[row.fer_table_id] : undefined} />
                  <PersonDaysCell row={row} hours={row.fer_table_id ? ferHoursByTableId[row.fer_table_id] : undefined} hoursPerDay={hoursPerDay} workersCount={calculationWorkers} />
                  <AIVectorCell row={row} running={runningAiRowId === row.id} onRun={handleAIVectorMatch} />
                </tr>
              )),
            ])}
            <tr style={{ background: "#f1f5f9", fontWeight: 700 }}>
              <td colSpan={4} style={{ padding: "10px 12px", textAlign: "right", fontSize: 11, color: "var(--muted)", letterSpacing: ".06em" }}>
                ИТОГО
              </td>
              <td style={{ padding: "10px 12px", textAlign: "right", fontFamily: "var(--mono)", fontSize: 15, color: "var(--blue-dark)" }}>
                {fmtMoney(summary?.total ?? rows.reduce((sum, row) => sum + (row.total_price ?? 0), 0))} ₽
              </td>
              <td colSpan={9} style={{ padding: "10px 12px" }} />
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
      {groupCandidatesModal && groupCandidatesRow && (
        <GroupCandidatesModal
          sectionName={groupCandidatesModal.sectionKey}
          representativeRow={groupCandidatesRow}
          saving={confirmingGroupSectionKey === groupCandidatesModal.sectionKey}
          onClose={() => setGroupCandidatesModal(null)}
          onConfirm={handleConfirmGroup}
        />
      )}
      {groupManualModal && groupManualRow && (
        <GroupManualModal
          sectionName={groupManualModal.sectionKey}
          representativeRow={groupManualRow}
          collections={groupManualOptions}
          loading={groupManualLoading}
          saving={confirmingGroupSectionKey === groupManualModal.sectionKey}
          error={groupManualError}
          onClose={() => setGroupManualModal(null)}
          onSave={handleManualGroupSave}
        />
      )}
    </div>
  );
}
