"use client";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useParams } from "next/navigation";
import { projects as projectsApi } from "@/lib/api";
import type { User } from "@/lib/types";

const ROLES = {
  owner:    { label: "Владелец",       color: "#7c3aed" },
  pm:       { label: "Рук. проекта",   color: "#0284c7" },
  foreman:  { label: "Прораб",         color: "#d97706" },
  supplier: { label: "Снабженец",      color: "#059669" },
  viewer:   { label: "Наблюдатель",    color: "#64748b" },
} as const;

type MemberRole = keyof typeof ROLES;

type ProjectMember = {
  id: string;
  role: MemberRole;
  user?: User | null;
};

export default function MembersPage() {
  const { id }    = useParams<{ id: string }>();
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [adding,  setAdding]  = useState(false);
  const [newEmail,setNewEmail]= useState("");
  const [newRole, setNewRole] = useState<MemberRole>("foreman");
  const [loading, setLoading] = useState(true);

  const reload = () =>
    projectsApi.listMembers(id)
      .then((data: ProjectMember[]) => setMembers(data))
      .finally(() => setLoading(false));

  useEffect(() => { reload(); }, [id]);

  async function handleAdd(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // NOTE: в реальной системе нужен поиск пользователя по email через /users/search
    // Здесь упрощённо — ввод user_id напрямую
    try {
      await projectsApi.addMember(id, { user_id: newEmail, role: newRole });
      setNewEmail(""); setAdding(false); reload();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Не удалось добавить участника");
    }
  }

  async function handleRoleChange(userId: string | undefined, role: MemberRole) {
    if (!userId) return;
    try {
      await projectsApi.updateMember(id, userId, { role });
      reload();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Не удалось обновить роль");
    }
  }

  async function handleRemove(userId: string | undefined) {
    if (!userId) return;
    if (!confirm("Удалить участника?")) return;
    try { await projectsApi.removeMember(id, userId); reload(); }
    catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Не удалось удалить участника");
    }
  }

  if (loading) return <div style={{padding:24,color:"var(--muted)"}}>Загрузка...</div>;

  return (
    <div style={{padding:20,maxWidth:700,overflow:"auto",height:"100%"}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:16}}>
        <h3 style={{fontSize:16,fontWeight:600}}>Участники проекта</h3>
        <button onClick={()=>setAdding(a=>!a)}
          style={{padding:"7px 14px",background:"var(--blue-dark)",color:"#fff",border:"none",borderRadius:5,fontSize:12,fontWeight:600,cursor:"pointer"}}>
          + Добавить
        </button>
      </div>

      {adding && (
        <form onSubmit={handleAdd}
          style={{background:"var(--surface)",border:"1px solid var(--blue)",borderRadius:8,padding:16,marginBottom:16,display:"flex",gap:10,flexWrap:"wrap"}}>
          <div style={{flex:1,minWidth:200}}>
            <label style={{fontSize:11,color:"var(--muted)",display:"block",marginBottom:4}}>User ID (временно)</label>
            <input required value={newEmail} onChange={e=>setNewEmail(e.target.value)}
              placeholder="UUID пользователя"
              style={{width:"100%",padding:"8px 10px",border:"1px solid var(--border2)",borderRadius:5,fontSize:13,outline:"none"}}/>
          </div>
          <div>
            <label style={{fontSize:11,color:"var(--muted)",display:"block",marginBottom:4}}>Роль</label>
            <select value={newRole} onChange={e=>setNewRole(e.target.value as MemberRole)}
              style={{padding:"8px 10px",border:"1px solid var(--border2)",borderRadius:5,fontSize:13,background:"var(--surface)"}}>
              {Object.entries(ROLES).map(([k,v])=><option key={k} value={k}>{v.label}</option>)}
            </select>
          </div>
          <div style={{display:"flex",gap:8,alignSelf:"flex-end"}}>
            <button type="submit" style={{padding:"8px 16px",background:"var(--blue-dark)",color:"#fff",border:"none",borderRadius:5,fontSize:13,fontWeight:600,cursor:"pointer"}}>Добавить</button>
            <button type="button" onClick={()=>setAdding(false)} style={{padding:"8px 14px",border:"1px solid var(--border2)",borderRadius:5,background:"var(--surface)",fontSize:13,cursor:"pointer"}}>Отмена</button>
          </div>
        </form>
      )}

      <div style={{background:"var(--surface)",border:"1px solid var(--border)",borderRadius:8,overflow:"hidden"}}>
        <table style={{width:"100%",borderCollapse:"collapse",fontSize:13}}>
          <thead>
            <tr style={{background:"#f8fafc"}}>
              {["Пользователь","Email","Роль",""].map(h=>(
                <th key={h} style={{padding:"9px 14px",textAlign:"left",fontSize:10,color:"var(--muted)",textTransform:"uppercase",letterSpacing:".06em",borderBottom:"1px solid var(--border)"}}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {members.map(m => {
              const rc = ROLES[m.role as keyof typeof ROLES];
              return (
                <tr key={m.id} style={{borderBottom:"1px solid var(--border)"}}>
                  <td style={{padding:"10px 14px",fontWeight:500}}>{m.user?.name ?? "—"}</td>
                  <td style={{padding:"10px 14px",color:"var(--muted)",fontSize:12}}>{m.user?.email ?? "—"}</td>
                  <td style={{padding:"10px 14px"}}>
                    <select value={m.role} onChange={e=>handleRoleChange(m.user?.id, e.target.value as MemberRole)}
                      style={{
                        padding:"3px 8px",borderRadius:10,fontSize:11,fontFamily:"var(--mono)",fontWeight:500,cursor:"pointer",
                        background:`${rc?.color ?? "#64748b"}18`,color:rc?.color ?? "#64748b",
                        border:`1px solid ${rc?.color ?? "#64748b"}40`,outline:"none",
                      }}>
                      {Object.entries(ROLES).map(([k,v])=><option key={k} value={k}>{v.label}</option>)}
                    </select>
                  </td>
                  <td style={{padding:"10px 14px",textAlign:"right"}}>
                    <button onClick={()=>handleRemove(m.user?.id)}
                      style={{background:"none",border:"none",cursor:"pointer",color:"#ef4444",fontSize:12}}>
                      Удалить
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {members.length === 0 && <div style={{padding:20,textAlign:"center",color:"var(--muted)",fontSize:13}}>Нет участников</div>}
      </div>
    </div>
  );
}
