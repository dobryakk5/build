"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";

import { estimates } from "@/lib/api";
import { fmtMoney } from "@/lib/dateUtils";
import type { EstimateBatch, EstimateRow, EstimateSummary } from "@/lib/types";
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

const TABLE_HEADERS = [
  "Наименование работ",
  "Акты",
  "Тип работ ФЕР",
  "Ед.",
  "Кол-во",
  "Цена за ед., ₽",
  "Сумма, ₽",
];

function countSelectedActs(row: EstimateRow) {
  return [
    row.req_hidden_work_act,
    row.req_intermediate_act,
    row.req_ks2_ks3,
  ].filter(Boolean).length;
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
    const handlePointerDown = (event: MouseEvent) => {
      if (!popupRef.current?.contains(event.target as Node)) {
        onClose();
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
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
        background: "var(--surface)",
        border: "1px solid var(--border2)",
        boxShadow: "0 12px 30px rgba(15,23,42,.18)",
        borderRadius: 10,
        padding: 14,
        zIndex: 40,
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text)", marginBottom: 10 }}>
        Отметки актов
      </div>
      <div style={{ display: "grid", gap: 10 }}>
        {[
          ["req_hidden_work_act", "Акты скрытых работ с приглашением технадзора"],
          ["req_intermediate_act", "Акты промежуточного выполнения работ"],
          ["req_ks2_ks3", "КС-2, КС-3 и исполнительная съемка по этапу"],
        ].map(([key, label]) => (
          <label key={key} style={{ display: "flex", gap: 10, alignItems: "flex-start", fontSize: 12, color: "var(--text)", lineHeight: 1.35 }}>
            <input
              type="checkbox"
              checked={draft[key as keyof typeof draft]}
              onChange={(event) => {
                const checked = event.target.checked;
                setDraft((current) => ({ ...current, [key]: checked }));
              }}
            />
            <span>{label}</span>
          </label>
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 14 }}>
        <button
          type="button"
          onClick={onClose}
          style={{
            padding: "7px 10px",
            borderRadius: 8,
            border: "1px solid var(--border)",
            background: "var(--surface)",
            cursor: "pointer",
            fontSize: 12,
          }}
        >
          Закрыть
        </button>
        <button
          type="button"
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

  const { job: matchJob, loading: matching } = useJobPoller(matchJobId);

  const loadBatches = useCallback(async () => {
    setBatchError(null);
    const data = await estimates.batches(id);
    setBatches(data);
    const latestBatch = data.length ? data[data.length - 1]?.id : null;
    const nextBatch = batchFromUrl ?? latestBatch ?? null;
    setActiveBatchId(nextBatch);
  }, [batchFromUrl, id]);

  const loadEstimateData = useCallback(async (batchId: string) => {
    setEstimateError(null);
    const [nextRows, nextSummary] = await Promise.all([
      estimates.list(id, batchId),
      estimates.summary(id, batchId),
    ]);
    setRows(nextRows);
    setSummary(nextSummary);
  }, [id]);

  useEffect(() => {
    loadBatches().catch(() => {
      setBatches([]);
      setActiveBatchId(batchFromUrl ?? null);
      setBatchError("Не удалось загрузить блоки сметы. Проверьте backend и миграции БД.");
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
      .catch((error: unknown) => {
        setRows([]);
        setSummary(null);
        setEstimateError(error instanceof Error ? error.message : "Не удалось загрузить строки сметы.");
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

  const selectBatch = (batchId: string) => {
    setActiveBatchId(batchId);
    setPopup(null);
    router.replace(`/projects/${id}/estimate?batch=${batchId}`);
  };

  const activeBatch = batches.find((batch) => batch.id === activeBatchId) ?? null;

  const handleMatchFer = async (batchId: string) => {
    try {
      setRunningBatchId(batchId);
      const res = await estimates.matchFer(id, batchId);
      setMatchJobId(res.job_id);
    } catch (error: any) {
      setRunningBatchId(null);
      alert(error.message);
    }
  };

  const handleOpenActs = (event: ReactMouseEvent<HTMLButtonElement>, row: EstimateRow) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setPopup({
      estimateId: row.id,
      top: rect.bottom + 8,
      left: Math.max(12, rect.left - 120),
    });
  };

  const handleActsUpdate = async (estimateId: string, patch: ActFlagsPatch) => {
    try {
      setSavingActsId(estimateId);
      const result = await estimates.updateActs(id, estimateId, patch);
      setRows((current) => current.map((row) => (
        row.id === estimateId
          ? { ...row, ...result }
          : row
      )));
      setPopup(null);
    } catch (error: any) {
      alert(error.message);
    } finally {
      setSavingActsId(null);
    }
  };

  if (loading) return <div style={{ padding: 24, color: "var(--muted)" }}>Загрузка сметы...</div>;

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
        <div style={{ padding: 48, textAlign: "center", color: estimateError ? "var(--red)" : "var(--muted)" }}>
          {estimateError ?? "В выбранном блоке нет строк сметы."}
        </div>
      </div>
    );
  }

  const sections: Record<string, EstimateRow[]> = {};
  for (const row of rows) {
    const sec = row.section ?? "Без раздела";
    (sections[sec] ??= []).push(row);
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
        )}
      </div>

      {activeBatch && (
        <div style={{ marginBottom: 12, fontSize: 12, color: "var(--muted)" }}>
          ФЕР размечено: <b style={{ color: "var(--text)" }}>{activeBatch.fer_matched_count}</b> из{" "}
          <b style={{ color: "var(--text)" }}>{activeBatch.estimates_count}</b>
        </div>
      )}

      {matchStatus === "processing" && (
        <div style={{ marginBottom: 16, padding: "12px 14px", borderRadius: 8, background: "rgba(59,130,246,.06)", border: "1px solid rgba(59,130,246,.16)", fontSize: 12, color: "var(--blue-dark)" }}>
          Векторное сопоставление сметы с ФЕР выполняется.
        </div>
      )}

      {matchStatus === "done" && matchJob?.result && (
        <div style={{ marginBottom: 16, padding: "12px 14px", borderRadius: 8, background: "rgba(34,197,94,.06)", border: "1px solid rgba(34,197,94,.18)", fontSize: 12, color: "#166534" }}>
          Векторное сопоставление завершено: найден тип ФЕР для {matchJob.result.matched_rows_count ?? 0} строк
          {typeof matchJob.result.low_confidence_count === "number"
            ? `, из них ${matchJob.result.low_confidence_count} с низкой уверенностью.`
            : "."}
        </div>
      )}

      {matchStatus === "failed" && (
        <div style={{ marginBottom: 16, padding: "12px 14px", borderRadius: 8, background: "rgba(239,68,68,.06)", border: "1px solid rgba(239,68,68,.18)", fontSize: 12, color: "var(--red)" }}>
          Не удалось выполнить векторное сопоставление с ФЕР: {matchJob?.result?.error ?? "неизвестная ошибка"}.
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
              {TABLE_HEADERS.map((header) => (
                <th
                  key={header}
                  style={{
                    padding: "9px 12px",
                    textAlign: header === "Наименование работ" || header === "Тип работ ФЕР" ? "left" : "right",
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
                <td colSpan={6} style={{ padding: "8px 12px", fontWeight: 600, fontSize: 11, background: "rgba(59,130,246,.06)", color: "var(--blue-dark)", letterSpacing: ".03em" }}>{sectionName}</td>
                <td style={{ padding: "8px 12px", textAlign: "right", fontFamily: "var(--mono)", fontSize: 11, background: "rgba(59,130,246,.06)", fontWeight: 600 }}>
                  {fmtMoney(sectionRows.reduce((sum, row) => sum + (row.total_price ?? 0), 0))}
                </td>
              </tr>,
              ...sectionRows.map((row, index) => (
                <tr key={row.id} style={{ background: index % 2 ? "var(--stripe)" : "" }}>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)" }}>{row.work_name}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right" }}>
                    <ActsCell row={row} onOpen={handleOpenActs} />
                  </td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", background: (row.fer_match_score ?? 0) < 0.45 ? "rgba(245,158,11,.05)" : undefined }}>
                    {row.fer_work_type ? (
                      <>
                        <div>{row.fer_work_type}</div>
                        <div style={{ marginTop: 2, fontSize: 10, color: "var(--muted)", fontFamily: "var(--mono)" }}>
                          score {(row.fer_match_score ?? 0).toFixed(2)}
                        </div>
                      </>
                    ) : (
                      <span style={{ color: "var(--muted)" }}>Не определён</span>
                    )}
                  </td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", color: "var(--muted)", fontFamily: "var(--mono)" }}>{row.unit}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)" }}>{row.quantity?.toLocaleString("ru")}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)" }}>{fmtMoney(row.unit_price ?? 0)}</td>
                  <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--border)", textAlign: "right", fontFamily: "var(--mono)", fontWeight: 500 }}>{fmtMoney(row.total_price ?? 0)}</td>
                </tr>
              )),
            ])}
            <tr style={{ background: "#f1f5f9", fontWeight: 700 }}>
              <td colSpan={6} style={{ padding: "10px 12px", textAlign: "right", fontSize: 11, color: "var(--muted)", letterSpacing: ".06em" }}>ИТОГО</td>
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
    </div>
  );
}
