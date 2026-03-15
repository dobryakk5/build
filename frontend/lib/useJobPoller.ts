"use client";
import { useState, useEffect, useRef } from "react";
import { jobs } from "./api";

export type JobStatus = "pending" | "processing" | "done" | "failed";

export interface JobResult {
  estimates_count?:   number;
  gantt_tasks_count?: number;
  strategy?:          string;
  confidence?:        number;
  total_price?:       number;
  error?:             string;
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

  useEffect(() => {
    if (!jobId) { setJob(null); return; }
    setLoading(true);

    const poll = async () => {
      try {
        const data = await jobs.get(jobId);
        setJob(data);
        if (data.status === "done" || data.status === "failed") {
          clearInterval(timer.current!);
          setLoading(false);
        }
      } catch {
        clearInterval(timer.current!);
        setLoading(false);
      }
    };

    poll();
    timer.current = setInterval(poll, intervalMs);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [jobId, intervalMs]);

  return { job, loading };
}
