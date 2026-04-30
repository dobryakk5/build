"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { estimates, ktp as ktpApi } from "@/lib/api";
import { fmtMoney } from "@/lib/dateUtils";
import type { EstimateBatch, KtpGroup } from "@/lib/types";

function fmtPrice(value: number | null): string {
  if (value == null) return "—";
  return `${fmtMoney(value)} ₽`;
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

export default function KtpGroupsPage() {
  const { id: projectId } = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const batchId = searchParams.get("batch");

  const [groups, setGroups] = useState<KtpGroup[]>([]);
  const [resolvedBatchId, setResolvedBatchId] = useState<string | null>(batchId);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasBatches, setHasBatches] = useState(true);

  useEffect(() => {
    setResolvedBatchId(batchId);
  }, [batchId]);

  useEffect(() => {
    if (batchId) return;

    setLoading(true);
    setError(null);

    estimates
      .batches(projectId)
      .then((batches) => {
        const latestBatch = [...batches].sort(
          (a: EstimateBatch, b: EstimateBatch) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        )[0];

        if (!latestBatch) {
          setHasBatches(false);
          return;
        }

        setResolvedBatchId(latestBatch.id);
        router.replace(`/projects/${projectId}/ktp?batch=${latestBatch.id}`);
      })
      .catch((nextError: Error) => setError(nextError.message))
      .finally(() => setLoading(false));
  }, [projectId, router, batchId]);

  useEffect(() => {
    if (!resolvedBatchId) return;

    setLoading(true);
    setError(null);
    setHasBatches(true);

    ktpApi
      .buildGroups(projectId, resolvedBatchId)
      .then(setGroups)
      .catch((nextError: Error) => setError(nextError.message))
      .finally(() => setLoading(false));
  }, [projectId, resolvedBatchId]);

  const nextGroup = useMemo(
    () =>
      groups.find((group) => group.status === "new") ??
      groups.find((group) => group.status === "questions_required") ??
      groups.find((group) => group.status === "failed") ??
      groups[0],
    [groups],
  );

  if (!resolvedBatchId && !loading && !hasBatches) {
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
        Для этого объекта ещё нет загруженных смет
      </div>
    );
  }

  if (loading) {
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
        {!resolvedBatchId ? "Ищем последний блок сметы..." : "Анализируем смету и выделяем группы работ..."}
      </div>
    );
  }

  if (error) {
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
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 20,
          marginBottom: 20,
          flexWrap: "wrap",
        }}
      >
        <div>
          <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 6 }}>Группы работ для КТП</div>
          <div style={{ fontSize: 13, color: "var(--muted)", maxWidth: 720, lineHeight: 1.5 }}>
            Сначала проверьте, как смета разбилась на группы. На следующем экране КТП создаётся по одной группе работ, начиная с первой незавершённой.
          </div>
        </div>

        {nextGroup && (
          <Link
            href={`/projects/${projectId}/ktp/${nextGroup.id}?batch=${resolvedBatchId}${nextGroup.status === "generated" ? "" : "&autoStart=1"}`}
            style={{
              padding: "10px 18px",
              background: "var(--blue-dark)",
              color: "#fff",
              textDecoration: "none",
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 600,
              whiteSpace: "nowrap",
            }}
          >
            {nextGroup.status === "generated" ? "Открыть КТП →" : "Перейти к первой группе →"}
          </Link>
        )}
      </div>

      <div
        style={{
          marginBottom: 18,
          padding: "14px 16px",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: 8,
          display: "flex",
          gap: 18,
          flexWrap: "wrap",
          fontSize: 12,
          color: "var(--muted)",
        }}
      >
        <span>Групп: <b style={{ color: "var(--text)", fontFamily: "var(--mono)" }}>{groups.length}</b></span>
        <span>Готово КТП: <b style={{ color: "var(--text)", fontFamily: "var(--mono)" }}>{groups.filter((group) => group.status === "generated").length}</b></span>
        <span>Нужны данные: <b style={{ color: "var(--text)", fontFamily: "var(--mono)" }}>{groups.filter((group) => group.status === "questions_required").length}</b></span>
      </div>

      <div
        style={{
          border: "1px solid var(--border)",
          borderRadius: 8,
          overflow: "hidden",
          background: "var(--surface)",
        }}
      >
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "rgba(148,163,184,.08)" }}>
              <th style={{ padding: "10px 16px", textAlign: "left", fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".06em" }}>
                Группа
              </th>
              <th style={{ padding: "10px 12px", textAlign: "right", fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".06em" }}>
                Позиций
              </th>
              <th style={{ padding: "10px 12px", textAlign: "right", fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".06em" }}>
                Статус
              </th>
              <th style={{ padding: "10px 16px", textAlign: "right", fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".06em" }}>
                Действие
              </th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => (
              <tr key={group.id} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "12px 16px" }}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 3 }}>{group.title}</div>
                  <div style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--mono)" }}>{group.group_key}</div>
                </td>
                <td style={{ padding: "12px", textAlign: "right", fontFamily: "var(--mono)", color: "var(--text)" }}>
                  {group.row_count}
                </td>
                <td style={{ padding: "12px", textAlign: "right" }}>
                  <span style={{ color: STATUS_COLOR[group.status], fontWeight: 600 }}>
                    {STATUS_LABEL[group.status]}
                  </span>
                </td>
                <td style={{ padding: "12px 16px", textAlign: "right" }}>
                  <Link
                    href={`/projects/${projectId}/ktp/${group.id}?batch=${resolvedBatchId}${group.status === "generated" ? "" : "&autoStart=1"}`}
                    style={{
                      display: "inline-block",
                      padding: "8px 14px",
                      borderRadius: 6,
                      textDecoration: "none",
                      border: "1px solid var(--border2)",
                      color: "var(--text)",
                      fontSize: 12,
                      fontWeight: 600,
                    }}
                  >
                    {group.status === "generated" ? "Открыть" : "Создать КТП"}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
