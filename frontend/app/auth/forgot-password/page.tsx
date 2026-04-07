"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";

import { auth } from "@/lib/api";

export default function ForgotPasswordPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      await auth.forgotPassword(email);
      setDone(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Ошибка отправки");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)", padding: 24 }}>
      <div style={{ width: "100%", maxWidth: 420, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 16, padding: "32px 28px" }}>
        <div style={{ fontWeight: 700, fontSize: 22, marginBottom: 8 }}>Сброс пароля</div>
        <div style={{ fontSize: 14, color: "var(--muted)", lineHeight: 1.6, marginBottom: 20 }}>
          {done ? "Если аккаунт существует, письмо со ссылкой уже отправлено." : "Введите email, и мы отправим ссылку для сброса пароля."}
        </div>

        {!done && (
          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email"
              style={{ width: "100%", padding: "12px", border: "1px solid var(--border2)", borderRadius: 10, fontSize: 14, outline: "none" }}
            />

            {error && <div style={{ fontSize: 12, color: "var(--red)" }}>{error}</div>}

            <button
              type="submit"
              disabled={loading}
              style={{ padding: "12px", background: "var(--blue-dark)", color: "#fff", border: "none", borderRadius: 10, fontSize: 14, fontWeight: 600, cursor: "pointer", opacity: loading ? 0.6 : 1 }}
            >
              {loading ? "Отправляем..." : "Отправить ссылку"}
            </button>
          </form>
        )}

        <button
          type="button"
          onClick={() => router.push("/auth/login")}
          style={{ marginTop: 16, width: "100%", padding: "12px", background: "transparent", color: "var(--muted)", border: "1px solid var(--border2)", borderRadius: 10, fontSize: 13, cursor: "pointer" }}
        >
          Вернуться ко входу
        </button>
      </div>
    </div>
  );
}
