"use client";
import { useState, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { estimates } from "@/lib/api";
import { useJobPoller } from "@/lib/useJobPoller";
import { fmtMoney } from "@/lib/dateUtils";

export default function UploadPage() {
  const { id }   = useParams<{ id: string }>();
  const router   = useRouter();
  const fileRef  = useRef<HTMLInputElement>(null);

  const [file,      setFile]      = useState<File | null>(null);
  const [drag,      setDrag]      = useState(false);
  const [startDate, setStartDate] = useState(new Date().toISOString().split("T")[0]);
  const [workers,   setWorkers]   = useState(3);
  const [jobId,     setJobId]     = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const { job, loading: polling } = useJobPoller(jobId);

  const handleDrop = useCallback((files: FileList | null) => {
    const f = files?.[0];
    if (f && (f.name.endsWith(".xlsx") || f.name.endsWith(".xls") || f.name.endsWith(".pdf"))) {
      setFile(f); setJobId(null);
    }
  }, []);

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    try {
      const res = await estimates.upload(id, file, startDate, workers);
      setJobId(res.job_id);
    } catch (e: any) {
      alert(e.message);
    } finally {
      setUploading(false);
    }
  }

  const status = job?.status;
  const result = job?.result;

  return (
    <div style={{padding:24,maxWidth:640}}>
      <h2 style={{fontSize:16,fontWeight:600,marginBottom:20}}>Загрузка Excel-сметы</h2>

      {/* Params */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:20}}>
        {[
          {label:"Дата начала работ", type:"date",   value:startDate, set:setStartDate},
          {label:"Рабочих в бригаде", type:"number", value:workers,   set:(v:any)=>setWorkers(+v)},
        ].map(f=>(
          <div key={f.label}>
            <label style={{fontSize:11,color:"var(--muted)",display:"block",marginBottom:4,textTransform:"uppercase",letterSpacing:".06em"}}>{f.label}</label>
            <input type={f.type} value={f.value} onChange={e=>f.set(e.target.value)} min={f.type==="number"?1:undefined} max={f.type==="number"?20:undefined}
              style={{width:"100%",padding:"8px 12px",border:"1px solid var(--border2)",borderRadius:5,fontSize:13,outline:"none"}}/>
          </div>
        ))}
      </div>

      {/* Dropzone */}
      {!status && (
        <div
          onClick={()=>fileRef.current?.click()}
          onDragOver={e=>{e.preventDefault();setDrag(true);}}
          onDragLeave={()=>setDrag(false)}
          onDrop={e=>{e.preventDefault();setDrag(false);handleDrop(e.dataTransfer.files);}}
          style={{
            border:`2px dashed ${drag?"var(--blue)":file?"#22c55e":"var(--border2)"}`,
            borderRadius:8, padding:"40px 24px", textAlign:"center", cursor:"pointer",
            background: drag?"rgba(59,130,246,.04)":file?"rgba(34,197,94,.04)":"var(--surface)",
            transition:"all .15s",
          }}>
          <input ref={fileRef} type="file" accept=".xlsx,.xls" style={{display:"none"}}
            onChange={e=>handleDrop(e.target.files)}/>
          <div style={{fontSize:36,marginBottom:10}}>{file?"📊":"⬆"}</div>
          <div style={{fontSize:15,fontWeight:500,marginBottom:6}}>
            {file ? file.name : "Перетащите Excel-смету сюда"}
          </div>
          <div style={{fontSize:12,color:"var(--muted)"}}>
            {file ? `${(file.size/1024).toFixed(1)} KB · нажмите для замены` : "Поддерживаются .xlsx, .xls, .pdf · ГрандСмета, CourtDoc, PDF-сметы"}
          </div>
        </div>
      )}

      {/* Upload button */}
      {file && !status && (
        <button onClick={handleUpload} disabled={uploading || polling}
          style={{
            marginTop:16,width:"100%",padding:"11px",
            background:"var(--blue-dark)",color:"#fff",border:"none",
            borderRadius:6,fontSize:14,fontWeight:600,cursor:"pointer",
            opacity:(uploading||polling)?.7:1,
          }}>
          {uploading ? "Отправляем..." : "→ Загрузить и построить Ганта"}
        </button>
      )}

      {/* Polling states */}
      {(status === "pending" || status === "processing") && (
        <div style={{marginTop:16,padding:"14px 16px",background:"rgba(59,130,246,.06)",border:"1px solid rgba(59,130,246,.2)",borderRadius:6}}>
          <div style={{fontSize:13,color:"var(--blue-dark)",fontWeight:500}}>
            ⏳ {status === "pending" ? "В очереди..." : "Парсим смету и строим Ганта..."}
          </div>
          <div style={{fontSize:11,color:"var(--muted)",marginTop:4}}>Это займёт несколько секунд</div>
        </div>
      )}

      {status === "done" && result && (
        <div style={{marginTop:16,padding:"16px",background:"rgba(34,197,94,.06)",border:"1px solid rgba(34,197,94,.2)",borderRadius:6}}>
          <div style={{color:"#15803d",fontWeight:600,fontSize:14,marginBottom:10}}>✓ Смета успешно обработана</div>
          <div style={{display:"flex",gap:20,fontSize:12,color:"var(--muted)",flexWrap:"wrap"}}>
            {[
              ["Позиций сметы",   result.estimates_count],
              ["Задач в графике", result.gantt_tasks_count],
              ["Сумма",           result.total_price ? fmtMoney(result.total_price)+" ₽" : "—"],
              ["Стратегия",       result.strategy],
            ].map(([l,v])=><span key={l as string}>{l}: <b style={{color:"var(--text)",fontFamily:"var(--mono)"}}>{v}</b></span>)}
          </div>
          <button onClick={()=>router.push(`/projects/${id}/gantt`)}
            style={{marginTop:14,padding:"8px 18px",background:"var(--blue-dark)",color:"#fff",border:"none",borderRadius:5,fontSize:13,fontWeight:600,cursor:"pointer"}}>
            Открыть диаграмму Ганта →
          </button>
        </div>
      )}

      {status === "failed" && (
        <div style={{marginTop:16,padding:"14px 16px",background:"rgba(239,68,68,.06)",border:"1px solid rgba(239,68,68,.2)",borderRadius:6}}>
          <div style={{color:"var(--red)",fontWeight:600,fontSize:13}}>❌ Ошибка обработки</div>
          <div style={{fontSize:12,color:"var(--muted)",marginTop:4}}>{result?.error}</div>
          <button onClick={()=>{setJobId(null);setFile(null);}}
            style={{marginTop:10,padding:"6px 14px",border:"1px solid var(--border2)",borderRadius:4,background:"var(--surface)",fontSize:12,cursor:"pointer"}}>
            Попробовать снова
          </button>
        </div>
      )}

      {/* Supported formats */}
      <div style={{marginTop:24,background:"var(--surface)",border:"1px solid var(--border)",borderRadius:6,padding:16}}>
        <div style={{fontSize:10,color:"var(--muted)",textTransform:"uppercase",letterSpacing:".08em",marginBottom:10,fontFamily:"var(--mono)"}}>Поддерживаемые форматы</div>
        {[
          ["ГрандСмета / АРПС",  "Экспорт в Excel"],
          ["CourtDoc / A0",      "Табличный формат"],
          ["1С: Подрядчик",      "Выгрузка в .xlsx"],
          ["Excel вручную",      "Строчный и столбцовый"],
          ["КП подрядчика",      "Произвольная таблица"],
          ["PDF-смета",          ".pdf с табличным содержимым"],
        ].map(([name, desc]) => (
          <div key={name} style={{display:"flex",justifyContent:"space-between",padding:"6px 0",borderBottom:"1px solid var(--border)",fontSize:12}}>
            <span style={{fontWeight:500}}>{name}</span>
            <span style={{color:"var(--muted)",fontSize:11}}>{desc}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
