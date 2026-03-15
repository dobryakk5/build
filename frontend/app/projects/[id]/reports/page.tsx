"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { reports } from "@/lib/api";
import { fmtDate } from "@/lib/dateUtils";

export default function ReportsPage() {
  const { id }   = useParams<{ id: string }>();
  const [today,  setToday]  = useState<any>(null);
  const [list,   setList]   = useState<any[]>([]);
  const [selRep, setSelRep] = useState<any>(null);
  const [loading,setLoading]= useState(true);

  useEffect(() => {
    Promise.all([reports.today(id), reports.list(id)])
      .then(([t, l]) => { setToday(t); setList(l); })
      .finally(() => setLoading(false));
  }, [id]);

  async function openReport(rid: string) {
    const r = await reports.get(id, rid);
    setSelRep(r);
  }

  if (loading) return <div style={{padding:24,color:"var(--muted)"}}>Загрузка...</div>;

  return (
    <div style={{display:"flex",height:"100%",overflow:"hidden"}}>

      {/* Left: today status + history */}
      <div style={{width:320,borderRight:"1px solid var(--border)",display:"flex",flexDirection:"column",overflow:"hidden"}}>
        {/* Today */}
        {today && (
          <div style={{padding:16,borderBottom:"1px solid var(--border)",background:"var(--surface)"}}>
            <div style={{fontSize:10,color:"var(--muted)",textTransform:"uppercase",letterSpacing:".08em",marginBottom:10,fontFamily:"var(--mono)"}}>
              Отчёты сегодня · {fmtDate(new Date().toISOString())}
            </div>
            {today.foremen?.map((f: any) => (
              <div key={f.foreman?.id} style={{
                display:"flex",alignItems:"center",justifyContent:"space-between",
                padding:"8px 0",borderBottom:"1px solid var(--border)",fontSize:13,
              }}>
                <div style={{display:"flex",alignItems:"center",gap:8}}>
                  <div style={{
                    width:28,height:28,borderRadius:"50%",
                    background:f.submitted?"rgba(34,197,94,.1)":f.status==="draft"?"rgba(245,158,11,.1)":"rgba(239,68,68,.1)",
                    display:"flex",alignItems:"center",justifyContent:"center",fontSize:11,fontWeight:700,
                    color:f.submitted?"#15803d":f.status==="draft"?"#b45309":"#dc2626",
                  }}>
                    {f.foreman?.name?.[0] ?? "?"}
                  </div>
                  <div>
                    <div style={{fontWeight:500}}>{f.foreman?.name}</div>
                    <div style={{fontSize:10,color:"var(--muted)"}}>
                      {f.submitted ? "✅ Сдан" : f.status === "draft" ? "⏳ Черновик" : "❌ Не сдан"}
                    </div>
                  </div>
                </div>
                {f.report_id && (
                  <button onClick={()=>openReport(f.report_id)}
                    style={{fontSize:11,color:"var(--blue-dark)",background:"none",border:"none",cursor:"pointer",textDecoration:"underline"}}>
                    Открыть
                  </button>
                )}
              </div>
            ))}
            {!today.foremen?.length && (
              <div style={{fontSize:12,color:"var(--muted)"}}>Нет назначенных прорабов</div>
            )}
          </div>
        )}

        {/* History */}
        <div style={{flex:1,overflow:"auto",padding:16}}>
          <div style={{fontSize:10,color:"var(--muted)",textTransform:"uppercase",letterSpacing:".08em",marginBottom:10,fontFamily:"var(--mono)"}}>История отчётов</div>
          {list.map(r => (
            <div key={r.id}
              onClick={()=>openReport(r.id)}
              style={{
                padding:"10px 12px",borderRadius:6,border:"1px solid var(--border)",
                marginBottom:8,cursor:"pointer",background:"var(--surface)",
                borderLeft:`3px solid ${r.status==="reviewed"?"#22c55e":r.status==="submitted"?"#3b82f6":"#f59e0b"}`,
              }}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
                <span style={{fontWeight:500,fontSize:13}}>{fmtDate(r.report_date)}.{new Date(r.report_date).getFullYear()}</span>
                <span style={{
                  fontSize:10,fontFamily:"var(--mono)",padding:"1px 7px",borderRadius:10,
                  background:r.status==="reviewed"?"rgba(34,197,94,.1)":r.status==="submitted"?"rgba(59,130,246,.1)":"rgba(245,158,11,.1)",
                  color:r.status==="reviewed"?"#15803d":r.status==="submitted"?"var(--blue-dark)":"#b45309",
                }}>
                  {r.status==="reviewed"?"Принят":r.status==="submitted"?"Отправлен":"Черновик"}
                </span>
              </div>
              <div style={{fontSize:11,color:"var(--muted)",marginTop:3}}>{r.author?.name}</div>
              {r.issues && <div style={{fontSize:11,color:"#dc2626",marginTop:3}}>⚠ {r.issues.slice(0,60)}{r.issues.length>60?"...":""}</div>}
            </div>
          ))}
          {!list.length && <div style={{fontSize:12,color:"var(--muted)"}}>Нет отчётов</div>}
        </div>
      </div>

      {/* Right: report detail */}
      <div style={{flex:1,overflow:"auto",padding:20}}>
        {selRep ? (
          <>
            <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:16}}>
              <h3 style={{fontSize:16,fontWeight:600}}>Отчёт за {fmtDate(selRep.report_date)}</h3>
              <span style={{fontSize:12,color:"var(--muted)"}}>{selRep.author?.name}</span>
            </div>

            {selRep.issues && (
              <div style={{padding:"10px 14px",background:"rgba(239,68,68,.06)",border:"1px solid rgba(239,68,68,.2)",borderRadius:6,marginBottom:14}}>
                <div style={{fontSize:11,fontWeight:600,color:"#dc2626",marginBottom:3}}>Проблемы</div>
                <div style={{fontSize:13}}>{selRep.issues}</div>
              </div>
            )}

            {selRep.summary && (
              <div style={{padding:"10px 14px",background:"var(--surface)",border:"1px solid var(--border)",borderRadius:6,marginBottom:14}}>
                <div style={{fontSize:11,color:"var(--muted)",marginBottom:3}}>Сводка за день</div>
                <div style={{fontSize:13}}>{selRep.summary}</div>
              </div>
            )}

            <div style={{background:"var(--surface)",border:"1px solid var(--border)",borderRadius:6,overflow:"hidden"}}>
              <table style={{width:"100%",borderCollapse:"collapse",fontSize:12}}>
                <thead>
                  <tr style={{background:"#f8fafc"}}>
                    {["Задача","Что сделано","Объём","Прогресс","Рабочих"].map(h=>(
                      <th key={h} style={{padding:"8px 12px",textAlign:"left",fontSize:10,color:"var(--muted)",textTransform:"uppercase",letterSpacing:".06em",borderBottom:"1px solid var(--border)"}}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {selRep.items?.map((item: any, i: number) => (
                    <tr key={item.id} style={{background:i%2?"var(--stripe)":""}}>
                      <td style={{padding:"8px 12px",borderBottom:"1px solid var(--border)",fontWeight:500}}>{item.task_name}</td>
                      <td style={{padding:"8px 12px",borderBottom:"1px solid var(--border)"}}>{item.work_done}</td>
                      <td style={{padding:"8px 12px",borderBottom:"1px solid var(--border)",fontFamily:"var(--mono)"}}>{item.volume_done ? `${item.volume_done} ${item.volume_unit??''}` : "—"}</td>
                      <td style={{padding:"8px 12px",borderBottom:"1px solid var(--border)"}}>
                        <div style={{display:"flex",alignItems:"center",gap:8}}>
                          <div style={{width:60,height:5,background:"#e2e8f0",borderRadius:3,overflow:"hidden"}}>
                            <div style={{width:`${item.progress_after}%`,height:"100%",background:item.progress_after>=100?"#22c55e":"#3b82f6",borderRadius:3}}/>
                          </div>
                          <span style={{fontFamily:"var(--mono)",fontSize:10}}>{item.progress_after}%</span>
                        </div>
                      </td>
                      <td style={{padding:"8px 12px",borderBottom:"1px solid var(--border)",fontFamily:"var(--mono)"}}>{item.workers_count ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div style={{display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",height:"100%",color:"var(--muted)"}}>
            <div style={{fontSize:32,marginBottom:10}}>📝</div>
            <div>Выберите отчёт из списка слева</div>
          </div>
        )}
      </div>
    </div>
  );
}
