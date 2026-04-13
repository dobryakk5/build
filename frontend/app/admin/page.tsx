"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import AdminFerEditor from "@/components/AdminFerEditor";
import { admin as adminApi } from "@/lib/api";
import { useUser } from "@/lib/UserContext";
import type { CurrentUser } from "@/lib/types";

type Org = {
  id: string;
  name: string;
  slug: string;
  plan: "free" | "pro" | "enterprise";
  logo_url?: string | null;
  created_at: string;
  users_count: number;
  projects_count: number;
};

type AdminUser = {
  id: string;
  name: string;
  email: string;
  avatar_url?: string | null;
  is_active: boolean;
  is_superadmin: boolean;
  email_verified: boolean;
  last_login_at?: string | null;
  created_at: string;
  organization?: { id: string; name: string; plan: string } | null;
};

type Stats = {
  orgs_count: number;
  users_count: number;
  active_users: number;
  projects_count: number;
  plans: Record<string, number>;
};

const planCfg = {
  free: { label: "Free", color: "#64748b", bg: "#64748b18" },
  pro: { label: "Pro", color: "#0284c7", bg: "#0284c718" },
  enterprise: { label: "Enterprise", color: "#7c3aed", bg: "#7c3aed18" },
} as const;

const plans = ["free", "pro", "enterprise"] as const;

function PlanBadge({ plan }: { plan: string }) {
  const cfg = planCfg[plan as keyof typeof planCfg] ?? planCfg.free;
  return (
    <span
      style={{
        padding: "2px 10px",
        borderRadius: 20,
        fontSize: 11,
        fontWeight: 700,
        background: cfg.bg,
        color: cfg.color,
        border: `1px solid ${cfg.color}30`,
        fontFamily: "var(--mono)",
        letterSpacing: ".04em",
      }}
    >
      {cfg.label}
    </span>
  );
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, color: active ? "#22c55e" : "#ef4444" }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: active ? "#22c55e" : "#ef4444", display: "inline-block" }} />
      {active ? "Активен" : "Заблокирован"}
    </span>
  );
}

function Avatar({ name, url, size = 30 }: { name?: string; url?: string | null; size?: number }) {
  const initials = (name ?? "?")
    .split(" ")
    .map((word) => word[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  if (url) {
    return <img src={url} alt={name} width={size} height={size} style={{ borderRadius: "50%", objectFit: "cover", flexShrink: 0 }} />;
  }

  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        flexShrink: 0,
        background: "var(--blue-dark)",
        color: "#fff",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: size * 0.37,
        fontWeight: 700,
      }}
    >
      {initials}
    </div>
  );
}

function fmt(value: number) {
  return value.toLocaleString("ru");
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("ru", { day: "numeric", month: "short", year: "numeric" });
}

