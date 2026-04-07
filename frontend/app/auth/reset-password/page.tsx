"use client";

import { Suspense, useState } from "react";
import type { FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { auth } from "@/lib/api";

function ResetPasswordContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!token) {
      setError("Ссылка сброса пароля неполная.");
      return;
    }

    setLoading(true);
    setError("");
    try {
      await auth.resetPassword(token, password);
      setDone(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Ошибка сброса пароля");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)", padding: 24 }}>
      <div style={{ width: "100%", maxWidth: 420, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 16, padding: "32px 28px" }}>
        <div style={{ fontWeight: 700, fontSize: 22, marginBottom: 8 }}>Новый пароль</div>
        <div style={{ fontSize: 14, color: "var(--muted)", lineHeight: 1.6, marginBottom: 20 }}>
          {done ? "Пароль обновлён. Войдите заново с новым паролем." : "Введите новый пароль для аккаунта."}
        </div>

        {!done && (
          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Новый пароль"
              style={{ width: "100%", padding: "12px", border: "1px solid var(--border2)", borderRadius: 10, fontSize: 14, outline: "none" }}
            />

            {error && <div style={{ fontSize: 12, color: "var(--red)" }}>{error}</div>}

            <button
              type="submit"
              disabled={loading}
              style={{ padding: "12px", background: "var(--blue-dark)", color: "#fff", border: "none", borderRadius: 10, fontSize: 14, fontWeight: 600, cursor: "pointer", opacity: loading ? 0.6 : 1 }}
            >
              {loading ? "Сохраняем..." : "Обновить пароль"}
            </button>
          </form>
        )}

        <button
          type="button"
          onClick={() => router.push("/auth/login")}
          style={{ marginTop: 16, width: "100%", padding: "12px", background: "transparent", color: "var(--muted)", border: "1px solid var(--border2)", borderRadius: 10, fontSize: 13, cursor: "pointer" }}
        >
          Перейти ко входу
        </button>
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)" }}>Загрузка...</div>}>
      <ResetPasswordContent />
    </Suspense>
  );
}
