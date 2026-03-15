"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { gantt, reports } from "@/lib/api";
import { fmtDate } from "@/lib/dateUtils";

export default function NewReportPage() {
  const { id }   = useParams<{ id: string }>();
  const router   = useRouter();

  const [tasks,   setTasks]   = useState<any[]>([]);
  const [step,    setStep]    = useState<1|2|3>(1);
  const [selIds,  setSelIds]  = useState<Set<string>>(new Set());
  const [items,   setItems]   = useState<Record<string, any>>({});
  const [summary, setSummary] = useState("");
  const [issues,  setIssues]  = useState("");
  const [weather, setWeather] = useState("");
  const [saving,  setSaving]  = useState(false);

  const today = new Date().toISOString().split("T")[0];

  useEffect(() => {
    gantt.list(id).then(data => {
      // Only leaf tasks (not groups) in progress
      setTasks((data.tasks ?? []).filter((t: any) => !t.is_group && t.progress < 100));
    });
  }, [id]);

  function toggleTask(tid: string) {
    setSelIds(s => {
      const n = new Set(s);
      n.has(tid) ? n.delete(tid) : n.add(tid);
      return n;
    });
    if (!items[tid]) {
      const task = tasks.find(t => t.id === tid);
      setItems(prev => ({
        ...prev,
        [tid]: { work_done: "", progress_after: task?.progress ?? 0, workers_count: "" },
      }));
    }
  }

  function setItem(tid: string, field: string, value: any) {
    setItems(prev => ({ ...prev, [tid]: { ...prev[tid], [field]: value } }));
  }

  const selectedTasks = tasks.filter(t => selIds.has(t.id));

  async function handleSubmit() {
    setSaving(true);
    try {
      const report_items = selectedTasks.map(t => ({
        task_id:        t.id,
        work_done:      items[t.id]?.work_done || "Выполнены работы",
        progress_after: Number(items[t.id]?.progress_after ?? t.progress),
        workers_count:  items[t.id]?.workers_count ? Number(items[t.id].workers_count) : null,
      }));

      const rep = await reports.create(id, {
        report_date: today,
        summary, issues, weather,
        items: report_items,
      });
      await reports.submit(id, rep.id);
      router.push(`/projects/${id}/reports`);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{maxWidth:560,margin:"0 auto",padding:20,height:"100%",overflow:"auto"}}>

      {/* Progress steps */}
      <div style={{display:"flex",gap:0,marginBottom:24}}>
        {[["1","Задачи"],["2","Прогресс"],["3","Итого"]].map(([n,label],i)=>(
          <div key={n} style={{flex:1,display:"flex",flexDirection:"column",alignItems:"center"}}>
            <div style={{
              width:28,height:28,borderRadius:"50%",display:"flex",alignItems:"center",
              justifyContent:"center",fontSize:12,fontWeight:700,marginBottom:4,
              background:step>i+1?"#22c55e":step===i+1?"var(--blue-dark)":"var(--border2)",
              color:step>=i+1?"#fff":"var(--muted)",
            }}>{step>i+1?"✓":n}</div>
            <div style={{fontSize:11,color:step===i+1?"var(--blue-dark)":"var(--muted)",fontWeight:step===i+1?600:400}}>{label}</div>
          </div>
        ))}
      </div>

      {/* Step 1: Select tasks */}
      {step === 1 && (
        <>
          <h3 style={{fontSize:15,fontWeight:600,marginBottom:12}}>Какие задачи работали сегодня?</h3>
          <div style={{display:"flex",flexDirection:"column",gap:8}}>
            {tasks.length === 0 && <div style={{color:"var(--muted)",fontSize:13}}>Нет активных задач</div>}
            {tasks.map(t => (
              <div key={t.id}
                onClick={()=>toggleTask(t.id)}
                style={{
                  padding:"12px 14px",borderRadius:6,border:`2px solid ${selIds.has(t.id)?"var(--blue-dark)":"var(--border)"}`,
                  background:selIds.has(t.id)?"rgba(29,78,216,.04)":"var(--surface)",
                  cursor:"pointer",display:"flex",alignItems:"center",gap:12,
                }}>
                <div style={{
                  width:20,height:20,borderRadius:4,flexShrink:0,
                  background:selIds.has(t.id)?"var(--blue-dark)":"transparent",
                  border:`2px solid ${selIds.has(t.id)?"var(--blue-dark)":"var(--border2)"}`,
                  display:"flex",alignItems:"center",justifyContent:"center",color:"#fff",fontSize:12,
                }}>{selIds.has(t.id)?"✓":""}</div>
                <div>
                  <div style={{fontSize:13,fontWeight:500}}>{t.name}</div>
                  <div style={{fontSize:11,color:"var(--muted)",marginTop:2}}>
                    {fmtDate(t.start_date)} · {t.progress}% выполнено
                  </div>
                </div>
              </div>
            ))}
          </div>
          <button
            onClick={()=>setStep(2)} disabled={selIds.size===0}
            style={{marginTop:20,width:"100%",padding:"11px",background:"var(--blue-dark)",color:"#fff",border:"none",borderRadius:6,fontSize:14,fontWeight:600,cursor:"pointer",opacity:selIds.size===0?.5:1}}>
            Далее → {selIds.size > 0 ? `(${selIds.size} задач)` : ""}
          </button>
        </>
      )}

      {/* Step 2: Progress per task */}
      {step === 2 && (
        <>
          <h3 style={{fontSize:15,fontWeight:600,marginBottom:12}}>Что сделано?</h3>
          <div style={{display:"flex",flexDirection:"column",gap:16}}>
            {selectedTasks.map(t => (
              <div key={t.id} style={{background:"var(--surface)",border:"1px solid var(--border)",borderRadius:8,padding:16}}>
                <div style={{fontWeight:600,fontSize:13,marginBottom:10,paddingBottom:8,borderBottom:"1px solid var(--border)"}}>{t.name}</div>

                <div style={{marginBottom:10}}>
                  <label style={{fontSize:11,color:"var(--muted)",display:"block",marginBottom:4}}>Что выполнено</label>
                  <textarea
                    value={items[t.id]?.work_done ?? ""}
                    onChange={e=>setItem(t.id,"work_done",e.target.value)}
                    rows={2} placeholder="Опишите выполненные работы..."
                    style={{width:"100%",padding:"8px 10px",border:"1px solid var(--border2)",borderRadius:5,fontSize:13,resize:"none",outline:"none",fontFamily:"var(--sans)"}}
                  />
                </div>

                <div style={{marginBottom:10}}>
                  <label style={{fontSize:11,color:"var(--muted)",display:"block",marginBottom:6}}>
                    Прогресс: <b style={{color:"var(--blue-dark)",fontFamily:"var(--mono)"}}>{items[t.id]?.progress_after ?? t.progress}%</b>
                  </label>
                  <input type="range" min={t.progress} max={100}
                    value={items[t.id]?.progress_after ?? t.progress}
                    onChange={e=>setItem(t.id,"progress_after",Number(e.target.value))}
                    style={{width:"100%",accentColor:"var(--blue-dark)"}}/>
                </div>

                <div>
                  <label style={{fontSize:11,color:"var(--muted)",display:"block",marginBottom:4}}>Рабочих сегодня</label>
                  <input type="number" min={1} max={50}
                    value={items[t.id]?.workers_count ?? ""}
                    onChange={e=>setItem(t.id,"workers_count",e.target.value)}
                    placeholder="—"
                    style={{width:100,padding:"7px 10px",border:"1px solid var(--border2)",borderRadius:5,fontSize:13,outline:"none"}}/>
                </div>
              </div>
            ))}
          </div>
          <div style={{display:"flex",gap:10,marginTop:20}}>
            <button onClick={()=>setStep(1)} style={{padding:"10px 20px",border:"1px solid var(--border2)",borderRadius:6,background:"var(--surface)",fontSize:13,cursor:"pointer"}}>← Назад</button>
            <button onClick={()=>setStep(3)} style={{flex:1,padding:"11px",background:"var(--blue-dark)",color:"#fff",border:"none",borderRadius:6,fontSize:14,fontWeight:600,cursor:"pointer"}}>Далее →</button>
          </div>
        </>
      )}

      {/* Step 3: Summary */}
      {step === 3 && (
        <>
          <h3 style={{fontSize:15,fontWeight:600,marginBottom:12}}>Сводка за день</h3>
          {[
            {label:"Общие заметки",  value:summary,  set:setSummary,  placeholder:"Как прошёл день?"},
            {label:"Проблемы",       value:issues,   set:setIssues,   placeholder:"Задержки, нехватка материалов, поломки..."},
            {label:"Погода",         value:weather,  set:setWeather,  placeholder:"Пасмурно, +5°C"},
          ].map(f=>(
            <div key={f.label} style={{marginBottom:14}}>
              <label style={{fontSize:11,color:"var(--muted)",display:"block",marginBottom:4,textTransform:"uppercase",letterSpacing:".06em"}}>{f.label}</label>
              {f.label==="Погода"
                ? <input value={f.value} onChange={e=>f.set(e.target.value)} placeholder={f.placeholder}
                    style={{width:"100%",padding:"8px 12px",border:"1px solid var(--border2)",borderRadius:5,fontSize:13,outline:"none"}}/>
                : <textarea rows={3} value={f.value} onChange={e=>f.set(e.target.value)} placeholder={f.placeholder}
                    style={{width:"100%",padding:"8px 12px",border:"1px solid var(--border2)",borderRadius:5,fontSize:13,resize:"none",outline:"none",fontFamily:"var(--sans)"}}/>
              }
            </div>
          ))}

          <div style={{background:"var(--surface)",border:"1px solid var(--border)",borderRadius:6,padding:12,marginBottom:16}}>
            <div style={{fontSize:11,color:"var(--muted)",marginBottom:6}}>Задачи в отчёте ({selectedTasks.length})</div>
            {selectedTasks.map(t=>(
              <div key={t.id} style={{display:"flex",justifyContent:"space-between",padding:"4px 0",borderBottom:"1px solid var(--border)",fontSize:12}}>
                <span>{t.name}</span>
                <span style={{fontFamily:"var(--mono)",color:"var(--blue-dark)",fontWeight:600}}>{items[t.id]?.progress_after ?? t.progress}%</span>
              </div>
            ))}
          </div>

          <div style={{display:"flex",gap:10}}>
            <button onClick={()=>setStep(2)} style={{padding:"10px 20px",border:"1px solid var(--border2)",borderRadius:6,background:"var(--surface)",fontSize:13,cursor:"pointer"}}>← Назад</button>
            <button onClick={handleSubmit} disabled={saving}
              style={{flex:1,padding:"11px",background:"#15803d",color:"#fff",border:"none",borderRadius:6,fontSize:14,fontWeight:600,cursor:"pointer",opacity:saving?.6:1}}>
              {saving ? "Отправляем..." : "✓ Отправить отчёт"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