function StatCard({ label, value, color, sub }: { label: string; value: number | string; color?: string; sub?: string }) {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 10,
        padding: "18px 22px",
        borderTop: `3px solid ${color ?? "var(--blue)"}`,
      }}
    >
      <div style={{ fontSize: 10, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 30, fontWeight: 800, fontFamily: "var(--mono)", color: color ?? "var(--text)" }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

export default function AdminPage() {
  const router = useRouter();
  const { user: currentUser, loading: userLoading } = useUser();

  const [me, setMe] = useState<CurrentUser | null>(null);
  const [tab, setTab] = useState<"orgs" | "users" | "fer">("orgs");
  const [stats, setStats] = useState<Stats | null>(null);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [orgTotal, setOrgTotal] = useState(0);
  const [userTotal, setUserTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<{ type: "org" | "user"; id: string; name: string } | null>(null);

  const loadStats = useCallback(async () => {
    const data = await adminApi.stats();
    setStats(data);
  }, []);

  const loadOrgs = useCallback(async (search = "") => {
    const data = await adminApi.listOrgs(search);
    setOrgs(data.items);
    setOrgTotal(data.total);
  }, []);

  const loadUsers = useCallback(async (search = "") => {
    const data = await adminApi.listUsers(search);
    setUsers(data.items);
    setUserTotal(data.total);
  }, []);

  useEffect(() => {
    if (userLoading) {
      return;
    }
    if (!currentUser) {
      router.push("/auth/login");
      return;
    }
    if (!currentUser.is_superadmin) {
      router.push("/projects");
      return;
    }

    setMe(currentUser);
    setLoading(true);
    Promise.all([loadStats(), loadOrgs(), loadUsers()]).finally(() => setLoading(false));
  }, [currentUser, loadOrgs, loadStats, loadUsers, router, userLoading]);

  useEffect(() => {
    const timeout = setTimeout(() => {
      if (tab === "orgs") {
        loadOrgs(q);
      } else {
        loadUsers(q);
      }
    }, 300);
    return () => clearTimeout(timeout);
  }, [loadOrgs, loadUsers, q, tab]);

  async function changePlan(orgId: string, plan: string) {
    await adminApi.updateOrgPlan(orgId, plan);
    await Promise.all([loadOrgs(q), loadStats()]);
  }

  async function toggleUser(userId: string, isActive: boolean) {
    await adminApi.updateUser(userId, { is_active: isActive });
    await loadUsers(q);
  }

  async function confirmAndDelete() {
    if (!confirmDelete) {
      return;
    }

    if (confirmDelete.type === "org") {
      await adminApi.deleteOrg(confirmDelete.id);
      await Promise.all([loadOrgs(q), loadStats()]);
    } else {
      await adminApi.deleteUser(confirmDelete.id);
      await Promise.all([loadUsers(q), loadStats()]);
    }

    setConfirmDelete(null);
  }

  if (loading) {
    return <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", color: "var(--muted)" }}>Загрузка...</div>;
  }

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <div style={{ background: "var(--hdr)", height: 52, display: "flex", alignItems: "center", padding: "0 24px", gap: 12 }}>
        <span style={{ color: "#e2e8f0", fontWeight: 800, fontSize: 15, letterSpacing: "-.02em" }}>🏗 СтройКонтроль</span>
        <span
          style={{
            padding: "2px 8px",
            borderRadius: 4,
            background: "#7c3aed22",
            color: "#a78bfa",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: ".08em",
            textTransform: "uppercase",
            border: "1px solid #7c3aed40",
          }}
        >
          Super Admin
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 12, alignItems: "center" }}>
          <Avatar name={me?.name} size={28} />
          <span style={{ color: "#94a3b8", fontSize: 12 }}>{me?.name}</span>
          <button onClick={() => router.push("/projects")} style={{ background: "none", border: "none", color: "#64748b", fontSize: 12, cursor: "pointer" }}>
            ← К проектам
          </button>
        </div>
      </div>

      <div style={{ maxWidth: 1200, margin: "0 auto", padding: 24 }}>
        {stats && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12, marginBottom: 28 }}>
            <StatCard label="Организации" value={fmt(stats.orgs_count)} color="#7c3aed" />
            <StatCard label="Пользователи" value={fmt(stats.users_count)} color="#0284c7" sub={`${fmt(stats.active_users)} активных`} />
            <StatCard label="Проекты" value={fmt(stats.projects_count)} color="#059669" />
            <StatCard label="Pro + Ent" value={fmt((stats.plans.pro ?? 0) + (stats.plans.enterprise ?? 0))} color="#f59e0b" sub={`${fmt(stats.plans.free ?? 0)} на Free`} />
          </div>
        )}

        <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 0, borderBottom: "1px solid var(--border)", padding: "0 16px", background: "#f8fafc", flexWrap: "wrap" }}>
            {(["orgs", "users", "fer"] as const).map((value) => (
              <button
                key={value}
                onClick={() => {
                  setTab(value);
                  setQ("");
                }}
                style={{
                  padding: "12px 18px",
                  border: "none",
                  background: "transparent",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                  color: tab === value ? "var(--blue-dark)" : "var(--muted)",
                  borderBottom: tab === value ? "2px solid var(--blue-dark)" : "2px solid transparent",
                }}
              >
                {value === "orgs" ? `Организации (${fmt(orgTotal)})` : value === "users" ? `Пользователи (${fmt(userTotal)})` : "FER"}
              </button>
            ))}
            {tab !== "fer" && (
              <div style={{ marginLeft: "auto", padding: "8px 0" }}>
                <input
                  value={q}
                  onChange={(event) => setQ(event.target.value)}
                  placeholder={tab === "orgs" ? "Поиск по названию..." : "Поиск по имени или email..."}
                  style={{ padding: "7px 12px", border: "1px solid var(--border2)", borderRadius: 6, fontSize: 13, outline: "none", background: "var(--surface)", width: 240 }}
                />
              </div>
            )}
          </div>

          {tab === "orgs" && (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr>
                  {["Организация", "План", "Пользователи", "Проекты", "Создана", ""].map((header) => (
                    <th
                      key={header}
                      style={{
                        padding: "10px 16px",
                        textAlign: "left",
                        fontSize: 10,
                        color: "var(--muted)",
                        textTransform: "uppercase",
                        letterSpacing: ".06em",
                        borderBottom: "1px solid var(--border)",
                        background: "#f8fafc",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {orgs.map((org) => (
                  <tr key={org.id} style={{ borderBottom: "1px solid var(--border)" }}>
                    <td style={{ padding: "12px 16px" }}>
                      <div style={{ fontWeight: 600 }}>{org.name}</div>
                      <div style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--mono)" }}>{org.slug}</div>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <select
                        value={org.plan}
                        onChange={(event) => changePlan(org.id, event.target.value)}
                        style={{
                          padding: "3px 8px",
                          borderRadius: 20,
                          fontSize: 11,
                          fontWeight: 700,
                          background: planCfg[org.plan]?.bg ?? "#64748b18",
                          color: planCfg[org.plan]?.color ?? "#64748b",
                          border: `1px solid ${(planCfg[org.plan]?.color ?? "#64748b")}30`,
                          cursor: "pointer",
                          outline: "none",
                          fontFamily: "var(--mono)",
                        }}
                      >
                        {plans.map((plan) => (
                          <option key={plan} value={plan}>
                            {planCfg[plan].label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td style={{ padding: "12px 16px", fontFamily: "var(--mono)", textAlign: "right" }}>{fmt(org.users_count)}</td>
                    <td style={{ padding: "12px 16px", fontFamily: "var(--mono)", textAlign: "right" }}>{fmt(org.projects_count)}</td>
                    <td style={{ padding: "12px 16px", color: "var(--muted)", fontSize: 12 }}>{fmtDate(org.created_at)}</td>
                    <td style={{ padding: "12px 16px", textAlign: "right" }}>
                      <button onClick={() => setConfirmDelete({ type: "org", id: org.id, name: org.name })} style={{ background: "none", border: "none", cursor: "pointer", color: "#ef4444", fontSize: 12, padding: "3px 8px", borderRadius: 4 }}>
                        Удалить
                      </button>
                    </td>
                  </tr>
                ))}
                {orgs.length === 0 && (
                  <tr>
                    <td colSpan={6} style={{ padding: 32, textAlign: "center", color: "var(--muted)" }}>
                      Не найдено
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}

          {tab === "users" && (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr>
                  {["Пользователь", "Организация", "Статус", "Email", "Последний вход", ""].map((header) => (
                    <th
                      key={header}
                      style={{
                        padding: "10px 16px",
                        textAlign: "left",
                        fontSize: 10,
                        color: "var(--muted)",
                        textTransform: "uppercase",
                        letterSpacing: ".06em",
                        borderBottom: "1px solid var(--border)",
                        background: "#f8fafc",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id} style={{ borderBottom: "1px solid var(--border)", opacity: user.is_active ? 1 : 0.55 }}>
                    <td style={{ padding: "11px 16px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                        <Avatar name={user.name} url={user.avatar_url} size={30} />
                        <div>
                          <div style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: 5 }}>
                            {user.name}
                            {user.is_superadmin && (
                              <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: "#7c3aed20", color: "#7c3aed", border: "1px solid #7c3aed30", fontWeight: 700 }}>
                                ADMIN
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: 11, color: "var(--muted)" }}>{user.email}</div>
                        </div>
                      </div>
                    </td>
                    <td style={{ padding: "11px 16px" }}>
                      {user.organization ? (
                        <>
                          <div style={{ fontSize: 12, fontWeight: 500 }}>{user.organization.name}</div>
                          <PlanBadge plan={user.organization.plan} />
                        </>
                      ) : (
                        <span style={{ color: "var(--muted)", fontSize: 11 }}>—</span>
                      )}
                    </td>
                    <td style={{ padding: "11px 16px" }}>
                      <StatusDot active={user.is_active} />
                    </td>
                    <td style={{ padding: "11px 16px" }}>
                      {user.email_verified ? <span style={{ color: "#22c55e", fontSize: 11 }}>✓ Подтверждён</span> : <span style={{ color: "#f59e0b", fontSize: 11 }}>⚠ Не подтверждён</span>}
                    </td>
                    <td style={{ padding: "11px 16px", color: "var(--muted)", fontSize: 11 }}>{user.last_login_at ? fmtDate(user.last_login_at) : "Никогда"}</td>
                    <td style={{ padding: "11px 16px", textAlign: "right" }}>
                      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                        <button
                          onClick={() => toggleUser(user.id, !user.is_active)}
                          style={{
                            padding: "3px 10px",
                            border: "1px solid var(--border2)",
                            borderRadius: 4,
                            background: "transparent",
                            cursor: "pointer",
                            fontSize: 11,
                            color: "var(--muted)",
                          }}
                        >
                          {user.is_active ? "Заблок." : "Разблок."}
                        </button>
                        <button onClick={() => setConfirmDelete({ type: "user", id: user.id, name: user.name })} style={{ background: "none", border: "none", cursor: "pointer", color: "#ef4444", fontSize: 12 }}>
                          ✕
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {users.length === 0 && (
                  <tr>
                    <td colSpan={6} style={{ padding: 32, textAlign: "center", color: "var(--muted)" }}>
                      Не найдено
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}

          {tab === "fer" && <AdminFerEditor />}
        </div>
      </div>

      {confirmDelete && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
          <div style={{ background: "var(--surface)", borderRadius: 12, padding: 28, width: 380, boxShadow: "0 20px 60px rgba(0,0,0,.25)" }}>
            <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 10 }}>
              Удалить {confirmDelete.type === "org" ? "организацию" : "пользователя"}?
            </div>
            <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 6 }}>
              <strong style={{ color: "var(--text)" }}>{confirmDelete.name}</strong> будет удалён без возможности восстановления.
            </p>
            {confirmDelete.type === "org" && (
              <p style={{ fontSize: 12, color: "#ef4444", background: "#ef444410", border: "1px solid #ef444430", borderRadius: 6, padding: "8px 12px", marginBottom: 16 }}>
                ⚠ Удаление организации удалит её проекты и пользователей
              </p>
            )}
            <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
              <button onClick={confirmAndDelete} style={{ flex: 1, padding: "9px 0", background: "#ef4444", color: "#fff", border: "none", borderRadius: 6, fontWeight: 600, cursor: "pointer" }}>
                Удалить
              </button>
              <button onClick={() => setConfirmDelete(null)} style={{ flex: 1, padding: "9px 0", border: "1px solid var(--border2)", borderRadius: 6, background: "transparent", cursor: "pointer" }}>
                Отмена
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
