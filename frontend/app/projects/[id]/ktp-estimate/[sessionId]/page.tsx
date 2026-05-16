"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { ktpEstimate } from "@/lib/api";
import { useJobPoller } from "@/lib/useJobPoller";
import type {
  KtpEstimateCard,
  KtpQuestion,
  KtpWbs,
  KtpWbsGroup,
  KtpWbsItem,
} from "@/lib/types";

const ORIGIN_BADGE: Record<KtpWbsItem["origin"], { label: string; color: string }> = {
  from_estimate: { label: "из сметы", color: "var(--muted)" },
  ai_added: { label: "ИИ добавил", color: "#b45309" },
  manual: { label: "вручную", color: "#2563eb" },
};

const card = {
  border: "1px solid var(--border)",
  borderRadius: 8,
  background: "var(--surface)",
};

const btn = (variant: "primary" | "ghost" | "danger" = "ghost"): React.CSSProperties => ({
  padding: "7px 13px",
  borderRadius: 6,
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  border: variant === "primary" ? "none" : "1px solid var(--border2)",
  background:
    variant === "primary" ? "var(--blue-dark)" : variant === "danger" ? "rgba(239,68,68,.08)" : "var(--surface)",
  color: variant === "primary" ? "#fff" : variant === "danger" ? "var(--red)" : "var(--text)",
});

