"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";

import { ktp as ktpApi } from "@/lib/api";
import { fmtMoney } from "@/lib/dateUtils";
import type { KtpCard, KtpGenerateResponse, KtpGroup, KtpQuestion, KtpStep } from "@/lib/types";

// ─── helpers ─────────────────────────────────────────────────────────────────

function fmtPrice(v: number | null): string {
  if (v == null) return "—";
  return `${fmtMoney(v)} ₽`;
}

const STATUS_LABEL: Record<KtpGroup["status"], string> = {
  new: "Не создана",
  questions_required: "Нужны данные",
  generated: "Готова",
  failed: "Ошибка",
};

const STATUS_COLOR: Record<KtpGroup["status"], string> = {
  new: "var(--muted)",
  questions_required: "#b45309",
  generated: "#15803d",
  failed: "var(--red)",
};

// ─── sub-components ──────────────────────────────────────────────────────────

function KtpTable({ card }: { card: KtpCard }) {
  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{card.title}</div>
        {card.goal && (
          <div style={{ fontSize: 12, color: "var(--muted)" }}>
            <b style={{ color: "var(--text)" }}>Цель:</b> {card.goal}
          </div>
        )}
      </div>

      <div style={{ overflowX: "auto", marginBottom: 16 }}>
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 12,
            tableLayout: "fixed",
          }}
        >
          <colgroup>
            <col style={{ width: 36 }} />
            <col style={{ width: "22%" }} />
            <col />
            <col style={{ width: "26%" }} />
          </colgroup>
          <thead>
            <tr style={{ background: "var(--surface)" }}>
              {["№", "Этап процесса", "Содержание работ и детали", "Точки контроля"].map(
                (h) => (
                  <th
                    key={h}
                    style={{
                      padding: "8px 10px",
                      textAlign: "left",
                      fontWeight: 600,
                      color: "var(--muted)",
                      borderBottom: "1px solid var(--border)",
                      fontSize: 11,
                      textTransform: "uppercase",
                      letterSpacing: ".05em",
                    }}
                  >
                    {h}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {card.steps.map((step: KtpStep) => (
              <tr
                key={step.no}
                style={{ borderBottom: "1px solid var(--border)" }}
              >
                <td
                  style={{
                    padding: "9px 10px",
                    color: "var(--muted)",
                    fontFamily: "var(--mono)",
                    fontSize: 11,
                    verticalAlign: "top",
                  }}
                >
                  {step.no}
                </td>
                <td
                  style={{
                    padding: "9px 10px",
                    fontWeight: 500,
                    verticalAlign: "top",
                    lineHeight: 1.45,
                  }}
                >
                  {step.stage}
                </td>
                <td
                  style={{
                    padding: "9px 10px",
                    verticalAlign: "top",
                    lineHeight: 1.55,
                    color: "var(--text)",
                  }}
                >
                  {step.work_details}
                </td>
                <td
                  style={{
                    padding: "9px 10px",
                    verticalAlign: "top",
                    lineHeight: 1.5,
                    color: "var(--muted)",
                    fontSize: 11,
                  }}
                >
                  {step.control_points}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {card.recommendations.length > 0 && (
        <div
          style={{
            borderLeft: "3px solid var(--blue)",
            paddingLeft: 12,
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: "var(--muted)",
              textTransform: "uppercase",
              letterSpacing: ".06em",
              marginBottom: 8,
            }}
          >
            Критические рекомендации
          </div>
          {card.recommendations.map((rec, i) => (
            <div
              key={i}
              style={{ fontSize: 12, lineHeight: 1.55, marginBottom: 6 }}
            >
              <span
                style={{
                  fontWeight: 600,
                  fontFamily: "var(--mono)",
                  color: "var(--muted)",
                  marginRight: 6,
                }}
              >
                {i + 1}.
              </span>
              {rec}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function QuestionsForm({
  questions,
  onSubmit,
  loading,
}: {
  questions: KtpQuestion[];
  onSubmit: (answers: Record<string, string>) => void;
  loading: boolean;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});

  function set(key: string, val: string) {
    setAnswers((prev) => ({ ...prev, [key]: val }));
  }

  const allAnswered = questions.every((q) => answers[q.key]?.trim());

  return (
    <div>
      <div
        style={{
          fontSize: 13,
          color: "var(--muted)",
          marginBottom: 16,
          lineHeight: 1.5,
        }}
      >
        Для точного КТП нужна дополнительная техническая информация. Ответьте
        на вопросы ниже.
      </div>

      {questions.map((q) => (
        <div key={q.key} style={{ marginBottom: 16 }}>
          <label
            style={{
              display: "block",
              fontSize: 13,
              fontWeight: 500,
              marginBottom: 6,
            }}
          >
            {q.label}
          </label>
          {q.hint && (
            <div
              style={{
                fontSize: 11,
                color: "var(--muted)",
                marginBottom: 6,
              }}
            >
              {q.hint}
            </div>
          )}
          {q.type === "textarea" ? (
            <textarea
              rows={3}
              value={answers[q.key] ?? ""}
              onChange={(e) => set(q.key, e.target.value)}
              placeholder={q.hint ?? "Введите ответ..."}
              style={{
                width: "100%",
                padding: "8px 10px",
                border: "1px solid var(--border2)",
                borderRadius: 5,
                fontSize: 13,
                background: "var(--surface)",
                color: "var(--text)",
                resize: "vertical",
                outline: "none",
                boxSizing: "border-box",
              }}
            />
          ) : q.type === "select" && q.options ? (
            <select
              value={answers[q.key] ?? ""}
              onChange={(e) => set(q.key, e.target.value)}
              style={{
                width: "100%",
                padding: "8px 10px",
                border: "1px solid var(--border2)",
                borderRadius: 5,
                fontSize: 13,
                background: "var(--surface)",
                color: "var(--text)",
                outline: "none",
              }}
            >
              <option value="">Выберите...</option>
              {q.options.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          ) : (
            <input
              type={q.type === "number" ? "number" : "text"}
              value={answers[q.key] ?? ""}
              onChange={(e) => set(q.key, e.target.value)}
              placeholder={q.hint ?? "Введите ответ..."}
              style={{
                width: "100%",
                padding: "8px 10px",
                border: "1px solid var(--border2)",
                borderRadius: 5,
                fontSize: 13,
                background: "var(--surface)",
                color: "var(--text)",
                outline: "none",
                boxSizing: "border-box",
              }}
            />
          )}
        </div>
      ))}

      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
        <button
          onClick={() => onSubmit(answers)}
          disabled={loading || !allAnswered}
          style={{
            padding: "9px 20px",
            background: "var(--blue-dark)",
            color: "#fff",
            border: "none",
            borderRadius: 5,
            fontSize: 13,
            fontWeight: 600,
            cursor: loading || !allAnswered ? "default" : "pointer",
            opacity: loading || !allAnswered ? 0.55 : 1,
          }}
        >
          {loading ? "Генерируем КТП..." : "Создать КТП →"}
        </button>
      </div>
    </div>
  );
}

// ─── main page ────────────────────────────────────────────────────────────────

type GroupPanelState =
  | { phase: "idle" }
  | { phase: "generating" }
  | { phase: "questions"; questions: KtpQuestion[] }
  | { phase: "done"; card: KtpCard };

export default function KtpPage() {
  const { id: projectId } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const batchId = searchParams.get("batch");

  const [groups, setGroups] = useState<KtpGroup[]>([]);
  const [loadingGroups, setLoadingGroups] = useState(false);
  const [groupsError, setGroupsError] = useState<string | null>(null);

  // Выбранная группа для правой панели
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null);
  const [panelState, setPanelState] = useState<GroupPanelState>({ phase: "idle" });

  // ── load / build groups ────────────────────────────────────────────────────

  useEffect(() => {
    if (!batchId) return;
    setLoadingGroups(true);
    setGroupsError(null);

    ktpApi
      .buildGroups(projectId, batchId)
      .then((data) => {
        setGroups(data);
        // Автоматически открываем первую группу без КТП
        const first = data.find((g) => g.status !== "generated") ?? data[0];
        if (first) openGroup(first, data);
      })
      .catch((e: Error) => setGroupsError(e.message))
      .finally(() => setLoadingGroups(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, batchId]);

  // ── open group ────────────────────────────────────────────────────────────

  function openGroup(group: KtpGroup, currentGroups = groups) {
    setActiveGroupId(group.id);

    if (group.status === "generated" && group.ktp_card_id) {
      // КТП уже есть — загружаем карточку
      setPanelState({ phase: "generating" });
      ktpApi
        .card(projectId, group.id)
        .then((card) => setPanelState({ phase: "done", card }))
        .catch(() => setPanelState({ phase: "idle" }));
      return;
    }

    if (group.status === "questions_required") {
      // Уже спрашивали — загружаем вопросы из group detail
      setPanelState({ phase: "generating" });
      ktpApi
        .group(projectId, group.id)
        .then(({ card }) => {
          if (card?.status === "questions_required" && card.questions_json) {
            setPanelState({ phase: "questions", questions: card.questions_json as KtpQuestion[] });
          } else if (card?.status === "generated") {
            setPanelState({ phase: "done", card });
          } else {
            startGenerate(group.id);
          }
        })
        .catch(() => startGenerate(group.id));
      return;
    }

    setPanelState({ phase: "idle" });
  }

  // ── generate ──────────────────────────────────────────────────────────────

  function startGenerate(groupId: string, answers: Record<string, string> = {}) {
    setPanelState({ phase: "generating" });

    ktpApi
      .generate(projectId, groupId, answers)
      .then((res: KtpGenerateResponse) => {
        if (!res.sufficient) {
          setPanelState({ phase: "questions", questions: res.questions });
          // Обновляем статус группы в таблице
          setGroups((prev) =>
            prev.map((g) =>
              g.id === groupId ? { ...g, status: "questions_required" } : g
            )
          );
        } else {
          setPanelState({ phase: "done", card: res.ktp });
          setGroups((prev) =>
            prev.map((g) =>
              g.id === groupId
                ? { ...g, status: "generated", ktp_card_id: res.ktp_card_id }
                : g
            )
          );
        }
      })
      .catch((e: Error) => {
        setPanelState({ phase: "idle" });
        setGroups((prev) =>
          prev.map((g) => (g.id === groupId ? { ...g, status: "failed" } : g))
        );
        alert(`Ошибка генерации КТП: ${e.message}`);
      });
  }

  // ── render ────────────────────────────────────────────────────────────────

  if (!batchId) {
    return (
      <div
        style={{
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--muted)",
          fontSize: 13,
        }}
      >
        Откройте страницу через кнопку «Создать КТП» после загрузки сметы
      </div>
    );
  }

  if (loadingGroups) {
    return (
      <div
        style={{
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--muted)",
          fontSize: 13,
        }}
      >
        Анализируем смету и выделяем группы работ...
      </div>
    );
  }

  if (groupsError) {
    return (
      <div style={{ padding: 24 }}>
        <div
          style={{
            padding: "14px 16px",
            background: "rgba(239,68,68,.06)",
            border: "1px solid rgba(239,68,68,.2)",
            borderRadius: 6,
            color: "var(--red)",
            fontSize: 13,
          }}
        >
          ❌ {groupsError}
        </div>
      </div>
    );
  }

  const activeGroup = groups.find((g) => g.id === activeGroupId) ?? null;

  return (
    <div style={{ height: "100%", display: "flex", overflow: "hidden" }}>
      {/* ── Left: groups table ── */}
      <div
        style={{
          width: 420,
          flexShrink: 0,
          borderRight: "1px solid var(--border)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            padding: "16px 20px 12px",
            borderBottom: "1px solid var(--border)",
            flexShrink: 0,
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 2 }}>
            Группы работ
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)" }}>
            {groups.length} групп
            {groups.filter((g) => g.status === "generated").length > 0 &&
              ` · ${groups.filter((g) => g.status === "generated").length} КТП готово`}
          </div>
        </div>

        <div style={{ flex: 1, overflow: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ background: "var(--surface)" }}>
                <th
                  style={{
                    padding: "8px 20px",
                    textAlign: "left",
                    fontSize: 10,
                    fontWeight: 600,
                    color: "var(--muted)",
                    textTransform: "uppercase",
                    letterSpacing: ".06em",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  Группа работ
                </th>
                <th
                  style={{
                    padding: "8px 8px",
                    textAlign: "right",
                    fontSize: 10,
                    fontWeight: 600,
                    color: "var(--muted)",
                    textTransform: "uppercase",
                    letterSpacing: ".06em",
                    borderBottom: "1px solid var(--border)",
                    whiteSpace: "nowrap",
                  }}
                >
                  Поз.
                </th>
                <th
                  style={{
                    padding: "8px 20px 8px 8px",
                    textAlign: "right",
                    fontSize: 10,
                    fontWeight: 600,
                    color: "var(--muted)",
                    textTransform: "uppercase",
                    letterSpacing: ".06em",
                    borderBottom: "1px solid var(--border)",
                    whiteSpace: "nowrap",
                  }}
                >
                  КТП
                </th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => {
                const isActive = group.id === activeGroupId;
                return (
                  <tr
                    key={group.id}
                    onClick={() => openGroup(group)}
                    style={{
                      cursor: "pointer",
                      background: isActive ? "rgba(59,130,246,.06)" : "transparent",
                      borderBottom: "1px solid var(--border)",
                      borderLeft: isActive
                        ? "3px solid var(--blue)"
                        : "3px solid transparent",
                      transition: "background .1s",
                    }}
                  >
                    <td style={{ padding: "10px 20px" }}>
                      <div
                        style={{
                          fontWeight: isActive ? 600 : 400,
                          marginBottom: 2,
                          lineHeight: 1.35,
                        }}
                      >
                        {group.title}
                      </div>
                      <div style={{ fontSize: 10, color: "var(--muted)", fontFamily: "var(--mono)" }}>
                        {group.row_count} позиций · {fmtPrice(group.total_price)}
                      </div>
                    </td>
                    <td
                      style={{
                        padding: "10px 8px",
                        textAlign: "right",
                        color: "var(--muted)",
                        fontFamily: "var(--mono)",
                        fontSize: 11,
                        verticalAlign: "middle",
                      }}
                    >
                      {group.row_count}
                    </td>
                    <td style={{ padding: "10px 20px 10px 8px", textAlign: "right", verticalAlign: "middle" }}>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 500,
                          color: STATUS_COLOR[group.status],
                        }}
                      >
                        {STATUS_LABEL[group.status]}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Кнопка Далее — активна когда есть группа без КТП */}
        {groups.length > 0 && (
          <div
            style={{
              padding: "12px 20px",
              borderTop: "1px solid var(--border)",
              display: "flex",
              justifyContent: "flex-end",
              flexShrink: 0,
            }}
          >
            <button
              onClick={() => {
                const next =
                  groups.find((g) => g.status === "new") ??
                  groups.find((g) => g.status === "questions_required") ??
                  groups.find((g) => g.status === "failed");
                if (next) openGroup(next);
              }}
              disabled={groups.every((g) => g.status === "generated")}
              style={{
                padding: "8px 20px",
                background: "var(--blue-dark)",
                color: "#fff",
                border: "none",
                borderRadius: 5,
                fontSize: 13,
                fontWeight: 600,
                cursor: groups.every((g) => g.status === "generated")
                  ? "default"
                  : "pointer",
                opacity: groups.every((g) => g.status === "generated") ? 0.4 : 1,
              }}
            >
              Далее →
            </button>
          </div>
        )}
      </div>

      {/* ── Right: panel ── */}
      <div
        style={{
          flex: 1,
          overflow: "auto",
          padding: 24,
        }}
      >
        {!activeGroup && (
          <div
            style={{
              height: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--muted)",
              fontSize: 13,
            }}
          >
            Выберите группу работ слева
          </div>
        )}

        {activeGroup && (
          <>
            {/* Header */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>
                {activeGroup.title}
              </div>
              <div
                style={{
                  fontSize: 12,
                  color: "var(--muted)",
                  display: "flex",
                  gap: 16,
                  flexWrap: "wrap",
                }}
              >
                <span>{activeGroup.row_count} позиций сметы</span>
                {activeGroup.total_price != null && (
                  <span>Сумма: <b style={{ color: "var(--text)", fontFamily: "var(--mono)" }}>{fmtPrice(activeGroup.total_price)}</b></span>
                )}
              </div>
            </div>

            {/* Panel content */}
            {panelState.phase === "idle" && (
              <div style={{ display: "flex", justifyContent: "flex-start" }}>
                <button
                  onClick={() => startGenerate(activeGroup.id)}
                  style={{
                    padding: "9px 22px",
                    background: "var(--blue-dark)",
                    color: "#fff",
                    border: "none",
                    borderRadius: 5,
                    fontSize: 13,
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  Создать КТП
                </button>
              </div>
            )}

            {panelState.phase === "generating" && (
              <div
                style={{
                  padding: "14px 16px",
                  background: "rgba(59,130,246,.06)",
                  border: "1px solid rgba(59,130,246,.2)",
                  borderRadius: 6,
                  fontSize: 13,
                  color: "var(--blue-dark)",
                  fontWeight: 500,
                }}
              >
                ⏳ Генерируем КТП...
              </div>
            )}

            {panelState.phase === "questions" && (
              <div
                style={{
                  padding: 20,
                  background: "rgba(245,158,11,.06)",
                  border: "1px solid rgba(245,158,11,.3)",
                  borderRadius: 8,
                }}
              >
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 600,
                    marginBottom: 16,
                    color: "#92400e",
                  }}
                >
                  ✏ Нужна дополнительная информация
                </div>
                <QuestionsForm
                  questions={panelState.questions}
                  loading={false}
                  onSubmit={(answers) => startGenerate(activeGroup.id, answers)}
                />
              </div>
            )}

            {panelState.phase === "done" && (
              <div
                style={{
                  padding: 20,
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                }}
              >
                <KtpTable card={panelState.card} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
