"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { estimates } from "@/lib/api";
import { fmtMoney } from "@/lib/dateUtils";
import type { EstimateBatch } from "@/lib/types";
import { useJobPoller } from "@/lib/useJobPoller";

type EstimateKind = "country_house" | "apartment" | "non_residential";

const KIND_OPTIONS: Array<{ id: EstimateKind; title: string; desc: string }> = [
  { id: "country_house", title: "Загородный дом", desc: "Коттеджи, таунхаусы, частные дома" },
  { id: "apartment", title: "Квартира", desc: "Отделка и инженерия внутри квартиры" },
  { id: "non_residential", title: "Нежилой объект", desc: "Офисы, ТЦ, склады, коммерческие помещения" },
];

const KIND_LABEL: Record<EstimateKind, string> = {
  country_house: "Загородный дом",
  apartment: "Квартира",
  non_residential: "Нежилой объект",
};

export default function UploadPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [startDate, setStartDate] = useState(new Date().toISOString().split("T")[0]);
  const [workers, setWorkers] = useState(3);
  const [estimateKind, setEstimateKind] = useState<EstimateKind>("country_house");
  const [complexMode, setComplexMode] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [batches, setBatches] = useState<EstimateBatch[]>([]);
  const [loadingBatches, setLoadingBatches] = useState(true);
  const [matchJobId, setMatchJobId] = useState<string | null>(null);
  const [runningBatchId, setRunningBatchId] = useState<string | null>(null);

  const { job, loading: polling } = useJobPoller(jobId);
  const { job: matchJob, loading: matching } = useJobPoller(matchJobId);

  const loadBatches = useCallback(async () => {
    if (!id) return;
    try {
      setLoadingBatches(true);
      const data = await estimates.batches(id);
      setBatches(data);
    } catch {
      setBatches([]);
    } finally {
      setLoadingBatches(false);
    }
  }, [id]);

  useEffect(() => {
    loadBatches();
  }, [loadBatches]);

  useEffect(() => {
    if (job?.status === "done") {
      loadBatches();
    }
  }, [job?.status, loadBatches]);

  useEffect(() => {
    if (matchJob?.status === "done") {
      loadBatches();
      setRunningBatchId(null);
    }
    if (matchJob?.status === "failed") {
      setRunningBatchId(null);
    }
  }, [loadBatches, matchJob?.status]);

  const handleDrop = useCallback((files: FileList | null) => {
    const f = files?.[0];
    if (f && (f.name.endsWith(".xlsx") || f.name.endsWith(".xls") || f.name.endsWith(".pdf"))) {
      setFile(f);
      setJobId(null);
    }
  }, []);

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    try {
      const res = await estimates.upload(id, file, startDate, workers, estimateKind, complexMode);
      setJobId(res.job_id);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setUploading(false);
    }
  }

  const status = job?.status;
  const result = job?.result;
  const matchStatus = matchJob?.status;

  async function handleMatchFer(batchId: string) {
    try {
      setRunningBatchId(batchId);
      const res = await estimates.matchFer(id, batchId);
      setMatchJobId(res.job_id);
    } catch (e: any) {
      setRunningBatchId(null);
      alert(e.message);
    }
  }

  return (
    <div style={{ padding: 24, maxWidth: 980 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 20 }}>
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>Загрузка сметы</h2>
          <div style={{ fontSize: 12, color: "var(--muted)", maxWidth: 620 }}>
            Сначала определите тип сметы, затем загрузите файл. В режиме <b style={{ color: "var(--text)" }}>Комплекс</b> новая смета добавится как отдельный блок работ внутри этого объекта.
          </div>
        </div>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "10px 14px",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          <input
            type="checkbox"
            checked={complexMode}
            onChange={(e) => setComplexMode(e.target.checked)}
          />
          <span style={{ fontSize: 13, fontWeight: 600 }}>Комплекс</span>
        </label>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12, marginBottom: 16 }}>
        {KIND_OPTIONS.map((option) => {
          const active = estimateKind === option.id;
          return (
            <button
              key={option.id}
              type="button"
              onClick={() => setEstimateKind(option.id)}
              style={{
                textAlign: "left",
                padding: "16px 16px 14px",
                borderRadius: 10,
                border: active ? "1px solid var(--blue)" : "1px solid var(--border)",
                background: active ? "rgba(59,130,246,.06)" : "var(--surface)",
                cursor: "pointer",
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>{option.title}</div>
              <div style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.45 }}>{option.desc}</div>
            </button>
          );
        })}
      </div>

      <div
        style={{
          marginBottom: 20,
          padding: "12px 14px",
          borderRadius: 8,
          border: "1px solid var(--border)",
          background: complexMode ? "rgba(34,197,94,.06)" : "rgba(245,158,11,.08)",
          color: complexMode ? "#166534" : "#92400e",
          fontSize: 12,
        }}
      >
        {complexMode
          ? "Новая загрузка создаст отдельный блок работ с собственным гантом внутри текущего объекта."
          : "Новая загрузка заменит текущую активную смету и график объекта."}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
        {[
          { label: "Дата начала работ", type: "date", value: startDate, set: setStartDate },
          { label: "Рабочих в бригаде", type: "number", value: workers, set: (v: any) => setWorkers(+v) },
        ].map((f) => (
          <div key={f.label}>
            <label style={{ fontSize: 11, color: "var(--muted)", display: "block", marginBottom: 4, textTransform: "uppercase", letterSpacing: ".06em" }}>
              {f.label}
            </label>
            <input
              type={f.type}
              value={f.value}
              onChange={(e) => f.set(e.target.value)}
              min={f.type === "number" ? 1 : undefined}
              max={f.type === "number" ? 20 : undefined}
              style={{ width: "100%", padding: "8px 12px", border: "1px solid var(--border2)", borderRadius: 5, fontSize: 13, outline: "none" }}
            />
          </div>
        ))}
      </div>

      {!status && (
        <div
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            handleDrop(e.dataTransfer.files);
          }}
          style={{
            border: `2px dashed ${drag ? "var(--blue)" : file ? "#22c55e" : "var(--border2)"}`,
            borderRadius: 8,
            padding: "40px 24px",
            textAlign: "center",
            cursor: "pointer",
            background: drag ? "rgba(59,130,246,.04)" : file ? "rgba(34,197,94,.04)" : "var(--surface)",
            transition: "all .15s",
          }}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.pdf"
            style={{ display: "none" }}
            onChange={(e) => handleDrop(e.target.files)}
          />
          <div style={{ fontSize: 36, marginBottom: 10 }}>{file ? "📊" : "⬆"}</div>
          <div style={{ fontSize: 15, fontWeight: 500, marginBottom: 6 }}>
            {file ? file.name : "Перетащите смету сюда"}
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>
            {file
              ? `${(file.size / 1024).toFixed(1)} KB · нажмите для замены`
              : "Поддерживаются .xlsx, .xls, .pdf · ГрандСмета, CourtDoc, PDF-сметы"}
          </div>
        </div>
      )}

      {file && !status && (
        <button
          onClick={handleUpload}
          disabled={uploading || polling}
          style={{
            marginTop: 16,
            width: "100%",
            padding: "11px",
            background: "var(--blue-dark)",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
            opacity: uploading || polling ? 0.7 : 1,
          }}
        >
          {uploading ? "Отправляем..." : complexMode ? "→ Добавить смету в комплекс" : "→ Загрузить смету"}
        </button>
      )}

      {(status === "pending" || status === "processing") && (
        <div style={{ marginTop: 16, padding: "14px 16px", background: "rgba(59,130,246,.06)", border: "1px solid rgba(59,130,246,.2)", borderRadius: 6 }}>
          <div style={{ fontSize: 13, color: "var(--blue-dark)", fontWeight: 500 }}>
            ⏳ {status === "pending" ? "В очереди..." : "Парсим смету и строим Ганта..."}
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>Это займёт несколько секунд</div>
        </div>
      )}

      {status === "done" && result && (
        <div style={{ marginTop: 16, padding: "16px", background: "rgba(34,197,94,.06)", border: "1px solid rgba(34,197,94,.2)", borderRadius: 6 }}>
          <div style={{ color: "#15803d", fontWeight: 600, fontSize: 14, marginBottom: 10 }}>✓ Смета успешно обработана</div>
          <div style={{ display: "flex", gap: 20, fontSize: 12, color: "var(--muted)", flexWrap: "wrap" }}>
            {[
              ["Блок", result.estimate_batch_name],
              ["Тип", KIND_LABEL[(result.estimate_kind as EstimateKind) ?? estimateKind] ?? "—"],
              ["Позиций сметы", result.estimates_count],
              ["Задач в графике", result.gantt_tasks_count],
              ["Сумма", result.total_price ? `${fmtMoney(result.total_price)} ₽` : "—"],
            ].map(([l, v]) => (
              <span key={l as string}>
                {l}: <b style={{ color: "var(--text)", fontFamily: "var(--mono)" }}>{v}</b>
              </span>
            ))}
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 14, flexWrap: "wrap" }}>
            {result.estimate_batch_id && (
              <button
                onClick={() => handleMatchFer(result.estimate_batch_id as string)}
                disabled={matching}
                style={{ padding: "8px 18px", background: "var(--surface)", color: "var(--text)", border: "1px solid var(--border2)", borderRadius: 5, fontSize: 13, fontWeight: 600, cursor: matching ? "default" : "pointer", opacity: matching ? 0.7 : 1 }}
              >
                {matching && runningBatchId === result.estimate_batch_id ? "Векторно сопоставляем..." : "Векторно сопоставить с ФЕР"}
              </button>
            )}
            <button
              onClick={() => router.push(`/projects/${id}/gantt${result.estimate_batch_id ? `?batch=${result.estimate_batch_id}` : ""}`)}
              style={{ padding: "8px 18px", background: "var(--blue-dark)", color: "#fff", border: "none", borderRadius: 5, fontSize: 13, fontWeight: 600, cursor: "pointer" }}
            >
              Открыть диаграмму Ганта →
            </button>
          </div>
        </div>
      )}

      {status === "failed" && (
        <div style={{ marginTop: 16, padding: "14px 16px", background: "rgba(239,68,68,.06)", border: "1px solid rgba(239,68,68,.2)", borderRadius: 6 }}>
          <div style={{ color: "var(--red)", fontWeight: 600, fontSize: 13 }}>❌ Ошибка обработки</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>{result?.error}</div>
          <button
            onClick={() => {
              setJobId(null);
              setFile(null);
            }}
            style={{ marginTop: 10, padding: "6px 14px", border: "1px solid var(--border2)", borderRadius: 4, background: "var(--surface)", fontSize: 12, cursor: "pointer" }}
          >
            Попробовать снова
          </button>
        </div>
      )}

      {matchStatus === "processing" && (
        <div style={{ marginTop: 16, padding: "14px 16px", background: "rgba(59,130,246,.06)", border: "1px solid rgba(59,130,246,.18)", borderRadius: 6 }}>
          <div style={{ color: "var(--blue-dark)", fontWeight: 600, fontSize: 13 }}>
            ⏳ Идёт векторное сопоставление сметы с ФЕР
          </div>
        </div>
      )}

      {matchStatus === "done" && matchJob?.result && (
        <div style={{ marginTop: 16, padding: "14px 16px", background: "rgba(34,197,94,.06)", border: "1px solid rgba(34,197,94,.18)", borderRadius: 6 }}>
          <div style={{ color: "#15803d", fontWeight: 600, fontSize: 13 }}>
            ✓ Векторное сопоставление с ФЕР завершено
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
            Размечено строк: <b style={{ color: "var(--text)" }}>{matchJob.result.matched_rows_count ?? 0}</b>
            {typeof matchJob.result.low_confidence_count === "number"
              ? ` · низкая уверенность: ${matchJob.result.low_confidence_count}`
              : ""}
          </div>
        </div>
      )}

      {matchStatus === "failed" && (
        <div style={{ marginTop: 16, padding: "14px 16px", background: "rgba(239,68,68,.06)", border: "1px solid rgba(239,68,68,.18)", borderRadius: 6 }}>
          <div style={{ color: "var(--red)", fontWeight: 600, fontSize: 13 }}>❌ Ошибка векторного сопоставления с ФЕР</div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>{matchJob?.result?.error}</div>
        </div>
      )}

      <div style={{ marginTop: 24, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".08em", fontFamily: "var(--mono)" }}>
            Блоки работ в объекте
          </div>
          {loadingBatches && <div style={{ fontSize: 11, color: "var(--muted)" }}>Загрузка...</div>}
        </div>

        {!loadingBatches && batches.length === 0 && (
          <div style={{ fontSize: 12, color: "var(--muted)" }}>
            Пока нет загруженных смет. Первая загрузка создаст первый блок работ.
          </div>
        )}

        <div style={{ display: "grid", gap: 10 }}>
          {batches.map((batch) => (
            <div
              key={batch.id}
              style={{
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: "12px 14px",
                background: "var(--bg)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{batch.name}</div>
                  <div style={{ marginTop: 4, fontSize: 11, color: "var(--muted)" }}>
                    {KIND_LABEL[(batch.estimate_kind as EstimateKind) ?? "non_residential"] ?? batch.estimate_kind}
                    {batch.source_filename ? ` · ${batch.source_filename}` : ""}
                  </div>
                </div>
                <button
                  onClick={() => router.push(`/projects/${id}/gantt?batch=${batch.id}`)}
                  style={{ padding: "6px 12px", border: "1px solid var(--border2)", borderRadius: 5, background: "var(--surface)", cursor: "pointer", fontSize: 12 }}
                >
                  Открыть гант
                </button>
              </div>
              <div style={{ display: "flex", gap: 16, marginTop: 10, fontSize: 11, color: "var(--muted)", flexWrap: "wrap" }}>
                <span>Позиций: <b style={{ color: "var(--text)" }}>{batch.estimates_count}</b></span>
                <span>Задач: <b style={{ color: "var(--text)" }}>{batch.gantt_tasks_count}</b></span>
                <span>ФЕР: <b style={{ color: "var(--text)" }}>{batch.fer_matched_count}</b> / {batch.estimates_count}</span>
                <span>Сумма: <b style={{ color: "var(--text)" }}>{fmtMoney(batch.total_price)} ₽</b></span>
              </div>
              <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
                <button
                  onClick={() => handleMatchFer(batch.id)}
                  disabled={matching}
                  style={{ padding: "7px 12px", border: "1px solid var(--border2)", borderRadius: 5, background: "var(--surface)", cursor: matching ? "default" : "pointer", fontSize: 12, fontWeight: 600, opacity: matching ? 0.7 : 1 }}
                >
                  {matching && runningBatchId === batch.id
                    ? "Векторно сопоставляем..."
                    : batch.fer_matched_count > 0
                      ? "Обновить векторные типы ФЕР"
                      : "Векторно сопоставить с ФЕР"}
                </button>
                <button
                  onClick={() => router.push(`/projects/${id}/estimate?batch=${batch.id}`)}
                  style={{ padding: "7px 12px", border: "1px solid var(--border2)", borderRadius: 5, background: "var(--surface)", cursor: "pointer", fontSize: 12 }}
                >
                  Открыть смету
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 24, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, padding: 16 }}>
        <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 10, fontFamily: "var(--mono)" }}>
          Поддерживаемые форматы
        </div>
        {[
          ["ГрандСмета / АРПС", "Экспорт в Excel"],
          ["CourtDoc / A0", "Табличный формат"],
          ["1С: Подрядчик", "Выгрузка в .xlsx"],
          ["Excel вручную", "Строчный и столбцовый"],
          ["КП подрядчика", "Произвольная таблица"],
          ["PDF-смета", ".pdf с табличным содержимым"],
        ].map(([name, desc]) => (
          <div key={name} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid var(--border)", fontSize: 12 }}>
            <span style={{ fontWeight: 500 }}>{name}</span>
            <span style={{ color: "var(--muted)", fontSize: 11 }}>{desc}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
