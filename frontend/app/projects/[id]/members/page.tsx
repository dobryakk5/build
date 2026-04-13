"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";

import { projects as projectsApi, users as usersApi } from "@/lib/api";

const roles = {
  owner: { label: "Владелец", color: "#7c3aed", hint: "Полный доступ, может удалить проект" },
  pm: { label: "Рук. проекта", color: "#0284c7", hint: "Редактирует план, смотрит отчёты" },
  foreman: { label: "Прораб", color: "#d97706", hint: "Подаёт ежедневные отчёты о прогрессе" },
  supplier: { label: "Снабженец", color: "#059669", hint: "Видит материалы, сообщает о задержках" },
  viewer: { label: "Наблюдатель", color: "#64748b", hint: "Только просмотр" },
} as const;

type MemberRole = keyof typeof roles;

type SearchUser = {
  id: string;
  name: string;
  email: string;
  avatar_url?: string | null;
};

type ProjectMember = {
  id: string;
  role: MemberRole;
  created_at: string;
  user?: SearchUser | null;
};

function Avatar({ name, avatarUrl, size = 32 }: { name?: string; avatarUrl?: string | null; size?: number }) {
  const initials = (name ?? "?")
    .split(" ")
    .map((word) => word[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  if (avatarUrl) {
    return <img src={avatarUrl} alt={name} width={size} height={size} style={{ borderRadius: "50%", objectFit: "cover", flexShrink: 0 }} />;
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
        fontSize: size * 0.38,
        fontWeight: 600,
        letterSpacing: "-.03em",
      }}
    >
      {initials}
    </div>
  );
}

function RoleBadge({ role }: { role: MemberRole }) {
  const cfg = roles[role];
  return (
    <span
      title={cfg.hint}
      style={{
        padding: "3px 9px",
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 600,
        cursor: "default",
        whiteSpace: "nowrap",
        background: `${cfg.color}18`,
        color: cfg.color,
        border: `1px solid ${cfg.color}40`,
      }}
    >
      {cfg.label}
    </span>
  );
}

