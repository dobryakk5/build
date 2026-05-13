"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { estimates, workPlan as wpApi, nw as nwApi, fer as ferApi } from "@/lib/api";
import type {
  FerRowOption,
  FerSearchResult,
  NwDictionaries,
  NwItem,
  WorkPlanCard,
  WorkPlanCardPatch,
  WorkPlanCardDetail,
  WorkPlanEstimateRow,
  WorkPlanPalette,
  WorkPlanStatus,
} from "@/lib/types";

const COLORS = {
  border: "#e2e8f0",
  borderHard: "#cbd5e1",
  bg: "#f8fafc",
  cardBg: "white",
  text: "#0f172a",
  muted: "#64748b",
  primary: "#0284c7",
  primaryBg: "#0284c715",
  ok: "#22c55e",
  okBg: "#22c55e18",
  warn: "#eab308",
  warnBg: "#eab30818",
  err: "#ef4444",
  errBg: "#ef444418",
  draft: "#94a3b8",
  draftBg: "#94a3b818",
};

const STATUS_LABEL: Record<WorkPlanStatus, string> = {
  auto_proposed: "автогенерация",
  confirmed: "подтверждено",
  removed: "удалено",
  custom_added: "добавлено вручную",
  fer_mapped: "ФЕР подобран",
  scheduled: "в графике",
  needs_volume: "нужен объём",
  needs_review: "нужна проверка",
};

const STATUS_COLOR: Record<WorkPlanStatus, { fg: string; bg: string }> = {
  auto_proposed: { fg: COLORS.primary, bg: COLORS.primaryBg },
  confirmed:     { fg: COLORS.ok,      bg: COLORS.okBg },
  removed:       { fg: COLORS.muted,   bg: COLORS.bg },
  custom_added:  { fg: "#7c3aed",      bg: "#7c3aed18" },
  fer_mapped:    { fg: COLORS.ok,      bg: COLORS.okBg },
  scheduled:     { fg: COLORS.ok,      bg: COLORS.okBg },
  needs_volume:  { fg: COLORS.warn,    bg: COLORS.warnBg },
  needs_review:  { fg: COLORS.err,     bg: COLORS.errBg },
};

function Chip({
  label,
  color = COLORS.muted,
  bg = COLORS.bg,
  title,
  onClick,
}: { label: string; color?: string; bg?: string; title?: string; onClick?: (e: React.MouseEvent<HTMLSpanElement>) => void }) {
  return (
    <span
      title={title}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: 12,
        fontSize: 11,
        fontWeight: 600,
        background: bg,
        color,
        border: `1px solid ${color}30`,
        whiteSpace: "nowrap",
        cursor: onClick ? "pointer" : "default",
      }}
    >
      {label}
    </span>
  );
}

function dictMap(entries: { code: string; name?: string; description?: string }[] | undefined) {
  if (!entries) return {};
  const out: Record<string, string> = {};
  for (const e of entries) out[e.code] = e.name ?? e.description ?? e.code;
  return out;
}