export default function KtpEstimateWizardPage() {
  const { id: projectId, sessionId } = useParams<{ id: string; sessionId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [wbs, setWbs] = useState<KtpWbs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(searchParams.get("job"));

  const { job } = useJobPoller(activeJobId);

  const loadWbs = useCallback(async () => {
    try {
      setWbs(await ktpEstimate.getWbs(projectId, sessionId));
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  }, [projectId, sessionId]);

  // нет ?job= — грузим WBS сразу
  useEffect(() => {
    if (!activeJobId) void loadWbs();
  }, [activeJobId, loadWbs]);

  // сеанс ещё обрабатывается, но мы зашли без ?job= — подцепляем поллер по
  // сохранённому job_id (recovery после перезагрузки страницы)
  useEffect(() => {
    if (!wbs || activeJobId) return;
    const s = wbs.session;
    const recoverJob =
      s.status === "stage1_processing" || s.status === "stage1_pending"
        ? s.stage1_job_id
        : s.status === "gpr_processing"
        ? s.gpr_job_id
        : null;
    if (recoverJob) setActiveJobId(recoverJob);
  }, [wbs, activeJobId]);

  // job завершился — перегружаем WBS
  useEffect(() => {
    if (!job) return;
    if (job.status === "done") {
      setActiveJobId(null);
      void loadWbs();
    } else if (job.status === "failed") {
      setActiveJobId(null);
      setError(job.result?.error || "Задача завершилась с ошибкой");
    }
  }, [job, loadWbs]);

  const session = wbs?.session;
  const status = session?.status;
  const batchId = session?.estimate_batch_id;

  const run = useCallback(
    async (fn: () => Promise<KtpWbs>) => {
      setBusy(true);
      try {
        setWbs(await fn());
        setError(null);
      } catch (e: any) {
        setError(e.message);
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  // ── состояния загрузки ───────────────────────────────────────────────
  if (activeJobId || status === "stage1_processing" || status === "stage1_pending") {
    return (
      <ProcessingScreen
        title="ИИ анализирует смету"
        subtitle="Строим структуру работ — группируем позиции и проверяем полноту охвата"
        progress={job?.result?._progress ?? null}
      />
    );
  }
  if (status === "gpr_processing") {
    return (
      <ProcessingScreen
        title="Строим график производства работ"
        subtitle="ИИ рассчитывает нормы, длительности и зависимости"
        progress={job?.result?._progress ?? null}
      />
    );
  }
  if (error) {
    return (
      <Centered>
        <div style={{ color: "var(--red)", fontSize: 13, marginBottom: 12 }}>❌ {error}</div>
        <button style={btn()} onClick={() => void loadWbs()}>
          Обновить
        </button>
      </Centered>
    );
  }
  if (!wbs || !session) return <Centered>Загрузка…</Centered>;
  if (status === "stage1_failed" || status === "gpr_failed") {
    return (
      <Centered>
        <div style={{ color: "var(--red)", fontSize: 13 }}>
          ❌ {session.error_message || "Ошибка обработки"}
        </div>
      </Centered>
    );
  }

  const stepIndex =
    status === "stage1_review" ? 1 : status === "stage2_review" ? 2 : 3;

  return (
    <div style={{ height: "100%", overflow: "auto", padding: 24, maxWidth: 1080, margin: "0 auto", boxSizing: "border-box" }}>
      <Steps current={stepIndex} />

      {status === "stage1_review" && (
        <Stage1
          wbs={wbs}
          busy={busy}
          run={run}
          projectId={projectId}
          sessionId={sessionId}
          onApprove={async () => {
            setBusy(true);
            try {
              await ktpEstimate.approveStage1(projectId, sessionId);
              await loadWbs();
            } catch (e: any) {
              setError(e.message);
            } finally {
              setBusy(false);
            }
          }}
        />
      )}

      {status === "stage2_review" && (
        <Stage2
          wbs={wbs}
          projectId={projectId}
          sessionId={sessionId}
          busy={busy}
          setBusy={setBusy}
          setError={setError}
          reload={loadWbs}
        />
      )}

      {(status === "gpr_pending" || status === "gpr_done") && (
        <Stage3
          wbs={wbs}
          projectId={projectId}
          sessionId={sessionId}
          busy={busy}
          run={run}
          done={status === "gpr_done"}
          onBuild={async () => {
            setBusy(true);
            try {
              const { job_id } = await ktpEstimate.buildGpr(projectId, sessionId);
              setActiveJobId(job_id);
            } catch (e: any) {
              setError(e.message);
              setBusy(false);
            }
          }}
          onOpenGantt={() => router.push(`/projects/${projectId}/gantt?batch=${batchId}`)}
        />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--muted)",
        fontSize: 13,
        textAlign: "center",
        padding: 24,
      }}
    >
      {children}
    </div>
  );
}

function ProcessingScreen({
  title,
  subtitle,
  progress,
}: {
  title: string;
  subtitle: string;
  progress: string | null;
}) {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  useEffect(() => {
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);
    return () => clearInterval(t);
  }, []);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const elapsedStr = mins > 0 ? `${mins} мин ${secs} сек` : `${secs} сек`;

  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: 32,
        gap: 0,
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 480,
          border: "1px solid var(--border)",
          borderRadius: 12,
          background: "var(--surface)",
          padding: 28,
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Spinner />
          <div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{title}</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>{subtitle}</div>
          </div>
        </div>

        {progress && (
          <div
            style={{
              padding: "10px 14px",
              borderRadius: 6,
              background: "rgba(59,130,246,.06)",
              border: "1px solid rgba(59,130,246,.15)",
              fontSize: 12,
              color: "var(--blue-dark, #1d4ed8)",
              fontFamily: "var(--mono)",
            }}
          >
            {progress}
          </div>
        )}

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 11,
            color: "var(--muted)",
            borderTop: "1px solid var(--border)",
            paddingTop: 10,
          }}
        >
          <span>Время: {elapsedStr}</span>
          <span>Можно закрыть — обработка идёт на сервере</span>
        </div>
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <div
      style={{
        width: 28,
        height: 28,
        borderRadius: "50%",
        border: "3px solid rgba(59,130,246,.2)",
        borderTopColor: "var(--blue-dark, #1d4ed8)",
        flexShrink: 0,
        animation: "ktp-spin 0.8s linear infinite",
      }}
    />
  );
}

function Steps({ current }: { current: number }) {
  const labels = ["Структура работ", "Карточки КТП", "ГПР"];
  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
      {labels.map((label, i) => {
        const n = i + 1;
        const active = n === current;
        const done = n < current;
        return (
          <div
            key={label}
            style={{
              flex: 1,
              padding: "9px 12px",
              borderRadius: 6,
              fontSize: 12,
              fontWeight: 600,
              textAlign: "center",
              border: "1px solid var(--border)",
              background: active ? "var(--blue-dark)" : done ? "rgba(34,197,94,.1)" : "var(--surface)",
              color: active ? "#fff" : done ? "#15803d" : "var(--muted)",
            }}
          >
            {done ? "✓ " : `${n}. `}
            {label}
          </div>
        );
      })}
    </div>
  );
}