export default function MembersPage() {
  const { id: projectId } = useParams<{ id: string }>();

  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [myRole, setMyRole] = useState<MemberRole | null>(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [emailQ, setEmailQ] = useState("");
  const [suggestions, setSuggestions] = useState<SearchUser[]>([]);
  const [selectedUser, setSelectedUser] = useState<SearchUser | null>(null);
  const [newRole, setNewRole] = useState<MemberRole>("foreman");
  const [searching, setSearching] = useState(false);
  const searchDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const canManage = myRole === "owner" || myRole === "pm";
  const ownersCount = members.filter((member) => member.role === "owner").length;

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [membersData, projectData] = await Promise.all([
        projectsApi.listMembers(projectId) as Promise<ProjectMember[]>,
        projectsApi.get(projectId),
      ]);
      setMembers(membersData);
      setMyRole((projectData.my_role as MemberRole | null) ?? null);
      setError(null);
    } catch {
      setError("Не удалось загрузить участников");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    if (selectedUser) {
      return;
    }
    if (emailQ.length < 2) {
      setSuggestions([]);
      return;
    }

    if (searchDebounce.current) {
      clearTimeout(searchDebounce.current);
    }

    searchDebounce.current = setTimeout(async () => {
      setSearching(true);
      try {
        const data = await usersApi.search(emailQ, projectId);
        setSuggestions(data);
      } catch {
        setSuggestions([]);
      } finally {
        setSearching(false);
      }
    }, 300);

    return () => {
      if (searchDebounce.current) {
        clearTimeout(searchDebounce.current);
      }
    };
  }, [emailQ, projectId, selectedUser]);

  useEffect(() => {
    function onClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setSuggestions([]);
      }
    }

    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function pickUser(user: SearchUser) {
    setSelectedUser(user);
    setEmailQ(user.email);
    setSuggestions([]);
  }

  function resetForm() {
    setEmailQ("");
    setSelectedUser(null);
    setSuggestions([]);
    setNewRole("foreman");
    setAdding(false);
    setError(null);
  }

  async function handleAdd() {
    if (!selectedUser) {
      setError("Выберите пользователя из списка");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await projectsApi.addMember(projectId, { user_id: selectedUser.id, role: newRole });
      resetForm();
      await reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Не удалось добавить участника");
    } finally {
      setSaving(false);
    }
  }

  async function handleRoleChange(userId: string | undefined, role: MemberRole) {
    if (!userId) {
      return;
    }
    try {
      await projectsApi.updateMember(projectId, userId, { role });
      setMembers((current) => current.map((member) => (member.user?.id === userId ? { ...member, role } : member)));
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Не удалось обновить роль");
      await reload();
    }
  }

  async function handleRemove(userId: string | undefined, role: MemberRole) {
    if (!userId) {
      return;
    }
    if (role === "owner" && ownersCount <= 1) {
      alert("Нельзя удалить единственного владельца проекта");
      return;
    }
    if (!confirm("Удалить участника из проекта?")) {
      return;
    }
    try {
      await projectsApi.removeMember(projectId, userId);
      setMembers((current) => current.filter((member) => member.user?.id !== userId));
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Не удалось удалить участника");
    }
  }

  if (loading) {
    return <div style={{ padding: 32, color: "var(--muted)", fontSize: 13 }}>Загрузка...</div>;
  }

  return (
    <div style={{ padding: 24, maxWidth: 760, height: "100%", overflow: "auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <div>
          <h3 style={{ fontSize: 17, fontWeight: 700, margin: 0 }}>Команда проекта</h3>
          <p style={{ margin: "3px 0 0", fontSize: 12, color: "var(--muted)" }}>
            {members.length} {members.length === 1 ? "участник" : members.length < 5 ? "участника" : "участников"}
          </p>
        </div>
        {canManage && !adding && (
          <button
            onClick={() => setAdding(true)}
            style={{
              padding: "8px 16px",
              background: "var(--blue-dark)",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            + Добавить участника
          </button>
        )}
      </div>

      {adding && (
        <div style={{ background: "var(--surface)", border: "1px solid var(--blue)", borderRadius: 10, padding: 20, marginBottom: 20 }}>
          <p style={{ margin: "0 0 14px", fontSize: 13, fontWeight: 600 }}>Новый участник</p>

          <div style={{ position: "relative", marginBottom: 14 }} ref={dropdownRef}>
            <label style={{ fontSize: 11, color: "var(--muted)", display: "block", marginBottom: 5, textTransform: "uppercase", letterSpacing: ".06em" }}>
              Email пользователя
            </label>
            <div style={{ position: "relative" }}>
              <input
                autoFocus
                value={emailQ}
                onChange={(event) => {
                  setEmailQ(event.target.value);
                  setSelectedUser(null);
                }}
                placeholder="Начните вводить email..."
                style={{
                  width: "100%",
                  padding: "9px 12px",
                  border: `1px solid ${selectedUser ? "var(--blue)" : "var(--border2)"}`,
                  borderRadius: 6,
                  fontSize: 13,
                  outline: "none",
                  background: "var(--surface)",
                  boxSizing: "border-box",
                }}
              />
              {searching && (
                <span style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", fontSize: 11, color: "var(--muted)" }}>
                  ···
                </span>
              )}
            </div>

            {suggestions.length > 0 && (
              <div
                style={{
                  position: "absolute",
                  top: "100%",
                  left: 0,
                  right: 0,
                  zIndex: 50,
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  boxShadow: "0 8px 24px rgba(0,0,0,.12)",
                  marginTop: 4,
                  overflow: "hidden",
                }}
              >
                {suggestions.map((user) => (
                  <div
                    key={user.id}
                    onMouseDown={() => pickUser(user)}
                    style={{ padding: "10px 14px", cursor: "pointer", display: "flex", alignItems: "center", gap: 10 }}
                    onMouseEnter={(event) => {
                      event.currentTarget.style.background = "rgba(59,130,246,.05)";
                    }}
                    onMouseLeave={(event) => {
                      event.currentTarget.style.background = "transparent";
                    }}
                  >
                    <Avatar name={user.name} avatarUrl={user.avatar_url} size={28} />
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 500 }}>{user.name}</div>
                      <div style={{ fontSize: 11, color: "var(--muted)" }}>{user.email}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {emailQ.length >= 2 && !searching && suggestions.length === 0 && !selectedUser && (
              <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--muted)" }}>
                Пользователей не найдено, убедитесь, что человек уже зарегистрирован в системе
              </p>
            )}

            {selectedUser && (
              <div
                style={{
                  marginTop: 8,
                  padding: "8px 12px",
                  borderRadius: 6,
                  background: "rgba(59,130,246,.08)",
                  border: "1px solid rgba(59,130,246,.25)",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                <Avatar name={selectedUser.name} avatarUrl={selectedUser.avatar_url} size={28} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{selectedUser.name}</div>
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>{selectedUser.email}</div>
                </div>
                <button
                  onClick={() => {
                    setSelectedUser(null);
                    setEmailQ("");
                  }}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "var(--muted)", fontSize: 16, lineHeight: 1 }}
                >
                  ×
                </button>
              </div>
            )}
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 11, color: "var(--muted)", display: "block", marginBottom: 8, textTransform: "uppercase", letterSpacing: ".06em" }}>
              Роль в проекте
            </label>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {(Object.entries(roles) as [MemberRole, (typeof roles)[MemberRole]][])
                .filter(([key]) => key !== "owner")
                .map(([key, value]) => (
                  <button
                    key={key}
                    onClick={() => setNewRole(key)}
                    title={value.hint}
                    style={{
                      padding: "6px 14px",
                      borderRadius: 20,
                      fontSize: 12,
                      fontWeight: 600,
                      cursor: "pointer",
                      transition: "all .15s",
                      background: newRole === key ? `${value.color}20` : "transparent",
                      color: newRole === key ? value.color : "var(--muted)",
                      border: `1.5px solid ${newRole === key ? value.color : "var(--border2)"}`,
                    }}
                  >
                    {value.label}
                  </button>
                ))}
            </div>
            <p style={{ margin: "6px 0 0", fontSize: 11, color: "var(--muted)" }}>{roles[newRole].hint}</p>
          </div>

          {error && <p style={{ margin: "0 0 12px", fontSize: 12, color: "#ef4444" }}>{error}</p>}

          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={handleAdd}
              disabled={saving || !selectedUser}
              style={{
                padding: "8px 20px",
                background: "var(--blue-dark)",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                fontSize: 13,
                fontWeight: 600,
                cursor: saving || !selectedUser ? "not-allowed" : "pointer",
                opacity: saving || !selectedUser ? 0.6 : 1,
              }}
            >
              {saving ? "Добавляем..." : "Добавить"}
            </button>
            <button
              onClick={resetForm}
              style={{
                padding: "8px 16px",
                border: "1px solid var(--border2)",
                borderRadius: 6,
                background: "transparent",
                fontSize: 13,
                cursor: "pointer",
              }}
            >
              Отмена
            </button>
          </div>
        </div>
      )}

      {error && !adding && <p style={{ margin: "0 0 12px", fontSize: 12, color: "#ef4444" }}>{error}</p>}

      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr>
              {["Участник", "Роль", "Email", ""].map((header) => (
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
                  }}
                >
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {members.map((member) => (
              <tr key={member.id} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "12px 16px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <Avatar name={member.user?.name} avatarUrl={member.user?.avatar_url} />
                    <div>
                      <div style={{ fontWeight: 600 }}>{member.user?.name ?? "—"}</div>
                      <div style={{ fontSize: 11, color: "var(--muted)" }}>
                        Добавлен {new Date(member.created_at).toLocaleDateString("ru")}
                      </div>
                    </div>
                  </div>
                </td>
                <td style={{ padding: "12px 16px" }}>
                  {canManage && member.role !== "owner" ? (
                    <select
                      value={member.role}
                      onChange={(event) => handleRoleChange(member.user?.id, event.target.value as MemberRole)}
                      style={{
                        padding: "4px 10px",
                        borderRadius: 20,
                        fontSize: 11,
                        fontWeight: 600,
                        cursor: "pointer",
                        border: `1px solid ${roles[member.role].color}40`,
                        color: roles[member.role].color,
                        background: `${roles[member.role].color}18`,
                        outline: "none",
                      }}
                    >
                      {(Object.keys(roles) as MemberRole[]).map((role) => (
                        <option key={role} value={role}>
                          {roles[role].label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <RoleBadge role={member.role} />
                  )}
                </td>
                <td style={{ padding: "12px 16px", color: "var(--muted)", fontSize: 12 }}>{member.user?.email ?? "—"}</td>
                <td style={{ padding: "12px 16px", textAlign: "right" }}>
                  {canManage && (
                    <button
                      onClick={() => handleRemove(member.user?.id, member.role)}
                      style={{ background: "none", border: "none", cursor: "pointer", color: "#ef4444", fontSize: 12 }}
                    >
                      Удалить
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {members.length === 0 && (
              <tr>
                <td colSpan={4} style={{ padding: 32, textAlign: "center", color: "var(--muted)" }}>
                  Нет участников
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