export default function WorkPlanPage() {
  const router = useRouter();
  const { id: projectId } = useParams<{ id: string }>();
  const search = useSearchParams();
  const batchId = search.get("batch");

  const [cards, setCards] = useState<WorkPlanCard[]>([]);
  const [palette, setPalette] = useState<WorkPlanPalette | null>(null);
  const [dicts, setDicts] = useState<NwDictionaries | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [llmResolving, setLlmResolving] = useState(false);
  const [matchingFer, setMatchingFer] = useState(false);
  const [building, setBuilding] = useState(false);
  const [showBuildDialog, setShowBuildDialog] = useState(false);
  const [ferRowDialogCard, setFerRowDialogCard] = useState<WorkPlanCard | null>(null);
  const [unmatched, setUnmatched] = useState<Array<{ id: string; section: string | null; work_name: string; unit: string | null; quantity: number | null }>>([]);
  const [showUnmatched, setShowUnmatched] = useState(false);
  const [unmatchedSelected, setUnmatchedSelected] = useState<Set<string>>(new Set());
  const [linkTarget, setLinkTarget] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<"all" | "active" | "needs">("active");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [detailCard, setDetailCard] = useState<WorkPlanCard | null>(null);
  const [openWtCodes, setOpenWtCodes] = useState<Set<string> | null>(null);
  const [matchingFerCardIds, setMatchingFerCardIds] = useState<Set<number>>(new Set());
  const [manualFerCard, setManualFerCard] = useState<WorkPlanCard | null>(null);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [resolvingBatch, setResolvingBatch] = useState(!batchId);
  const autoTriggeredRef = useRef(false);

  useEffect(() => {
    if (batchId) {
      setResolvingBatch(false);
      return;
    }

    let cancelled = false;
    setResolvingBatch(true);
    estimates
      .batches(projectId)
      .then((batches) => {
        if (cancelled) return;
        const latestBatchId = batches.length ? batches[batches.length - 1]?.id ?? null : null;
        if (latestBatchId) {
          router.replace(`/projects/${projectId}/work-plan?batch=${latestBatchId}`);
          return;
        }
        setResolvingBatch(false);
      })
      .catch((e: any) => {
        if (cancelled) return;
        setError(e.message ?? "Не удалось найти загруженную смету.");
        setResolvingBatch(false);
      });

    return () => {
      cancelled = true;
    };
  }, [batchId, projectId, router]);

  const reload = useCallback(async () => {
    if (!batchId) return;
    setLoading(true);
    setError(null);
    try {
      const [pl, pal, un] = await Promise.all([
        wpApi.list(projectId, batchId),
        wpApi.palette(projectId, batchId).catch(() => null),
        wpApi.unmatched(projectId, batchId).catch(() => ({ items: [], total: 0 })),
      ]);
      setCards(pl.items);
      setPalette(pal);
      setUnmatched(un.items);
      setUnmatchedSelected(new Set());
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, [projectId, batchId]);

  useEffect(() => { reload(); }, [reload]);

  useEffect(() => {
    nwApi.dictionaries().then(setDicts).catch(() => {});
  }, []);

  const otMap = useMemo(() => dictMap(dicts?.object_types), [dicts]);
  const btMap = useMemo(() => dictMap(dicts?.building_technologies), [dicts]);
  const lsMap = useMemo(() => dictMap(dicts?.location_scopes), [dicts]);
  const stMap = useMemo(() => dictMap(dicts?.stages), [dicts]);

  // Group cards by work_type, hide removed unless filterStatus='all'
  const grouped = useMemo(() => {
    const visible = cards.filter((c) => {
      if (c.parent_id !== null) return false; // sub-cards shown nested
      if (filterStatus === "all") return true;
      if (filterStatus === "needs") return c.status === "needs_volume" || c.status === "needs_review";
      return c.status !== "removed";
    });
    const grp: Record<string, { wtName: string; cards: WorkPlanCard[] }> = {};
    for (const c of visible) {
      const k = c.work_type_code;
      if (!grp[k]) grp[k] = { wtName: c.work_type_name, cards: [] };
      grp[k].cards.push(c);
    }
    return grp;
  }, [cards, filterStatus]);

  useEffect(() => {
    if (openWtCodes !== null) return;
    const codes = Object.keys(grouped);
    if (codes.length > 0) setOpenWtCodes(new Set(codes));
  }, [grouped, openWtCodes]);

  // Find sub-cards by parent
  const childrenOf = useCallback(
    (parentId: number) => cards.filter((c) => c.parent_id === parentId),
    [cards],
  );

  function toggleWt(wtCode: string) {
    setOpenWtCodes((prev) => {
      const next = new Set(prev ?? []);
      if (next.has(wtCode)) next.delete(wtCode); else next.add(wtCode);
      return next;
    });
  }

  async function handleAuto(force: boolean, silent = false) {
    if (!batchId) return;
    setGenerating(true);
    setError(null);
    try {
      const res = await wpApi.autoCreate(projectId, batchId, force);
      if (!silent) {
        alert(
          `Создано карточек: ${res.cards_created}\n` +
          `Сматчилось строк сметы: ${res.matched_rows} из ${res.estimate_rows_total}\n` +
          `Не определилось (нужен LLM/ручной): ${res.unmatched_rows}\n` +
          `Из палитры добавлено: ${res.expected_added}`,
        );
      }
      await reload();
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setGenerating(false);
    }
  }

  // Авто-триггер генерации плана если попали на пустой план у свежей сметы
  useEffect(() => {
    if (loading || generating) return;
    if (autoTriggeredRef.current) return;
    if (cards.length === 0 && unmatched.length > 0) {
      autoTriggeredRef.current = true;
      handleAuto(false, true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cards.length, unmatched.length, loading, generating]);

  async function patchCard(id: number, patch: WorkPlanCardPatch) {
    if (!batchId) return;
    try {
      await wpApi.update(projectId, batchId, id, patch);
      await reload();
    } catch (e: any) {
      alert(`Ошибка: ${e.message}`);
    }
  }

  async function confirmCard(id: number) {
    if (!batchId) return;
    await wpApi.confirm(projectId, batchId, id);
    await reload();
  }

  async function removeCard(id: number) {
    if (!batchId) return;
    if (!confirm("Удалить карточку?")) return;
    await wpApi.remove(projectId, batchId, id, false);
    await reload();
  }

  async function handleLlmResolve() {
    if (!batchId) return;
    if (!confirm("Запустить LLM разбор строк сметы которые не сматчились keyword'ами?\nИспользует OpenRouter (gpt-4o-mini), дёшево.")) return;
    setLlmResolving(true);
    try {
      const res = await wpApi.llmResolve(projectId, batchId);
      alert(
        `LLM-разбор завершён:\n` +
        `Было непривязанных строк: ${res.unmatched_before}\n` +
        `LLM сматчил: ${res.matched_by_llm}\n` +
        `Осталось: ${res.still_unmatched}\n` +
        `Новых карточек: ${res.new_cards}, добавлено к существующим: ${res.linked_to_existing}`,
      );
      await reload();
    } catch (e: any) {
      alert(`Ошибка: ${e.message}`);
    } finally {
      setLlmResolving(false);
    }
  }

  async function confirmAll() {
    if (!batchId) return;
    if (!confirm("Подтвердить все авто-карточки?")) return;
    const res = await wpApi.confirmAll(projectId, batchId);
    alert(`Подтверждено: ${res.confirmed}`);
    await reload();
  }

  async function handleMatchFerAll() {
    if (!batchId) return;
    if (!confirm("Подобрать ФЕР расценки для всех карточек без ФЕР?\nИспользует LLM (free model).")) return;
    setMatchingFer(true);
    try {
      const res = await wpApi.matchFerAll(projectId, batchId);
      alert(
        `ФЕР подбор завершён:\n` +
        `Обработано карточек: ${res.total_processed}\n` +
        `Сматчилось: ${res.fer_mapped}\n` +
        `Нужна проверка (low score): ${res.needs_review}\n` +
        `Нет кандидатов: ${res.no_candidates}\n` +
        `Ошибок: ${res.errors}`,
      );
      await reload();
    } catch (e: any) {
      alert(`Ошибка: ${e.message}`);
    } finally {
      setMatchingFer(false);
    }
  }

  async function handleMatchFerCard(planId: number) {
    if (!batchId) return;
    setMatchingFerCardIds((prev) => new Set(prev).add(planId));
    try {
      const res = await wpApi.matchFer(projectId, batchId, planId);
      if (res.fer_table_id) {
        await reload();
      } else {
        alert(`Не нашлось ФЕР кандидатов для этой карточки.\n${res.reason ?? ""}`);
      }
    } catch (e: any) {
      alert(`Ошибка: ${e.message}`);
    } finally {
      setMatchingFerCardIds((prev) => {
        const next = new Set(prev);
        next.delete(planId);
        return next;
      });
    }
  }

  async function handleManualFerSelect(card: WorkPlanCard, result: FerSearchResult | null) {
    if (!batchId) return;
    await wpApi.setFerTable(projectId, batchId, card.id, result?.table_id ?? null);
    setManualFerCard(null);
    await reload();
  }

  async function handleLinkSelected() {
    if (!batchId || !linkTarget) {
      alert("Выберите карточку для привязки");
      return;
    }
    const ids = Array.from(unmatchedSelected);
    if (ids.length === 0) {
      alert("Выберите строки сметы");
      return;
    }
    const res = await wpApi.linkEstimates(projectId, batchId, Number(linkTarget), ids);
    alert(`Привязано: ${res.linked}`);
    setLinkTarget("");
    await reload();
  }

  async function handleComputeDurations() {
    if (!batchId) return;
    setBuilding(true);
    try {
      const res = await wpApi.computeDurations(projectId, batchId);
      alert(
        `Длительности рассчитаны:\n` +
        `Карточек обработано: ${res.total}\n` +
        `Длительности заданы: ${res.computed}\n` +
        `Пропущено (без ФЕР/объёма): ${res.skipped}`,
      );
      await reload();
    } catch (e: any) {
      alert(`Ошибка: ${e.message}`);
    } finally {
      setBuilding(false);
    }
  }

  async function handleBuildGantt(startDate: string, replace: boolean) {
    if (!batchId) return;
    setBuilding(true);
    try {
      const res = await wpApi.buildGantt(projectId, batchId, { start_date: startDate, replace });
      const lines: string[] = [];
      if (res.created > 0) {
        lines.push(`✓ ГПР собран:`);
        lines.push(`  Задач: ${res.created}`);
        lines.push(`  Зависимостей: ${res.deps}`);
        lines.push(`  Этапов: ${res.stages}`);
        if (res.fallback_used) lines.push(`\n⚠️ ${res.fallback_note}`);
      } else {
        lines.push(`⚠️ ГПР не собрался.`);
        if (res.warning) lines.push(res.warning);
      }
      alert(lines.join("\n"));
      setShowBuildDialog(false);
      await reload();
      if (res.created > 0 && confirm("Перейти на экран ГПР?")) {
        router.push(`/projects/${projectId}/gantt?batch=${batchId}`);
      }
    } catch (e: any) {
      alert(`Ошибка: ${e.message}`);
    } finally {
      setBuilding(false);
    }
  }

  function toggleUnmatchedRow(id: string) {
    const next = new Set(unmatchedSelected);
    if (next.has(id)) next.delete(id); else next.add(id);
    setUnmatchedSelected(next);
  }

  if (resolvingBatch) {
    return <div style={{ padding: 40, color: COLORS.muted, fontSize: 14 }}>Открываю последний план работ…</div>;
  }

  if (!batchId) {
    return (
      <div style={{ padding: 40, color: COLORS.muted, fontSize: 14 }}>
        <p>Выберите загруженную смету (batch) — план работ строится для конкретного batch'а.</p>
        <button
          onClick={() => router.push(`/projects/${projectId}/upload`)}
          style={{ marginTop: 12, padding: "8px 14px", background: COLORS.primary, color: "white", border: "none", borderRadius: 6, cursor: "pointer" }}
        >
          К загрузке смет →
        </button>
      </div>
    );
  }

  const totalCards = cards.length;
  const confirmedCount = cards.filter((c) => c.status === "confirmed" || c.status === "fer_mapped" || c.status === "scheduled").length;
  const needsVolumeCount = cards.filter((c) => c.status === "needs_volume").length;

  return (
    <div style={{ padding: 16, background: COLORS.bg, minHeight: "calc(100vh - 64px)" }}>
      <style jsx global>{`
        @keyframes work-plan-spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
      {/* Top toolbar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 16,
          flexWrap: "wrap",
        }}
      >
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: COLORS.text }}>
          План работ
        </h2>
        <span style={{ fontSize: 13, color: COLORS.muted }}>
          Всего карточек: <strong>{totalCards}</strong> · Подтверждено: <strong>{confirmedCount}</strong> · Нужен объём: <strong>{needsVolumeCount}</strong>
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {totalCards === 0 ? (
            <button
              onClick={() => handleAuto(false)}
              disabled={generating}
              style={btn(COLORS.primary, "white")}
            >
              {generating ? "Генерация…" : "🪄 Сгенерировать план из сметы"}
            </button>
          ) : (
            <>
              <button
                onClick={handleLlmResolve}
                disabled={llmResolving}
                style={btn("#7c3aed", "white")}
                title="LLM разбор для unmatched строк сметы"
              >
                {llmResolving ? "LLM…" : "🤖 Доразобрать LLM"}
              </button>
              <button
                onClick={() => handleAuto(true)}
                disabled={generating}
                style={btn(COLORS.warn, "white")}
                title="Удалить план и собрать заново"
              >
                {generating ? "…" : "🔄 Пересобрать"}
              </button>
              <button onClick={confirmAll} style={btn(COLORS.ok, "white")}>
                ✓ Подтвердить все
              </button>
              <button
                onClick={handleMatchFerAll}
                disabled={matchingFer}
                style={btn("#0284c7", "white")}
                title="Узкий FER matcher для всех карточек"
              >
                {matchingFer ? "ФЕР…" : "🔗 Подобрать ФЕР"}
              </button>
              <button
                onClick={handleComputeDurations}
                disabled={building}
                style={btn("#0891b2", "white")}
                title="Рассчитать длительность из FER human_hours × объём"
              >
                {building ? "…" : "🧮 Длительности"}
              </button>
              <button
                onClick={() => setShowBuildDialog(true)}
                disabled={building}
                style={btn("#16a34a", "white")}
                title="Создать задачи ГПР из плана"
              >
                📊 Построить ГПР
              </button>
              <button onClick={() => setShowAddDialog(true)} style={btn("white", COLORS.text)}>
                + Добавить карточку
              </button>
            </>
          )}
        </div>
      </div>

      {/* Filters */}
      {totalCards > 0 && (
        <div style={{ display: "flex", gap: 4, marginBottom: 12 }}>
          {(["active", "needs", "all"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setFilterStatus(v)}
              style={{
                padding: "6px 12px",
                fontSize: 12,
                background: filterStatus === v ? COLORS.primaryBg : "white",
                color: filterStatus === v ? COLORS.primary : COLORS.muted,
                border: `1px solid ${filterStatus === v ? COLORS.primary : COLORS.border}`,
                borderRadius: 6,
                cursor: "pointer",
                fontWeight: 600,
              }}
            >
              {v === "active" ? "Активные" : v === "needs" ? "Нужен объём" : "Все"}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div style={{ padding: 12, background: COLORS.errBg, color: COLORS.err, borderRadius: 6, marginBottom: 12, fontSize: 13 }}>
          {error}
        </div>
      )}

      {/* UNMATCHED section */}
      {unmatched.length > 0 && (
        <div style={{ marginBottom: 16, background: COLORS.cardBg, border: `1px solid ${COLORS.warn}50`, borderRadius: 8, padding: 12 }}>
          <div
            style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", userSelect: "none" }}
            onClick={() => setShowUnmatched(!showUnmatched)}
          >
            <span style={{ fontSize: 14, fontWeight: 700, color: COLORS.warn }}>
              ⚠️ Не привязано к плану ({unmatched.length})
            </span>
            <span style={{ fontSize: 11, color: COLORS.muted }}>
              — это строки сметы которые ни keyword, ни LLM не определили. Привяжите вручную или создайте новую карточку.
            </span>
            <span style={{ marginLeft: "auto", fontSize: 12, color: COLORS.muted }}>
              {showUnmatched ? "▲ свернуть" : "▼ показать"}
            </span>
          </div>

          {showUnmatched && (
            <div style={{ marginTop: 12 }}>
              {/* Toolbar для bulk-привязки */}
              {unmatchedSelected.size > 0 && (
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, padding: 8, background: COLORS.warnBg, borderRadius: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 600 }}>
                    Выбрано: {unmatchedSelected.size}
                  </span>
                  <select
                    value={linkTarget}
                    onChange={(e) => setLinkTarget(e.target.value === "" ? "" : Number(e.target.value))}
                    style={{ ...inputStyle, flex: 1, maxWidth: 350 }}
                  >
                    <option value="">— выбрать карточку плана —</option>
                    {cards.filter((c) => c.parent_id === null && c.status !== "removed").map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.nw_item_code} {c.nw_label.slice(0, 40)} {c.unit ? `(${c.unit})` : ""}
                      </option>
                    ))}
                  </select>
                  <button onClick={handleLinkSelected} style={btn(COLORS.primary, "white")}>
                    🎯 Привязать
                  </button>
                  <button onClick={() => setUnmatchedSelected(new Set())} style={btn("white", COLORS.muted)}>
                    Сбросить
                  </button>
                </div>
              )}

              <div style={{ maxHeight: 400, overflow: "auto", border: `1px solid ${COLORS.border}`, borderRadius: 4 }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr style={{ background: COLORS.bg, borderBottom: `1px solid ${COLORS.border}` }}>
                      <th style={{ width: 30, padding: "6px 8px" }}>
                        <input
                          type="checkbox"
                          checked={unmatchedSelected.size === unmatched.length && unmatched.length > 0}
                          onChange={(e) => {
                            if (e.target.checked) setUnmatchedSelected(new Set(unmatched.map((u) => u.id)));
                            else setUnmatchedSelected(new Set());
                          }}
                        />
                      </th>
                      <th style={{ width: 150, padding: "6px 8px", textAlign: "left", fontWeight: 600, color: COLORS.muted }}>Раздел</th>
                      <th style={{ padding: "6px 8px", textAlign: "left", fontWeight: 600, color: COLORS.muted }}>Работа</th>
                      <th style={{ width: 80, padding: "6px 8px", textAlign: "right", fontWeight: 600, color: COLORS.muted }}>Объём</th>
                      <th style={{ width: 60, padding: "6px 8px", textAlign: "left", fontWeight: 600, color: COLORS.muted }}>Ед.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {unmatched.map((u) => (
                      <tr
                        key={u.id}
                        onClick={() => toggleUnmatchedRow(u.id)}
                        style={{ cursor: "pointer", background: unmatchedSelected.has(u.id) ? COLORS.warnBg : "white", borderBottom: `1px solid ${COLORS.border}` }}
                      >
                        <td style={{ padding: "6px 8px" }} onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={unmatchedSelected.has(u.id)}
                            onChange={() => toggleUnmatchedRow(u.id)}
                          />
                        </td>
                        <td style={{ padding: "6px 8px", color: COLORS.muted }}>{u.section ?? "—"}</td>
                        <td style={{ padding: "6px 8px" }}>{u.work_name}</td>
                        <td style={{ padding: "6px 8px", textAlign: "right", fontFamily: "var(--mono, monospace)" }}>
                          {u.quantity != null ? Number(u.quantity).toLocaleString("ru") : "—"}
                        </td>
                        <td style={{ padding: "6px 8px", color: COLORS.muted }}>{u.unit ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {loading && <div style={{ padding: 20, color: COLORS.muted, fontSize: 13 }}>Загрузка…</div>}
      {generating && (
        <div style={{ padding: 16, color: COLORS.primary, fontSize: 14, fontWeight: 600, background: COLORS.primaryBg, borderRadius: 6, marginBottom: 12, border: `1px solid ${COLORS.primary}30` }}>
          🪄 Генерируется план работ из сметы… (keyword-классификация по строкам). Это занимает 1-3 секунды.
        </div>
      )}

      {/* Empty state */}
      {!loading && !generating && totalCards === 0 && palette && (
        <div style={{ padding: 24, background: COLORS.cardBg, borderRadius: 8, border: `1px solid ${COLORS.border}` }}>
          <h3 style={{ margin: "0 0 8px 0", fontSize: 15 }}>Плана пока нет</h3>
          <p style={{ margin: "0 0 12px 0", color: COLORS.muted, fontSize: 13 }}>
            По типу сметы предполагается {palette.nw_items.length} видов работ из {palette.wt_codes.length} категорий:
          </p>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
            {palette.wt_codes.map((wt) => (
              <Chip key={wt} label={wt} color={COLORS.primary} bg={COLORS.primaryBg} />
            ))}
          </div>
          <p style={{ margin: 0, color: COLORS.muted, fontSize: 12 }}>
            Нажмите «Сгенерировать план из сметы» — алгоритм пройдётся по строкам сметы и автоматически создаст карточки плана.
          </p>
        </div>
      )}

      {/* Cards by WT */}
      {!loading && Object.keys(grouped).length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {Object.entries(grouped).map(([wtCode, group]) => {
            const isOpen = openWtCodes?.has(wtCode) ?? true;
            return (
              <section key={wtCode}>
                <button
                  type="button"
                  onClick={() => toggleWt(wtCode)}
                  style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    margin: "0 0 8px 0",
                    padding: "8px 10px",
                    background: "white",
                    border: `1px solid ${COLORS.border}`,
                    borderRadius: 6,
                    cursor: "pointer",
                    textAlign: "left",
                  }}
                >
                  <span style={{ width: 14, color: COLORS.muted, fontSize: 12 }}>
                    {isOpen ? "⌄" : "›"}
                  </span>
                  <span style={{ fontFamily: "var(--mono, monospace)", color: COLORS.muted, fontSize: 12 }}>{wtCode}</span>
                  <span style={{ fontSize: 14, color: COLORS.text, fontWeight: 700 }}>{group.wtName}</span>
                  <span style={{ marginLeft: "auto", fontSize: 12, color: COLORS.muted, fontWeight: 500 }}>
                    {group.cards.length}
                  </span>
                </button>
                {isOpen && (
                  <div style={{ background: COLORS.cardBg, border: `1px solid ${COLORS.border}`, borderRadius: 6, overflowX: "auto" }}>
                    <table style={{ width: "max-content", minWidth: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                      <thead>
                        <tr style={{ background: "#1e293b" }}>
                          {["Работа", "Ед.", "Кол-во", "Статус", "ФЕР", "Трудоемкость", "Действия"].map((header) => (
                            <th
                              key={header}
                              style={{
                                ...planThStyle,
                                textAlign: ["Ед.", "Кол-во", "Трудоемкость"].includes(header) ? "right" : "left",
                                minWidth:
                                  header === "Работа" ? 420 :
                                  header === "ФЕР" ? 85 :
                                  header === "Трудоемкость" ? 75 :
                                  header === "Действия" ? 140 : 86,
                              }}
                            >
                              {header}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {group.cards.map((c, index) => (
                          <PlanTableRow
                            key={c.id}
                            projectId={projectId}
                            batchId={batchId}
                            card={c}
                            children={childrenOf(c.id)}
                            index={index}
                            isEditing={editingId === c.id}
                            onEdit={() => setEditingId(c.id)}
                            onClose={() => setEditingId(null)}
                            onPatch={(p) => patchCard(c.id, p)}
                            onConfirm={() => confirmCard(c.id)}
                            onRemove={() => removeCard(c.id)}
                            onMatchFer={() => handleMatchFerCard(c.id)}
                            isMatchingFer={matchingFerCardIds.has(c.id)}
                            onManualFer={() => setManualFerCard(c)}
                            onPickRow={() => setFerRowDialogCard(c)}
                            onOpenDetails={() => setDetailCard(c)}
                            dicts={{ otMap, btMap, lsMap, stMap }}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}

      {/* Add dialog */}
      {showAddDialog && (
        <AddCardDialog
          batchId={batchId}
          projectId={projectId}
          onClose={() => setShowAddDialog(false)}
          onAdded={async () => { setShowAddDialog(false); await reload(); }}
        />
      )}

      {/* Build gantt dialog */}
      {showBuildDialog && (
        <BuildGanttDialog
          onClose={() => setShowBuildDialog(false)}
          onBuild={handleBuildGantt}
        />
      )}

      {/* FER row picker dialog */}
      {ferRowDialogCard && (
        <FerRowDialog
          projectId={projectId}
          batchId={batchId}
          card={ferRowDialogCard}
          onClose={() => setFerRowDialogCard(null)}
          onSaved={async () => { setFerRowDialogCard(null); await reload(); }}
        />
      )}

      {detailCard && (
        <WorkPlanDetailPanel
          projectId={projectId}
          batchId={batchId}
          card={detailCard}
          onClose={() => setDetailCard(null)}
          onPickRow={() => {
            setFerRowDialogCard(detailCard);
            setDetailCard(null);
          }}
          onReplaceFer={(cardToReplace) => {
            setManualFerCard(cardToReplace);
            setDetailCard(null);
          }}
        />
      )}

      {manualFerCard && (
        <WorkPlanFerSearchModal
          card={manualFerCard}
          projectId={projectId}
          batchId={batchId}
          onClose={() => setManualFerCard(null)}
          onSelect={(result) => handleManualFerSelect(manualFerCard, result)}
        />
      )}
    </div>
  );
}

function FerRowDialog({
  projectId,
  batchId,
  card,
  onClose,
  onSaved,
}: {
  projectId: string;
  batchId: string;
  card: WorkPlanCard;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [rows, setRows] = useState<FerRowOption[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [autoLlm, setAutoLlm] = useState(false);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<number | null>(card.fer_row_id);

  useEffect(() => {
    setLoading(true);
    wpApi
      .ferRows(projectId, batchId, card.id)
      .then((r) => setRows(r.items))
      .catch((e) => alert(`Ошибка: ${e.message}`))
      .finally(() => setLoading(false));
  }, [projectId, batchId, card.id]);

  const filtered = useMemo(() => {
    if (!rows) return [];
    if (!search) return rows;
    const q = search.toLowerCase();
    return rows.filter((r) => (r.clarification || "").toLowerCase().includes(q));
  }, [rows, search]);

  async function save() {
    setSaving(true);
    try {
      await wpApi.setFerRow(projectId, batchId, card.id, selected);
      onSaved();
    } catch (e: any) {
      alert(`Ошибка: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }

  async function autoPickLlm() {
    if (!confirm("LLM подберёт строку из ФЕР таблицы. Продолжить?")) return;
    setAutoLlm(true);
    try {
      const res = await wpApi.autoPickFerRow(projectId, batchId, card.id);
      if (res.fer_row_id) {
        setSelected(res.fer_row_id);
        const pickedPosition = rows?.find((row) => row.id === res.fer_row_id)?.position;
        alert(`LLM выбрал строку ${formatFerRowPosition(pickedPosition)}\nUverennost: ${res.score?.toFixed(2)}\nОбоснование: ${res.reason ?? "—"}`);
      } else {
        alert(`LLM не смог подобрать: ${res.skipped ?? "?"}`);
      }
      onSaved();
    } catch (e: any) {
      alert(`Ошибка: ${e.message}`);
    } finally {
      setAutoLlm(false);
    }
  }

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "#0f172a40", zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: "white", padding: 20, borderRadius: 8, width: 720, maxHeight: "85vh", display: "flex", flexDirection: "column" }}>
        <div style={{ marginBottom: 12 }}>
          <h3 style={{ margin: "0 0 4px 0", fontSize: 16 }}>Выбрать строку расценки</h3>
          <div style={{ fontSize: 12, color: COLORS.muted }}>
            Карточка <strong>{card.nw_item_code}</strong>: {card.nw_label}
            {card.quantity != null && card.unit && (
              <> · объём <strong>{card.quantity} {card.unit}</strong></>
            )}
          </div>
          {card.fer_table_title && (
            <div style={{ fontSize: 11, color: COLORS.muted, marginTop: 4 }}>
              ФЕР {formatFerCode(card)}: {card.fer_table_title}
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          <input
            type="search"
            placeholder="Поиск по тексту строки..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ ...inputStyle, flex: 1 }}
          />
          <button onClick={autoPickLlm} disabled={autoLlm} style={btn("#7c3aed", "white")}>
            {autoLlm ? "LLM…" : "🤖 Подобрать LLM"}
          </button>
        </div>

        {loading && <div style={{ padding: 20, color: COLORS.muted, fontSize: 13 }}>Загрузка…</div>}
        {rows && filtered.length === 0 && (
          <div style={{ padding: 20, color: COLORS.muted, fontSize: 12 }}>
            Нет строк {search ? "по запросу" : "в этой ФЕР таблице"}.
          </div>
        )}

        {rows && filtered.length > 0 && (
          <div style={{ flex: 1, overflow: "auto", border: `1px solid ${COLORS.border}`, borderRadius: 4 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead style={{ position: "sticky", top: 0, background: COLORS.bg, zIndex: 1 }}>
                <tr style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                  <th style={{ width: 30 }}></th>
                  <th style={{ padding: "8px 10px", textAlign: "left", fontWeight: 600, color: COLORS.muted }}>Описание (clarification)</th>
                  <th style={{ width: 80, padding: "8px 10px", textAlign: "right", fontWeight: 600, color: COLORS.muted }}>Чел.час</th>
                  <th style={{ width: 80, padding: "8px 10px", textAlign: "right", fontWeight: 600, color: COLORS.muted }}>Маш.час</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr
                    key={r.id}
                    onClick={() => setSelected(r.id)}
                    style={{
                      cursor: "pointer",
                      background: selected === r.id ? "#7c3aed18" : "white",
                      borderBottom: `1px solid ${COLORS.border}`,
                    }}
                  >
                    <td style={{ padding: "6px 10px", textAlign: "center" }}>
                      <input type="radio" checked={selected === r.id} onChange={() => setSelected(r.id)} />
                    </td>
                    <td style={{ padding: "6px 10px", lineHeight: 1.3 }}>
                      <code style={{ fontSize: 10, color: COLORS.muted, marginRight: 4 }}>с{r.position}</code>
                      {r.clarification}
                    </td>
                    <td style={{ padding: "6px 10px", textAlign: "right", fontFamily: "var(--mono, monospace)" }}>
                      {r.h_hour != null ? Number(r.h_hour).toLocaleString("ru") : "—"}
                    </td>
                    <td style={{ padding: "6px 10px", textAlign: "right", fontFamily: "var(--mono, monospace)" }}>
                      {r.m_hour != null ? Number(r.m_hour).toLocaleString("ru") : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "space-between", marginTop: 12 }}>
          <button
            onClick={() => { setSelected(null); }}
            disabled={selected === null}
            style={btn("white", COLORS.muted)}
            title="Использовать AVG по всем строкам"
          >
            ✕ Сбросить (AVG)
          </button>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={onClose} style={btn("white", COLORS.muted)}>Отмена</button>
            <button onClick={save} disabled={saving} style={btn(COLORS.primary, "white")}>
              {saving ? "…" : "✓ Сохранить и пересчитать"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function WorkPlanFerSearchModal({
  card,
  projectId,
  batchId,
  onClose,
  onSelect,
}: {
  card: WorkPlanCard;
  projectId: string;
  batchId: string;
  onClose: () => void;
  onSelect: (result: FerSearchResult | null) => Promise<void>;
}) {
  const [q, setQ] = useState(card.source_label ?? card.nw_label);
  const [results, setResults] = useState<FerSearchResult[]>([]);
  const [ferScopes, setFerScopes] = useState<Array<{ key: string; label: string; collectionId?: number; sectionId?: number }>>([]);
  const [allFerScopes, setAllFerScopes] = useState<Array<{ key: string; label: string; collectionId?: number; sectionId?: number }>>([]);
  const [scopeSource, setScopeSource] = useState<"nw" | "wt">("nw");
  const [scopeMode, setScopeMode] = useState<"mapped" | "all">("mapped");
  const [scopeLoading, setScopeLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    setScopeLoading(true);
    setError(null);
    Promise.all([nwApi.item(card.nw_item_code), wpApi.ferScopes(projectId, batchId)])
      .then(([item, projectFer]) => {
        if (cancelled) return;
        const mappings = item.fer_mappings.length > 0 ? item.fer_mappings : item.work_type_fer_mappings ?? [];
        setScopeSource(item.fer_mappings.length > 0 ? "nw" : "wt");
        const seen = new Set<string>();
        const scopes: Array<{ key: string; label: string; collectionId?: number; sectionId?: number }> = [];
        for (const mapping of mappings) {
          const collectionId = mapping.collection_id ?? undefined;
          const sectionId = mapping.section_id ?? undefined;
          if (!collectionId && !sectionId) continue;
          const key = sectionId ? `s:${sectionId}` : `c:${collectionId}`;
          if (seen.has(key)) continue;
          seen.add(key);
          scopes.push({
            key,
            collectionId,
            sectionId,
            label: `${String(mapping.fer_collection_num).padStart(2, "0")}-${String(mapping.fer_section_num).padStart(2, "0")}`,
          });
        }
        setFerScopes(scopes);
        setAllFerScopes(
          projectFer.scopes.map((scope) => ({
            key: `s:${scope.section_id}`,
            sectionId: scope.section_id,
            collectionId: scope.collection_id,
            label: `Сб. ${scope.collection_num} · ${scope.section_title}`,
          })),
        );
      })
      .catch((e: any) => {
        if (cancelled) return;
        setFerScopes([]);
        setAllFerScopes([]);
        setError(e.message ?? "Не удалось загрузить область поиска ФЕР");
      })
      .finally(() => {
        if (!cancelled) setScopeLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [batchId, card.nw_item_code, projectId]);

  useEffect(() => {
    const query = q.trim();
    const activeScopes = scopeMode === "all" ? allFerScopes : ferScopes;
    if (query.length < 2) {
      setResults([]);
      return;
    }
    if (scopeLoading) return;
    if (activeScopes.length === 0) {
      setResults([]);
      return;
    }
    if (debounce.current) clearTimeout(debounce.current);
    let cancelled = false;
    debounce.current = setTimeout(async () => {
      setSearching(true);
      setError(null);
      try {
        const scopedResults = await Promise.all(
          activeScopes.map((scope) =>
            ferApi
              .search(query, 50, scope.sectionId ? { sectionId: scope.sectionId } : { collectionId: scope.collectionId })
              .catch(() => []),
          ),
        );
        if (cancelled) return;
        const byTableId = new Map<number, FerSearchResult>();
        for (const result of scopedResults.flat()) {
          if (!byTableId.has(result.table_id)) {
            byTableId.set(result.table_id, result);
          }
        }
        setResults(Array.from(byTableId.values()).slice(0, 50));
      } catch (e: any) {
        if (cancelled) return;
        setResults([]);
        setError(e.message ?? "Не удалось выполнить поиск ФЕР");
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, 300);
    return () => {
      cancelled = true;
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [allFerScopes, ferScopes, q, scopeLoading, scopeMode]);

  useEffect(() => {
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [onClose]);

  async function pick(result: FerSearchResult | null) {
    if (result?.effective_ignored) return;
    setSaving(true);
    setError(null);
    try {
      await onSelect(result);
    } catch (e: any) {
      setError(e.message ?? "Не удалось назначить ФЕР");
    } finally {
      setSaving(false);
    }
  }

  const activeScopeCount = scopeMode === "all" ? allFerScopes.length : ferScopes.length;

  return (
    <div
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "#0f172a80",
        zIndex: 120,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
      }}
    >
      <div
        style={{
          width: 900,
          maxWidth: "96vw",
          maxHeight: "86vh",
          background: "white",
          borderRadius: 8,
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 24px 64px rgba(0,0,0,.28)",
          overflow: "hidden",
        }}
      >
        <div style={{ padding: "14px 18px", borderBottom: `1px solid ${COLORS.border}`, display: "flex", gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4, color: COLORS.text }}>
              Ручное назначение ФЕР
            </div>
            <div style={{ fontSize: 12, color: COLORS.muted, lineHeight: 1.4 }}>
              {card.source_label ?? card.nw_label}
            </div>
            {card.fer_table_id && (
              <div style={{ marginTop: 4, fontSize: 11, color: COLORS.primary }}>
                Сейчас: {formatFerChipLabel(card)}
              </div>
            )}
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: COLORS.muted, fontSize: 20, lineHeight: 1 }}>
            ×
          </button>
        </div>

        <div style={{ padding: "12px 18px", borderBottom: `1px solid ${COLORS.border}` }}>
          <input
            autoFocus
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Поиск только по ФЕР, привязанным к этому NW..."
            style={{ ...inputStyle, boxSizing: "border-box", width: "100%" }}
          />
          <div style={{ marginTop: 8, fontSize: 11, color: COLORS.muted, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            {scopeLoading ? (
              <span>Загружаю привязки NW к ФЕР...</span>
            ) : allFerScopes.length > 0 || ferScopes.length > 0 ? (
              <>
                <span>Область поиска:</span>
                {allFerScopes.length > 0 && (
                  <Chip
                    label="Все"
                    color={scopeMode === "all" ? "white" : COLORS.primary}
                    bg={scopeMode === "all" ? COLORS.primary : COLORS.primaryBg}
                    onClick={() => setScopeMode("all")}
                    title="Искать по всем ФЕР, доступным для типа загруженной сметы"
                  />
                )}
                {ferScopes.map((scope) => (
                  <Chip
                    key={scope.key}
                    label={scope.label}
                    color={scopeMode === "mapped" ? "white" : COLORS.primary}
                    bg={scopeMode === "mapped" ? COLORS.primary : COLORS.primaryBg}
                    onClick={() => setScopeMode("mapped")}
                    title={`Искать по ФЕР ${scopeSource === "wt" ? "родительского WT" : "этого NW"}`}
                  />
                ))}
                {ferScopes.length === 0 && <span>Для NW/WT нет узких меток, доступен режим «Все».</span>}
              </>
            ) : (
              <span style={{ color: COLORS.warn }}>У этого NW и родительского WT нет привязанных разделов ФЕР.</span>
            )}
          </div>
          {error && <div style={{ marginTop: 8, fontSize: 12, color: COLORS.err }}>{error}</div>}
        </div>

        <div style={{ flex: 1, overflow: "auto" }}>
          {(scopeLoading || searching) && <div style={{ padding: 24, textAlign: "center", color: COLORS.muted, fontSize: 13 }}>{scopeLoading ? "Загружаю область поиска..." : "Поиск..."}</div>}
          {!scopeLoading && !searching && activeScopeCount === 0 && (
            <div style={{ padding: 24, textAlign: "center", color: COLORS.muted, fontSize: 13 }}>Нет привязанных ФЕР для ручного назначения.</div>
          )}
          {!scopeLoading && !searching && activeScopeCount > 0 && q.trim().length >= 2 && results.length === 0 && (
            <div style={{ padding: 24, textAlign: "center", color: COLORS.muted, fontSize: 13 }}>
              Ничего не найдено {scopeMode === "all" ? "в доступных ФЕР для типа сметы" : "в привязанных разделах ФЕР"}
            </div>
          )}
          {!scopeLoading && !searching && activeScopeCount > 0 && q.trim().length < 2 && (
            <div style={{ padding: 24, textAlign: "center", color: COLORS.muted, fontSize: 13 }}>Введите минимум 2 символа</div>
          )}

          {!scopeLoading && !searching && results.length > 0 && (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead style={{ position: "sticky", top: 0, background: COLORS.bg, zIndex: 1 }}>
                <tr style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                  <th style={manualFerThStyle}>Код</th>
                  <th style={manualFerThStyle}>Иерархия</th>
                  <th style={manualFerThStyle}>Таблица</th>
                  <th style={manualFerThStyle}>Работа</th>
                  <th style={{ ...manualFerThStyle, textAlign: "right" }}>Строк</th>
                </tr>
              </thead>
              <tbody>
                {results.map((result) => {
                  const disabled = saving || result.effective_ignored;
                  const selected = result.table_id === card.fer_table_id;
                  return (
                    <tr
                      key={result.table_id}
                      onClick={() => !disabled && pick(result)}
                      style={{
                        borderBottom: `1px solid ${COLORS.border}`,
                        cursor: disabled ? "default" : "pointer",
                        opacity: result.effective_ignored ? 0.5 : 1,
                        background: selected ? COLORS.primaryBg : result.effective_ignored ? "#f8fafc" : "white",
                      }}
                      onMouseEnter={(event) => {
                        if (!disabled && !selected) event.currentTarget.style.background = COLORS.bg;
                      }}
                      onMouseLeave={(event) => {
                        event.currentTarget.style.background = selected ? COLORS.primaryBg : result.effective_ignored ? "#f8fafc" : "white";
                      }}
                    >
                      <td style={{ ...manualFerTdStyle, fontFamily: "var(--mono, monospace)", whiteSpace: "nowrap", color: COLORS.primary, fontWeight: 700 }}>
                        {formatFerSearchCode(result)}
                      </td>
                      <td style={{ ...manualFerTdStyle, color: COLORS.muted, minWidth: 170 }}>
                        {formatFerBreadcrumb(result)}
                      </td>
                      <td style={{ ...manualFerTdStyle, minWidth: 260 }}>
                        <div style={{ fontWeight: 600, color: COLORS.text, lineHeight: 1.35 }}>{result.table_title}</div>
                        {result.effective_ignored && <div style={{ marginTop: 4, color: COLORS.warn, fontSize: 11 }}>Игнорируется и недоступна для назначения</div>}
                      </td>
                      <td style={{ ...manualFerTdStyle, color: COLORS.muted, minWidth: 220, lineHeight: 1.35 }}>
                        {result.common_work_name ?? "—"}
                      </td>
                      <td style={{ ...manualFerTdStyle, textAlign: "right", fontFamily: "var(--mono, monospace)" }}>
                        {result.row_count}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {card.fer_table_id && (
          <div style={{ padding: "10px 18px", borderTop: `1px solid ${COLORS.border}`, background: "#fef9f9" }}>
            <button
              onClick={() => !saving && pick(null)}
              disabled={saving}
              style={{ ...btn("white", COLORS.err), borderColor: "#ef444440", cursor: saving ? "wait" : "pointer" }}
            >
              Сбросить назначение ФЕР
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

const manualFerThStyle: React.CSSProperties = {
  padding: "8px 10px",
  textAlign: "left",
  color: COLORS.muted,
  fontWeight: 700,
  fontSize: 11,
};

const manualFerTdStyle: React.CSSProperties = {
  padding: "9px 10px",
  verticalAlign: "top",
};

function WorkPlanDetailPanel({
  projectId,
  batchId,
  card,
  onClose,
  onPickRow,
  onReplaceFer,
}: {
  projectId: string;
  batchId: string;
  card: WorkPlanCard;
  onClose: () => void;
  onPickRow: () => void;
  onReplaceFer: (card: WorkPlanCard) => void;
}) {
  const [detail, setDetail] = useState<WorkPlanCardDetail | null>(null);
  const [ferRows, setFerRows] = useState<FerRowOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    Promise.all([
      wpApi.detail(projectId, batchId, card.id),
      card.fer_table_id ? wpApi.ferRows(projectId, batchId, card.id).catch(() => ({ items: [], total: 0 })) : Promise.resolve({ items: [], total: 0 }),
    ])
      .then(([d, rows]) => {
        if (!alive) return;
        setDetail(d);
        setFerRows(rows.items);
      })
      .catch((e) => {
        if (alive) setError(e.message ?? String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, [projectId, batchId, card.id, card.fer_table_id]);

  const c = detail?.card ?? card;
  const estimateRows = detail?.estimate_rows ?? [];
  const selectedFerRow = ferRows.find((r) => r.id === c.fer_row_id);
  const candidates = c.fer_candidates ?? [];
  const stCol = STATUS_COLOR[c.status];

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "#0f172a40",
        zIndex: 110,
        display: "flex",
        justifyContent: "flex-end",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 620,
          maxWidth: "94vw",
          background: "white",
          padding: 24,
          overflow: "auto",
          boxShadow: "-4px 0 24px #0001",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 12 }}>
          <div>
            <code style={{ fontSize: 12, color: COLORS.muted }}>{c.nw_item_code}</code>
            <h2 style={{ margin: "4px 0 4px 0", fontSize: 18, fontWeight: 700, color: COLORS.text }}>
              {c.nw_label}
            </h2>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <Chip label={c.work_type_name} color={COLORS.primary} bg={COLORS.primaryBg} />
              <Chip label={STATUS_LABEL[c.status]} color={stCol.fg} bg={stCol.bg} />
              {c.quantity != null && <Chip label={`${formatNumber(c.quantity)} ${c.unit ?? "ед."}`} />}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", color: COLORS.muted, fontSize: 22, alignSelf: "flex-start" }}
          >
            ×
          </button>
        </div>

        {loading && <div style={{ padding: 16, color: COLORS.muted, fontSize: 13 }}>Загрузка деталей…</div>}
        {error && <div style={{ padding: 12, background: COLORS.errBg, color: COLORS.err, borderRadius: 6, fontSize: 12 }}>{error}</div>}

        {c.notes && (
          <div style={{ padding: 12, background: COLORS.bg, borderLeft: `3px solid ${COLORS.borderHard}`, fontSize: 12, color: COLORS.text, marginBottom: 16, borderRadius: 4, whiteSpace: "pre-wrap" }}>
            {c.notes}
          </div>
        )}

        <h3 style={detailTitleStyle}>Строки сметы ({estimateRows.length})</h3>
        {estimateRows.length === 0 ? (
          <EmptyDetailText>К этой карточке не привязаны строки сметы.</EmptyDetailText>
        ) : (
          <EstimateRowsTable rows={estimateRows} />
        )}

        <h3 style={detailTitleStyle}>Подобранный ФЕР</h3>
        {!c.fer_table_id ? (
          <EmptyDetailText>ФЕР для этой карточки пока не подобран.</EmptyDetailText>
        ) : (
          <div style={{ border: `1px solid ${COLORS.border}`, borderRadius: 6, padding: 12, fontSize: 12, marginBottom: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 6 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                <strong style={{ color: COLORS.text }}>ФЕР {formatFerCode(c)}</strong>
                <button
                  type="button"
                  onClick={() => onReplaceFer(c)}
                  style={{
                    background: "none",
                    border: "none",
                    padding: 0,
                    color: COLORS.primary,
                    cursor: "pointer",
                    fontSize: 12,
                    fontWeight: 600,
                  }}
                >
                  Заменить
                </button>
              </div>
              <Chip
                label={c.fer_match_score != null ? `${(Number(c.fer_match_score) * 100).toFixed(0)}%` : "без оценки"}
                color={COLORS.primary}
                bg={COLORS.primaryBg}
              />
            </div>
            <div style={{ color: COLORS.text, lineHeight: 1.35 }}>{c.fer_table_title ?? "Название таблицы не найдено"}</div>
            <div style={{ marginTop: 6, color: COLORS.muted }}>
              Источник: {c.fer_match_source ?? "—"}
            </div>

            <div style={{ marginTop: 12, paddingTop: 10, borderTop: `1px dashed ${COLORS.border}` }}>
              <div style={{ fontSize: 11, color: COLORS.muted, fontWeight: 700, marginBottom: 4 }}>
                Строка расценки
              </div>
              {selectedFerRow || c.fer_row_id ? (
                <div style={{ lineHeight: 1.35 }}>
                  <code style={{ fontSize: 11, color: COLORS.muted, marginRight: 4 }}>
                    {formatFerRowPosition(selectedFerRow?.position)}
                  </code>
                  {selectedFerRow?.clarification ?? c.fer_row_clarification ?? "Описание строки не найдено"}
                  <div style={{ color: COLORS.muted, marginTop: 4 }}>
                    Чел.час: {formatMaybeNumber(selectedFerRow?.h_hour ?? c.fer_row_h_hour)} · Маш.час: {formatMaybeNumber(selectedFerRow?.m_hour ?? c.fer_row_m_hour)}
                  </div>
                </div>
              ) : (
                <div style={{ color: COLORS.muted }}>Конкретная строка ФЕР не выбрана, длительность считается по среднему значению таблицы.</div>
              )}
              <button onClick={onPickRow} style={{ ...btn("white", COLORS.primary), marginTop: 10 }}>
                📋 Выбрать строку ФЕР
              </button>
            </div>
          </div>
        )}

        {candidates.length > 0 && (
          <>
            <h3 style={detailTitleStyle}>Кандидаты ФЕР ({candidates.length})</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {candidates.map((cand) => (
                <div key={cand.id} style={{ border: `1px solid ${COLORS.border}`, borderRadius: 6, padding: 10, fontSize: 12 }}>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4, flexWrap: "wrap" }}>
                    <code style={{ fontSize: 11, color: COLORS.muted }}>#{cand.id}</code>
                    {cand.coll_num != null && <Chip label={`Сб. ${cand.coll_num}`} />}
                    <Chip label={cand.mapping_type} color={cand.is_primary ? COLORS.primary : COLORS.muted} bg={cand.is_primary ? COLORS.primaryBg : COLORS.bg} />
                    <Chip label={cand.confidence} color={COLORS.ok} bg={COLORS.okBg} />
                  </div>
                  <div style={{ color: COLORS.text, lineHeight: 1.35 }}>{cand.title}</div>
                  {cand.section_title && <div style={{ color: COLORS.muted, marginTop: 3 }}>{cand.section_title}</div>}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function EstimateRowsTable({ rows }: { rows: WorkPlanEstimateRow[] }) {
  return (
    <div style={{ overflow: "auto", border: `1px solid ${COLORS.border}`, borderRadius: 6, marginBottom: 16 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead style={{ background: COLORS.bg }}>
          <tr style={{ borderBottom: `1px solid ${COLORS.border}` }}>
            <th style={detailThStyle}>№</th>
            <th style={detailThStyle}>Раздел</th>
            <th style={detailThStyle}>Работа</th>
            <th style={{ ...detailThStyle, textAlign: "right" }}>Объём</th>
            <th style={detailThStyle}>Ед.</th>
            <th style={{ ...detailThStyle, textAlign: "right" }}>Сумма</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} style={{ borderBottom: `1px solid ${COLORS.border}` }}>
              <td style={detailTdStyle}>{r.row_order ?? "—"}</td>
              <td style={{ ...detailTdStyle, color: COLORS.muted }}>{r.section ?? "—"}</td>
              <td style={{ ...detailTdStyle, minWidth: 220, lineHeight: 1.35 }}>{r.work_name}</td>
              <td style={{ ...detailTdStyle, textAlign: "right", fontFamily: "var(--mono, monospace)" }}>{formatMaybeNumber(r.quantity)}</td>
              <td style={{ ...detailTdStyle, color: COLORS.muted }}>{r.unit ?? "—"}</td>
              <td style={{ ...detailTdStyle, textAlign: "right", fontFamily: "var(--mono, monospace)" }}>{formatMoney(r.total_price)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EmptyDetailText({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 12, color: COLORS.muted, padding: 12, background: COLORS.bg, borderRadius: 4, marginBottom: 16 }}>
      {children}
    </div>
  );
}

const detailTitleStyle: React.CSSProperties = {
  margin: "18px 0 8px 0",
  fontSize: 14,
  fontWeight: 700,
  color: COLORS.text,
};

const detailThStyle: React.CSSProperties = {
  padding: "7px 8px",
  textAlign: "left",
  fontWeight: 700,
  color: COLORS.muted,
  fontSize: 11,
};

const detailTdStyle: React.CSSProperties = {
  padding: "7px 8px",
  verticalAlign: "top",
};

function formatNumber(value: number | string) {
  return Number(value).toLocaleString("ru");
}

function formatMaybeNumber(value: number | string | null | undefined) {
  return value == null ? "—" : formatNumber(value);
}

function formatMoney(value: number | string | null | undefined) {
  return value == null ? "—" : `${Number(value).toLocaleString("ru")} ₽`;
}

function formatFerCode(card: Pick<WorkPlanCard, "fer_table_code" | "fer_table_id">) {
  return card.fer_table_code ?? `#${card.fer_table_id ?? "—"}`;
}

function formatFerChipLabel(card: Pick<WorkPlanCard, "fer_table_code" | "fer_table_id" | "fer_match_score">) {
  const code = formatFerCode(card);
  return card.fer_match_score ? `${code} (${(Number(card.fer_match_score) * 100).toFixed(0)}%)` : code;
}

function formatFerSearchCode(result: FerSearchResult) {
  const source = `${result.table_title} ${result.table_url}`;
  const match = source.match(/(\d{2}-\d{2}-\d{3})/);
  return match?.[1] ?? `#${result.table_id}`;
}

function formatFerBreadcrumb(result: FerSearchResult) {
  return [`Сб. ${result.collection.num}`, result.section?.title, result.subsection?.title].filter(Boolean).join(" › ");
}

function BuildGanttDialog({
  onClose, onBuild,
}: {
  onClose: () => void;
  onBuild: (startDate: string, replace: boolean) => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [startDate, setStartDate] = useState(today);
  const [replace, setReplace] = useState(true);

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "#0f172a40", zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: "white", padding: 24, borderRadius: 8, width: 380 }}>
        <h3 style={{ margin: "0 0 12px 0", fontSize: 16 }}>Построить ГПР из плана</h3>
        <p style={{ fontSize: 12, color: COLORS.muted, marginBottom: 12 }}>
          Карточки группируются по виду работ × этапу → одна задача ГПР на группу. Зависимости устанавливаются автоматически по порядку этапов.
        </p>
        <Field label="Дата начала">
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} style={inputStyle} />
        </Field>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, marginTop: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
          Удалить существующие задачи ГПР этой сметы
        </label>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
          <button onClick={onClose} style={btn("white", COLORS.muted)}>Отмена</button>
          <button onClick={() => onBuild(startDate, replace)} style={btn("#16a34a", "white")}>📊 Построить</button>
        </div>
      </div>
    </div>
  );
}

function btn(bg: string, fg: string): React.CSSProperties {
  return {
    padding: "8px 14px",
    fontSize: 13,
    background: bg,
    color: fg,
    border: bg === "white" ? `1px solid ${COLORS.borderHard}` : "none",
    borderRadius: 6,
    cursor: "pointer",
    fontWeight: 600,
  };
}

const planThStyle: React.CSSProperties = {
  padding: "9px 12px",
  fontSize: 10,
  color: "#94a3b8",
  textTransform: "uppercase",
  letterSpacing: ".06em",
  fontFamily: "var(--mono)",
  fontWeight: 400,
  borderRight: "1px solid #334155",
  whiteSpace: "nowrap",
};

const planTdStyle: React.CSSProperties = {
  padding: "8px 12px",
  borderBottom: `1px solid ${COLORS.border}`,
  verticalAlign: "top",
};

function formatFerRowPosition(position?: number | null) {
  return position != null ? `с${position}` : "с—";
}

function FerRowPositionBadge({
  projectId,
  batchId,
  card,
  onClick,
}: {
  projectId: string;
  batchId: string;
  card: WorkPlanCard;
  onClick?: () => void;
}) {
  const [position, setPosition] = useState<number | null>(null);

  useEffect(() => {
    if (!card.fer_row_id) {
      setPosition(null);
      return;
    }
    let cancelled = false;
    wpApi
      .ferRows(projectId, batchId, card.id)
      .then((response) => {
        if (!cancelled) {
          setPosition(response.items.find((row) => row.id === card.fer_row_id)?.position ?? null);
        }
      })
      .catch(() => {
        if (!cancelled) setPosition(null);
      });
    return () => {
      cancelled = true;
    };
  }, [batchId, card.fer_row_id, card.id, projectId]);

  return (
    <span
      onClick={(event) => {
        if (!onClick) return;
        event.stopPropagation();
        onClick();
      }}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      title={onClick ? "Сменить строку ФЕР" : undefined}
      style={{
        fontSize: 10,
        color: onClick ? "#7c3aed" : COLORS.muted,
        fontFamily: "var(--mono, monospace)",
        cursor: onClick ? "pointer" : "default",
        textDecoration: onClick ? "underline" : "none",
        textUnderlineOffset: 2,
      }}
    >
      {formatFerRowPosition(position)}
    </span>
  );
}

function PlanTableRow({
  projectId,
  batchId,
  card,
  children,
  index,
  depth = 0,
  isEditing = false,
  onEdit,
  onClose,
  onPatch,
  onConfirm,
  onRemove,
  onMatchFer,
  isMatchingFer = false,
  onManualFer,
  onPickRow,
  onOpenDetails,
  dicts,
}: {
  projectId: string;
  batchId: string;
  card: WorkPlanCard;
  children: WorkPlanCard[];
  index: number;
  depth?: number;
  isEditing?: boolean;
  onEdit?: () => void;
  onClose?: () => void;
  onPatch?: (p: WorkPlanCardPatch) => void;
  onConfirm?: () => void;
  onRemove?: () => void;
  onMatchFer?: () => void;
  isMatchingFer?: boolean;
  onManualFer?: () => void;
  onPickRow?: () => void;
  onOpenDetails?: () => void;
  dicts: { otMap: Record<string, string>; btMap: Record<string, string>; lsMap: Record<string, string>; stMap: Record<string, string> };
}) {
  const stCol = STATUS_COLOR[card.status];
  const quantity = card.quantity != null ? Number(card.quantity) : null;
  const hoursPerUnit = card.human_hours_per_unit != null ? Number(card.human_hours_per_unit) : null;
  const totalHours = quantity != null && hoursPerUnit != null ? quantity * hoursPerUnit : null;
  const rowBg = card.status === "removed" ? COLORS.bg : index % 2 ? "#f8fafc" : "white";
  const firstCellStyle = {
    ...planTdStyle,
    borderLeft: `${depth ? 2 : 3}px solid ${depth ? COLORS.borderHard : stCol.fg}`,
    paddingLeft: 12 + depth * 20,
  };

  return (
    <>
      <tr style={{ background: rowBg, opacity: card.status === "removed" ? 0.55 : 1 }}>
        <td style={firstCellStyle}>
          <div style={{ minWidth: 360 }}>
            {card.source_label ? (
              <>
                <div style={{ fontSize: 13, fontWeight: 600, color: COLORS.text, lineHeight: 1.35 }}>
                  {depth > 0 && <span style={{ color: COLORS.muted, marginRight: 6 }}>↳</span>}
                  {card.source_label}
                </div>
                {card.source_section && (
                  <div style={{ marginTop: 3, fontSize: 11, color: COLORS.muted }}>
                    {card.source_section}
                  </div>
                )}
              </>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                {depth > 0 && <span style={{ color: COLORS.muted }}>↳</span>}
                <code style={{ fontSize: 11, color: COLORS.muted }}>{card.nw_item_code}</code>
                <strong style={{ fontSize: 13, color: COLORS.text }}>{card.nw_label}</strong>
              </div>
            )}
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 6 }}>
              {card.object_type_code && <Chip label={dicts.otMap[card.object_type_code] ?? card.object_type_code} title="Тип объекта" />}
              {card.building_technology_code && <Chip label={dicts.btMap[card.building_technology_code] ?? card.building_technology_code} title="Технология" />}
              {card.location_scope_code && <Chip label={dicts.lsMap[card.location_scope_code] ?? card.location_scope_code} title="Зона" />}
              {card.stage_code && <Chip label={dicts.stMap[card.stage_code] ?? card.stage_code} title="Этап" />}
            </div>
          </div>
        </td>
        <td style={{ ...planTdStyle, textAlign: "right", color: COLORS.muted }}>{card.unit ?? "—"}</td>
        <td style={{ ...planTdStyle, textAlign: "right", fontFamily: "var(--mono, monospace)" }}>
          {quantity != null ? quantity.toLocaleString("ru") : <span style={{ color: COLORS.warn }}>—</span>}
        </td>
        <td style={planTdStyle}>
          <Chip
            label={STATUS_LABEL[card.status]}
            color={stCol.fg}
            bg={stCol.bg}
            onClick={onOpenDetails ? (e) => { e.stopPropagation(); onOpenDetails(); } : undefined}
            title="Показать детали карточки"
          />
        </td>
        <td style={planTdStyle}>
          {card.fer_table_id ? (
            <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap", minWidth: 72 }}>
              <button
                type="button"
                onClick={onOpenDetails}
                title={card.fer_table_title ? `${card.fer_table_title}\nИсточник: ${card.fer_match_source ?? "—"}` : `Источник: ${card.fer_match_source ?? "—"}`}
                style={{
                  border: `1px solid ${COLORS.primary}35`,
                  background: COLORS.primaryBg,
                  color: COLORS.primary,
                  borderRadius: 4,
                  padding: "3px 7px",
                  fontFamily: "var(--mono, monospace)",
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: onOpenDetails ? "pointer" : "default",
                }}
              >
                {formatFerCode(card)}
              </button>
              {onPickRow && card.status !== "removed" && !card.fer_row_id && (
                <button
                  type="button"
                  onClick={onPickRow}
                  style={smallBtn(card.fer_row_id ? "#7c3aed" : COLORS.muted)}
                  title={card.fer_row_clarification ? `Уточнение: ${card.fer_row_clarification}` : "Выбрать уточнение строки ФЕР"}
                >
                  📋
                </button>
              )}
              {card.fer_row_id && (
                <FerRowPositionBadge
                  projectId={projectId}
                  batchId={batchId}
                  card={card}
                  onClick={card.status !== "removed" ? onPickRow : undefined}
                />
              )}
            </div>
          ) : card.status !== "removed" && (onManualFer || onMatchFer) ? (
            <div style={{ display: "flex", alignItems: "center", gap: 4, minWidth: 72 }}>
              {onManualFer && (
                <button type="button" onClick={onManualFer} style={smallBtn(COLORS.primary)} title="Назначить ФЕР вручную">
                  ＋ ФЕР
                </button>
              )}
              {onMatchFer && (
                <button
                  type="button"
                  onClick={onMatchFer}
                  disabled={isMatchingFer}
                  style={smallBtn(COLORS.primary, isMatchingFer)}
                  title={isMatchingFer ? "Подбирается ФЕР" : "Подобрать ФЕР векторным поиском"}
                >
                  {isMatchingFer ? <Spinner /> : "🤖"}
                </button>
              )}
            </div>
          ) : (
            <span style={{ color: COLORS.muted }}>—</span>
          )}
        </td>
        <td style={{ ...planTdStyle, textAlign: "right", fontFamily: "var(--mono, monospace)" }}>
          {totalHours != null ? (
            <div>
              <div style={{ fontWeight: 700, color: COLORS.text }}>{formatMaybeNumber(totalHours)} чел-ч</div>
              <div style={{ marginTop: 2, fontSize: 10, color: COLORS.muted }}>
                {formatMaybeNumber(hoursPerUnit)} ч/{card.unit ?? "ед"}
                {card.duration_days ? ` · ${card.duration_days} дн` : ""}
              </div>
            </div>
          ) : card.duration_days ? (
            <span>{card.duration_days} дн</span>
          ) : (
            <span style={{ color: COLORS.muted }}>—</span>
          )}
        </td>
        <td style={planTdStyle}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 4 }}>
            {onOpenDetails && <button onClick={onOpenDetails} style={smallBtn(COLORS.primary)} title="Детали">i</button>}
            {onConfirm && card.status !== "confirmed" && card.status !== "removed" && (
              <button onClick={onConfirm} style={smallBtn(COLORS.ok)} title="Подтвердить">✓</button>
            )}
            {onEdit && <button onClick={onEdit} style={smallBtn(COLORS.muted)} title="Редактировать">✎</button>}
            {onRemove && card.status !== "removed" && (
              <button onClick={onRemove} style={smallBtn(COLORS.err)} title="Удалить">✕</button>
            )}
          </div>
        </td>
      </tr>
      {isEditing && onPatch && onClose && (
        <tr>
          <td colSpan={7} style={{ padding: 12, background: "#f8fafc", borderBottom: `1px solid ${COLORS.border}` }}>
            <CardEditor card={card} onPatch={(p) => { onPatch(p); onClose(); }} onCancel={onClose} />
          </td>
        </tr>
      )}
      {children.map((child, childIndex) => (
        <PlanTableRow
          key={child.id}
          projectId={projectId}
          batchId={batchId}
          card={child}
          children={[]}
          index={childIndex}
          depth={depth + 1}
          dicts={dicts}
        />
      ))}
    </>
  );
}

function CardItem({
  projectId,
  batchId,
  card,
  children,
  isEditing,
  onEdit,
  onClose,
  onPatch,
  onConfirm,
  onRemove,
  onMatchFer,
  isMatchingFer = false,
  onManualFer,
  onPickRow,
  onOpenDetails,
  dicts,
}: {
  projectId?: string;
  batchId?: string;
  card: WorkPlanCard;
  children: WorkPlanCard[];
  isEditing: boolean;
  onEdit: () => void;
  onClose: () => void;
  onPatch: (p: WorkPlanCardPatch) => void;
  onConfirm: () => void;
  onRemove: () => void;
  onMatchFer?: () => void;
  isMatchingFer?: boolean;
  onManualFer?: () => void;
  onPickRow?: () => void;
  onOpenDetails?: () => void;
  dicts: { otMap: Record<string, string>; btMap: Record<string, string>; lsMap: Record<string, string>; stMap: Record<string, string> };
}) {
  const stCol = STATUS_COLOR[card.status];
  const isSub = card.parent_id !== null;
  const hasChildren = children.length > 0;

  return (
    <div
      style={{
        background: card.status === "removed" ? COLORS.bg : COLORS.cardBg,
        border: `1px solid ${COLORS.border}`,
        borderLeft: `3px solid ${stCol.fg}`,
        borderRadius: 6,
        padding: 12,
        opacity: card.status === "removed" ? 0.5 : 1,
        marginLeft: isSub ? 24 : 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 300px", minWidth: 250 }}>
          {card.source_label ? (
            <>
              {/* Сверху: исходное название из сметы */}
              <div style={{ fontSize: 14, fontWeight: 600, color: COLORS.text, marginBottom: 2, lineHeight: 1.3 }}>
                {card.source_label}
              </div>
              {/* Снизу мельче: тип работ NW */}
              <div style={{ fontSize: 11, color: COLORS.muted, marginBottom: 4, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                {card.source_section && (
                  <span style={{ background: COLORS.bg, padding: "1px 6px", borderRadius: 3 }}>
                    {card.source_section}
                  </span>
                )}
                <code style={{ fontSize: 10 }}>{card.nw_item_code}</code>
                <span>· {card.nw_label}</span>
              </div>
            </>
          ) : (
            <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4, flexWrap: "wrap" }}>
              <code style={{ fontSize: 11, color: COLORS.muted }}>{card.nw_item_code}</code>
              <strong style={{ fontSize: 13, color: COLORS.text }}>{card.nw_label}</strong>
            </div>
          )}
          {card.notes && (
            <div style={{ fontSize: 11, color: COLORS.muted, marginBottom: 4, fontStyle: "italic" }}>
              {card.notes}
            </div>
          )}
          {/* Attribute chips */}
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {card.object_type_code && (
              <Chip label={`👤 ${dicts.otMap[card.object_type_code] ?? card.object_type_code}`} title="Тип объекта" />
            )}
            {card.building_technology_code && (
              <Chip label={`🏗 ${dicts.btMap[card.building_technology_code] ?? card.building_technology_code}`} title="Технология" />
            )}
            {card.location_scope_code && (
              <Chip label={`📍 ${dicts.lsMap[card.location_scope_code] ?? card.location_scope_code}`} title="Зона" />
            )}
            {card.stage_code && (
              <Chip label={`⏳ ${dicts.stMap[card.stage_code] ?? card.stage_code}`} title="Этап" />
            )}
            {card.is_capital_repair === true && (
              <Chip label="кап.ремонт" color={COLORS.primary} bg={COLORS.primaryBg} />
            )}
            {card.is_capital_repair === false && (
              <Chip label="не ремонт" color={COLORS.muted} bg={COLORS.bg} />
            )}
          </div>
        </div>

        {/* Volume + unit */}
        <div style={{ flex: "0 0 140px", textAlign: "right", fontSize: 13 }}>
          {card.quantity != null ? (
            <>
              <div style={{ fontSize: 16, fontWeight: 700, color: COLORS.text }}>
                {Number(card.quantity).toLocaleString("ru")}
              </div>
              <div style={{ fontSize: 11, color: COLORS.muted }}>{card.unit ?? "—"}</div>
            </>
          ) : (
            <div style={{ fontSize: 11, color: COLORS.warn }}>объём не задан</div>
          )}
        </div>

        {/* Status + actions */}
        <div style={{ flex: "0 0 auto", display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
          <Chip
            label={STATUS_LABEL[card.status]}
            color={stCol.fg}
            bg={stCol.bg}
            onClick={onOpenDetails ? (e) => { e.stopPropagation(); onOpenDetails(); } : undefined}
            title="Показать детали карточки"
          />
          {card.fer_table_id && (
            <Chip
              label={formatFerChipLabel(card)}
              color={COLORS.primary}
              bg={COLORS.primaryBg}
              title={card.fer_table_title ? `${card.fer_table_title}\nИсточник: ${card.fer_match_source ?? "—"}` : `Источник: ${card.fer_match_source ?? "—"}`}
              onClick={onOpenDetails ? (e) => { e.stopPropagation(); onOpenDetails(); } : undefined}
            />
          )}
          {card.fer_row_id && card.fer_row_clarification && (
            <span
              title={`${card.fer_row_clarification}\n${card.fer_row_h_hour ?? card.fer_row_m_hour ?? "?"} ч`}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding: "2px 8px",
                borderRadius: 12,
                fontSize: 11,
                fontWeight: 600,
                color: "#7c3aed",
                background: "#7c3aed18",
                border: "1px solid #7c3aed30",
                whiteSpace: "nowrap",
              }}
            >
              {projectId && batchId ? (
                <FerRowPositionBadge
                  projectId={projectId}
                  batchId={batchId}
                  card={card}
                  onClick={card.status !== "removed" ? onPickRow : undefined}
                />
              ) : (
                <span style={{ fontSize: 10, fontFamily: "var(--mono, monospace)" }}>{formatFerRowPosition()}</span>
              )}
            </span>
          )}
          {card.duration_days && (
            <Chip
              label={`⏱ ${card.duration_days} дн × ${card.workers_count ?? "?"} раб`}
              color="#0891b2"
              bg="#0891b218"
              title={
                card.human_hours_per_unit
                  ? `${Number(card.human_hours_per_unit).toFixed(4)} ч/${card.unit ?? "ед"}` +
                    (card.fer_row_id
                      ? " (по выбранной строке)"
                      : " (AVG по всем строкам ФЕР)")
                  : ""
              }
            />
          )}
          <div style={{ display: "flex", gap: 4 }}>
            {!card.fer_table_id && onMatchFer && card.status !== "removed" && (
              <button
                onClick={onMatchFer}
                disabled={isMatchingFer}
                style={smallBtn(COLORS.primary, isMatchingFer)}
                title={isMatchingFer ? "Подбирается ФЕР" : "Подобрать ФЕР"}
              >
                {isMatchingFer ? <Spinner /> : "🔗"}
              </button>
            )}
            {onManualFer && card.status !== "removed" && (
              <button
                onClick={onManualFer}
                style={smallBtn(card.fer_table_id ? "#7c3aed" : COLORS.primary)}
                title={card.fer_table_id ? "Переназначить ФЕР вручную" : "Назначить ФЕР вручную"}
              >
                {card.fer_table_id ? "↻" : "＋"}
              </button>
            )}
            {card.fer_table_id && onPickRow && card.status !== "removed" && !card.fer_row_id && (
              <button onClick={onPickRow} style={smallBtn("#7c3aed")} title="Выбрать строку расценки">📋</button>
            )}
            {card.status !== "confirmed" && card.status !== "removed" && (
              <button onClick={onConfirm} style={smallBtn(COLORS.ok)}>✓</button>
            )}
            <button onClick={onEdit} style={smallBtn(COLORS.muted)}>✎</button>
            {card.status !== "removed" && (
              <button onClick={onRemove} style={smallBtn(COLORS.err)}>✕</button>
            )}
          </div>
        </div>
      </div>

      {/* Inline editor */}
      {isEditing && (
        <CardEditor card={card} onPatch={(p) => { onPatch(p); onClose(); }} onCancel={onClose} />
      )}

      {/* Sub-cards */}
      {hasChildren && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: `1px dashed ${COLORS.border}` }}>
          <div style={{ fontSize: 11, color: COLORS.muted, marginBottom: 6, fontWeight: 600 }}>
            ↳ Декомпозиция ({children.length} подкарточек):
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {children.map((ch) => (
              <CardItem
                key={ch.id}
                projectId={projectId}
                batchId={batchId}
                card={ch}
                children={[]}
                isEditing={false}
                onEdit={() => {}}
                onClose={() => {}}
                onPatch={() => {}}
                onConfirm={() => {}}
                onRemove={() => {}}
                dicts={dicts}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function smallBtn(color: string, disabled = false): React.CSSProperties {
  return {
    padding: "3px 7px",
    fontSize: 11,
    background: "transparent",
    color,
    border: `1px solid ${color}${disabled ? "25" : "50"}`,
    borderRadius: 4,
    cursor: disabled ? "wait" : "pointer",
    fontWeight: 700,
    minWidth: 24,
    minHeight: 24,
    opacity: disabled ? 0.75 : 1,
  };
}

function Spinner() {
  return (
    <span
      aria-label="Загрузка"
      style={{
        display: "inline-block",
        width: 12,
        height: 12,
        border: `2px solid ${COLORS.primary}40`,
        borderTopColor: COLORS.primary,
        borderRadius: "50%",
        animation: "work-plan-spin 0.75s linear infinite",
        verticalAlign: "middle",
      }}
    />
  );
}

function CardEditor({
  card,
  onPatch,
  onCancel,
}: {
  card: WorkPlanCard;
  onPatch: (p: WorkPlanCardPatch) => void;
  onCancel: () => void;
}) {
  const [unit, setUnit] = useState(card.unit ?? "");
  const [quantity, setQuantity] = useState(card.quantity?.toString() ?? "");
  const [workersCount, setWorkersCount] = useState(card.workers_count?.toString() ?? "");
  const [notes, setNotes] = useState(card.notes ?? "");
  const [isCapitalRepair, setIsCapitalRepair] = useState<string>(
    card.is_capital_repair === true ? "true" : card.is_capital_repair === false ? "false" : "",
  );

  function save() {
    const patch: WorkPlanCardPatch = {};
    if (unit !== (card.unit ?? "")) patch.unit = unit || null;
    if (quantity !== (card.quantity?.toString() ?? "")) patch.quantity = quantity ? Number(quantity) : null;
    if (workersCount !== (card.workers_count?.toString() ?? "")) patch.workers_count = workersCount ? Number(workersCount) : null;
    if (notes !== (card.notes ?? "")) patch.notes = notes || null;
    const newCap = isCapitalRepair === "true" ? true : isCapitalRepair === "false" ? false : null;
    if (newCap !== card.is_capital_repair) patch.is_capital_repair = newCap;
    if (Object.keys(patch).length === 0) {
      onCancel();
      return;
    }
    onPatch(patch);
  }

  return (
    <div style={{ marginTop: 12, padding: 12, background: COLORS.bg, borderRadius: 6 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 8 }}>
        <Field label="Единица">
          <input
            type="text"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            placeholder="м², м³, шт..."
            style={inputStyle}
          />
        </Field>
        <Field label="Объём">
          <input
            type="number"
            step="any"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            style={inputStyle}
          />
        </Field>
        <Field label="Рабочих">
          <input
            type="number"
            value={workersCount}
            onChange={(e) => setWorkersCount(e.target.value)}
            style={inputStyle}
          />
        </Field>
        <Field label="Класс ремонта">
          <select value={isCapitalRepair} onChange={(e) => setIsCapitalRepair(e.target.value)} style={inputStyle}>
            <option value="">не задан</option>
            <option value="true">капитальный</option>
            <option value="false">текущий</option>
          </select>
        </Field>
      </div>
      <Field label="Заметка">
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
        />
      </Field>
      <div style={{ display: "flex", gap: 8, marginTop: 8, justifyContent: "flex-end" }}>
        <button onClick={onCancel} style={btn("white", COLORS.muted)}>Отмена</button>
        <button onClick={save} style={btn(COLORS.primary, "white")}>Сохранить</button>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "6px 10px",
  fontSize: 13,
  border: `1px solid ${COLORS.borderHard}`,
  borderRadius: 4,
  background: "white",
  color: COLORS.text,
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "block", fontSize: 11, color: COLORS.muted, marginBottom: 4 }}>
      <div style={{ marginBottom: 2, fontWeight: 600 }}>{label}</div>
      {children}
    </label>
  );
}

function AddCardDialog({
  batchId,
  projectId,
  onClose,
  onAdded,
}: {
  batchId: string;
  projectId: string;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [items, setItems] = useState<NwItem[]>([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string>("");
  const [unit, setUnit] = useState("");
  const [quantity, setQuantity] = useState("");

  useEffect(() => {
    nwApi.items({ q: search }).then(setItems).catch(() => {});
  }, [search]);

  async function add() {
    if (!selected) {
      alert("Выберите NW из списка");
      return;
    }
    await wpApi.add(projectId, batchId, {
      nw_item_code: selected,
      unit: unit || undefined,
      quantity: quantity ? Number(quantity) : undefined,
    });
    onAdded();
  }

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "#0f172a40", zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: "white", padding: 24, borderRadius: 8, width: 480, maxHeight: "80vh", overflow: "auto" }}>
        <h3 style={{ margin: "0 0 12px 0", fontSize: 16 }}>Добавить карточку плана</h3>
        <input
          type="search"
          placeholder="Поиск NW по названию..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ ...inputStyle, marginBottom: 8 }}
        />
        <div style={{ maxHeight: 250, overflow: "auto", border: `1px solid ${COLORS.border}`, borderRadius: 4, marginBottom: 12 }}>
          {items.slice(0, 100).map((it) => (
            <div
              key={it.code}
              onClick={() => setSelected(it.code)}
              style={{
                padding: "6px 10px",
                fontSize: 12,
                cursor: "pointer",
                background: selected === it.code ? COLORS.primaryBg : "transparent",
                color: selected === it.code ? COLORS.primary : COLORS.text,
                borderBottom: `1px solid ${COLORS.border}`,
              }}
            >
              <code style={{ fontSize: 10, color: COLORS.muted, marginRight: 6 }}>{it.code}</code>
              {it.unique_label}
            </div>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
          <Field label="Единица"><input type="text" value={unit} onChange={(e) => setUnit(e.target.value)} style={inputStyle} /></Field>
          <Field label="Объём"><input type="number" step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)} style={inputStyle} /></Field>
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={btn("white", COLORS.muted)}>Отмена</button>
          <button onClick={add} style={btn(COLORS.primary, "white")}>Добавить</button>
        </div>
      </div>
    </div>
  );
}
