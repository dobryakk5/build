"use client";
import { useEffect } from "react";
import { useRouter, useParams } from "next/navigation";

export default function ProjectPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();

  useEffect(() => {
    router.replace(`/projects/${id}/gantt`);
  }, [id]);

  return null;
}