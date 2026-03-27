"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { enir as enirApi, enirMapping as mappingApi } from "@/lib/api";

/* ─── types ─────────────────────────────────────────────────────────────── */
interface Alt { collection_id?: number; paragraph_id?: number; code: string; title: string; confidence: number; }

interface GroupMapping {
  id: number; task_id: string; task_name: string | null;
  collection_id: number | null; collection_code: string | null; collection_title: string | null;
  status: string; confidence: number | null; ai_reasoning: string | null;
  alternatives: Alt[]; estimates: EstimateMapping[];
}
interface EstimateMapping {
  id: number; estimate_id: string; work_name: string | null; unit: string | null;
  paragraph_id: number | null; paragraph_code: string | null; paragraph_title: string | null;
  norm_row_id: string | null; norm_row_hint: string | null;
  status: string; confidence: number | null; ai_reasoning: string | null; alternatives: Alt[];
}
interface Stats {
  groups_total: number; groups_confirmed: number;
  estimates_total: number; estimates_confirmed: number;
  estimates_suggested: number; estimates_missing: number;
}

/* ─── design tokens (поверх CSS-переменных приложения) ───────────────────── */
const D = {
  confirmed:    { bg: "#dcfce7", border: "#86efac", text: "#15803d", dot: "#22c55e" },
  manual:       { bg: "#dbeafe", border: "#93c5fd", text: "#1d4ed8", dot: "#3b82f6" },
  ai_suggested: { bg: "#fef9c3", border: "#fde047", text: "#854d0e", dot: "#eab308" },
  rejected:     { bg: "#fee2e2", border: "#fca5a5", text: "#b91c1c", dot: "#ef4444" },
  missing:      { bg: "#fff7ed", border: "#fed7aa", text: "#c2410c", dot: "#f97316" },
};
type DKey = keyof typeof D;

const LABEL: Record<string, string> = {
  confirmed: "Подтверждено", manual: "Вручную",
  ai_suggested: "ИИ предложил", rejected: "Отклонено",
};

/* ─── helpers ─────────────────────────────────────────────────────────────── */
function pct(v: number | null) { return v == null ? 0 : Math.round(v * 100); }

function StatusPill({ status, small }: { status: string; small?: boolean }) {
  const key = (D[status as DKey] ? status : "missing") as DKey;
  const s = D[key];
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      background: s.bg, border: `1px solid ${s.border}`, color: s.text,
      borderRadius: 20, padding: small ? "1px 7px" : "2px 9px",
      fontSize: small ? 10 : 11, fontWeight: 600, whiteSpace: "nowrap",
      lineHeight: 1.6,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: s.dot, flexShrink: 0 }} />
      {LABEL[status] ?? status}
    </span>
  );
}

function ConfBar({ value, small }: { value: number | null; small?: boolean }) {
  const p = pct(value);
  const color = p >= 85 ? "#22c55e" : p >= 60 ? "#eab308" : "#f97316";
  const w = small ? 60 : 80;
  const h = small ? 4 : 5;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
      <div style={{ width: w, height: h, background: "#e2e8f0", borderRadius: h, overflow: "hidden", flexShrink: 0 }}>
        <div style={{ width: `${p}%`, height: "100%", background: color, borderRadius: h, transition: "width .3s ease" }} />
      </div>
      <span style={{ fontSize: small ? 10 : 11, fontFamily: "var(--mono)", color, fontWeight: 600, minWidth: 28 }}>{p}%</span>
    </div>
  );
}

function GroupProgress({ estimates }: { estimates: EstimateMapping[] }) {
  const total     = estimates.length;
  const confirmed = estimates.filter(e => e.status === "confirmed" || e.status === "manual").length;
  const missing   = estimates.filter(e => !e.paragraph_id).length;
  if (total === 0) return <span style={{ fontSize: 10, color: "var(--muted)" }}>нет строк</span>;
  const pct = Math.round(confirmed / total * 100);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 48, height: 4, background: "#e2e8f0", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: "#22c55e", transition: "width .3s" }} />
      </div>
      <span style={{ fontSize: 10, fontFamily: "var(--mono)", color: "var(--muted)" }}>
        {confirmed}/{total}
        {missing > 0 && <span style={{ color: "#f97316", marginLeft: 4 }}>·{missing}❓</span>}
      </span>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN COMPONENT