// ── ЭТАП 1 ───────────────────────────────────────────────────────────────────

function Stage1({
  wbs,
  busy,
  run,
  projectId,
  sessionId,
  onApprove,
}: {
  wbs: KtpWbs;
  busy: boolean;
  run: (fn: () => Promise<KtpWbs>) => Promise<void>;
  projectId: string;
  sessionId: string;
  onApprove: () => void;
}) {
  const [newGroup, setNewGroup] = useState("");
  const pendingAi = wbs.groups
    .flatMap((g) => g.items)
    .filter((it) => it.origin === "ai_added" && it.review_status === "pending").length;
  const groupOptions = wbs.groups.map((g) => ({ id: g.id, title: g.title }));

  return (
    <div>
      <Header
        title="Структура работ"
        hint="ИИ собрал позиции сметы в группы и добавил недостающие работы. Проверьте и поправьте структуру, затем утвердите."
        right={
          <button
            style={btn("primary")}
            disabled={busy || pendingAi > 0}
            onClick={onApprove}
            title={pendingAi > 0 ? `Проверьте ${pendingAi} добавленных ИИ работ` : ""}
          >
            Утвердить структуру →
          </button>
        }
      />
      {pendingAi > 0 && (
        <div style={{ fontSize: 12, color: "#b45309", marginBottom: 14 }}>
          Не проверено добавленных ИИ работ: {pendingAi}
        </div>
      )}

      {wbs.groups.map((g) => (
        <Stage1Group
          key={g.id}
          group={g}
          groupOptions={groupOptions}
          busy={busy}
          run={run}
          projectId={projectId}
        />
      ))}

      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <input
          value={newGroup}
          onChange={(e) => setNewGroup(e.target.value)}
          placeholder="Новая группа работ"
          style={inputStyle}
        />
        <button
          style={btn()}
          disabled={busy || !newGroup.trim()}
          onClick={() =>
            run(async () => {
              const r = await ktpEstimate.createGroup(projectId, sessionId, newGroup.trim());
              setNewGroup("");
              return r;
            })
          }
        >
          + Группа
        </button>
      </div>
    </div>
  );
}

function Stage1Group({
  group,
  groupOptions,
  busy,
  run,
  projectId,
}: {
  group: KtpWbsGroup;
  groupOptions: { id: string; title: string }[];
  busy: boolean;
  run: (fn: () => Promise<KtpWbs>) => Promise<void>;
  projectId: string;
}) {
  const [title, setTitle] = useState(group.title);
  const [newItem, setNewItem] = useState("");

  return (
    <div style={{ ...card, marginBottom: 12, padding: 14 }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => {
            if (title.trim() && title !== group.title) {
              void run(() => ktpEstimate.updateGroup(projectId, group.id, { title: title.trim() }));
            }
          }}
          style={{ ...inputStyle, fontWeight: 600, flex: 1 }}
        />
        {group.wt_code && (
          <span style={{ fontSize: 11, color: "var(--muted)", alignSelf: "center" }}>
            WT {group.wt_code}
          </span>
        )}
        <button
          style={btn("danger")}
          disabled={busy}
          onClick={() => run(() => ktpEstimate.deleteGroup(projectId, group.id))}
          title={group.items.length ? "Сначала перенесите или удалите работы" : "Удалить группу"}
        >
          Удалить группу
        </button>
      </div>

      {group.items.map((it) => {
        const badge = ORIGIN_BADGE[it.origin];
        const rejected = it.review_status === "rejected";
        return (
          <div
            key={it.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "7px 0",
              borderTop: "1px solid var(--border)",
              opacity: rejected ? 0.5 : 1,
            }}
          >
            <span style={{ flex: 1, fontSize: 13 }}>{it.name}</span>
            <span style={{ fontSize: 10, fontWeight: 600, color: badge.color, whiteSpace: "nowrap" }}>
              {badge.label}
            </span>
            {it.origin === "ai_added" && it.ai_reason && (
              <span style={{ fontSize: 10, color: "var(--muted)", maxWidth: 220 }} title={it.ai_reason}>
                {it.ai_reason}
              </span>
            )}
            {it.origin === "ai_added" && (
              <>
                <button
                  style={{
                    ...btn(),
                    padding: "4px 9px",
                    color: it.review_status === "accepted" ? "#15803d" : "var(--text)",
                  }}
                  disabled={busy}
                  onClick={() =>
                    run(() =>
                      ktpEstimate.updateItem(projectId, it.id, { review_status: "accepted" }),
                    )
                  }
                >
                  ✓
                </button>
                <button
                  style={{ ...btn(), padding: "4px 9px", color: rejected ? "var(--red)" : "var(--text)" }}
                  disabled={busy}
                  onClick={() =>
                    run(() =>
                      ktpEstimate.updateItem(projectId, it.id, { review_status: "rejected" }),
                    )
                  }
                >
                  ✕
                </button>
              </>
            )}
            <select
              value={group.id}
              disabled={busy}
              onChange={(e) =>
                run(() => ktpEstimate.updateItem(projectId, it.id, { group_id: e.target.value }))
              }
              style={{ ...inputStyle, padding: "4px 6px", maxWidth: 150 }}
            >
              {groupOptions.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.title}
                </option>
              ))}
            </select>
            <button
              style={{ ...btn("danger"), padding: "4px 9px" }}
              disabled={busy}
              onClick={() => run(() => ktpEstimate.deleteItem(projectId, it.id))}
            >
              🗑
            </button>
          </div>
        );
      })}

      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <input
          value={newItem}
          onChange={(e) => setNewItem(e.target.value)}
          placeholder="Добавить работу вручную"
          style={inputStyle}
        />
        <button
          style={btn()}
          disabled={busy || !newItem.trim()}
          onClick={() =>
            run(async () => {
              const r = await ktpEstimate.createItem(projectId, group.id, { name: newItem.trim() });
              setNewItem("");
              return r;
            })
          }
        >
          + Работа
        </button>
      </div>
    </div>
  );
}

