"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { ktpEstimate } from "@/lib/api";
import { trackActivity } from "@/lib/activity";
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

function buttonStyle(
  variant: "primary" | "ghost" | "danger" = "ghost",
  disabled = false,
): React.CSSProperties {
  return {
    ...btn(variant),
    opacity: disabled ? 0.65 : 1,
    cursor: disabled ? "not-allowed" : "pointer",
  };
}

function InlineSpinner() {
  return (
    <span
      aria-hidden="true"
      style={{
        width: 13,
        height: 13,
        borderRadius: "50%",
        border: "2px solid currentColor",
        borderTopColor: "transparent",
        display: "inline-block",
        flexShrink: 0,
        animation: "ktp-spin 0.8s linear infinite",
      }}
    />
  );
}

function ButtonContent({ loading, children }: { loading?: boolean; children: React.ReactNode }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 7 }}>
      {loading && <InlineSpinner />}
      {children}
    </span>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <span
      aria-hidden="true"
      style={{
        width: 7,
        height: 7,
        borderRight: "2px solid currentColor",
        borderBottom: "2px solid currentColor",
        display: "inline-block",
        transform: open ? "rotate(45deg)" : "rotate(-45deg)",
        transition: "transform .15s ease",
      }}
    />
  );
}

export default function KtpEstimateWizardPage() {
  const { id: projectId, sessionId } = useParams<{ id: string; sessionId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [wbs, setWbs] = useState<KtpWbs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(searchParams.get("job"));

  const { job } = useJobPoller(activeJobId);
  const session = wbs?.session;
  const status = session?.status;
  const batchId = session?.estimate_batch_id;

  useEffect(() => {
    trackActivity("KTP_ESTIMATE_WIZARD_OPENED", {
      projectId,
      entityType: "ktp_estimate_session",
      entityId: sessionId,
      metadata: {
        estimate_batch_id: searchParams.get("batch"),
        job_id: searchParams.get("job"),
      },
    });
  }, [projectId, searchParams, sessionId]);

  const loadWbs = useCallback(async () => {
    try {
      setWbs(await ktpEstimate.getWbs(projectId, sessionId));
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  }, [projectId, sessionId]);

  // WBS грузим всегда: stale ?job= не должен блокировать вход в мастер.
  useEffect(() => {
    void loadWbs();
  }, [loadWbs]);

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

  // Если пользователь открыл старую ссылку с ?job=, но сеанс уже ушёл дальше,
  // не держим экран на processing-состоянии.
  useEffect(() => {
    if (!session || !activeJobId) return;
    const expectedJob =
      session.status === "stage1_processing" || session.status === "stage1_pending"
        ? session.stage1_job_id
        : session.status === "gpr_processing"
        ? session.gpr_job_id
        : null;

    if (expectedJob && expectedJob !== activeJobId) {
      setActiveJobId(expectedJob);
    } else if (!expectedJob) {
      setActiveJobId(null);
    }
  }, [activeJobId, session]);

  // job завершился — перегружаем WBS
  useEffect(() => {
    if (!job) return;
    if (job.status === "done") {
      if (status === "gpr_processing") {
        trackActivity("GPR_BUILD_COMPLETED", {
          projectId,
          entityType: "ktp_estimate_session",
          entityId: sessionId,
          metadata: {
            job_id: job.id,
            estimate_batch_id: batchId,
          },
        });
      }
      setActiveJobId(null);
      void loadWbs();
    } else if (job.status === "failed") {
      setActiveJobId(null);
      setError(job.result?.error || "Задача завершилась с ошибкой");
    }
  }, [job, loadWbs]);

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

  const stage1Processing = status === "stage1_processing" || status === "stage1_pending";
  const gprProcessing = status === "gpr_processing";

  const restartStage1 = useCallback(async () => {
    if (!batchId) return;
    setBusy(true);
    try {
      const started = await ktpEstimate.startSession(projectId, batchId, true);
      trackActivity("KTP_ESTIMATE_SESSION_RESTARTED", {
        projectId,
        entityType: "ktp_estimate_session",
        entityId: started.session_id,
        metadata: { estimate_batch_id: batchId, previous_session_id: sessionId, job_id: started.job_id },
      });
      const suffix = started.job_id ? `?job=${started.job_id}` : "";
      router.replace(`/projects/${projectId}/ktp-estimate/${started.session_id}${suffix}`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [batchId, projectId, router, sessionId]);

  const openUploadStep = useCallback(() => {
    router.push(
      `/projects/${projectId}/upload${
        batchId ? `?batch=${batchId}&session=${sessionId}&fromKtp=1` : ""
      }`,
    );
  }, [batchId, projectId, router, sessionId]);

  // ── состояния загрузки ───────────────────────────────────────────────
  if (!wbs && activeJobId) {
    return (
      <ProcessingScreen
        title="ИИ анализирует смету"
        subtitle="Строим структуру работ — группируем позиции и проверяем полноту охвата"
        progress={job?.result?._progress ?? null}
      />
    );
  }
  if (stage1Processing) {
    return (
      <ProcessingScreen
        title="ИИ анализирует смету"
        subtitle="Строим структуру работ — группируем позиции и проверяем полноту охвата"
        progress={job?.result?._progress ?? null}
      />
    );
  }
  if (gprProcessing) {
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
        <div style={{ color: "var(--red)", fontSize: 13, maxWidth: 560, lineHeight: 1.5 }}>
          ❌ {session.error_message || "Ошибка обработки"}
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 16, flexWrap: "wrap", justifyContent: "center" }}>
          {status === "stage1_failed" && (
            <button
              type="button"
              style={buttonStyle("primary", busy)}
              disabled={busy || !batchId}
              onClick={() => void restartStage1()}
            >
              <ButtonContent loading={busy}>Запустить заново</ButtonContent>
            </button>
          )}
          <button type="button" style={btn()} onClick={openUploadStep}>
            К шагу «Новая смета»
          </button>
        </div>
      </Centered>
    );
  }

  const stepIndex =
    status === "stage1_review" ? 2 : status === "stage2_review" ? 3 : 4;

  return (
    <div style={{ height: "100%", overflow: "auto", padding: 24, maxWidth: 1080, margin: "0 auto", boxSizing: "border-box" }}>
      <Steps
        current={stepIndex}
        onNewEstimate={() =>
          router.push(
            `/projects/${projectId}/upload${batchId ? `?batch=${batchId}&session=${sessionId}&fromKtp=1` : ""}`,
          )
        }
      />

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
              trackActivity("KTP_STAGE1_APPROVED", {
                projectId,
                entityType: "ktp_estimate_session",
                entityId: sessionId,
                metadata: { estimate_batch_id: batchId },
              });
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
              trackActivity("GPR_BUILD_STARTED", {
                projectId,
                entityType: "ktp_estimate_session",
                entityId: sessionId,
                metadata: { estimate_batch_id: batchId },
              });
              const { job_id } = await ktpEstimate.buildGpr(projectId, sessionId);
              setActiveJobId(job_id);
              await loadWbs();
            } catch (e: any) {
              setError(e.message);
              setBusy(false);
            }
          }}
          onOpenGantt={() => {
            trackActivity("GPR_GANTT_OPENED", {
              projectId,
              entityType: "estimate_batch",
              entityId: batchId ?? null,
              metadata: {
                estimate_batch_id: batchId,
                ktp_estimate_session_id: sessionId,
              },
            });
            router.push(`/projects/${projectId}/gantt?batch=${batchId}`);
          }}
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

function Steps({ current, onNewEstimate }: { current: number; onNewEstimate: () => void }) {
  const labels = ["Новая смета", "Структура работ", "КТП", "ГПР"];
  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
      {labels.map((label, i) => {
        const n = i + 1;
        const active = n === current;
        const done = n < current;
        const stepStyle: React.CSSProperties = {
          flex: 1,
          padding: "9px 12px",
          borderRadius: 6,
          fontSize: 12,
          fontWeight: 600,
          textAlign: "center",
          border: "1px solid var(--border)",
          background: active ? "var(--blue-dark)" : done ? "rgba(34,197,94,.1)" : "var(--surface)",
          color: active ? "#fff" : done ? "#15803d" : "var(--muted)",
        };
        if (n === 1) {
          return (
            <button
              key={label}
              type="button"
              onClick={onNewEstimate}
              style={{
                ...stepStyle,
                cursor: "pointer",
                fontFamily: "var(--sans)",
              }}
            >
              {done ? "✓ " : `${n}. `}
              {label}
            </button>
          );
        }
        return (
          <div
            key={label}
            style={stepStyle}
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
  const pendingAiItems = wbs.groups.flatMap((g) =>
    g.items
      .filter((it) => it.origin === "ai_added" && it.review_status === "pending")
      .map((item) => ({ group: g, item })),
  );
  const pendingAi = pendingAiItems.length;
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
        <PendingAiReview
          items={pendingAiItems}
          busy={busy}
          run={run}
          projectId={projectId}
        />
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
          <span
            title={group.wt_name || group.wt_code}
            style={{ fontSize: 11, color: "var(--muted)", alignSelf: "center" }}
          >
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
        const pendingAi = it.origin === "ai_added" && it.review_status === "pending";
        return (
          <div
            key={it.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: pendingAi ? "7px 8px" : "7px 0",
              borderTop: "1px solid var(--border)",
              borderRadius: pendingAi ? 6 : 0,
              background: pendingAi ? "rgba(245,158,11,.08)" : "transparent",
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

function PendingAiReview({
  items,
  busy,
  run,
  projectId,
}: {
  items: Array<{ group: KtpWbsGroup; item: KtpWbsItem }>;
  busy: boolean;
  run: (fn: () => Promise<KtpWbs>) => Promise<void>;
  projectId: string;
}) {
  return (
    <div
      style={{
        ...feedbackStyle,
        marginBottom: 14,
        display: "grid",
        gap: 10,
      }}
    >
      <div style={{ fontWeight: 700 }}>Не проверено добавленных ИИ работ: {items.length}</div>
      {items.map(({ group, item }) => (
        <div
          key={item.id}
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) auto",
            gap: 10,
            alignItems: "center",
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ color: "var(--text)", fontWeight: 600 }}>{item.name}</div>
            <div style={{ color: "var(--muted)", marginTop: 2 }}>
              Группа: {group.title}
              {item.ai_reason ? ` · ${item.ai_reason}` : ""}
            </div>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              style={{ ...buttonStyle("ghost", busy), padding: "5px 9px", color: "#15803d" }}
              disabled={busy}
              onClick={() =>
                run(() => ktpEstimate.updateItem(projectId, item.id, { review_status: "accepted" }))
              }
            >
              Принять
            </button>
            <button
              style={{ ...buttonStyle("ghost", busy), padding: "5px 9px", color: "var(--red)" }}
              disabled={busy}
              onClick={() =>
                run(() => ktpEstimate.updateItem(projectId, item.id, { review_status: "rejected" }))
              }
            >
              Отклонить
            </button>
          </div>
        </div>
      ))}
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
  const groupsWithWorks = wbs.groups.filter((g) =>
    g.items.some((item) => item.review_status !== "rejected"),
  );
  const allReady = groupsWithWorks.every((g) => g.status === "card_generated");
  const [approving, setApproving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [generatingGroupIds, setGeneratingGroupIds] = useState<Set<string>>(new Set());
  const missingCards = groupsWithWorks.filter((g) => g.status !== "card_generated").length;
  const hasGeneratingCards = generatingGroupIds.size > 0;

  const markGenerating = useCallback((groupId: string, generating: boolean) => {
    setGeneratingGroupIds((prev) => {
      const next = new Set(prev);
      if (generating) {
        next.add(groupId);
      } else {
        next.delete(groupId);
      }
      return next;
    });
  }, []);

  return (
    <div>
      <Header
        title="КТП"
        hint="Создайте КТП для каждой группы работ. ИИ может задать уточняющие вопросы."
        right={
          <button
            style={buttonStyle("primary", busy || hasGeneratingCards)}
            disabled={busy || hasGeneratingCards}
            onClick={async () => {
              if (hasGeneratingCards) {
                setNotice(`Дождитесь завершения создания КТП. В работе: ${generatingGroupIds.size}.`);
                return;
              }
              if (!allReady) {
                setNotice(`Сначала создайте все КТП. Осталось: ${missingCards}.`);
                return;
              }
              setNotice(null);
              setApproving(true);
              setBusy(true);
              try {
                await ktpEstimate.approveStage2(projectId, sessionId);
                trackActivity("KTP_STAGE2_APPROVED", {
                  projectId,
                  entityType: "ktp_estimate_session",
                  entityId: sessionId,
                  metadata: {
                    estimate_batch_id: wbs.session.estimate_batch_id,
                    groups_count: groupsWithWorks.length,
                  },
                });
                await reload();
              } catch (e: any) {
                setError(e.message);
              } finally {
                setApproving(false);
                setBusy(false);
              }
            }}
          >
            <ButtonContent loading={approving}>Все карточки готовы → к ГПР</ButtonContent>
          </button>
        }
      />
      {notice && (
        <div
          role="alert"
          style={{
            ...feedbackStyle,
            marginTop: -4,
            marginBottom: 12,
          }}
        >
          {notice}
        </div>
      )}
      {groupsWithWorks.map((g) => (
        <Stage2Group
          key={g.id}
          group={g}
          projectId={projectId}
          busy={busy}
          setError={setError}
          reload={reload}
          onGeneratingChange={markGenerating}
        />
      ))}
    </div>
  );
}

function Stage2Group({
  group,
  projectId,
  busy,
  setError,
  reload,
  onGeneratingChange,
}: {
  group: KtpWbsGroup;
  projectId: string;
  busy: boolean;
  setError: (v: string | null) => void;
  reload: () => Promise<void>;
  onGeneratingChange: (groupId: string, generating: boolean) => void;
}) {
  const [questions, setQuestions] = useState<KtpQuestion[] | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [cardData, setCardData] = useState<KtpEstimateCard | null>(null);
  const [generating, setGenerating] = useState(false);
  const [validation, setValidation] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (group.status === "card_generated" || group.status === "card_questions") {
      void ktpEstimate.getCard(projectId, group.id).then((c) => {
        setCardData(c);
        if (c.status === "card_questions" && c.questions_json) setQuestions(c.questions_json);
      });
    }
  }, [projectId, group.id, group.status]);

  const generate = async (withAnswers: Record<string, string>) => {
    if (generating) return;
    setGenerating(true);
    onGeneratingChange(group.id, true);
    trackActivity("KTP_STAGE2_CARD_GENERATION_STARTED", {
      projectId,
      entityType: "ktp_wbs_group",
      entityId: group.id,
      metadata: {
        group_title: group.title,
        answers_count: Object.keys(withAnswers).length,
      },
    });
    try {
      const res = await ktpEstimate.generateCard(projectId, group.id, withAnswers);
      setValidation(null);
      if (res.sufficient) {
        setQuestions(null);
        setCardData(res.card);
        trackActivity("KTP_STAGE2_CARD_GENERATED", {
          projectId,
          entityType: "ktp_wbs_group",
          entityId: group.id,
          metadata: {
            group_title: group.title,
            card_status: res.card.status,
          },
        });
      } else {
        setQuestions(res.questions);
        trackActivity("KTP_STAGE2_CARD_QUESTIONS_REQUIRED", {
          projectId,
          entityType: "ktp_wbs_group",
          entityId: group.id,
          metadata: {
            group_title: group.title,
            questions_count: res.questions.length,
          },
        });
      }
      await reload();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setGenerating(false);
      onGeneratingChange(group.id, false);
    }
  };

  const requiredAnswersMissing = questions?.some((q) => !answers[q.key]?.trim()) ?? false;

  const statusLabel: Record<KtpWbsGroup["status"], string> = {
    draft: "Не создана",
    card_questions: "Нужны данные",
    card_generated: "Готова",
    card_failed: "Ошибка",
  };

  return (
    <div style={{ ...card, marginBottom: 12, padding: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 9,
            minWidth: 0,
            flex: 1,
            padding: 0,
            border: "none",
            background: "transparent",
            color: "var(--text)",
            cursor: "pointer",
            fontFamily: "var(--sans)",
            textAlign: "left",
          }}
        >
          <span
            style={{
              width: 22,
              height: 22,
              borderRadius: 5,
              border: "1px solid var(--border)",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--muted)",
              flexShrink: 0,
            }}
          >
            <Chevron open={expanded} />
          </span>
          <span style={{ fontSize: 14, fontWeight: 600, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
            {group.title}
          </span>
          <span style={{ fontSize: 11, color: "var(--muted)", whiteSpace: "nowrap" }}>
            {group.items.length} работ
          </span>
        </button>
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
          <button style={buttonStyle("ghost", busy || generating)} disabled={busy || generating} onClick={() => generate(answers)}>
            <ButtonContent loading={generating}>
              {group.status === "card_generated" ? "Пересоздать КТП" : "Создать КТП"}
            </ButtonContent>
          </button>
        </div>
      </div>

      {expanded && (
        <div
          style={{
            marginTop: 12,
            padding: "10px 12px",
            borderRadius: 6,
            border: "1px solid var(--border)",
            background: "rgba(148,163,184,.06)",
            display: "grid",
            gap: 7,
          }}
        >
          {group.items.length ? (
            group.items.map((item, index) => (
              <div
                key={item.id}
                style={{
                  display: "grid",
                  gridTemplateColumns: "34px minmax(0, 1fr) auto",
                  gap: 10,
                  alignItems: "start",
                  fontSize: 12,
                  color: "var(--text)",
                }}
              >
                <span style={{ color: "var(--muted)", fontFamily: "var(--mono)" }}>{index + 1}</span>
                <span style={{ minWidth: 0 }}>{item.name}</span>
                {(item.quantity != null || item.unit) && (
                  <span style={{ color: "var(--muted)", whiteSpace: "nowrap" }}>
                    {item.quantity ?? ""} {item.unit ?? ""}
                  </span>
                )}
              </div>
            ))
          ) : (
            <div style={{ fontSize: 12, color: "var(--muted)" }}>В группе пока нет работ.</div>
          )}
        </div>
      )}

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
                onChange={(e) => {
                  setValidation(null);
                  setAnswers((a) => ({ ...a, [q.key]: e.target.value }));
                }}
              />
            </div>
          ))}
          {validation && (
            <div role="alert" style={feedbackStyle}>
              {validation}
            </div>
          )}
          <button
            style={buttonStyle("primary", busy || generating)}
            disabled={busy || generating}
            onClick={() => {
              if (requiredAnswersMissing) {
                setValidation("Заполните ответы на вопросы, чтобы создать КТП.");
                return;
              }
              void generate(answers);
            }}
          >
            <ButtonContent loading={generating}>Ответить и создать КТП</ButtonContent>
          </button>
        </div>
      )}

      {cardData && cardData.status === "card_generated" && (
        <CardView
          card={cardData}
          busy={busy || generating}
          onSave={async (patch) => {
            try {
              setCardData(await ktpEstimate.updateCard(projectId, group.id, patch));
            } catch (e: any) {
              setError(e.message);
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
  onSave: (patch: { title?: string; goal?: string }) => Promise<void>;
}) {
  const [title, setTitle] = useState(card.title || "");
  const [goal, setGoal] = useState(card.goal || "");
  const [saving, setSaving] = useState(false);
  // sync локальный state при перегенерации/обновлении карточки
  useEffect(() => {
    setTitle(card.title || "");
    setGoal(card.goal || "");
  }, [card.id, card.title, card.goal]);
  const dirty = title !== (card.title || "") || goal !== (card.goal || "");

  return (
    <div style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
      <div style={{ display: "grid", gap: 8, marginBottom: 10 }}>
        <input
          style={{ ...inputStyle, width: "100%", fontWeight: 600 }}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <textarea
          style={{ ...inputStyle, width: "100%", minHeight: 50, resize: "vertical" }}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="Цель"
        />
      </div>
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
        <button
          style={buttonStyle("primary", busy)}
          disabled={busy}
          onClick={async () => {
            setSaving(true);
            try {
              await onSave({ title, goal });
            } finally {
              setSaving(false);
            }
          }}
        >
          <ButtonContent loading={saving}>Сохранить правки</ButtonContent>
        </button>
      )}
    </div>
  );
}

// ── ЭТАП 3 ───────────────────────────────────────────────────────────────────

const HOURS_PER_DAY = 8;

function isSubDay(it: KtpWbsItem): boolean {
  if (it.labor_hours == null) return false;
  const brigade = it.brigade_size ?? 1;
  return it.labor_hours / brigade < HOURS_PER_DAY;
}

function fmtDuration(it: KtpWbsItem): string | null {
  if (!it.duration_days && it.labor_hours == null) return null;
  if (isSubDay(it)) {
    const brigade = it.brigade_size ?? 1;
    const h = (it.labor_hours as number) / brigade;
    const hStr = Number.isInteger(h) ? String(h) : h.toFixed(1);
    return `${hStr} ч.${it.norm_kind === "fallback" ? " (нет оценки)" : ""}`;
  }
  if (!it.duration_days) return null;
  return `${it.duration_days} дн.${it.norm_kind === "fallback" ? " (нет оценки)" : ""}`;
}

function normTooltip(it: KtpWbsItem): string | undefined {
  if (!it.duration_days && it.labor_hours == null) return undefined;
  const qty = it.quantity != null ? `${it.quantity}${it.unit ? ` ${it.unit}` : ""}` : "?";
  const brigade = it.brigade_size ?? 1;
  const sub = isSubDay(it);

  if (it.norm_kind === "norm_time" && it.norm_value != null) {
    const labor = it.labor_hours != null ? `${it.labor_hours.toFixed(1)} чел-ч` : "?";
    const result = sub
      ? `${((it.labor_hours as number) / brigade).toFixed(1)} ч. на бригаду (${brigade} чел.)`
      : `${brigade} чел. → ${it.duration_days} дн.`;
    return `${qty} × ${it.norm_value} чел-ч/${it.norm_unit || "ед"} = ${labor}\n${result}`;
  }
  if (it.norm_kind === "vyrabotka" && it.norm_value != null) {
    const result = sub
      ? `${((it.labor_hours as number) / brigade).toFixed(1)} ч. на бригаду (${brigade} чел.)`
      : `= ${it.duration_days} дн.`;
    return `${qty} ÷ (${it.norm_value} ${it.norm_unit || "ед"}/чел-день × ${brigade} чел.) ${result}`;
  }
  if (it.norm_kind === "fallback") {
    return "Норму определить не удалось — поставлен 1 день по умолчанию";
  }
  return undefined;
}

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
  onBuild: () => Promise<void> | void;
  onOpenGantt: () => void;
}) {
  const missingQty = useMemo(
    () =>
      wbs.groups
        .flatMap((g) => g.items)
        .filter((it) => it.origin !== "from_estimate" && it.quantity == null),
    [wbs],
  );
  const [building, setBuilding] = useState(false);
  const qtyRefs = useRef<(HTMLInputElement | null)[]>([]);

  return (
    <div>
      <Header
        title="График производства работ"
        hint="Укажите объёмы для добавленных работ — ИИ подберёт нормы, система рассчитает длительности и зависимости."
        right={
          done ? (
            <button style={buttonStyle("primary")} onClick={onOpenGantt}>
              Открыть Гант →
            </button>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 5 }}>
              <button
                style={buttonStyle("primary", busy)}
                disabled={busy}
                onClick={async () => {
                  setBuilding(true);
                  try {
                    await onBuild();
                  } finally {
                    setBuilding(false);
                  }
                }}
              >
                <ButtonContent loading={building}>Построить ГПР</ButtonContent>
              </button>
              {building && (
                <span style={{ fontSize: 11, color: "var(--muted)" }}>
                  Идёт процесс оценки трудоёмкости…
                </span>
              )}
            </div>
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
          {missingQty.map((it, idx) => (
            <QtyRow
              key={it.id}
              item={it}
              projectId={projectId}
              inputRef={(el) => { qtyRefs.current[idx] = el; }}
              onNext={idx < missingQty.length - 1 ? () => qtyRefs.current[idx + 1]?.focus() : undefined}
            />
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
                gap: 8,
              }}
            >
              <span style={{ flex: 1 }}>{it.name}</span>
              <span style={{ whiteSpace: "nowrap", display: "flex", gap: 8, alignItems: "center" }}>
                {fmtQty(it) && (
                  <span style={{ color: "var(--text)", fontFamily: "var(--mono)", fontSize: 11 }}>
                    {fmtQty(it)}
                  </span>
                )}
                <span
                  title={normTooltip(it)}
                  style={normTooltip(it) ? { cursor: "help", borderBottom: "1px dotted var(--border2)" } : undefined}
                >
                  {fmtDuration(it) ?? (fmtQty(it) ? "" : "—")}
                </span>
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function parseQty(raw: string): { quantity: number | null; unit: string | null } {
  // "100 м3" → 100, "м3"; "12,5 м²" → 12.5, "м²"; "м3" → null, "м3"
  const m = raw.trim().match(/^([\d]+(?:[.,]\d+)?)\s*(.*)$/);
  if (m) {
    const n = Number(m[1].replace(",", "."));
    return {
      quantity: Number.isFinite(n) ? n : null,
      unit: m[2].trim() || null,
    };
  }
  return { quantity: null, unit: raw.trim() || null };
}

function fmtQty(item: KtpWbsItem): string {
  const q = item.quantity ?? "";
  const u = item.unit ?? "";
  return q !== "" || u !== "" ? `${q}${q !== "" && u ? " " : ""}${u}`.trim() : "";
}

function QtyRow({
  item,
  projectId,
  inputRef,
  onNext,
}: {
  item: KtpWbsItem;
  projectId: string;
  inputRef?: (el: HTMLInputElement | null) => void;
  onNext?: () => void;
}) {
  const [value, setValue] = useState(fmtQty(item));
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const lastSaved = useRef(fmtQty(item));

  const save = async () => {
    const trimmed = value.trim();
    if (trimmed === lastSaved.current || saving) return;
    const { quantity, unit } = parseQty(trimmed);
    setSaving(true);
    try {
      await ktpEstimate.updateItem(projectId, item.id, { quantity, unit });
      lastSaved.current = trimmed;
      setConfirmed(trimmed || null);
    } catch {
      // не блокируем UI — пользователь может попробовать ещё раз
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 0" }}>
      <span style={{ flex: 1, fontSize: 12 }}>{item.name}</span>
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => { setValue(e.target.value); setConfirmed(null); }}
        onBlur={() => void save()}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            // фокус на следующую строку → браузер сам вызовет blur → save
            if (onNext) onNext();
            else (e.target as HTMLInputElement).blur();
          }
        }}
        placeholder="например: 100 м3"
        disabled={saving}
        style={{ ...inputStyle, maxWidth: 180 }}
      />
      <span style={{ fontSize: 11, minWidth: 60, textAlign: "right" }}>
        {saving
          ? <span style={{ color: "var(--muted)" }}>…</span>
          : confirmed
            ? <span style={{ color: "#15803d", fontWeight: 600 }}>{confirmed}</span>
            : null}
      </span>
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

const feedbackStyle: React.CSSProperties = {
  padding: "9px 11px",
  borderRadius: 6,
  border: "1px solid rgba(245,158,11,.3)",
  background: "rgba(245,158,11,.08)",
  color: "#92400e",
  fontSize: 12,
  lineHeight: 1.4,
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