═══════════════════════════════════════════════════════════════════════════ */
export default function EnirMapping({ projectId }: { projectId: string }) {
  const [groups,      setGroups]      = useState<GroupMapping[]>([]);
  const [stats,       setStats]       = useState<Stats | null>(null);
  const [loading,     setLoading]     = useState(true);
  const [running,     setRunning]     = useState<string | null>(null);
  const [activeGroup, setActiveGroup] = useState<GroupMapping | null>(null);
  const [collections, setCollections] = useState<any[]>([]);
  const [toast,       setToast]       = useState<{ msg: string; ok: boolean } | null>(null);

  const showToast = (msg: string, ok = true) => {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 2800);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [state, colls] = await Promise.all([
        mappingApi.state(projectId),
        enirApi.collections(),
      ]);
      setGroups(state.groups);
      setStats(state.stats);
      setCollections(colls);
      // обновляем активную группу если она уже выбрана
      setActiveGroup(prev => prev ? (state.groups.find((g: GroupMapping) => g.id === prev.id) ?? null) : null);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  async function runAll() {
    setRunning("all");
    try { await mappingApi.mapAll(projectId); showToast("Маппинг всей сметы завершён"); await load(); }
    catch (e: any) { showToast(e.message, false); }
    finally { setRunning(null); }
  }

  async function runGroup(taskId: string) {
    setRunning(taskId);
    try { await mappingApi.mapGroup(projectId, taskId); showToast("Группа сопоставлена"); await load(); }
    catch (e: any) { showToast(e.message, false); }
    finally { setRunning(null); }
  }

  async function confirmGroup(mappingId: number, collectionId?: number) {
    await mappingApi.confirmGroup(projectId, mappingId, collectionId);
    showToast("Сборник подтверждён");
    await load();
  }

  async function confirmEstimate(mappingId: number, body: any) {
    await mappingApi.confirmEstimate(projectId, mappingId, body);
    await load();
  }

  async function confirmAllSuggested() {
    if (!activeGroup) return;
    const toConfirm = activeGroup.estimates.filter(e => e.status === "ai_suggested" && e.paragraph_id);
    for (const e of toConfirm) {
      await mappingApi.confirmEstimate(projectId, e.id, {});
    }
    showToast(`Подтверждено ${toConfirm.length} строк`);
    await load();
  }

  /* ── render ──────────────────────────────────────────────────────────── */
  if (loading) return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", flexDirection: "column", gap: 12 }}>
      <div style={{ width: 32, height: 32, border: "3px solid var(--border)", borderTopColor: "var(--blue)", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
      <div style={{ fontSize: 13, color: "var(--muted)" }}>Загрузка маппинга…</div>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden", fontFamily: "var(--sans)" }}>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg) } }
        @keyframes fadeIn { from { opacity:0; transform:translateY(-6px) } to { opacity:1; transform:none } }
        .em-row:hover { background: rgba(59,130,246,.04) !important; }
        .em-row { transition: background .12s; }
        .em-btn { transition: all .15s; }
        .em-btn:hover:not(:disabled) { filter: brightness(1.08); transform: translateY(-1px); }
        .em-btn:active:not(:disabled) { transform: translateY(0); }
        .group-row { transition: background .12s, border-color .12s; }
        .group-row:hover { background: rgba(59,130,246,.05) !important; }
      `}</style>

      {/* ═══ LEFT — GROUPS PANEL ═══════════════════════════════════════════ */}
      <div style={{
        width: 300, flexShrink: 0, display: "flex", flexDirection: "column",
        borderRight: "1px solid var(--border)", background: "#fafbfc",
      }}>
        {/* header */}
        <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: "var(--muted)" }}>
              Группы работ
            </span>
            <button className="em-btn" onClick={runAll} disabled={!!running}
              style={{
                display: "flex", alignItems: "center", gap: 5, padding: "5px 10px",
                background: running ? "#e2e8f0" : "var(--blue)",
                color: running ? "var(--muted)" : "#fff",
                border: "none", borderRadius: 6, fontSize: 11, fontWeight: 600,
                cursor: running ? "not-allowed" : "pointer",
              }}>
              {running === "all"
                ? <><span style={{ width:12, height:12, border:"2px solid #fff4", borderTopColor:"#fff", borderRadius:"50%", animation:"spin 1s linear infinite", display:"inline-block" }} /> Работаю…</>
                : <><span>⚡</span> Вся смета</>
              }
            </button>
          </div>

          {/* stats summary */}
          {stats && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6 }}>
              {[
                { v: stats.estimates_confirmed, label: "подтв.",  color: "#15803d", bg: "#dcfce7" },
                { v: stats.estimates_suggested, label: "ИИ",      color: "#854d0e", bg: "#fef9c3" },
                { v: stats.estimates_missing,   label: "❓",       color: "#c2410c", bg: "#fff7ed" },
              ].map(s => (
                <div key={s.label} style={{ background: s.bg, borderRadius: 6, padding: "5px 8px", textAlign: "center" }}>
                  <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "var(--mono)", color: s.color, lineHeight: 1 }}>{s.v}</div>
                  <div style={{ fontSize: 9, color: s.color, marginTop: 2, textTransform: "uppercase", letterSpacing: ".04em" }}>{s.label}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* group list */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {groups.length === 0 ? (
            <div style={{ padding: "32px 16px", textAlign: "center", color: "var(--muted)" }}>
              <div style={{ fontSize: 28, marginBottom: 8 }}>🔗</div>
              <div style={{ fontSize: 12 }}>Нажмите «Вся смета»<br/>чтобы запустить маппинг</div>
            </div>
          ) : groups.map(g => {
            const isActive = activeGroup?.id === g.id;
            const isRun    = running === g.task_id;
            const key      = (D[g.status as DKey] ? g.status : "missing") as DKey;
            const dot      = D[key].dot;
            return (
              <div key={g.id} className="group-row"
                onClick={() => setActiveGroup(g)}
                style={{
                  padding: "10px 14px", borderBottom: "1px solid var(--border)",
                  cursor: "pointer", position: "relative",
                  background: isActive ? "#eff6ff" : "transparent",
                  borderLeft: `3px solid ${isActive ? "var(--blue)" : "transparent"}`,
                }}>
                {/* status dot + name */}
                <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: dot, flexShrink: 0, marginTop: 4 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--fg)", lineHeight: 1.35,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {g.task_name ?? "—"}
                    </div>
                    <div style={{ marginTop: 4, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      {g.collection_code ? (
                        <span style={{ fontSize: 10, fontFamily: "var(--mono)", fontWeight: 700, color: "var(--blue-dark)", background: "#dbeafe", padding: "0 5px", borderRadius: 3 }}>
                          {g.collection_code}
                        </span>
                      ) : (
                        <span style={{ fontSize: 10, color: "#c2410c" }}>нет сборника</span>
                      )}
                      <GroupProgress estimates={g.estimates} />
                    </div>
                  </div>

                  {/* run button */}
                  <button className="em-btn"
                    onClick={e => { e.stopPropagation(); runGroup(g.task_id); }}
                    disabled={!!running}
                    title="Маппинг этой группы"
                    style={{
                      padding: "3px 6px", background: "transparent", border: "1px solid var(--border)",
                      borderRadius: 4, fontSize: 11, cursor: running ? "not-allowed" : "pointer",
                      color: "var(--muted)", flexShrink: 0,
                    }}>
                    {isRun ? <span style={{ width:10, height:10, border:"1.5px solid var(--muted)", borderTopColor:"var(--blue)", borderRadius:"50%", animation:"spin 1s linear infinite", display:"inline-block" }} /> : "⚡"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ═══ RIGHT — ESTIMATES PANEL ══════════════════════════════════════ */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {!activeGroup ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", flexDirection: "column", gap: 10, color: "var(--muted)" }}>
            <div style={{ fontSize: 36 }}>←</div>
            <div style={{ fontSize: 13 }}>Выберите группу работ</div>
          </div>
        ) : (
          <GroupDetail
            group={activeGroup}
            collections={collections}
            running={running}
            onConfirmGroup={confirmGroup}
            onConfirmEstimate={confirmEstimate}
            onConfirmAll={confirmAllSuggested}
            onRunGroup={() => runGroup(activeGroup.task_id)}
          />
        )}
      </div>

      {/* ═══ TOAST ════════════════════════════════════════════════════════ */}
      {toast && (
        <div style={{
          position: "fixed", bottom: 20, right: 20, zIndex: 1000,
          background: toast.ok ? "#15803d" : "#b91c1c", color: "#fff",
          padding: "10px 18px", borderRadius: 8, fontSize: 13, fontWeight: 500,
          boxShadow: "0 4px 20px rgba(0,0,0,.25)",
          animation: "fadeIn .2s ease",
        }}>
          {toast.ok ? "✓" : "✗"}  {toast.msg}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   GROUP DETAIL PANEL
═══════════════════════════════════════════════════════════════════════════ */
function GroupDetail({
  group, collections, running,
  onConfirmGroup, onConfirmEstimate, onConfirmAll, onRunGroup,
}: {
  group: GroupMapping; collections: any[]; running: string | null;
  onConfirmGroup: (id: number, collId?: number) => void;
  onConfirmEstimate: (id: number, body: any) => void;
  onConfirmAll: () => void;
  onRunGroup: () => void;
}) {
  const [showCollPicker, setShowCollPicker] = useState(false);
  const [filterStatus,   setFilterStatus]   = useState<string>("all");

  const suggested  = group.estimates.filter(e => e.status === "ai_suggested" && e.paragraph_id).length;
  const missing    = group.estimates.filter(e => !e.paragraph_id).length;
  const confirmed  = group.estimates.filter(e => e.status === "confirmed" || e.status === "manual").length;
  const total      = group.estimates.length;

  const filtered = group.estimates.filter(e => {
    if (filterStatus === "all")       return true;
    if (filterStatus === "pending")   return e.status === "ai_suggested";
    if (filterStatus === "confirmed") return e.status === "confirmed" || e.status === "manual";
    if (filterStatus === "missing")   return !e.paragraph_id;
    return true;
  });

  return (
    <>
      {/* ── top bar ────────────────────────────────────────────────────── */}
      <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", background: "#fff", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
          {/* group name + collection */}
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--fg)", marginBottom: 4 }}>
              {group.task_name}
            </div>

            {/* collection badge + picker */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <div style={{ position: "relative" }}>
                <button className="em-btn"
                  onClick={() => setShowCollPicker(p => !p)}
                  style={{
                    display: "flex", alignItems: "center", gap: 6, padding: "4px 10px",
                    background: group.collection_code ? "#eff6ff" : "#fff7ed",
                    border: `1px solid ${group.collection_code ? "#93c5fd" : "#fed7aa"}`,
                    borderRadius: 6, cursor: "pointer", fontSize: 12,
                    color: group.collection_code ? "#1d4ed8" : "#c2410c", fontWeight: 600,
                  }}>
                  <span style={{ fontFamily: "var(--mono)" }}>{group.collection_code ?? "Сборник не выбран"}</span>
                  {group.collection_title && <span style={{ fontWeight: 400, color: "var(--muted)", fontSize: 11 }}>· {group.collection_title}</span>}
                  <span style={{ fontSize: 9, color: "var(--muted)" }}>▾</span>
                </button>

                {showCollPicker && (
                  <CollectionPicker
                    collections={collections}
                    currentId={group.collection_id}
                    alternatives={group.alternatives}
                    onPick={collId => { setShowCollPicker(false); onConfirmGroup(group.id, collId); }}
                    onClose={() => setShowCollPicker(false)}
                  />
                )}
              </div>

              <StatusPill status={group.status} small />
              {group.confidence != null && <ConfBar value={group.confidence} small />}

              {group.status === "ai_suggested" && group.collection_id && (
                <button className="em-btn" onClick={() => onConfirmGroup(group.id)}
                  style={{ padding: "3px 10px", background: "#dcfce7", border: "1px solid #86efac", color: "#15803d", borderRadius: 5, fontSize: 11, cursor: "pointer", fontWeight: 600 }}>
                  ✓ Подтвердить сборник
                </button>
              )}
            </div>

            {/* AI reasoning */}
            {group.ai_reasoning && (
              <div style={{ marginTop: 6, fontSize: 11, color: "var(--muted)", fontStyle: "italic", lineHeight: 1.5 }}>
                💡 {group.ai_reasoning}
              </div>
            )}
          </div>

          {/* action bar right */}
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
            {suggested > 0 && (
              <button className="em-btn" onClick={onConfirmAll}
                style={{ padding: "6px 14px", background: "#dcfce7", border: "1px solid #86efac", color: "#15803d", borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                ✓ Принять всё ({suggested})
              </button>
            )}
            <button className="em-btn" onClick={onRunGroup} disabled={!!running}
              style={{ padding: "6px 14px", background: running ? "#e2e8f0" : "#eff6ff", border: "1px solid #93c5fd", color: running ? "var(--muted)" : "var(--blue-dark)", borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: running ? "not-allowed" : "pointer" }}>
              {running === group.task_id
                ? <><span style={{ width:10, height:10, border:"1.5px solid var(--blue-dark)4", borderTopColor:"var(--blue-dark)", borderRadius:"50%", animation:"spin 1s linear infinite", display:"inline-block", marginRight:5 }} />Работаю…</>
                : "⚡ Повторить маппинг"
              }
            </button>
          </div>
        </div>

        {/* progress row */}
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 10, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
          {/* overall bar */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1 }}>
            <div style={{ flex: 1, height: 6, background: "#e2e8f0", borderRadius: 6, overflow: "hidden", maxWidth: 300 }}>
              <div style={{ height: "100%", width: `${total ? Math.round(confirmed/total*100) : 0}%`, background: "linear-gradient(90deg, #22c55e, #16a34a)", transition: "width .4s ease", borderRadius: 6 }} />
            </div>
            <span style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--muted)" }}>{confirmed}/{total} строк подтверждено</span>
          </div>

          {/* filter tabs */}
          <div style={{ display: "flex", gap: 2, background: "var(--border)", borderRadius: 6, padding: 2 }}>
            {[
              { k: "all",       label: `Все (${total})` },
              { k: "pending",   label: `ИИ (${suggested})` },
              { k: "missing",   label: `❓ (${missing})` },
              { k: "confirmed", label: `✓ (${confirmed})` },
            ].map(f => (
              <button key={f.k} onClick={() => setFilterStatus(f.k)}
                style={{
                  padding: "3px 10px", border: "none", borderRadius: 4, fontSize: 11,
                  fontWeight: filterStatus === f.k ? 600 : 400, cursor: "pointer",
                  background: filterStatus === f.k ? "#fff" : "transparent",
                  color: filterStatus === f.k ? "var(--fg)" : "var(--muted)",
                  boxShadow: filterStatus === f.k ? "0 1px 3px rgba(0,0,0,.08)" : "none",
                  transition: "all .15s",
                }}>
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── estimates table ─────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {filtered.length === 0 ? (
          <div style={{ padding: 32, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>Нет строк по фильтру</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#f8fafc", position: "sticky", top: 0, zIndex: 5 }}>
                {["Наименование работ", "Параграф ЕНИР", "Уверенность", "Статус", ""].map((h, i) => (
                  <th key={i} style={{
                    padding: "8px 12px", textAlign: "left",
                    fontSize: 10, color: "var(--muted)", fontWeight: 600,
                    textTransform: "uppercase", letterSpacing: ".06em",
                    borderBottom: "2px solid var(--border)",
                    whiteSpace: "nowrap",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((est, idx) => (
                <EstimateTableRow
                  key={est.id}
                  est={est}
                  isOdd={idx % 2 === 1}
                  onConfirm={(body) => onConfirmEstimate(est.id, body)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

/* ─── EstimateTableRow ───────────────────────────────────────────────────── */
function EstimateTableRow({
  est, isOdd, onConfirm,
}: {
  est: EstimateMapping; isOdd: boolean;
  onConfirm: (body: any) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [editHint, setEditHint] = useState(est.norm_row_hint ?? "");
  const isDone    = est.status === "confirmed" || est.status === "manual";
  const isMissing = !est.paragraph_id;

  return (
    <>
      <tr className="em-row"
        style={{ background: isOdd ? "#fafbfc" : "#fff", cursor: "pointer" }}
        onClick={() => setExpanded(p => !p)}>

        {/* work name */}
        <td style={{ padding: "9px 12px", borderBottom: "1px solid var(--border)", maxWidth: 320 }}>
          <div style={{ fontSize: 12, color: "var(--fg)", fontWeight: 500, lineHeight: 1.4 }}>
            {est.work_name}
          </div>
          {est.unit && (
            <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 2, fontFamily: "var(--mono)" }}>{est.unit}</div>
          )}
        </td>

        {/* paragraph */}
        <td style={{ padding: "9px 12px", borderBottom: "1px solid var(--border)", whiteSpace: "nowrap" }}>
          {isMissing ? (
            <span style={{ fontSize: 11, color: "#c2410c", fontStyle: "italic" }}>не найдено</span>
          ) : (
            <div>
              <span style={{ fontFamily: "var(--mono)", fontWeight: 700, fontSize: 12, color: "var(--blue-dark)", background: "#dbeafe", padding: "2px 6px", borderRadius: 4 }}>
                {est.paragraph_code}
              </span>
              {est.paragraph_title && (
                <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 3, maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {est.paragraph_title}
                </div>
              )}
              {est.norm_row_hint && (
                <div style={{ fontSize: 10, color: "#0284c7", marginTop: 2, fontStyle: "italic", maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  › {est.norm_row_hint}
                </div>
              )}
            </div>
          )}
        </td>

        {/* confidence */}
        <td style={{ padding: "9px 12px", borderBottom: "1px solid var(--border)" }}>
          {est.confidence != null && !isMissing && <ConfBar value={est.confidence} small />}
        </td>

        {/* status */}
        <td style={{ padding: "9px 12px", borderBottom: "1px solid var(--border)" }}>
          <StatusPill status={isMissing ? "missing" : est.status} small />
        </td>

        {/* actions */}
        <td style={{ padding: "9px 12px", borderBottom: "1px solid var(--border)" }}
          onClick={e => e.stopPropagation()}>
          <div style={{ display: "flex", gap: 5, justifyContent: "flex-end" }}>
            {!isDone && !isMissing && (
              <button className="em-btn"
                onClick={() => onConfirm({})}
                style={{ padding: "3px 10px", background: "#dcfce7", border: "1px solid #86efac", color: "#15803d", borderRadius: 4, fontSize: 11, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap" }}>
                ✓ Принять
              </button>
            )}
            <button className="em-btn"
              onClick={() => setExpanded(p => !p)}
              style={{ padding: "3px 8px", background: "transparent", border: "1px solid var(--border)", color: "var(--muted)", borderRadius: 4, fontSize: 11, cursor: "pointer" }}>
              {expanded ? "▲" : "▼"}
            </button>
          </div>
        </td>
      </tr>

      {/* expanded detail row */}
      {expanded && (
        <tr>
          <td colSpan={5} style={{ padding: "12px 16px 14px 24px", background: "#f0f7ff", borderBottom: "1px solid #bfdbfe" }}>
            <div style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "flex-start" }}>

              {/* reasoning */}
              {est.ai_reasoning && (
                <div style={{ flex: 1, minWidth: 220 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 4 }}>Объяснение ИИ</div>
                  <div style={{ fontSize: 11, color: "var(--fg)", lineHeight: 1.6, fontStyle: "italic" }}>
                    {est.ai_reasoning}
                  </div>
                </div>
              )}

              {/* norm hint editor */}
              <div style={{ flex: 1, minWidth: 200 }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 4 }}>Строка нормы</div>
                <input
                  value={editHint}
                  onChange={e => setEditHint(e.target.value)}
                  onBlur={() => { if (editHint !== est.norm_row_hint) onConfirm({ norm_row_hint: editHint }); }}
                  placeholder="Например: толщина 1,5 кирпича, стены с проёмами…"
                  style={{ width: "100%", boxSizing: "border-box", background: "#fff", border: "1px solid #93c5fd", borderRadius: 5, padding: "6px 10px", fontSize: 12, outline: "none", color: "var(--fg)" }}
                />
              </div>

              {/* alternatives */}
              {est.alternatives.length > 0 && (
                <div style={{ flex: 1, minWidth: 200 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 6 }}>Альтернативы</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {est.alternatives.map((alt, i) => (
                      <button key={i} className="em-btn"
                        onClick={() => onConfirm({ paragraph_id: alt.paragraph_id, norm_row_hint: editHint || est.norm_row_hint })}
                        style={{
                          display: "flex", alignItems: "center", gap: 8,
                          padding: "5px 10px", background: "#fff", border: "1px solid var(--border)",
                          borderRadius: 5, cursor: "pointer", textAlign: "left",
                        }}>
                        <span style={{ fontFamily: "var(--mono)", fontSize: 11, fontWeight: 700, color: "var(--blue-dark)", background: "#dbeafe", padding: "1px 5px", borderRadius: 3 }}>{alt.code}</span>
                        <span style={{ fontSize: 11, color: "var(--fg)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{alt.title}</span>
                        <ConfBar value={alt.confidence} small />
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/* ─── CollectionPicker ───────────────────────────────────────────────────── */
function CollectionPicker({
  collections, currentId, alternatives, onPick, onClose,
}: {
  collections: any[]; currentId: number | null; alternatives: Alt[];
  onPick: (id: number) => void; onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handler(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) onClose(); }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  const altIds = new Set(alternatives.map(a => a.collection_id));

  return (
    <div ref={ref} style={{
      position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 100,
      background: "#fff", border: "1px solid var(--border)", borderRadius: 8,
      boxShadow: "0 8px 24px rgba(0,0,0,.12)", minWidth: 280, overflow: "hidden",
      animation: "fadeIn .15s ease",
    }}>
      <div style={{ padding: "8px 12px", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".07em", color: "var(--muted)", borderBottom: "1px solid var(--border)", background: "#f8fafc" }}>
        Выбрать сборник ЕНИР
      </div>
      {collections.map(c => {
        const isCurrent = c.id === currentId;
        const isAlt     = altIds.has(c.id);
        const alt       = alternatives.find(a => a.collection_id === c.id);
        return (
          <button key={c.id}
            onClick={() => onPick(c.id)}
            style={{
              display: "flex", alignItems: "center", gap: 10, width: "100%",
              padding: "9px 12px", border: "none", borderBottom: "1px solid var(--border)",
              background: isCurrent ? "#eff6ff" : isAlt ? "#fefce8" : "#fff",
              cursor: "pointer", textAlign: "left", transition: "background .1s",
            }}>
            <span style={{ fontFamily: "var(--mono)", fontWeight: 700, fontSize: 12, color: "var(--blue-dark)", background: "#dbeafe", padding: "2px 7px", borderRadius: 4, minWidth: 32, textAlign: "center" }}>{c.code}</span>
            <span style={{ fontSize: 12, flex: 1, color: "var(--fg)" }}>{c.title}</span>
            {isCurrent && <span style={{ fontSize: 10, color: "#15803d", fontWeight: 600 }}>✓ текущий</span>}
            {isAlt && alt && <ConfBar value={alt.confidence} small />}
          </button>
        );
      })}
    </div>
  );
}