// ── ЭТАП 2 ───────────────────────────────────────────────────────────────────

function Stage2({
  wbs,
  projectId,
  sessionId,
  busy,
  setBusy,
  setError,
  reload,
}: {
  wbs: KtpWbs;
  projectId: string;
  sessionId: string;
  busy: boolean;
  setBusy: (v: boolean) => void;
  setError: (v: string | null) => void;
  reload: () => Promise<void>;
}) {
  const allReady = wbs.groups.every((g) => g.status === "card_generated");

  return (
    <div>
      <Header
        title="Карточки КТП"
        hint="Сгенерируйте карточку технологического процесса для каждой группы. ИИ может задать уточняющие вопросы."
        right={
          <button
            style={btn("primary")}
            disabled={busy || !allReady}
            onClick={async () => {
              setBusy(true);
              try {
                await ktpEstimate.approveStage2(projectId, sessionId);
                await reload();
              } catch (e: any) {
                setError(e.message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Все карточки готовы → к ГПР
          </button>
        }
      />
      {wbs.groups.map((g) => (
        <Stage2Group
          key={g.id}
          group={g}
          projectId={projectId}
          busy={busy}
          setBusy={setBusy}
          setError={setError}
          reload={reload}
        />
      ))}
    </div>
  );
}

function Stage2Group({
  group,
  projectId,
  busy,
  setBusy,
  setError,
  reload,
}: {
  group: KtpWbsGroup;
  projectId: string;
  busy: boolean;
  setBusy: (v: boolean) => void;
  setError: (v: string | null) => void;
  reload: () => Promise<void>;
}) {
  const [questions, setQuestions] = useState<KtpQuestion[] | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [cardData, setCardData] = useState<KtpEstimateCard | null>(null);

  useEffect(() => {
    if (group.status === "card_generated" || group.status === "card_questions") {
      void ktpEstimate.getCard(projectId, group.id).then((c) => {
        setCardData(c);
        if (c.status === "card_questions" && c.questions_json) setQuestions(c.questions_json);
      });
    }
  }, [projectId, group.id, group.status]);

  const generate = async (withAnswers: Record<string, string>) => {
    setBusy(true);
    try {
      const res = await ktpEstimate.generateCard(projectId, group.id, withAnswers);
      if (res.sufficient) {
        setQuestions(null);
        setCardData(res.card);
      } else {
        setQuestions(res.questions);
      }
      await reload();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const statusLabel: Record<KtpWbsGroup["status"], string> = {
    draft: "Не создана",
    card_questions: "Нужны данные",
    card_generated: "Готова",
    card_failed: "Ошибка",
  };

  return (
    <div style={{ ...card, marginBottom: 12, padding: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ fontSize: 14, fontWeight: 600 }}>{group.title}</div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              color:
                group.status === "card_generated"
                  ? "#15803d"
                  : group.status === "card_failed"
                  ? "var(--red)"
                  : "var(--muted)",
            }}
          >
            {statusLabel[group.status]}
          </span>
          <button style={btn()} disabled={busy} onClick={() => generate(answers)}>
            {group.status === "card_generated" ? "Перегенерировать" : "Сгенерировать карточку"}
          </button>
        </div>
      </div>

      {questions && (
        <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
          {questions.map((q) => (
            <div key={q.key}>
              <label style={{ fontSize: 12, fontWeight: 600, display: "block", marginBottom: 3 }}>
                {q.label}
              </label>
              {q.hint && (
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 3 }}>{q.hint}</div>
              )}
              <input
                style={inputStyle}
                value={answers[q.key] || ""}
                onChange={(e) => setAnswers((a) => ({ ...a, [q.key]: e.target.value }))}
              />
            </div>
          ))}
          <button
            style={btn("primary")}
            disabled={busy || questions.some((q) => !answers[q.key])}
            onClick={() => generate(answers)}
          >
            Ответить и сгенерировать
          </button>
        </div>
      )}

      {cardData && cardData.status === "card_generated" && (
        <CardView
          card={cardData}
          busy={busy}
          onSave={async (patch) => {
            setBusy(true);
            try {
              setCardData(await ktpEstimate.updateCard(projectId, group.id, patch));
            } catch (e: any) {
              setError(e.message);
            } finally {
              setBusy(false);
            }
          }}
        />
      )}
    </div>
  );
}

function CardView({
  card,
  busy,
  onSave,
}: {
  card: KtpEstimateCard;
  busy: boolean;
  onSave: (patch: { title?: string; goal?: string }) => void;
}) {
  const [title, setTitle] = useState(card.title || "");
  const [goal, setGoal] = useState(card.goal || "");
  // sync локальный state при перегенерации/обновлении карточки
  useEffect(() => {
    setTitle(card.title || "");
    setGoal(card.goal || "");
  }, [card.id, card.title, card.goal]);
  const dirty = title !== (card.title || "") || goal !== (card.goal || "");

  return (
    <div style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
      <input style={{ ...inputStyle, fontWeight: 600, marginBottom: 6 }} value={title} onChange={(e) => setTitle(e.target.value)} />
      <textarea
        style={{ ...inputStyle, minHeight: 50, marginBottom: 8 }}
        value={goal}
        onChange={(e) => setGoal(e.target.value)}
        placeholder="Цель"
      />
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, marginBottom: 8 }}>
        <thead>
          <tr style={{ background: "rgba(148,163,184,.08)" }}>
            <th style={thCell}>№</th>
            <th style={thCell}>Этап</th>
            <th style={thCell}>Содержание работ</th>
            <th style={thCell}>Контроль</th>
          </tr>
        </thead>
        <tbody>
          {(card.steps || []).map((s: any, i: number) => (
            <tr key={i} style={{ borderTop: "1px solid var(--border)" }}>
              <td style={tdCell}>{s.no ?? i + 1}</td>
              <td style={tdCell}>{s.stage}</td>
              <td style={tdCell}>{s.work_details}</td>
              <td style={tdCell}>{s.control_points}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!!card.recommendations?.length && (
        <ul style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 8px", paddingLeft: 18 }}>
          {card.recommendations.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      {dirty && (
        <button style={btn("primary")} disabled={busy} onClick={() => onSave({ title, goal })}>
          Сохранить правки
        </button>
      )}
    </div>
  );
}

// ── ЭТАП 3 ───────────────────────────────────────────────────────────────────

function Stage3({
  wbs,
  projectId,
  busy,
  run,
  done,
  onBuild,
  onOpenGantt,
}: {
  wbs: KtpWbs;
  projectId: string;
  sessionId: string;
  busy: boolean;
  run: (fn: () => Promise<KtpWbs>) => Promise<void>;
  done: boolean;
  onBuild: () => void;
  onOpenGantt: () => void;
}) {
  const missingQty = useMemo(
    () =>
      wbs.groups
        .flatMap((g) => g.items)
        .filter((it) => it.origin !== "from_estimate" && it.quantity == null),
    [wbs],
  );

  return (
    <div>
      <Header
        title="График производства работ"
        hint="Укажите объёмы для добавленных работ — ИИ подберёт нормы, система рассчитает длительности и зависимости."
        right={
          done ? (
            <button style={btn("primary")} onClick={onOpenGantt}>
              Открыть Гант →
            </button>
          ) : (
            <button style={btn("primary")} disabled={busy} onClick={onBuild}>
              Построить ГПР
            </button>
          )
        }
      />

      {done && (
        <div
          style={{
            ...card,
            padding: 14,
            marginBottom: 14,
            color: "#15803d",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          ✓ ГПР построен и записан в график проекта
        </div>
      )}

      {missingQty.length > 0 && !done && (
        <div style={{ ...card, padding: 14, marginBottom: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
            Объёмы для добавленных работ ({missingQty.length})
          </div>
          {missingQty.map((it) => (
            <QtyRow key={it.id} item={it} busy={busy} run={run} projectId={projectId} />
          ))}
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 6 }}>
            Если оставить пустым — объём оценит ИИ.
          </div>
        </div>
      )}

      {wbs.groups.map((g) => (
        <div key={g.id} style={{ ...card, padding: 14, marginBottom: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, fontWeight: 600 }}>
            <span>{g.title}</span>
            <span style={{ color: "var(--muted)", fontWeight: 400 }}>
              {g.start_date ? `${g.start_date} · ` : ""}
              {g.duration_days ? `${g.duration_days} дн.` : "—"}
            </span>
          </div>
          {g.items.map((it) => (
            <div
              key={it.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 12,
                color: "var(--muted)",
                padding: "4px 0",
              }}
            >
              <span>{it.name}</span>
              <span>
                {it.duration_days ? `${it.duration_days} дн.` : "—"}
                {it.norm_kind ? ` · ${it.norm_kind}` : ""}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function QtyRow({
  item,
  busy,
  run,
  projectId,
}: {
  item: KtpWbsItem;
  busy: boolean;
  run: (fn: () => Promise<KtpWbs>) => Promise<void>;
  projectId: string;
}) {
  const [qty, setQty] = useState("");
  const [unit, setUnit] = useState(item.unit || "");
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 0" }}>
      <span style={{ flex: 1, fontSize: 12 }}>{item.name}</span>
      <input
        value={qty}
        onChange={(e) => setQty(e.target.value)}
        placeholder="объём"
        style={{ ...inputStyle, maxWidth: 90 }}
      />
      <input
        value={unit}
        onChange={(e) => setUnit(e.target.value)}
        placeholder="ед."
        style={{ ...inputStyle, maxWidth: 70 }}
      />
      <button
        style={btn()}
        disabled={busy || !qty.trim()}
        onClick={() =>
          run(() =>
            ktpEstimate.updateItem(projectId, item.id, {
              quantity: Number(qty),
              unit: unit.trim() || null,
            }),
          )
        }
      >
        OK
      </button>
    </div>
  );
}

// ── общее ────────────────────────────────────────────────────────────────────

function Header({
  title,
  hint,
  right,
}: {
  title: string;
  hint: string;
  right: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        gap: 16,
        marginBottom: 16,
      }}
    >
      <div>
        <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 4 }}>{title}</div>
        <div style={{ fontSize: 12, color: "var(--muted)", maxWidth: 640, lineHeight: 1.5 }}>{hint}</div>
      </div>
      {right}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "7px 10px",
  border: "1px solid var(--border2)",
  borderRadius: 5,
  fontSize: 13,
  outline: "none",
  flex: 1,
  background: "var(--surface)",
  color: "var(--text)",
};

const thCell: React.CSSProperties = {
  padding: "7px 10px",
  textAlign: "left",
  fontSize: 10,
  color: "var(--muted)",
  textTransform: "uppercase",
};

const tdCell: React.CSSProperties = {
  padding: "7px 10px",
  fontSize: 12,
  verticalAlign: "top",
};
