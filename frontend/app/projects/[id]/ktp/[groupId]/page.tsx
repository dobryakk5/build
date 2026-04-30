"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { ktp as ktpApi } from "@/lib/api";
import { fmtMoney } from "@/lib/dateUtils";
import type {
  KtpCard,
  KtpGenerateResponse,
  KtpGroup,
  KtpQuestion,
  KtpStep,
} from "@/lib/types";

function fmtPrice(value: number | null): string {
  if (value == null) return "—";
  return `${fmtMoney(value)} ₽`;
}

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
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: 36 }} />
            <col style={{ width: "22%" }} />
            <col />
            <col style={{ width: "26%" }} />
          </colgroup>
          <thead>
            <tr style={{ background: "var(--surface)" }}>
              {["№", "Этап процесса", "Содержание работ и детали", "Точки контроля"].map((header) => (
                <th
                  key={header}
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
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {card.steps.map((step: KtpStep) => (
              <tr key={step.no} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "9px 10px", color: "var(--muted)", fontFamily: "var(--mono)", fontSize: 11, verticalAlign: "top" }}>
                  {step.no}
                </td>
                <td style={{ padding: "9px 10px", fontWeight: 500, verticalAlign: "top", lineHeight: 1.45 }}>
                  {step.stage}
                </td>
                <td style={{ padding: "9px 10px", verticalAlign: "top", lineHeight: 1.55, color: "var(--text)" }}>
                  {step.work_details}
                </td>
                <td style={{ padding: "9px 10px", verticalAlign: "top", lineHeight: 1.5, color: "var(--muted)", fontSize: 11 }}>
                  {step.control_points}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {card.recommendations.length > 0 && (
        <div style={{ borderLeft: "3px solid var(--blue)", paddingLeft: 12 }}>
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
          {card.recommendations.map((recommendation, index) => (
            <div key={index} style={{ fontSize: 12, lineHeight: 1.55, marginBottom: 6 }}>
              <span style={{ fontWeight: 600, fontFamily: "var(--mono)", color: "var(--muted)", marginRight: 6 }}>
                {index + 1}.
              </span>
              {recommendation}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function QuestionsForm({
  questions,
  loading,
  onSubmit,
}: {
  questions: KtpQuestion[];
  loading: boolean;
  onSubmit: (answers: Record<string, string>) => void;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});

  function updateAnswer(key: string, value: string) {
    setAnswers((prev) => ({ ...prev, [key]: value }));
  }

  const allAnswered = questions.every((question) => answers[question.key]?.trim());

  return (
    <div>
      <div style={{ fontSize: 13, color: "var(--muted)", marginBottom: 16, lineHeight: 1.5 }}>
        Для точного КТП нужна дополнительная техническая информация. Ответьте на вопросы ниже.
      </div>

      {questions.map((question) => (
        <div key={question.key} style={{ marginBottom: 16 }}>
          <label style={{ display: "block", fontSize: 13, fontWeight: 500, marginBottom: 6 }}>
            {question.label}
          </label>
          {question.hint && (
            <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>
              {question.hint}
            </div>
          )}
          {question.type === "textarea" ? (
            <textarea
              rows={3}
              value={answers[question.key] ?? ""}
              onChange={(event) => updateAnswer(question.key, event.target.value)}
              placeholder={question.hint ?? "Введите ответ..."}
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
          ) : question.type === "select" && question.options ? (
            <select
              value={answers[question.key] ?? ""}
              onChange={(event) => updateAnswer(question.key, event.target.value)}
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
              {question.options.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          ) : (
            <input
              type={question.type === "number" ? "number" : "text"}
              value={answers[question.key] ?? ""}
              onChange={(event) => updateAnswer(question.key, event.target.value)}
              placeholder={question.hint ?? "Введите ответ..."}
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

type GroupPageState =
  | { phase: "loading" }
  | { phase: "idle" }
  | { phase: "generating" }
  | { phase: "questions"; questions: KtpQuestion[] }
  | { phase: "done"; card: KtpCard };

export default function KtpGroupPage() {
  const { id: projectId, groupId } = useParams<{ id: string; groupId: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const batchId = searchParams.get("batch");
  const autoStart = searchParams.get("autoStart") === "1";

  const [groups, setGroups] = useState<KtpGroup[]>([]);
  const [group, setGroup] = useState<KtpGroup | null>(null);
  const [state, setState] = useState<GroupPageState>({ phase: "loading" });
  const [error, setError] = useState<string | null>(null);

  async function generateForGroup(targetGroup: KtpGroup, answers: Record<string, string> = {}) {
    setState({ phase: "generating" });
    setError(null);

    try {
      const response: KtpGenerateResponse = await ktpApi.generate(projectId, targetGroup.id, answers);
      const groupsData = batchId ? await ktpApi.groups(projectId, batchId) : groups;
      setGroups(groupsData);
      const currentGroup = groupsData.find((item) => item.id === targetGroup.id) ?? targetGroup;
      setGroup(currentGroup);

      if (!response.sufficient) {
        setState({ phase: "questions", questions: response.questions });
        return;
      }

      setState({ phase: "done", card: response.ktp });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Ошибка генерации КТП");
      setState({ phase: "idle" });
    }
  }

  useEffect(() => {
    if (!batchId) return;
    const currentBatchId = batchId;

    let cancelled = false;

    async function load() {
      setError(null);
      setState({ phase: "loading" });

      try {
        const [groupsData, detail] = await Promise.all([
          ktpApi.buildGroups(projectId, currentBatchId),
          ktpApi.group(projectId, groupId),
        ]);

        if (cancelled) return;

        setGroups(groupsData);
        const currentGroup = groupsData.find((item) => item.id === groupId) ?? detail.group;
        setGroup(currentGroup);

        if (detail.card?.status === "generated") {
          setState({ phase: "done", card: detail.card });
          return;
        }

        if (detail.card?.status === "questions_required" && detail.card.questions_json?.length) {
          setState({ phase: "questions", questions: detail.card.questions_json });
          return;
        }

        if (autoStart) {
          await generateForGroup(currentGroup);
          return;
        }

        setState({ phase: "idle" });
      } catch (nextError) {
        if (cancelled) return;
        setError(nextError instanceof Error ? nextError.message : "Ошибка загрузки КТП");
        setState({ phase: "idle" });
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [projectId, groupId, batchId, autoStart]);

  const currentIndex = groups.findIndex((item) => item.id === groupId);
  const nextGroup = useMemo(() => {
    if (currentIndex < 0) return null;
    const tail = groups.slice(currentIndex + 1);
    return (
      tail.find((item) => item.status === "new") ??
      tail.find((item) => item.status === "questions_required") ??
      tail.find((item) => item.status === "failed") ??
      null
    );
  }, [groups, currentIndex]);

  async function generate(answers: Record<string, string> = {}) {
    if (!group) return;
    await generateForGroup(group, answers);
  }

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
        Откройте КТП из загруженной сметы
      </div>
    );
  }

  if (state.phase === "loading" && !group) {
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
        Загружаем группу работ...
      </div>
    );
  }

  if (error && !group) {
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
          ❌ {error}
        </div>
      </div>
    );
  }

  return (
    <div style={{ height: "100%", overflow: "auto", padding: 24, maxWidth: 1080, margin: "0 auto", boxSizing: "border-box" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap", marginBottom: 18 }}>
        <div>
          <Link
            href={`/projects/${projectId}/ktp?batch=${batchId}`}
            style={{ color: "var(--muted)", textDecoration: "none", fontSize: 12, display: "inline-block", marginBottom: 8 }}
          >
            ← Назад к группам
          </Link>
          <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 6 }}>{group?.title}</div>
        </div>

        {nextGroup && (
          <button
            onClick={() =>
              router.push(
                `/projects/${projectId}/ktp/${nextGroup.id}?batch=${batchId}${nextGroup.status === "generated" ? "" : "&autoStart=1"}`,
              )
            }
            style={{
              padding: "9px 18px",
              background: "var(--surface)",
              color: "var(--text)",
              border: "1px solid var(--border2)",
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            Следующая группа
          </button>
        )}
      </div>

      {error && (
        <div
          style={{
            marginBottom: 16,
            padding: "14px 16px",
            background: "rgba(239,68,68,.06)",
            border: "1px solid rgba(239,68,68,.2)",
            borderRadius: 6,
            color: "var(--red)",
            fontSize: 13,
          }}
        >
          ❌ {error}
        </div>
      )}

      <div style={{ padding: 20, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8 }}>
        {state.phase === "idle" && (
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <div style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.5 }}>
              На этом экране КТП создаётся для одной группы работ. После успешной генерации карточка сразу сохраняется в базе данных.
            </div>
            <button
              onClick={() => generate()}
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

        {state.phase === "generating" && (
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
            ⏳ Генерируем КТП и сохраняем результат...
          </div>
        )}

        {state.phase === "questions" && (
          <div
            style={{
              padding: 20,
              background: "rgba(245,158,11,.06)",
              border: "1px solid rgba(245,158,11,.3)",
              borderRadius: 8,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 16, color: "#92400e" }}>
              ✏ Нужна дополнительная информация
            </div>
            <QuestionsForm
              questions={state.questions}
              loading={false}
              onSubmit={(answers) => generate(answers)}
            />
          </div>
        )}

        {state.phase === "done" && (
          <>
            <KtpTable card={state.card} />
          </>
        )}
      </div>
    </div>
  );
}
