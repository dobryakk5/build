"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { useParams, useRouter } from "next/navigation";

import ProjectMembersPanel from "@/components/ProjectMembersPanel";
import { projects as projectsApi } from "@/lib/api";

type ProjectFull = {
  id: string;
  name: string;
  address?: string | null;
  status: string;
  color?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  my_role: string;
};

const statuses = [
  { value: "active", label: "Активный", color: "#22c55e" },
  { value: "paused", label: "Приостановлен", color: "#f59e0b" },
  { value: "done", label: "Завершён", color: "#0284c7" },
  { value: "archived", label: "Архив", color: "#64748b" },
];

const colors = ["#3b82f6", "#8b5cf6", "#ec4899", "#f97316", "#22c55e", "#14b8a6", "#f59e0b", "#ef4444", "#6366f1", "#64748b"];

export default function ProjectSettingsPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [project, setProject] = useState<ProjectFull | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteStep, setDeleteStep] = useState<0 | 1>(0);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);

  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [status, setStatus] = useState("active");
  const [color, setColor] = useState("#3b82f6");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  useEffect(() => {
    projectsApi.get(id)
      .then((data) => {
        const projectData = data as ProjectFull;
        setProject(projectData);
        setName(projectData.name ?? "");
        setAddress(projectData.address ?? "");
        setStatus(projectData.status ?? "active");
        setColor(projectData.color ?? "#3b82f6");
        setStartDate(projectData.start_date ?? "");
        setEndDate(projectData.end_date ?? "");
      })
      .catch(() => router.push("/projects"))
      .finally(() => setLoading(false));
  }, [id, router]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await projectsApi.update(id, {
        name: name.trim() || undefined,
        address: address.trim() || null,
        status,
        color: color || null,
        start_date: startDate || null,
        end_date: endDate || null,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err: any) {
      setError(err.message ?? "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (deleteConfirm !== project?.name) {
      setError("Название не совпадает");
      return;
    }
    setDeleting(true);
    try {
      await projectsApi.delete(id);
      router.push("/projects");
    } catch (err: any) {
      setError(err.message ?? "Не удалось удалить");
      setDeleting(false);
    }
  }

  if (loading) {
    return <div style={{ padding: 32, color: "var(--muted)", fontSize: 13 }}>Загрузка...</div>;
  }

  if (!project) {
    return null;
  }

  const isOwner = project.my_role === "owner";
  const canEdit = project.my_role === "owner" || project.my_role === "pm";

  return (
    <div style={{ padding: 24, maxWidth: 1080, overflow: "auto", height: "100%" }}>
      <div style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 17, fontWeight: 700, margin: 0 }}>Настройки проекта</h3>
        <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--muted)" }}>
          Роль: <strong>{project.my_role}</strong>
        </p>
      </div>

      {canEdit && <ProjectMembersPanel projectId={id} />}

      {canEdit && (
        <>
          <div style={{ fontSize: 16, fontWeight: 700, margin: "0 0 14px", color: "var(--text)" }}>
            Основная информация
          </div>
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: 24, marginBottom: 20 }}>

            <label style={labelStyle}>Название объекта</label>
            <input value={name} onChange={(event) => setName(event.target.value)} style={inputStyle} placeholder="Название проекта" />

            <label style={labelStyle}>Адрес</label>
            <input value={address} onChange={(event) => setAddress(event.target.value)} style={inputStyle} placeholder="Адрес объекта" />

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
              <div>
                <label style={labelStyle}>Дата начала</label>
                <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} style={inputStyle} />
              </div>
              <div>
                <label style={labelStyle}>Дата окончания</label>
                <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} style={inputStyle} />
              </div>
            </div>

            <label style={labelStyle}>Статус</label>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
              {statuses.map((item) => (
                <button
                  key={item.value}
                  onClick={() => setStatus(item.value)}
                  style={{
                    padding: "6px 14px",
                    borderRadius: 20,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                    transition: "all .15s",
                    background: status === item.value ? `${item.color}20` : "transparent",
                    color: status === item.value ? item.color : "var(--muted)",
                    border: `1.5px solid ${status === item.value ? item.color : "var(--border2)"}`,
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>

            <label style={labelStyle}>Цвет проекта</label>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 18 }}>
              {colors.map((value) => (
                <button
                  key={value}
                  onClick={() => setColor(value)}
                  style={{
                    width: 26,
                    height: 26,
                    borderRadius: "50%",
                    background: value,
                    border: color === value ? "3px solid var(--text)" : "3px solid transparent",
                    cursor: "pointer",
                    outline: "none",
                    padding: 0,
                    boxShadow: color === value ? `0 0 0 2px #fff, 0 0 0 4px ${value}` : "none",
                    transition: "all .15s",
                  }}
                />
              ))}
            </div>

            {error && <p style={{ fontSize: 12, color: "#ef4444", margin: "0 0 12px" }}>{error}</p>}

          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button
              onClick={handleSave}
              disabled={saving}
              style={{
                padding: "9px 24px",
                background: "var(--blue-dark)",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                fontWeight: 600,
                cursor: saving ? "not-allowed" : "pointer",
                opacity: saving ? 0.7 : 1,
                fontSize: 13,
              }}
            >
              {saving ? "Сохранение..." : "Сохранить"}
            </button>
            {saved && <span style={{ fontSize: 12, color: "#22c55e", fontWeight: 600 }}>✓ Сохранено</span>}
          </div>
        </>
      )}

      {isOwner && (
        <div style={{ background: "var(--surface)", border: "1.5px solid #ef444440", borderRadius: 10, padding: 24 }}>
          <p style={{ fontSize: 13, fontWeight: 700, color: "#ef4444", margin: "0 0 6px" }}>⚠ Опасная зона</p>
          <p style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 16px", lineHeight: 1.6 }}>
            Удаление проекта необратимо. Все задачи, сметы, отчёты и файлы будут удалены.
          </p>

          {deleteStep === 0 && (
            <button
              onClick={() => setDeleteStep(1)}
              style={{
                padding: "8px 18px",
                background: "transparent",
                border: "1.5px solid #ef4444",
                color: "#ef4444",
                borderRadius: 6,
                fontWeight: 600,
                cursor: "pointer",
                fontSize: 13,
              }}
            >
              Удалить проект
            </button>
          )}

          {deleteStep === 1 && (
            <div style={{ background: "#ef444408", border: "1px solid #ef444430", borderRadius: 8, padding: 18 }}>
              <p style={{ fontSize: 13, margin: "0 0 14px", lineHeight: 1.6 }}>
                Для подтверждения введите точное название проекта:
                <br />
                <strong style={{ fontFamily: "var(--mono)" }}>«{project.name}»</strong>
              </p>
              <input
                value={deleteConfirm}
                onChange={(event) => {
                  setDeleteConfirm(event.target.value);
                  setError(null);
                }}
                placeholder={project.name}
                style={{ ...inputStyle, border: "1.5px solid #ef444460", marginBottom: 14 }}
              />
              {error && <p style={{ fontSize: 12, color: "#ef4444", margin: "0 0 12px" }}>{error}</p>}
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  onClick={handleDelete}
                  disabled={deleting || deleteConfirm !== project.name}
                  style={{
                    padding: "8px 20px",
                    background: "#ef4444",
                    color: "#fff",
                    border: "none",
                    borderRadius: 6,
                    fontWeight: 600,
                    cursor: "pointer",
                    opacity: deleting || deleteConfirm !== project.name ? 0.5 : 1,
                    fontSize: 13,
                  }}
                >
                  {deleting ? "Удаление..." : "Удалить навсегда"}
                </button>
                <button
                  onClick={() => {
                    setDeleteStep(0);
                    setDeleteConfirm("");
                    setError(null);
                  }}
                  style={{
                    padding: "8px 16px",
                    border: "1px solid var(--border2)",
                    borderRadius: 6,
                    background: "transparent",
                    cursor: "pointer",
                    fontSize: 13,
                  }}
                >
                  Отмена
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const labelStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--muted)",
  display: "block",
  marginBottom: 5,
  textTransform: "uppercase",
  letterSpacing: ".06em",
};

const inputStyle: CSSProperties = {
  width: "100%",
  padding: "9px 12px",
  marginBottom: 14,
  border: "1px solid var(--border2)",
  borderRadius: 6,
  fontSize: 13,
  outline: "none",
  background: "var(--surface)",
  color: "var(--text)",
  boxSizing: "border-box",
};
