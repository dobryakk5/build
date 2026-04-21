"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";

import EmailVerificationBanner from "@/components/EmailVerificationBanner";
import { auth, notifications as notifApi } from "@/lib/api";
import { useUser } from "@/lib/UserContext";

export default function ProjectLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const { user: currentUser, loading: userLoading } = useUser();

  const [unread, setUnread] = useState(0);
  const [showNotif, setShowNotif] = useState(false);
  const [notifs, setNotifs] = useState<any[]>([]);
  const [resendingVerification, setResendingVerification] = useState(false);

  useEffect(() => {
    if (!userLoading && !currentUser) {
      router.push("/auth/login");
    }
  }, [currentUser, router, userLoading]);

  useEffect(() => {
    notifApi.listQuiet(true).then((items) => setUnread(items.length)).catch(() => {});
  }, [pathname]);

  async function openNotifs() {
    const items = await notifApi.listQuiet(false).catch(() => []);
    setNotifs(items);
    setShowNotif(true);
    setUnread(0);
    await notifApi.markAllReadQuiet().catch(() => {});
  }

  async function handleLogout() {
    await auth.logout();
  }

  async function handleResendVerification() {
    setResendingVerification(true);
    try {
      await auth.resendVerification();
    } finally {
      setResendingVerification(false);
    }
  }

  const myRole = currentUser?.projects?.find((project) => project.project_id === id)?.role ?? null;
  const canManage = myRole === "owner" || myRole === "pm";
  const isOwner = myRole === "owner";

  const tabs = [
    { id: "gantt", label: "📊 Ганта", path: `/projects/${id}/gantt` },
    { id: "estimate", label: "📋 Смета", path: `/projects/${id}/estimate` },
    { id: "journal", label: "🗒 Журнал", path: `/projects/${id}/journal` },
    { id: "fer", label: "🧾 ФЕР", path: `/projects/${id}/fer` },
    { id: "upload", label: "⬆ Загрузка", path: `/projects/${id}/upload` },
    { id: "reports", label: "📝 Отчёты", path: `/projects/${id}/reports` },
    ...(canManage ? [{ id: "members", label: "👥 Команда", path: `/projects/${id}/members` }] : []),
    ...(canManage || isOwner ? [{ id: "settings", label: "⚙ Настройки", path: `/projects/${id}/settings` }] : []),
  ];

  const activeTab = tabs.find((tab) => pathname.startsWith(tab.path))?.id ?? "gantt";

  if (userLoading) {
    return (
      <div style={{ height: "100vh", background: "var(--bg)", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>Загрузка...</span>
      </div>
    );
  }

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "var(--bg)" }}>
      <div
        style={{
          background: "var(--hdr)",
          height: 44,
          display: "flex",
          alignItems: "center",
          padding: "0 16px",
          gap: 8,
          flexShrink: 0,
          zIndex: 50,
        }}
      >
        <Link
          href="/projects"
          style={{ color: "#64748b", cursor: "pointer", fontSize: 13, display: "flex", alignItems: "center", gap: 4, textDecoration: "none" }}
        >
          ← Объекты
        </Link>

        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          {currentUser?.is_superadmin && (
            <Link
              href="/admin"
              style={{
                padding: "3px 10px",
                background: "#7c3aed18",
                border: "1px solid #7c3aed40",
                borderRadius: 4,
                color: "#a78bfa",
                fontSize: 11,
                fontWeight: 700,
                cursor: "pointer",
                letterSpacing: ".04em",
                textDecoration: "none",
              }}
            >
              ⚡ Admin
            </Link>
          )}

          <div style={{ position: "relative" }}>
            <button
              onClick={openNotifs}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                color: "#94a3b8",
                fontSize: 16,
                padding: "4px 8px",
                borderRadius: 4,
                position: "relative",
              }}
            >
              🔔
              {unread > 0 && (
                <span
                  style={{
                    position: "absolute",
                    top: 0,
                    right: 0,
                    background: "#ef4444",
                    color: "#fff",
                    borderRadius: "50%",
                    width: 16,
                    height: 16,
                    fontSize: 9,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontFamily: "var(--mono)",
                    fontWeight: 700,
                  }}
                >
                  {unread > 9 ? "9+" : unread}
                </span>
              )}
            </button>

            {showNotif && (
              <>
                <div onClick={() => setShowNotif(false)} style={{ position: "fixed", inset: 0, zIndex: 40 }} />
                <div
                  style={{
                    position: "absolute",
                    right: 0,
                    top: "calc(100% + 6px)",
                    width: 320,
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    boxShadow: "0 8px 24px rgba(0,0,0,.12)",
                    zIndex: 50,
                    maxHeight: 400,
                    overflow: "auto",
                  }}
                >
                  <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)", fontWeight: 600, fontSize: 13 }}>
                    Уведомления
                  </div>
                  {notifs.length === 0 ? (
                    <div style={{ padding: 20, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>
                      Нет уведомлений
                    </div>
                  ) : (
                    notifs.map((notif) => (
                      <div key={notif.id} style={{ padding: "10px 14px", borderBottom: "1px solid var(--border)", fontSize: 12 }}>
                        <div style={{ fontWeight: 500, marginBottom: 2 }}>{notif.title}</div>
                        {notif.body && <div style={{ color: "var(--muted)" }}>{notif.body}</div>}
                        <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 4, fontFamily: "var(--mono)" }}>
                          {new Date(notif.created_at).toLocaleString("ru")}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </>
            )}
          </div>

          <button
            onClick={handleLogout}
            style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b", fontSize: 12, padding: "4px 8px" }}
          >
            Выйти
          </button>
        </div>
      </div>

      <div
        style={{
          background: "var(--hdr2)",
          borderBottom: "1px solid var(--hdr3)",
          display: "flex",
          padding: "0 16px",
          flexShrink: 0,
          overflowX: "auto",
        }}
      >
        {tabs.map((tab) => (
          <Link
            key={tab.id}
            href={tab.path}
            onClick={(event) => {
              const isPlainLeftClick = event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
              if (isPlainLeftClick && tab.id === "fer" && pathname.startsWith(tab.path)) {
                event.preventDefault();
                window.dispatchEvent(new Event("fer:navigate-root"));
              }
            }}
            style={{
              padding: "10px 14px",
              display: "inline-flex",
              alignItems: "center",
              cursor: "pointer",
              fontSize: 12,
              fontWeight: 500,
              background: "transparent",
              whiteSpace: "nowrap",
              color: activeTab === tab.id ? "#e2e8f0" : "#64748b",
              borderBottom: activeTab === tab.id ? "2px solid var(--blue)" : "2px solid transparent",
              textDecoration: "none",
            }}
          >
            {tab.label}
          </Link>
        ))}
      </div>

      <div style={{ flex: 1, overflow: "hidden", paddingTop: currentUser && !currentUser.email_verified ? 16 : 0 }}>
        {currentUser && !currentUser.email_verified && (
          <div style={{ padding: "0 16px" }}>
            <EmailVerificationBanner loading={resendingVerification} onResend={handleResendVerification} />
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
