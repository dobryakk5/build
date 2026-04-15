"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/api";
import { useUser } from "@/lib/UserContext";

type AuthLoginFormProps = {
  variant?: "page" | "modal";
  onSuccess?: () => void;
};

const fieldLabelStyle = {
  fontSize: 11,
  color: "var(--muted)",
  display: "block",
  marginBottom: 4,
  textTransform: "uppercase" as const,
  letterSpacing: ".06em",
};

const fieldInputStyle = {
  width: "100%",
  padding: "11px 12px",
  border: "1px solid var(--border2)",
  borderRadius: 10,
  fontSize: 14,
  outline: "none",
  background: "#fff",
};

export default function AuthLoginForm({
  variant = "page",
  onSuccess,
}: AuthLoginFormProps) {
  const router = useRouter();
  const { refresh } = useUser();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const isModal = variant === "modal";

  const cardStyle = {
    background: "var(--surface)",
    borderRadius: isModal ? 24 : 16,
    border: "1px solid var(--border)",
    padding: isModal ? "32px 28px" : "40px 36px",
    width: "100%",
    maxWidth: isModal ? 440 : 360,
    boxShadow: isModal ? "0 20px 60px rgba(15, 23, 42, 0.2)" : "none",
  };

  async function completeLogin(loginEmail: string, loginPassword: string) {
    await auth.login(loginEmail, loginPassword);
    await refresh();
    onSuccess?.();
    router.push("/projects");
  }

  async function handleTestLogin() {
    setError("");
    setLoading(true);
    try {
      await completeLogin("test@example.com", "test123");
    } catch (err: unknown) {
      setError("Тест: " + (err instanceof Error ? err.message : "неизвестная ошибка"));
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await completeLogin(email, password);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Ошибка входа");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={cardStyle}>
      <div
        style={{
          fontWeight: 700,
          fontSize: isModal ? 24 : 20,
          marginBottom: 8,
          color: "var(--text)",
        }}
      >
        СтройКонтроль
      </div>

      <div
        style={{
          fontSize: 13,
          color: "var(--muted)",
          marginBottom: 24,
          lineHeight: 1.5,
        }}
      >
        Войдите в личный кабинет, чтобы перейти к проектам и рабочим данным.
      </div>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div>
          <label style={fieldLabelStyle}>Email</label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={fieldInputStyle}
          />
        </div>

        <div>
          <label style={fieldLabelStyle}>Пароль</label>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={fieldInputStyle}
          />
        </div>

        {error && (
          <div
            style={{
              fontSize: 12,
              color: "var(--red)",
              padding: "8px 12px",
              background: "#fef2f2",
              borderRadius: 10,
            }}
          >
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          style={{
            padding: "12px",
            background: "var(--blue-dark)",
            color: "#fff",
            border: "none",
            borderRadius: 10,
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
            opacity: loading ? 0.6 : 1,
          }}
        >
          {loading ? "Входим..." : "Войти"}
        </button>

        <button
          type="button"
          onClick={handleTestLogin}
          disabled={loading}
          style={{
            padding: "12px",
            background: "transparent",
            color: "var(--muted)",
            border: "1px dashed var(--border2)",
            borderRadius: 10,
            fontSize: 13,
            fontWeight: 500,
            cursor: "pointer",
            opacity: loading ? 0.6 : 1,
          }}
        >
          Тестовый вход
        </button>

        <button
          type="button"
          onClick={() => router.push("/auth/forgot-password")}
          style={{
            padding: "6px 0 0",
            background: "transparent",
            color: "var(--blue-dark)",
            border: "none",
            fontSize: 13,
            cursor: "pointer",
            textAlign: "left" as const,
          }}
        >
          Забыли пароль?
        </button>
      </form>

      <div style={{ marginTop: 16, fontSize: 13, color: "var(--muted)" }}>
        Нет аккаунта?{" "}
        <button
          type="button"
          onClick={() => router.push("/auth/register")}
          style={{ background: "transparent", border: "none", color: "var(--blue-dark)", cursor: "pointer", padding: 0, fontSize: 13, fontWeight: 600 }}
        >
          Зарегистрироваться
        </button>
      </div>
    </div>
  );
}
