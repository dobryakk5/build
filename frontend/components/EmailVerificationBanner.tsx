"use client";

type EmailVerificationBannerProps = {
  loading?: boolean;
  onResend: () => void | Promise<void>;
};

export default function EmailVerificationBanner({
  loading = false,
  onResend,
}: EmailVerificationBannerProps) {
  return (
    <div
      style={{
        marginBottom: 16,
        padding: "14px 16px",
        borderRadius: 10,
        border: "1px solid rgba(245, 158, 11, 0.35)",
        background: "rgba(245, 158, 11, 0.12)",
        color: "#92400e",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
      }}
    >
      <div style={{ fontSize: 13, lineHeight: 1.5 }}>
        Подтвердите email, чтобы управлять участниками проекта и чувствительными действиями.
      </div>
      <button
        type="button"
        onClick={onResend}
        disabled={loading}
        style={{
          border: "none",
          borderRadius: 8,
          background: "#b45309",
          color: "#fff",
          padding: "10px 12px",
          fontSize: 12,
          fontWeight: 600,
          cursor: loading ? "default" : "pointer",
          opacity: loading ? 0.7 : 1,
          whiteSpace: "nowrap",
        }}
      >
        {loading ? "Отправляем..." : "Отправить письмо ещё раз"}
      </button>
    </div>
  );
}
