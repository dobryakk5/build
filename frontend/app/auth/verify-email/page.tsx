"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { auth } from "@/lib/api";

function VerifyEmailContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("Проверяем ссылку подтверждения...");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("Ссылка подтверждения неполная.");
      return;
    }

    auth.verifyEmail(token)
      .then(() => {
        setStatus("success");
        setMessage("Email подтверждён. Можно продолжать работу.");
      })
      .catch((err: unknown) => {
        setStatus("error");
        setMessage(err instanceof Error ? err.message : "Не удалось подтвердить email");
      });
  }, [token]);

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)", padding: 24 }}>
      <div style={{ width: "100%", maxWidth: 420, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 16, padding: "32px 28px" }}>
        <div style={{ fontWeight: 700, fontSize: 22, marginBottom: 10 }}>Подтверждение email</div>
        <div style={{ fontSize: 14, color: "var(--muted)", lineHeight: 1.6, marginBottom: 20 }}>{message}</div>
        <button
          type="button"
          onClick={() => router.push(status === "success" ? "/projects" : "/auth/login")}
          style={{
            width: "100%",
            padding: "12px",
            background: "var(--blue-dark)",
            color: "#fff",
            border: "none",
            borderRadius: 10,
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          {status === "success" ? "Перейти к проектам" : "Вернуться ко входу"}
        </button>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)" }}>Загрузка...</div>}>
      <VerifyEmailContent />
    </Suspense>
  );
}
