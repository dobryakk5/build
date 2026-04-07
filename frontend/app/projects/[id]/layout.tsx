"use client";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useRouter, useParams, usePathname } from "next/navigation";
import { notifications as notifApi } from "@/lib/api";

export default function ProjectLayout({ children }: { children: ReactNode }) {
  const router   = useRouter();
  const { id }   = useParams<{ id: string }>();
  const pathname = usePathname();

  const [unread, setUnread] = useState(0);
  const [showNotif, setShowNotif] = useState(false);
  const [notifs,    setNotifs]    = useState<any[]>([]);

  useEffect(() => {
    notifApi.list(true).then(n => setUnread(n.length)).catch(()=>{});
  }, [pathname]);

  async function openNotifs() {
    const n = await notifApi.list(false).catch(()=>[]);
    setNotifs(n);
    setShowNotif(true);
    setUnread(0);
    await notifApi.markAllRead().catch(()=>{});
  }

  const TABS = [
    { id: "gantt",    label: "📊 Ганта",   path: `/projects/${id}/gantt`    },
    { id: "estimate", label: "📋 Смета",   path: `/projects/${id}/estimate` },
    { id: "journal",  label: "🗒 Журнал",  path: `/projects/${id}/journal`  },
    { id: "fer",      label: "🧾 ФЕР",     path: `/projects/${id}/fer`      },
    { id: "upload",   label: "⬆ Загрузка", path: `/projects/${id}/upload`   },
    { id: "reports",  label: "📝 Отчёты",  path: `/projects/${id}/reports`  },
  ];

  const activeTab = TABS.find(t => pathname.startsWith(t.path))?.id ?? "gantt";

  return (
    <div style={{height:"100vh",display:"flex",flexDirection:"column",background:"var(--bg)"}}>
      {/* Top bar */}
      <div style={{background:"var(--hdr)",height:44,display:"flex",alignItems:"center",padding:"0 16px",gap:8,flexShrink:0,zIndex:50}}>
        <span onClick={()=>router.push("/projects")}
          style={{color:"#64748b",cursor:"pointer",fontSize:13,display:"flex",alignItems:"center",gap:4}}>
          ← Объекты
        </span>

        <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:8}}>
          {/* Notification bell */}
          <div style={{position:"relative"}}>
            <button onClick={openNotifs}
              style={{background:"none",border:"none",cursor:"pointer",color:"#94a3b8",fontSize:16,padding:"4px 8px",borderRadius:4,position:"relative"}}>
              🔔
              {unread > 0 && (
                <span style={{
                  position:"absolute",top:0,right:0,
                  background:"#ef4444",color:"#fff",borderRadius:"50%",
                  width:16,height:16,fontSize:9,display:"flex",alignItems:"center",justifyContent:"center",
                  fontFamily:"var(--mono)",fontWeight:700,
                }}>{unread > 9 ? "9+" : unread}</span>
              )}
            </button>

            {showNotif && (
              <>
                <div onClick={()=>setShowNotif(false)}
                  style={{position:"fixed",inset:0,zIndex:40}}/>
                <div style={{
                  position:"absolute",right:0,top:"calc(100% + 6px)",
                  width:320,background:"var(--surface)",border:"1px solid var(--border)",
                  borderRadius:8,boxShadow:"0 8px 24px rgba(0,0,0,.12)",zIndex:50,
                  maxHeight:400,overflow:"auto",
                }}>
                  <div style={{padding:"10px 14px",borderBottom:"1px solid var(--border)",fontWeight:600,fontSize:13}}>Уведомления</div>
                  {notifs.length === 0
                    ? <div style={{padding:20,textAlign:"center",color:"var(--muted)",fontSize:13}}>Нет уведомлений</div>
                    : notifs.map(n => (
                        <div key={n.id} style={{padding:"10px 14px",borderBottom:"1px solid var(--border)",fontSize:12}}>
                          <div style={{fontWeight:500,marginBottom:2}}>{n.title}</div>
                          {n.body && <div style={{color:"var(--muted)"}}>{n.body}</div>}
                          <div style={{fontSize:10,color:"var(--muted)",marginTop:4,fontFamily:"var(--mono)"}}>{new Date(n.created_at).toLocaleString("ru")}</div>
                        </div>
                      ))
                  }
                </div>
              </>
            )}
          </div>

          <button onClick={()=>{ localStorage.clear(); router.push("/auth/login"); }}
            style={{background:"none",border:"none",cursor:"pointer",color:"#64748b",fontSize:12,padding:"4px 8px"}}>
            Выйти
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{background:"var(--hdr2)",borderBottom:"1px solid var(--hdr3)",display:"flex",padding:"0 16px",flexShrink:0}}>
        {TABS.map(t => (
          <button key={t.id} onClick={()=>router.push(t.path)}
            style={{
              padding:"10px 14px",border:"none",cursor:"pointer",fontSize:12,fontWeight:500,
              background:"transparent",
              color:      activeTab===t.id ? "#e2e8f0" : "#64748b",
              borderBottom: activeTab===t.id ? "2px solid var(--blue)" : "2px solid transparent",
            }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Page content */}
      <div style={{flex:1,overflow:"hidden"}}>
        {children}
      </div>
    </div>
  );
}
