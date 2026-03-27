"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { estimates } from "@/lib/api";
import { fmtMoney } from "@/lib/dateUtils";

export default function EstimatePage() {
  const { id }     = useParams<{ id: string }>();
  const [rows,     setRows]    = useState<any[]>([]);
  const [summary,  setSummary] = useState<any>(null);
  const [loading,  setLoading] = useState(true);

  useEffect(() => {
    Promise.all([estimates.list(id), estimates.summary(id)])
      .then(([r, s]) => { setRows(r); setSummary(s); })
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div style={{padding:24,color:"var(--muted)"}}>Загрузка сметы...</div>;

  if (!rows.length) return (
    <div style={{padding:48,textAlign:"center",color:"var(--muted)"}}>
      <div style={{fontSize:32,marginBottom:12}}>📋</div>
      <div style={{fontSize:15,fontWeight:500}}>Смета ещё не загружена</div>
      <div style={{fontSize:13,marginTop:6}}>Перейдите на вкладку «Загрузить смету»</div>
    </div>
  );

  // Группируем по разделам
  const sections: Record<string, any[]> = {};
  for (const row of rows) {
    const sec = row.section ?? "Без раздела";
    (sections[sec] ??= []).push(row);
  }

  return (
    <div style={{padding:16,height:"100%",overflow:"auto"}}>
      {/* Summary */}
      {summary && (
        <div style={{display:"flex",gap:12,marginBottom:16,flexWrap:"wrap"}}>
          <div style={{background:"var(--surface)",border:"1px solid var(--border)",borderRadius:6,padding:"12px 16px"}}>
            <div style={{fontSize:10,color:"var(--muted)",textTransform:"uppercase",letterSpacing:".06em",marginBottom:4}}>Итого по смете</div>
            <div style={{fontSize:20,fontWeight:700,fontFamily:"var(--mono)",color:"var(--blue-dark)"}}>{fmtMoney(summary.total)} ₽</div>
          </div>
          {summary.sections?.map((s: any) => (
            <div key={s.name} style={{background:"var(--surface)",border:"1px solid var(--border)",borderRadius:6,padding:"12px 16px"}}>
              <div style={{fontSize:10,color:"var(--muted)",marginBottom:4}}>{s.name}</div>
              <div style={{fontSize:14,fontWeight:600,fontFamily:"var(--mono)"}}>{fmtMoney(s.subtotal)} ₽</div>
              <div style={{fontSize:10,color:"var(--muted)"}}>{s.items} позиций</div>
            </div>
          ))}
        </div>
      )}

      {/* Table */}
      <div style={{background:"var(--surface)",border:"1px solid var(--border)",borderRadius:6,overflow:"hidden"}}>
        <table style={{width:"100%",borderCollapse:"collapse",fontSize:12}}>
          <thead>
            <tr style={{background:"#1e293b"}}>
              {["Наименование работ","Ед.","Кол-во","Цена за ед., ₽","Сумма, ₽"].map(h => (
                <th key={h} style={{
                  padding:"9px 12px",textAlign:h==="Наименование работ"?"left":"right",
                  fontSize:10,color:"#94a3b8",textTransform:"uppercase",letterSpacing:".06em",
                  fontFamily:"var(--mono)",fontWeight:400,borderRight:"1px solid #334155",whiteSpace:"nowrap",
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(sections).map(([section, sRows]) => [
              <tr key={`s-${section}`}>
                <td colSpan={4} style={{padding:"8px 12px",fontWeight:600,fontSize:11,background:"rgba(59,130,246,.06)",color:"var(--blue-dark)",letterSpacing:".03em"}}>{section}</td>
                <td style={{padding:"8px 12px",textAlign:"right",fontFamily:"var(--mono)",fontSize:11,background:"rgba(59,130,246,.06)",fontWeight:600}}>
                  {fmtMoney(sRows.reduce((s,r)=>s+(r.total_price??0),0))}
                </td>
              </tr>,
              ...sRows.map((row: any, i) => (
                <tr key={row.id} style={{background:i%2?"var(--stripe)":""}}>
                  <td style={{padding:"8px 12px",borderBottom:"1px solid var(--border)"}}>{row.work_name}</td>
                  <td style={{padding:"8px 12px",borderBottom:"1px solid var(--border)",textAlign:"right",color:"var(--muted)",fontFamily:"var(--mono)"}}>{row.unit}</td>
                  <td style={{padding:"8px 12px",borderBottom:"1px solid var(--border)",textAlign:"right",fontFamily:"var(--mono)"}}>{row.quantity?.toLocaleString("ru")}</td>
                  <td style={{padding:"8px 12px",borderBottom:"1px solid var(--border)",textAlign:"right",fontFamily:"var(--mono)"}}>{fmtMoney(row.unit_price)}</td>
                  <td style={{padding:"8px 12px",borderBottom:"1px solid var(--border)",textAlign:"right",fontFamily:"var(--mono)",fontWeight:500}}>{fmtMoney(row.total_price)}</td>
                </tr>
              ))
            ])}
            <tr style={{background:"#f1f5f9",fontWeight:700}}>
              <td colSpan={4} style={{padding:"10px 12px",textAlign:"right",fontSize:11,color:"var(--muted)",letterSpacing:".06em"}}>ИТОГО</td>
              <td style={{padding:"10px 12px",textAlign:"right",fontFamily:"var(--mono)",fontSize:15,color:"var(--blue-dark)"}}>
                {fmtMoney(summary?.total ?? rows.reduce((s,r)=>s+(r.total_price??0),0))} ₽
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
