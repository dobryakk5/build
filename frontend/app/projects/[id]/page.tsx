"use client";
import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { projects } from "@/lib/api";
import { fmtMoney } from "@/lib/dateUtils";

const TABS = [
  { id: "gantt",    label: "📊 Диаграмма Ганта" },
  { id: "estimate", label: "📋 Смета"           },
  { id: "upload",   label: "⬆ Загрузить смету"  },
  { id: "reports",  label: "📝 Отчёты"           },
];

export default function ProjectPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const pid    = params.id;

  const [project, setProject] = useState<any>(null);
  const [tab,     setTab]     = useState("gantt");

  useEffect(() => {
    projects.get(pid).then(setProject).catch(() => router.push("/projects"));
  }, [pid]);

  if (!project) return (
    <div style={{display:"flex",alignItems:"center",justifyContent:"center",height:"100vh",color:"var(--muted)"}}>
      Загрузка...
    </div>
  );

  const sColor = project.dashboard_status === "red" ? "#ef4444"
               : project.dashboard_status === "yellow" ? "#f59e0b" : "#22c55e";

  return (
    <div style={{height:"100vh",display:"flex",flexDirection:"column",background:"var(--bg)"}}>
      {/* Topbar */}
      <div style={{background:"var(--hdr)",height:44,display:"flex",alignItems:"center",padding:"0 16px",gap:8,flexShrink:0}}>
        <span onClick={()=>router.push("/projects")}
          style={{color:"#64748b",cursor:"pointer",fontSize:13,display:"flex",alignItems:"center",gap:4}}
        >← Объекты</span>
        <span style={{color:"#334155"}}>›</span>
        <span style={{color:"#e2e8f0",fontSize:13,fontWeight:500}}>{project.name}</span>
        <span style={{
          marginLeft:8,display:"inline-flex",alignItems:"center",gap:4,
          padding:"2px 8px",borderRadius:20,fontSize:10,
          background:`${sColor}18`,border:`1px solid ${sColor}40`,color:sColor,
        }}>
          <span style={{width:5,height:5,borderRadius:"50%",background:sColor,display:"inline-block"}}/>
          {project.dashboard_status === "red" ? "Нужно внимание" : project.dashboard_status === "yellow" ? "Есть вопросы" : "По графику"}
        </span>
        {project.address && <span style={{fontSize:11,color:"#64748b",marginLeft:4}}>📍 {project.address}</span>}
        <div style={{marginLeft:"auto",display:"flex",gap:16,fontSize:11,color:"#94a3b8",fontFamily:"var(--mono)"}}>
          {project.budget > 0 && <span>💰 {fmtMoney(project.budget)} ₽</span>}
          <span style={{color:"#475569",cursor:"pointer"}} onClick={()=>router.push("/projects")}>Выйти</span>
        </div>
      </div>

      {/* Tabs */}
      <div style={{background:"var(--hdr2)",borderBottom:"1px solid var(--hdr3)",display:"flex",padding:"0 16px",gap:2,flexShrink:0}}>
        {TABS.map(t => (
          <button key={t.id} onClick={()=>{ setTab(t.id); router.push(`/projects/${pid}/${t.id}`); }}
            style={{
              padding:"10px 14px",border:"none",cursor:"pointer",
              fontSize:12,fontWeight:500,
              background: tab === t.id ? "var(--bg)" : "transparent",
              color:      tab === t.id ? "var(--text)" : "#64748b",
              borderRadius:"4px 4px 0 0",
              borderBottom: tab === t.id ? "2px solid var(--blue)" : "2px solid transparent",
            }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Content iframe area — реальные страницы */}
      <div style={{flex:1,overflow:"hidden"}}>
        {tab === "gantt"    && <iframe src={`/projects/${pid}/gantt`}    style={{width:"100%",height:"100%",border:"none"}}/>}
        {tab === "estimate" && <iframe src={`/projects/${pid}/estimate`} style={{width:"100%",height:"100%",border:"none"}}/>}
        {tab === "upload"   && <iframe src={`/projects/${pid}/upload`}   style={{width:"100%",height:"100%",border:"none"}}/>}
        {tab === "reports"  && <iframe src={`/projects/${pid}/reports`}  style={{width:"100%",height:"100%",border:"none"}}/>}
      </div>
    </div>
  );
}
