"use client";
import { useState, useEffect, useRef } from "react";
import { jobs } from "./api";

export type JobStatus = "pending" | "processing" | "done" | "failed";

export interface JobResult {
  estimates_count?:   number;
  gantt_tasks_count?: number;
  estimate_batch_id?: string;
  estimate_batch_name?: string;
  estimate_kind?: number;
  matched_rows_count?: number;
  low_confidence_count?: number;
  normalized_rows_count?: number;
  reranked_rows_count?: number;
  rerank_corrected_count?: number;
  fallback_rows_count?: number;
  review_rows_count?: number;
  review_estimate_ids?: string[];
  complex_mode?: boolean;
  strategy?:          string;
  confidence?:        number;
  total_price?:       number;
  error?:             string;
  _progress?:         string;
}

export interface Job {
  id:          string;
  status:      JobStatus;
  result:      JobResult | null;
  finished_at: string | null;
}

export function useJobPoller(jobId: string | null, intervalMs = 1500) {
  const [job,     setJob]     = useState<Job | null>(null);
  const [loading, setLoading] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const failures = useRef(0);

  useEffect(() => {
    if (!jobId) { setJob(null); failures.current = 0; return; }
    setLoading(true);
    failures.current = 0;

    const poll = async () => {
      try {
        const data = await jobs.get(jobId);
        failures.current = 0;
        setJob(data);
        if (data.status === "done" || data.status === "failed") {
          clearInterval(timer.current!);
          setLoading(false);
        } else {
          setLoading(true);
        }
      } catch {
        failures.current += 1;
        if (failures.current >= 20) {
          setLoading(false);
        }
      }
    };

    poll();
    timer.current = setInterval(poll, intervalMs);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [jobId, intervalMs]);

  return { job, loading };
}
