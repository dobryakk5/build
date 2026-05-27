"use client";
import { useEffect } from "react";
import { useRouter, useParams } from "next/navigation";
import { estimates, gantt, ktpEstimate } from "@/lib/api";
import type { EstimateBatch } from "@/lib/types";

function latestBatch(batches: EstimateBatch[]) {
  return [...batches].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at)).at(-1) ?? null;
}

export default function ProjectPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();

  useEffect(() => {
    async function redirect() {
      try {
        const data = await gantt.list(id, null, 1, 0);
        const hasTasks = (data?.tasks ?? []).length > 0;

        if (hasTasks) {
          router.replace(`/projects/${id}/gantt`);
          return;
        }

        // GPR пуст — открыть Загрузку, проверяя resumable-сессию (как при клике на таб)
        const uploadFallback = `/projects/${id}/upload`;
        try {
          const batches = await estimates.batches(id);
          const batch = latestBatch(batches);
          if (!batch) { router.replace(uploadFallback); return; }

          const session = await ktpEstimate.getSession(id, batch.id);
          if (!session) {
            router.replace(uploadFallback);
            return;
          }

          const jobId =
            session.status === "stage1_pending" || session.status === "stage1_processing"
              ? session.stage1_job_id
              : session.status === "gpr_processing"
                ? session.gpr_job_id
                : null;
          router.replace(`/projects/${id}/ktp-estimate/${session.id}${jobId ? `?job=${jobId}` : ""}`);
        } catch {
          router.replace(uploadFallback);
        }
      } catch {
        router.replace(`/projects/${id}/gantt`);
      }
    }
    void redirect();
  }, [id]);

  return null;
}
