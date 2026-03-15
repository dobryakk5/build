"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { projects } from "@/lib/api";
import { fmtMoney } from "@/lib/dateUtils";

const STATUS_CFG = {
  green:  { label: "По графику",     dot: "#22c55e", bg: "rgba(34,197,94,.1)",   border: "rgba(34,197,94,.3)"   },
  yellow: { label: "Есть вопросы",   dot: "#f59e0b", bg: "rgba(245,158,11,.1)",  border: "rgba(245,158,11,.3)"  },
  red:    { label: "Нужно внимание", dot: "#ef4444", bg: "rgba(239,68,68,.1)",   border: "rgba(239,68,68,.3)"   },
} as const;

export default function ProjectsPage() {
  const router  = useRouter();
  const [list,    setList]    = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName,  setNewName]  = useState("");

  useEffect(() => {
    projects.list()
      .then(setList)
      .catch(() => router.push("/auth/login"))
      .finally(() => setLoading(false));
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      const p = await projects.create({ name: newName });
      router.push(`/projects/${p.id}`);
    } catch {}
  }

  const counts = { green: 0, yellow: 0, red: 0 };
  list.forEach(p => { const s = p.dashboard_status as keyof typeof counts; if (s in counts) counts[s]++; });

  if (loading) return <div style={{display:"flex",alignItems:"center",justifyContent:"center",height:"100vh",color:"var(--muted)"}}>Загрузка...</div>;

  return (
    <div style={{minHeight:"100vh",background:"var(--bg)"}}>
      {/* Header */}
      <div style={{background:"var(--hdr)",padding:"0 24px",height:52,display:"flex",alignItems:"center",gap:16}}>
        <span style={{color:"#e2e8f0",fontWeight:700,fontSize:16}}>🏗 СтройКонтроль</span>
        <div style={{marginLeft:"auto",display:"flex",gap:8}}>
          {(["green","yellow","red"] as const).map(s => (
            <span key={s} style={{
              display:"flex",alignItems:"center",gap:5,padding:"3px 10px",borderRadius:20,
              background:STATUS_CFG[s].bg, border:`1px solid ${STATUS_CFG[s].border}`,
              fontSize:11, color:STATUS_CFG[s].dot, fontFamily:"var(--mono)"
            }}>
              <span style={{width:6,height:6,borderRadius:"50%",background:STATUS_CFG[s].dot,display:"inline-block"}}/>
              {counts[s]}
            </span>
          ))}
        </div>
      </div>

      <div style={{maxWidth:1100,margin:"0 auto",padding:"24px"}}>
        {/* Stats */}
        <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:12,marginBottom:24}}>
          {[
            ["Всего объектов",    list.length, ""],
            ["По графику",        counts.green, "#22c55e"],
            ["Требуют внимания",  counts.red + counts.yellow, "#ef4444"],
          ].map(([label, val, color]) => (
            <div key={label as string} style={{background:"var(--surface)",border:"1px solid var(--border)",borderRadius:8,padding:"16px 20px"}}>
              <div style={{fontSize:10,color:"var(--muted)",textTransform:"uppercase",letterSpacing:".08em",marginBottom:6}}>{label}</div>
              <div style={{fontSize:28,fontWeight:700,fontFamily:"var(--mono)",color:(color as string)||"var(--text)"}}>{val}</div>
            </div>
          ))}
        </div>

        {/* Create project */}
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:16}}>
          <span style={{fontSize:11,color:"var(--muted)",textTransform:"uppercase",letterSpacing:".08em",fontFamily:"var(--mono)"}}>Объекты</span>
          {creating
            ? <form onSubmit={handleCreate} style={{display:"flex",gap:8}}>
                <input autoFocus value={newName} onChange={e=>setNewName(e.target.value)}
                  placeholder="Название объекта"
                  style={{padding:"6px 12px",border:"1px solid var(--blue)",borderRadius:5,fontSize:13,outline:"none",width:240}}/>
                <button type="submit" style={{padding:"6px 14px",background:"var(--blue-dark)",color:"#fff",border:"none",borderRadius:5,fontSize:12,fontWeight:600,cursor:"pointer"}}>Создать</button>
                <button type="button" onClick={()=>setCreating(false)} style={{padding:"6px 12px",background:"var(--bg)",border:"1px solid var(--border2)",borderRadius:5,fontSize:12,cursor:"pointer"}}>Отмена</button>
              </form>
            : <button onClick={()=>setCreating(true)}
                style={{padding:"7px 16px",background:"var(--blue-dark)",color:"#fff",border:"none",borderRadius:5,fontSize:12,fontWeight:600,cursor:"pointer"}}>
                + Новый объект
              </button>
          }
        </div>

        {/* Project cards */}
        <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(300px,1fr))",gap:12}}>
          {list.map(p => {
            const s = (p.dashboard_status ?? "green") as keyof typeof STATUS_CFG;
            const cfg = STATUS_CFG[s] ?? STATUS_CFG.green;
            return (
              <div key={p.id}
                onClick={() => router.push(`/projects/${p.id}`)}
                style={{
                  background:"var(--surface)", border:`1px solid var(--border)`,
                  borderRadius:8, padding:18, cursor:"pointer",
                  borderTop:`3px solid ${cfg.dot}`,
                  transition:"box-shadow .15s",
                }}
                onMouseEnter={e=>(e.currentTarget.style.boxShadow="0 4px 12px rgba(0,0,0,.08)")}
                onMouseLeave={e=>(e.currentTarget.style.boxShadow="none")}
              >
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:10}}>
                  <div>
                    <div style={{fontWeight:600,fontSize:14}}>{p.name}</div>
                    {p.address && <div style={{fontSize:11,color:"var(--muted)",marginTop:2}}>📍 {p.address}</div>}
                  </div>
                  <span style={{
                    display:"flex",alignItems:"center",gap:4,padding:"2px 8px",
                    borderRadius:20,fontSize:10,background:cfg.bg,border:`1px solid ${cfg.border}`,
                    color:cfg.dot,fontFamily:"var(--mono)",whiteSpace:"nowrap",
                  }}>
                    <span style={{width:5,height:5,borderRadius:"50%",background:cfg.dot,display:"inline-block"}}/>
                    {cfg.label}
                  </span>
                </div>
                <div style={{display:"flex",gap:16,fontSize:11,color:"var(--muted)"}}>
                  {p.budget > 0 && <span>💰 {fmtMoney(p.budget)} ₽</span>}
                  {p.tasks_count > 0 && <span>📋 {p.tasks_count} задач</span>}
                  {p.members_count > 0 && <span>👥 {p.members_count}</span>}
                </div>
              </div>
            );
          })}
        </div>

        {list.length === 0 && (
          <div style={{textAlign:"center",padding:"60px 0",color:"var(--muted)"}}>
            <div style={{fontSize:40,marginBottom:12}}>🏗</div>
            <div style={{fontSize:16,fontWeight:500}}>Нет активных объектов</div>
            <div style={{fontSize:13,marginTop:6}}>Создайте первый проект</div>
          </div>
        )}
      </div>
    </div>
  );
}
