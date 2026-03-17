"use client";
import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useParams } from "next/navigation";
import { gantt as ganttApi, comments as commentsApi } from "@/lib/api";

const DAY_W = 24;
const ROW_H = 32;

const z    = n => String(n).padStart(2,'0');
const pd   = s => { const [y,m,d]=s.split('-'); return new Date(+y,+m-1,+d); };
const fd   = d => `${d.getFullYear()}-${z(d.getMonth()+1)}-${z(d.getDate())}`;
const addD = (s,n) => { const d=new Date(pd(s)); d.setDate(d.getDate()+n); return fd(d); };
const diff = (a,b) => Math.round((pd(b)-pd(a))/86400000);
const dispD= s => { const d=pd(s); return `${z(d.getDate())}.${z(d.getMonth()+1)}`; };
const MONTHS=['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];

let _uid = 300;
const uid = () => String(++_uid);

// ─── Topological date propagation ────────────────────────────────────────────
// depends_on = comma-separated task IDs. Start = max(end of all predecessors).
function parseDeps(depends_on) {
  if (!depends_on) return [];
  return depends_on.split(',').map(s=>s.trim()).filter(Boolean);
}

function resolveDates(tasks) {
  const resMap = Object.fromEntries(tasks.map(t => [t.id, {...t}]));
  const result = tasks.map(t => resMap[t.id]);
  const visited = new Set();
  const resolving = new Set();

  const resolve = (id) => {
    if (visited.has(id) || resolving.has(id)) return;
    resolving.add(id);
    const task = resMap[id];
    const depIds = parseDeps(task?.depends_on);
    depIds.forEach(depId => {
      if (resMap[depId]) {
        resolve(depId);
        const predEnd = addD(resMap[depId].start, resMap[depId].dur);
        if (diff(task.start, predEnd) > 0) task.start = predEnd;
      }
    });
    resolving.delete(id);
    visited.add(id);
  };

  result.forEach(t => resolve(t.id));
  return result;
}

// ─── Initial data ─────────────────────────────────────────────────────────────
const INIT_TASKS = resolveDates([
  {id:'1', pid:null,depends_on:null,name:'Подготовительные работы',    start:'2026-03-02',dur:7, prog:100,clr:'#6366f1'},
  {id:'2', pid:'1', depends_on:null,name:'Разбивка осей здания',        start:'2026-03-02',dur:2, prog:100,clr:'#6366f1'},
  {id:'3', pid:'1', depends_on:null,name:'Ограждение площадки',         start:'2026-03-02',dur:3, prog:100,clr:'#6366f1'},
  {id:'4', pid:'1', depends_on:'3', name:'Завоз стройматериалов',       start:'2026-03-02',dur:5, prog:100,clr:'#6366f1'},

  {id:'5', pid:null,depends_on:'1', name:'Земляные работы',             start:'2026-03-02',dur:10,prog:100,clr:'#d97706'},
  {id:'6', pid:'5', depends_on:null,name:'Разработка грунта ковшом',    start:'2026-03-02',dur:6, prog:100,clr:'#d97706'},
  {id:'7', pid:'5', depends_on:'6', name:'Ручная доработка',            start:'2026-03-02',dur:3, prog:100,clr:'#d97706'},
  {id:'8', pid:'5', depends_on:'6', name:'Вывоз грунта',                start:'2026-03-02',dur:2, prog:100,clr:'#d97706'},
  {id:'9', pid:'5', depends_on:'7', name:'Уплотнение основания',        start:'2026-03-02',dur:2, prog:100,clr:'#d97706'},

  {id:'10',pid:null,depends_on:'5', name:'Фундамент',                   start:'2026-03-02',dur:22,prog:70, clr:'#dc2626'},
  {id:'11',pid:'10',depends_on:null,name:'Щебёночная подготовка 100мм', start:'2026-03-02',dur:3, prog:100,clr:'#dc2626'},
  {id:'12',pid:'10',depends_on:'11',name:'Армирование ф-та Ø12 А500С',  start:'2026-03-02',dur:7, prog:100,clr:'#dc2626'},
  {id:'13',pid:'10',depends_on:'11',name:'Опалубка фундаментной плиты', start:'2026-03-02',dur:4, prog:80, clr:'#dc2626'},
  {id:'14',pid:'10',depends_on:'12',name:'Бетонирование B25 W6',        start:'2026-03-02',dur:2, prog:60, clr:'#dc2626'},
  {id:'15',pid:'10',depends_on:'14',name:'Выдержка бетона (28 сут.)',   start:'2026-03-02',dur:8, prog:0,  clr:'#dc2626'},

  {id:'16',pid:null,depends_on:'10',name:'Стены и перекрытия',          start:'2026-03-02',dur:26,prog:0,  clr:'#0284c7'},
  {id:'17',pid:'16',depends_on:null,name:'Кладка газобетон 1-й этаж',   start:'2026-03-02',dur:10,prog:0,  clr:'#0284c7'},
  {id:'18',pid:'16',depends_on:'17',name:'Армопояс 1-го этажа',         start:'2026-03-02',dur:3, prog:0,  clr:'#0284c7'},
  {id:'19',pid:'16',depends_on:'18',name:'Монтаж плит перекрытия',      start:'2026-03-02',dur:3, prog:0,  clr:'#0284c7'},
  {id:'20',pid:'16',depends_on:'19',name:'Кладка газобетон 2-й этаж',   start:'2026-03-02',dur:10,prog:0,  clr:'#0284c7'},
  {id:'21',pid:'16',depends_on:'20',name:'Армопояс под мауэрлат',       start:'2026-03-02',dur:3, prog:0,  clr:'#0284c7'},

  {id:'22',pid:null,depends_on:'16',name:'Кровля',                      start:'2026-03-02',dur:18,prog:0,  clr:'#0f766e'},
  {id:'23',pid:'22',depends_on:null,name:'Монтаж мауэрлата',            start:'2026-03-02',dur:2, prog:0,  clr:'#0f766e'},
  {id:'24',pid:'22',depends_on:'23',name:'Стропильная система',         start:'2026-03-02',dur:7, prog:0,  clr:'#0f766e'},
  {id:'25',pid:'22',depends_on:'24',name:'Гидроизоляция кровли',        start:'2026-03-02',dur:3, prog:0,  clr:'#0f766e'},
  {id:'26',pid:'22',depends_on:'24',name:'Утеплитель (минвата 200мм)',  start:'2026-03-02',dur:3, prog:0,  clr:'#0f766e'},
  {id:'27',pid:'22',depends_on:'25',name:'Металлочерепица',             start:'2026-03-02',dur:4, prog:0,  clr:'#0f766e'},
  {id:'28',pid:'22',depends_on:'27',name:'Водосточная система',         start:'2026-03-02',dur:2, prog:0,  clr:'#0f766e'},

  {id:'29',pid:null,depends_on:'22',name:'Инженерные сети',             start:'2026-03-02',dur:25,prog:0,  clr:'#7c3aed'},
  {id:'30',pid:'29',depends_on:null,name:'Электромонтаж (скрытый)',     start:'2026-03-02',dur:10,prog:0,  clr:'#7c3aed'},
  {id:'31',pid:'29',depends_on:null,name:'Система отопления',           start:'2026-03-02',dur:12,prog:0,  clr:'#7c3aed'},
  {id:'32',pid:'29',depends_on:null,name:'Водоснабжение',               start:'2026-03-02',dur:8, prog:0,  clr:'#7c3aed'},
  {id:'33',pid:'29',depends_on:'32',name:'Канализация',                 start:'2026-03-02',dur:8, prog:0,  clr:'#7c3aed'},
  {id:'34',pid:'29',depends_on:'30',name:'Вентиляция',                  start:'2026-03-02',dur:7, prog:0,  clr:'#7c3aed'},

  {id:'35',pid:null,depends_on:'29',name:'Окна и двери',                start:'2026-03-02',dur:8, prog:0,  clr:'#0369a1'},
  {id:'36',pid:'35',depends_on:null,name:'Монтаж оконных блоков',       start:'2026-03-02',dur:4, prog:0,  clr:'#0369a1'},
  {id:'37',pid:'35',depends_on:'36',name:'Монтаж входной группы',       start:'2026-03-02',dur:2, prog:0,  clr:'#0369a1'},
  {id:'38',pid:'35',depends_on:'37',name:'Внутренние двери',            start:'2026-03-02',dur:2, prog:0,  clr:'#0369a1'},

  {id:'39',pid:null,depends_on:'35',name:'Фасад и утепление',           start:'2026-03-02',dur:20,prog:0,  clr:'#b45309'},
  {id:'40',pid:'39',depends_on:null,name:'Грунтование стен',            start:'2026-03-02',dur:3, prog:0,  clr:'#b45309'},
  {id:'41',pid:'39',depends_on:'40',name:'Монтаж утеплителя (ЭППС)',    start:'2026-03-02',dur:7, prog:0,  clr:'#b45309'},
  {id:'42',pid:'39',depends_on:'41',name:'Армирующий слой',             start:'2026-03-02',dur:4, prog:0,  clr:'#b45309'},
  {id:'43',pid:'39',depends_on:'42',name:'Декоративная штукатурка',     start:'2026-03-02',dur:6, prog:0,  clr:'#b45309'},

  {id:'44',pid:null,depends_on:'39',name:'Внутренняя отделка',          start:'2026-03-02',dur:35,prog:0,  clr:'#059669'},
  {id:'45',pid:'44',depends_on:null,name:'Штукатурка стен машинная',    start:'2026-03-02',dur:12,prog:0,  clr:'#059669'},
  {id:'46',pid:'44',depends_on:'45',name:'Стяжка пола (60мм)',          start:'2026-03-02',dur:7, prog:0,  clr:'#059669'},
  {id:'47',pid:'44',depends_on:'46',name:'Плитка (санузлы, кухня)',     start:'2026-03-02',dur:10,prog:0,  clr:'#059669'},
  {id:'48',pid:'44',depends_on:'46',name:'Поклейка обоев',              start:'2026-03-02',dur:8, prog:0,  clr:'#059669'},
  {id:'49',pid:'44',depends_on:'47',name:'Чистовой пол (ламинат)',      start:'2026-03-02',dur:6, prog:0,  clr:'#059669'},
  {id:'50',pid:'44',depends_on:'48',name:'Потолки (гипсокартон)',       start:'2026-03-02',dur:8, prog:0,  clr:'#059669'},
]);

// ─── Tree helpers ─────────────────────────────────────────────────────────────
function getDepth(tasks,id,d=0){const t=tasks.find(x=>x.id===id);if(!t?.pid)return d;return getDepth(tasks,t.pid,d+1);}

function getVisibleRows(tasks,collapsed){
  const rows=[];
  // Build children map for fast lookup
  const childMap={};
  tasks.forEach(t=>{
    const p=t.pid??'__root__';
    if(!childMap[p]) childMap[p]=[];
    childMap[p].push(t);
  });
  // Depth-first traversal — children always appear right after parent
  const visit=(id,depth)=>{
    const t=tasks.find(x=>x.id===id);
    if(!t) return;
    const kids=childMap[id]||[];
    rows.push({...t,depth,hasKids:kids.length>0,isOpen:!collapsed.has(id)});
    if(!collapsed.has(id)) kids.forEach(k=>visit(k.id,depth+1));
  };
  (childMap['__root__']||[]).forEach(t=>visit(t.id,0));
  return rows;
}

function getAllDescendants(tasks,id){
  const res=[],q=[id];
  while(q.length){const c=q.shift();tasks.filter(t=>t.pid===c).forEach(k=>{res.push(k.id);q.push(k.id);});}
  return res;
}

// ─── ROLES ───────────────────────────────────────────────────────────────────
type RoleKey = 'owner'|'pm'|'foreman'|'supplier'|'viewer';
const ROLES: Record<RoleKey,{label:string;color:string;can:string[]}> = {
  owner:    { label:'Владелец',           color:'#7c3aed', can: ['view','edit','delete','comment','manage_users','manage_projects'] },
  pm:       { label:'Рук. проекта',       color:'#0284c7', can: ['view','edit','comment','manage_projects'] },
  foreman:  { label:'Прораб',             color:'#d97706', can: ['view','edit_progress','comment'] },
  supplier: { label:'Снабженец',          color:'#059669', can: ['view','comment'] },
  viewer:   { label:'Наблюдатель',        color:'#64748b', can: ['view'] },
};
const can = (role: RoleKey, action: string) => ROLES[role]?.can.includes(action) ?? false;

// ─── MOCK COMMENTS ────────────────────────────────────────────────────────────
// { taskId → [{id, author, role, text, ts}] }
const INIT_COMMENTS = {
  '12': [
    {id:'c1', author:'Козлов А.В.',  role:'pm',      text:'Армирование начали в срок, диаметр прутка проверен — соответствует проекту.',       ts:'10.03 09:14'},
    {id:'c2', author:'Петров В.С.',  role:'foreman', text:'Бригада 2 в полном составе. Расход арматуры чуть выше нормы — закажи 0.3т дополнительно.', ts:'10.03 11:42'},
    {id:'c3', author:'Иванов А.',    role:'viewer',  text:'Сфоткал ход работ, прикладываю к отчёту.', ts:'11.03 08:30'},
  ],
  '14': [
    {id:'c4', author:'Бетонщик Р.',  role:'foreman', text:'Бетон B25 W6 принят, накладная № 447. Начали заливку в 08:00.', ts:'28.03 08:15'},
  ],
  '6': [
    {id:'c5', author:'Механизатор', role:'foreman', text:'Экскаватор вышел из строя в 14:00, ремонт ~2 часа. Сдвиг не критичный.', ts:'11.03 14:05'},
  ],
};

let _cuid = 100;
const cuid = () => 'c'+(++_cuid);

// ─── CSS ─────────────────────────────────────────────────────────────────────
const CSS=`
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
:root{
  --surface:#fff;--border:#e2e8f0;--hdr:#0f172a;--hdr2:#1e293b;--hdr3:#334155;
  --text:#1e293b;--muted:#64748b;--blue:#3b82f6;
  --sel:#e0f2fe;--sel-b:#38bdf8;--today:#f97316;--stripe:#f8fafc;
  --dep-c:#a855f7;--mono:'JetBrains Mono',monospace;--sans:'DM Sans',sans-serif;
}
body,html,#root{height:100%;font-family:var(--sans);color:var(--text);background:#f1f5f9;}
::-webkit-scrollbar{width:8px;height:8px;}
::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:4px;border:2px solid transparent;background-clip:padding-box;}
::-webkit-scrollbar-thumb:hover{background:#94a3b8;}
::-webkit-scrollbar-track{background:transparent;}

.root{display:flex;flex-direction:column;height:100vh;overflow:hidden;}

/* toolbar */
.tb{height:42px;min-height:42px;background:var(--hdr);display:flex;align-items:center;padding:0 10px;gap:2px;border-bottom:1px solid #0f172a;flex-shrink:0;user-select:none;}
.tb-sep{width:1px;height:20px;background:var(--hdr3);margin:0 5px;}
.btn{display:flex;align-items:center;gap:4px;padding:5px 10px;border-radius:4px;border:none;cursor:pointer;font-size:12px;font-weight:500;font-family:var(--sans);background:transparent;color:#94a3b8;transition:all .12s;}
.btn:hover{background:var(--hdr2);color:#e2e8f0;}
.btn.p{background:#1d4ed8;color:#fff;}
.btn.p:hover{background:#2563eb;}
.btn:disabled{opacity:.3;cursor:not-allowed;}
.btn.danger{color:#f87171;}
.hint{font-size:10px;color:#475569;font-family:var(--mono);padding:0 6px;}
.pname{margin-left:auto;font-size:13px;font-weight:600;color:#e2e8f0;padding:4px 12px;border-radius:4px;background:var(--hdr2);border:1px solid var(--hdr3);cursor:pointer;}

/* split */
.split{display:flex;flex:1;overflow:hidden;}
.splitter{width:4px;min-width:4px;background:#e2e8f0;cursor:col-resize;flex-shrink:0;transition:background .15s;}
.splitter:hover,.splitter.drag{background:var(--blue);}

/* left */
.left{display:flex;flex-direction:column;background:var(--surface);border-right:2px solid var(--hdr);flex-shrink:0;}
.thead{background:var(--hdr2);display:flex;align-items:stretch;border-bottom:1px solid var(--hdr3);flex-shrink:0;height:52px;padding-right:8px;}
.th{display:flex;align-items:center;padding:0 7px;font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.07em;font-family:var(--mono);border-right:1px solid var(--hdr3);white-space:nowrap;flex-shrink:0;}
.th.g{flex:1;}
.tbody{flex:1;overflow-y:scroll;overflow-x:hidden;}

/* rows */
.tr{display:flex;align-items:center;height:32px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .07s;position:relative;}
.tr.even{background:var(--stripe);}
.tr:hover{background:#f0f9ff;}
.tr.sel{background:var(--sel)!important;outline:1px solid var(--sel-b);outline-offset:-1px;z-index:1;}
.tr.par{font-weight:600;}

/* cells */
.td{display:flex;align-items:center;padding:0 6px;font-size:12px;flex-shrink:0;overflow:hidden;border-right:1px solid var(--border);height:100%;}
.td.g{flex:1;min-width:0;}
.td.c{justify-content:center;}
.td.mn{font-family:var(--mono);font-size:11px;}
.td input{width:100%;border:none;outline:none;background:transparent;font-family:inherit;font-size:inherit;font-weight:inherit;color:inherit;}
.td.ed{background:#fff!important;outline:2px solid var(--blue);outline-offset:-1px;z-index:2;}
.td.ed-dep{background:#fff!important;outline:2px solid var(--dep-c);outline-offset:-1px;z-index:2;}

/* tree */
.tcell{display:flex;align-items:center;min-width:0;flex:1;}
.tog{width:16px;height:16px;flex-shrink:0;display:flex;align-items:center;justify-content:center;border-radius:3px;font-size:9px;color:var(--muted);cursor:pointer;}
.tog:hover{background:var(--border);}
.sp{width:16px;flex-shrink:0;}
.nt{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;}

/* dep chip */
.chip{display:inline-flex;align-items:center;padding:1px 7px;border-radius:10px;font-size:10px;font-family:var(--mono);font-weight:500;background:rgba(168,85,247,.1);color:#7c3aed;border:1px solid rgba(168,85,247,.25);}
.chip.e{color:var(--muted);background:transparent;border-color:transparent;font-weight:400;}

/* prog */
.pb{width:100%;height:5px;background:#e2e8f0;border-radius:3px;overflow:hidden;}
.pf{height:100%;border-radius:3px;background:var(--blue);transition:width .3s;}
.pf.ok{background:#22c55e;}
.pf.mid{background:#f59e0b;}
.rn{width:30px;min-width:30px;justify-content:center;color:var(--muted);font-family:var(--mono);font-size:10px;}

/* right / gantt */
.right{display:flex;flex-direction:column;flex:1;overflow:hidden;background:var(--surface);}
.ghdr{height:52px;min-height:52px;overflow:hidden;background:var(--hdr2);border-bottom:1px solid var(--hdr3);flex-shrink:0;}
.mr{display:flex;height:26px;border-bottom:1px solid var(--hdr3);}
.mc{display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:#cbd5e1;border-right:1px solid var(--hdr3);flex-shrink:0;}
.wr{display:flex;height:26px;}
.wc{display:flex;align-items:center;justify-content:center;font-size:10px;color:#64748b;border-right:1px solid #1e293b;flex-shrink:0;font-family:var(--mono);}
.gbw{flex:1;overflow:scroll;position:relative;}
.gb{position:relative;}
.gl{position:absolute;top:0;bottom:0;width:1px;background:var(--border);pointer-events:none;}
.gl.m{background:#e2e8f0;}
.gr{position:relative;height:32px;display:flex;align-items:center;border-bottom:1px solid var(--border);}
.gr.even{background:var(--stripe);}
.gr.sel{background:var(--sel)!important;}
.tl{position:absolute;top:0;bottom:0;width:1px;background:var(--today);z-index:20;pointer-events:none;}
.tlb{position:absolute;top:2px;transform:translateX(-50%);background:var(--today);color:#fff;font-size:9px;font-family:var(--mono);padding:2px 4px;border-radius:2px;white-space:nowrap;z-index:21;}
.bw{position:absolute;top:50%;transform:translateY(-50%);}
.bar{border-radius:3px;overflow:hidden;position:relative;display:flex;align-items:center;cursor:pointer;background:#fff;}
.bar:hover{box-shadow:0 2px 6px rgba(0,0,0,.18);}
.bar.par{border-radius:2px;}
.bp{position:absolute;left:0;top:0;bottom:0;border-radius:3px 0 0 3px;}
.bl{position:relative;padding:0 6px;font-size:10px;color:rgba(255,255,255,.9);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-family:var(--sans);font-weight:500;z-index:1;}
.darr{position:absolute;top:0;left:0;pointer-events:none;z-index:15;overflow:visible;}

/* ── TASK DETAIL PANEL ─────────────────────────────────────────────────────── */
.panel-overlay{position:fixed;inset:0;background:rgba(15,23,42,.35);z-index:100;display:flex;justify-content:flex-end;}
.panel{
  width:420px;height:100%;background:#fff;box-shadow:-4px 0 24px rgba(0,0,0,.15);
  display:flex;flex-direction:column;animation:slideIn .2s ease;
}
@keyframes slideIn{from{transform:translateX(100%)}to{transform:translateX(0)}}
.panel-hdr{
  padding:16px 20px 12px;border-bottom:1px solid var(--border);
  display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-shrink:0;
}
.panel-title{font-size:15px;font-weight:700;line-height:1.3;color:var(--text);flex:1;}
.panel-close{
  width:28px;height:28px;border:none;background:none;cursor:pointer;
  display:flex;align-items:center;justify-content:center;border-radius:4px;
  font-size:16px;color:var(--muted);flex-shrink:0;
}
.panel-close:hover{background:var(--border);}
.panel-body{flex:1;overflow-y:auto;padding:16px 20px;}
.panel-section{margin-bottom:20px;}
.panel-section-title{
  font-size:10px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--muted);font-family:var(--mono);margin-bottom:8px;
}
.panel-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.pfield{background:var(--stripe);border:1px solid var(--border);border-radius:6px;padding:8px 10px;}
.pfield-label{font-size:10px;color:var(--muted);margin-bottom:2px;font-family:var(--mono);}
.pfield-val{font-size:13px;font-weight:500;}
.pfield-val.mono{font-family:var(--mono);}
.prog-big{margin-top:4px;height:6px;background:#e2e8f0;border-radius:3px;overflow:hidden;}
.prog-big-fill{height:100%;border-radius:3px;transition:width .3s;}

/* color bar on top */
.panel-color-bar{height:3px;flex-shrink:0;}

/* comments */
.comments{display:flex;flex-direction:column;gap:8px;}
.comment{
  background:var(--stripe);border:1px solid var(--border);border-radius:8px;
  padding:10px 12px;
}
.comment-hdr{display:flex;align-items:center;gap:8px;margin-bottom:5px;}
.comment-avatar{
  width:24px;height:24px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-size:10px;font-weight:700;color:#fff;flex-shrink:0;
}
.comment-author{font-size:12px;font-weight:600;}
.comment-role{font-size:10px;padding:1px 6px;border-radius:10px;font-family:var(--mono);}
.comment-ts{font-size:10px;color:var(--muted);margin-left:auto;font-family:var(--mono);}
.comment-text{font-size:12px;line-height:1.5;color:var(--text);}

/* comment input */
.comment-input-wrap{
  border-top:1px solid var(--border);padding:12px 20px;flex-shrink:0;
  display:flex;flex-direction:column;gap:8px;
}
.comment-textarea{
  width:100%;border:1px solid var(--border2);border-radius:6px;
  padding:8px 10px;font-family:var(--sans);font-size:12px;color:var(--text);
  resize:none;outline:none;transition:border-color .15s;min-height:60px;
}
.comment-textarea:focus{border-color:var(--blue);}
.comment-submit{
  align-self:flex-end;padding:6px 14px;background:var(--blue);color:#fff;
  border:none;border-radius:4px;font-size:12px;font-weight:500;cursor:pointer;
  font-family:var(--sans);transition:background .15s;
}
.comment-submit:hover{background:#2563eb;}
.comment-submit:disabled{opacity:.4;cursor:not-allowed;}
.no-comments{font-size:12px;color:var(--muted);text-align:center;padding:16px 0;}

/* ── ROLE SWITCHER ─────────────────────────────────────────────────────────── */
.role-bar{
  display:flex;align-items:center;gap:6px;padding:0 12px;
  background:var(--hdr2);border-bottom:1px solid var(--hdr3);
  height:32px;flex-shrink:0;
}
.role-label{font-size:10px;color:#64748b;font-family:var(--mono);text-transform:uppercase;letter-spacing:.06em;}
.role-btn{
  padding:3px 10px;border-radius:3px;border:1px solid transparent;
  font-size:11px;font-weight:500;cursor:pointer;font-family:var(--sans);
  background:transparent;color:#64748b;transition:all .12s;
}
.role-btn:hover{background:#334155;color:#e2e8f0;}
.role-btn.active{color:#fff;border-color:transparent;}
.role-access-hint{
  margin-left:auto;font-size:10px;color:#475569;font-family:var(--mono);
}
/* locked overlay */
.locked{opacity:.45;pointer-events:none;cursor:not-allowed!important;}
`;

// ─── Component ────────────────────────────────────────────────────────────────
export default function App() {
  const params  = useParams<{id: string}>();
  const pid     = params?.id ?? "";

  // Map API fields -> local field names used in Gantt
  const apiToLocal = (t: any) => ({
    ...t,
    pid:   t.parent_id,
    dur:   t.working_days,
    start: t.start_date,
    prog:  t.progress,
    clr:   t.color ?? "#3b82f6",
    who:   t.assignee?.name ?? "—",
    depends_on: t.depends_on ?? "",   // already comma-string from API
  });

  const [tasks,    setTasks]    = useState([]);
  const [apiLoaded, setApiLoaded] = useState(false);
  const [coll,     setColl]     = useState(new Set());
  const [sel,      setSel]      = useState('1');
  const [editing,  setEditing]  = useState(null);
  const [editVal,  setEditVal]  = useState('');
  const [leftW,    setLeftW]    = useState(560);
  const [pname,    setPname]    = useState('Коттедж Петровых — ул. Солнечная, 5');
  const [editP,    setEditP]    = useState(false);
  // roles
  const [role,     setRole]     = useState<RoleKey>('pm');
  // task detail panel
  const [panelId,  setPanelId]  = useState(null);
  // comments: { taskId: [{id,author,role,text,ts}] }
  const [comments, setComments] = useState(INIT_COMMENTS);
  const [newComment, setNewComment] = useState('');

  const lbRef = useRef(); // left body
  const rbRef = useRef(); // right body
  const rhRef = useRef(); // right header (h-scroll sync)
  const splRef= useRef();
  const drg   = useRef(false);
  const ssync = useRef(false);
  const inpRef= useRef();

  // Load tasks from API
  useEffect(() => {
    if (!pid) return;
    // Reset state when project changes
    setTasks([]);
    setColl(new Set());
    setSel(null);
    setApiLoaded(false);
    ganttApi.list(pid).then(data => {
      if (data?.tasks?.length) {
        const loaded = resolveDates(data.tasks.map(apiToLocal));
        setTasks(loaded);
        setApiLoaded(true);
        setSel(data.tasks[0]?.id ?? null);
      } else {
        setTasks([]);
        setApiLoaded(true);
      }
    }).catch(() => {
      setTasks([]);
      setApiLoaded(true);
    });
  }, [pid]);

  const TODAY = '2026-03-13';

  const submitComment = useCallback(() => {
    if (!newComment.trim() || !panelId) return;
    const now = new Date();
    const ts = `${z(now.getDate())}.${z(now.getMonth()+1)} ${z(now.getHours())}:${z(now.getMinutes())}`;
    const NAMES = {owner:'Директор',pm:'Козлов А.В.',foreman:'Прораб',supplier:'Снабженец',viewer:'Наблюдатель'};
    setComments(c=>({...c,[panelId]:[...(c[panelId]||[]),{id:cuid(),author:NAMES[role],role,text:newComment.trim(),ts}]}));
    setNewComment('');
  },[newComment,panelId,role]);

  const panelTask = tasks.find(t=>t.id===panelId);

  const rows = useMemo(()=>getVisibleRows(tasks,coll),[tasks,coll]);

  // map task id → visible row number (1-based)
  const numMap = useMemo(()=>{
    const m={};rows.forEach((r,i)=>m[r.id]=i+1);return m;
  },[rows]);

  // gantt bounds
  const {origin,totalDays} = useMemo(()=>{
    if(!tasks.length) return {origin:'2026-01-01',totalDays:180};
    const s=tasks.map(t=>t.start),e=tasks.map(t=>addD(t.start,t.dur));
    const mn=s.reduce((a,b)=>a<b?a:b),mx=e.reduce((a,b)=>a>b?a:b);
    const o=fd(new Date(pd(mn).getTime()-7*86400000));
    return {origin:o,totalDays:diff(o,mx)+14};
  },[tasks]);

  const W = totalDays*DAY_W;

  // month/week bands
  const {mb,wb} = useMemo(()=>{
    const months=[],weeks=[];
    const od=pd(origin);
    let c=new Date(od.getFullYear(),od.getMonth(),1);
    while(true){
      const n=new Date(c.getFullYear(),c.getMonth()+1,1);
      const s=Math.max(0,diff(origin,fd(c))),e=Math.min(totalDays,diff(origin,fd(n)));
      if(s<e) months.push({label:MONTHS[c.getMonth()]+' '+c.getFullYear(),x:s*DAY_W,w:(e-s)*DAY_W});
      c=n;if(diff(origin,fd(c))>=totalDays)break;
    }
    for(let d=0;d<totalDays;d+=7) weeks.push({x:d*DAY_W,w:7*DAY_W,label:dispD(addD(origin,d))});
    return {mb:months,wb:weeks};
  },[origin,totalDays]);

  // grid lines
  const gridLines = useMemo(()=>{
    const ls=[];
    for(let d=0;d<totalDays;d+=7) ls.push({x:d*DAY_W,m:false});
    const od=pd(origin);let c=new Date(od.getFullYear(),od.getMonth(),1);
    while(true){const n=new Date(c.getFullYear(),c.getMonth()+1,1);const dx=diff(origin,fd(n));if(dx>=totalDays)break;if(dx>0)ls.push({x:dx*DAY_W,m:true});c=n;}
    return ls;
  },[origin,totalDays]);

  const todayX = diff(origin,TODAY)*DAY_W;

  // dependency arrows — one per (predecessor → successor) pair
  const arrows = useMemo(()=>{
    const a=[];
    rows.forEach((row,ri)=>{
      parseDeps(row.depends_on).forEach(depId=>{
        const pi=rows.findIndex(r=>r.id===depId);
        if(pi<0) return;
        const pred=rows[pi];
        const x1=(diff(origin,pred.start)+pred.dur)*DAY_W;
        const y1=pi*ROW_H+ROW_H/2;
        const x2=diff(origin,row.start)*DAY_W;
        const y2=ri*ROW_H+ROW_H/2;
        a.push({x1,y1,x2,y2});
      });
    });
    return a;
  },[rows,origin]);

  // scroll sync
  const onRS=useCallback(()=>{
    if(ssync.current)return;ssync.current=true;
    if(lbRef.current) lbRef.current.scrollTop=rbRef.current.scrollTop;
    if(rhRef.current) rhRef.current.scrollLeft=rbRef.current.scrollLeft;
    ssync.current=false;
  },[]);
  const onLS=useCallback(()=>{
    if(ssync.current)return;ssync.current=true;
    if(rbRef.current) rbRef.current.scrollTop=lbRef.current.scrollTop;
    ssync.current=false;
  },[]);

  // splitter drag
  useEffect(()=>{
    const mv=e=>{if(!drg.current)return;setLeftW(Math.max(280,Math.min(900,e.clientX)));};
    const up=()=>{drg.current=false;splRef.current?.classList.remove('drag');};
    window.addEventListener('mousemove',mv);window.addEventListener('mouseup',up);
    return()=>{window.removeEventListener('mousemove',mv);window.removeEventListener('mouseup',up);};
  },[]);

  // editing helpers
  const startEdit=(id,field,val)=>{
    setEditing({id,field});setEditVal(String(val??''));
    setTimeout(()=>{inpRef.current?.focus();inpRef.current?.select();},10);
  };

  const applyAndClose=useCallback((id,field,raw)=>{
    let v=raw;
    if(field==='dur') v=Math.max(1,parseInt(v)||1);
    if(field==='prog') v=Math.max(0,Math.min(100,parseInt(v)||0));
    if(field==='depends_on'){
      v=v.trim();
      if(v===''||v==='-'||v==='—') v=null;
      else{
        // accept comma-separated row numbers or IDs, e.g. "3,5" or "id1,id2"
        const parts=v.split(',').map(s=>s.trim()).filter(Boolean);
        const resolved=parts.map(p=>{
          const num=parseInt(p);
          if(!isNaN(num)&&num>=1&&num<=rows.length) return rows[num-1].id;
          if(tasks.some(t=>t.id===p)) return p;
          return null;
        }).filter(x=>x&&x!==id); // drop nulls and self-deps
        v=resolved.length>0?resolved.join(','):null;
      }
    }
    setTasks(ts=>resolveDates(ts.map(t=>t.id===id?{...t,[field]:v}:t)));
    setEditing(null);
    // Sync to API if loaded from server
    if (pid) {
      const apiField: Record<string,string> = {dur:'working_days', start:'start_date', prog:'progress'};
      const af = apiField[field] ?? field;
      ganttApi.update(pid, id, {[af]: v}).catch(()=>{});
    }
  },[rows,tasks,pid]);

  const commit=useCallback(()=>{
    if(!editing)return;
    applyAndClose(editing.id,editing.field,editVal);
  },[editing,editVal,applyAndClose]);

  // add sibling task after given id
  const addAfter=useCallback((afterId)=>{
    const src=tasks.find(t=>t.id===afterId);
    const newT={id:uid(),pid:src?.pid??null,depends_on:null,name:'Новая задача',
      start:src?addD(src.start,src.dur):TODAY,dur:5,prog:0,clr:src?.clr??'#3b82f6'};
    setTasks(ts=>{
      const idx=ts.findIndex(t=>t.id===afterId);
      const descs=getAllDescendants(ts,afterId);
      const last=descs.reduce((mx,did)=>{const i=ts.findIndex(t=>t.id===did);return i>mx?i:mx;},idx);
      const next=[...ts];next.splice(last+1,0,newT);
      return resolveDates(next);
    });
    setSel(newT.id);
    setTimeout(()=>startEdit(newT.id,'name','Новая задача'),40);
  },[tasks]);

  // keyboard handler inside editing input
  const onKD=useCallback(e=>{
    if(e.key==='Escape'){setEditing(null);return;}
    if(e.key==='Tab'){e.preventDefault();commit();return;}
    if(e.key==='Enter'){
      e.preventDefault();
      const saved={...editing};const v=editVal;
      setEditing(null);
      applyAndClose(saved.id,saved.field,v);
      // Add sibling after the row we were editing (or currently selected)
      setTimeout(()=>addAfter(saved.id),20);
    }
  },[editing,editVal,commit,applyAndClose,addAfter]);

  // task tree ops
  const addSubtask=()=>{
    if(!sel)return;
    const src=tasks.find(t=>t.id===sel);
    const newT={id:uid(),pid:sel,depends_on:null,name:'Подзадача',start:src?.start??TODAY,dur:3,prog:0,clr:src?.clr??'#3b82f6'};
    setTasks(ts=>{
      const idx=ts.findIndex(t=>t.id===sel);
      const descs=getAllDescendants(ts,sel);
      const last=descs.reduce((mx,did)=>{const i=ts.findIndex(t=>t.id===did);return i>mx?i:mx;},idx);
      const next=[...ts];next.splice(last+1,0,newT);
      return resolveDates(next);
    });
    setColl(c=>{const n=new Set(c);n.delete(sel);return n;});
    setSel(newT.id);
    setTimeout(()=>startEdit(newT.id,'name','Подзадача'),40);
  };

  const delTask=()=>{
    if(!sel)return;
    const descs=getAllDescendants(tasks,sel);
    const rm=new Set([sel,...descs]);
    const nt=tasks.filter(t=>!rm.has(t.id));
    setTasks(resolveDates(nt));setSel(nt[0]?.id??null);
  };

  const indent=()=>{
    const idx=tasks.findIndex(t=>t.id===sel);if(idx<1)return;
    const cur=tasks[idx],cd=getDepth(tasks,cur.id);
    for(let i=idx-1;i>=0;i--){
      const c=tasks[i];
      if(getDepth(tasks,c.id)===cd&&c.pid===cur.pid){
        setTasks(ts=>resolveDates(ts.map(t=>t.id===sel?{...t,pid:c.id}:t)));
        setColl(c2=>{const n=new Set(c2);n.delete(c.id);return n;});return;
      }
    }
  };

  const outdent=()=>{
    const cur=tasks.find(t=>t.id===sel);if(!cur?.pid)return;
    const par=tasks.find(t=>t.id===cur.pid);
    setTasks(ts=>resolveDates(ts.map(t=>t.id===sel?{...t,pid:par?.pid??null}:t)));
  };

  const toggle=(id,e)=>{
    e.stopPropagation();
    setColl(c=>{const n=new Set(c);n.has(id)?n.delete(id):n.add(id);return n;});
  };

  const selTask=tasks.find(t=>t.id===sel);

  return(
    <>
      <style>{CSS}</style>
      <div className="root">

        {/* TOOLBAR */}
        <div className="tb">
          <button className={`btn p${!can(role,'edit')?' locked':''}`} onClick={()=>addAfter(sel)}>＋ Задача</button>
          <button className={`btn${!can(role,'edit')?' locked':''}`} onClick={addSubtask} disabled={!sel}>⤷ Подзадача</button>
          <div className="tb-sep"/>
          <button className={`btn${!can(role,'edit')?' locked':''}`} onClick={indent} disabled={!sel}>→ Отступ</button>
          <button className={`btn${!can(role,'edit')?' locked':''}`} onClick={outdent} disabled={!selTask?.pid}>← Выступ</button>
          <div className="tb-sep"/>
          <button className={`btn danger${!can(role,'delete')?' locked':''}`} onClick={delTask} disabled={!sel}>✕ Удалить</button>
          <div className="tb-sep"/>
          <span className="hint">Enter = новая задача · Dbl.click = ред. · «Зависит от»: номера через запятую</span>
          {editP
            ? <input style={{marginLeft:'auto',background:'#1e293b',border:'1px solid #3b82f6',color:'#e2e8f0',
                padding:'4px 10px',borderRadius:4,fontSize:13,fontWeight:600,fontFamily:'DM Sans,sans-serif',outline:'none',minWidth:280}}
                value={pname} autoFocus onChange={e=>setPname(e.target.value)}
                onBlur={()=>setEditP(false)} onKeyDown={e=>{if(e.key==='Enter')setEditP(false);}}/>
            : <div className="pname" onClick={()=>setEditP(true)}>{pname}</div>
          }
        </div>

        {/* ROLE BAR */}
        <div className="role-bar">
          <span className="role-label">Роль:</span>
          {Object.entries(ROLES).map(([key,cfg])=>(
            <button key={key}
              className={`role-btn${role===key?' active':''}`}
              style={role===key?{background:cfg.color}:{}}
              onClick={()=>setRole(key)}
            >{cfg.label}</button>
          ))}
          <span className="role-access-hint">
            {ROLES[role].can.map(a=>a).join(' · ')}
          </span>
        </div>

        {/* SPLIT */}
        <div className="split">

          {/* LOADING STATE */}
        {!apiLoaded && (
          <div style={{position:'absolute',inset:0,display:'flex',alignItems:'center',
            justifyContent:'center',zIndex:10,background:'var(--surface)',opacity:.9}}>
            <span style={{color:'var(--muted)',fontSize:13,fontFamily:'var(--mono)'}}>Загрузка задач...</span>
          </div>
        )}

      {/* LEFT */}
          <div className="left" style={{width:leftW}}>
            <div className="thead" style={{width:leftW}}>
              <div className="th rn">#</div>
              <div className="th g">Наименование работ</div>
              <div className="th" style={{width:48,justifyContent:'center'}}>Дней</div>
              <div className="th" style={{width:64,justifyContent:'center'}}>Начало</div>
              <div className="th" style={{width:64,justifyContent:'center'}}>Конец</div>
              <div className="th" style={{width:50,justifyContent:'center'}}>%</div>
              <div className="th" style={{width:72,justifyContent:'center'}}>Зависит от</div>
            </div>

            <div className="tbody" ref={lbRef} onScroll={onLS}>
              {rows.map((row,i)=>{
                const isSel=row.id===sel;
                const isEd=editing?.id===row.id;
                const end=addD(row.start,row.dur);
                const depNums = parseDeps(row.depends_on)
                  .map(depId => numMap[depId] ?? '?')
                  .filter(Boolean);
                const indent2=row.depth*16;

                return(
                  <div key={row.id}
                    className={`tr${isSel?' sel':''}${row.hasKids?' par':''}${i%2===1?' even':''}`}
                    onClick={()=>{commit();setSel(row.id);}}
                    onKeyDown={e=>{
                      if(editing) return;
                      if(e.key==='Enter'){e.preventDefault();addAfter(row.id);}
                      if((e.key==='Delete'||e.key==='Backspace')&&!editing){e.preventDefault();delTask();}
                    }}
                    tabIndex={0}
                  >
                    {/* # — click opens task detail panel */}
                    <div className="td rn"
                      style={{cursor:'pointer',color:'var(--blue)'}}
                      title="Открыть карточку задачи"
                      onClick={e=>{e.stopPropagation();setPanelId(row.id);setNewComment('');}}>
                      {i+1}
                    </div>

                    {/* Name */}
                    <div className={`td g${isEd&&editing.field==='name'?' ed':''}`}
                      style={{paddingLeft:6+indent2}}
                      onDoubleClick={()=>startEdit(row.id,'name',row.name)}
                    >
                      <div className="tcell">
                        {row.hasKids
                          ? <span className="tog" onClick={e=>toggle(row.id,e)}>{row.isOpen?'▾':'▸'}</span>
                          : <span className="sp"/>
                        }
                        {isEd&&editing.field==='name'
                          ? <input ref={inpRef} style={{flex:1,minWidth:0}}
                              value={editVal} onChange={e=>setEditVal(e.target.value)}
                              onBlur={commit} onKeyDown={onKD}/>
                          : <span className="nt">{row.name}</span>
                        }
                      </div>
                    </div>

                    {/* Dur */}
                    <div className={`td mn c${isEd&&editing.field==='dur'?' ed':''}`}
                      style={{width:48}} onDoubleClick={()=>startEdit(row.id,'dur',row.dur)}>
                      {isEd&&editing.field==='dur'
                        ? <input ref={inpRef} style={{width:32,textAlign:'center'}}
                            value={editVal} onChange={e=>setEditVal(e.target.value)}
                            onBlur={commit} onKeyDown={onKD}/>
                        : row.dur+'д'
                      }
                    </div>

                    {/* Start */}
                    <div className={`td mn c${isEd&&editing.field==='start'?' ed':''}`}
                      style={{width:64,fontSize:11}} onDoubleClick={()=>startEdit(row.id,'start',row.start)}>
                      {isEd&&editing.field==='start'
                        ? <input ref={inpRef} style={{width:58,textAlign:'center',fontSize:10}}
                            value={editVal} onChange={e=>setEditVal(e.target.value)}
                            onBlur={commit} onKeyDown={onKD}/>
                        : dispD(row.start)
                      }
                    </div>

                    {/* End (computed) */}
                    <div className="td mn c" style={{width:64,fontSize:11,color:'var(--muted)'}}>
                      {dispD(end)}
                    </div>

                    {/* Progress */}
                    <div className={`td${isEd&&editing.field==='prog'?' ed':''}`}
                      style={{width:50,flexDirection:'column',gap:2,padding:'0 5px',justifyContent:'center'}}
                      onDoubleClick={()=>startEdit(row.id,'prog',row.prog)}>
                      {isEd&&editing.field==='prog'
                        ? <input ref={inpRef} style={{width:34,textAlign:'center',fontSize:11,fontFamily:'var(--mono)'}}
                            value={editVal} onChange={e=>setEditVal(e.target.value)}
                            onBlur={commit} onKeyDown={onKD}/>
                        : <>
                            <div style={{fontSize:9,fontFamily:'var(--mono)',color:'var(--muted)',textAlign:'right'}}>{row.prog}%</div>
                            <div className="pb"><div className={`pf${row.prog>=100?' ok':row.prog>=50?' mid':''}`} style={{width:row.prog+'%'}}/></div>
                          </>
                      }
                    </div>

                    {/* Depends on — comma-separated row numbers */}
                    <div className={`td c${isEd&&editing.field==='depends_on'?' ed-dep':''}`}
                      style={{width:72,gap:2,flexWrap:'nowrap',overflow:'hidden'}}
                      onDoubleClick={()=>startEdit(row.id,'depends_on',
                        depNums.length ? depNums.join(',') : ''
                      )}>
                      {isEd&&editing.field==='depends_on'
                        ? <input ref={inpRef} style={{width:58,textAlign:'center',fontSize:11,fontFamily:'var(--mono)',
                            border:'none',outline:'none',background:'transparent',color:'#7c3aed'}}
                            placeholder="№,№…"
                            value={editVal} onChange={e=>setEditVal(e.target.value)}
                            onBlur={commit} onKeyDown={onKD}/>
                        : depNums.length>0
                          ? <span style={{display:'flex',gap:2,flexWrap:'nowrap'}}>
                              {depNums.map((n,i)=>(
                                <span key={i} className="chip">#{n}</span>
                              ))}
                            </span>
                          : <span className="chip e">—</span>
                      }
                    </div>
                  </div>
                );
              })}
              <div style={{height:120}}/>
            </div>
          </div>

          {/* SPLITTER */}
          <div className="splitter" ref={splRef}
            onMouseDown={()=>{drg.current=true;splRef.current?.classList.add('drag');}}/>

          {/* RIGHT GANTT */}
          <div className="right">
            <div className="ghdr" ref={rhRef} style={{overflowX:'hidden'}}>
              <div style={{width:W}}>
                <div className="mr">
                  {mb.map((m,i)=><div key={i} className="mc" style={{width:m.w,minWidth:m.w}}>{m.w>60?m.label:''}</div>)}
                </div>
                <div className="wr">
                  {wb.map((w,i)=><div key={i} className="wc" style={{width:w.w,minWidth:w.w}}>{w.w>30?w.label:''}</div>)}
                </div>
              </div>
            </div>

            <div className="gbw" ref={rbRef} onScroll={onRS}>
              <div className="gb" style={{width:W,minHeight:rows.length*ROW_H+120}}>

                {/* Rows — plain flow, no other siblings so nth-child is clean */}
                {rows.map((row,ri)=>{
                  const bx=diff(origin,row.start)*DAY_W;
                  const bw=Math.max(4,row.dur*DAY_W);
                  const isP=row.hasKids;
                  const bh=isP?14:20;
                  return(
                    <div key={row.id}
                      className={`gr${row.id===sel?' sel':''}${ri%2===1?' even':''}`}
                      style={{height:ROW_H}} onClick={()=>setSel(row.id)}>
                      <div className="bw" style={{left:bx}}>
                        <div className={`bar${isP?' par':''}`}
                          style={{
                            width:bw, height:bh,
                            background:'#fff',
                            border:`1.5px solid ${row.clr}`,
                            opacity: isP ? .85 : 1,
                          }}
                          title={`${row.name} · ${dispD(row.start)}–${dispD(addD(row.start,row.dur))} · ${row.dur}д · ${row.prog}%`}>
                          {/* color fill = progress % */}
                          {row.prog>0&&<div className="bp" style={{width:row.prog+'%',background:row.clr,opacity:.82}}/>}
                          {bw>44&&<div className="bl" style={{
                            fontSize:isP?9:10,
                            color: row.prog>55 ? 'rgba(255,255,255,.95)' : row.clr,
                          }}>
                            {!isP&&row.prog>0?row.prog+'% · ':''}{bw>90?row.name:''}
                          </div>}
                        </div>
                      </div>
                    </div>
                  );
                })}

                {/* Absolute overlays — in one wrapper so they never affect row nth-child */}
                <div style={{position:'absolute',inset:0,pointerEvents:'none'}}>
                  {/* Grid lines */}
                  {gridLines.map((l,i)=><div key={i} className={`gl${l.m?' m':''}`} style={{left:l.x}}/>)}

                  {/* Today */}
                  {todayX>0&&todayX<W&&<>
                    <div className="tl" style={{left:todayX}}/>
                    <div className="tlb" style={{left:todayX}}>Сегодня</div>
                  </>}

                  {/* Dependency arrows — smooth bezier like Miro */}
                  <svg className="darr" style={{width:W,height:rows.length*ROW_H+120}}>
                    <defs>
                      <marker id="arr" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
                        <path d="M0,0.5 L0,5.5 L6,3 z" fill="rgba(150,150,160,.7)"/>
                      </marker>
                    </defs>
                    {arrows.map((a,i)=>{
                      // Gaussian S-curve: exit right from pred-end, enter left into succ-start
                      // Control points pulled horizontally — creates the smooth "Miro" feel
                      const dx   = Math.abs(a.x2 - a.x1);
                      const dy   = a.y2 - a.y1;
                      // tension: more horizontal pull when bars are close vertically
                      const pull = Math.max(40, Math.min(dx * 0.55, 120));
                      const cx1  = a.x1 + pull;
                      const cy1  = a.y1;
                      const cx2  = a.x2 - pull;
                      const cy2  = a.y2;
                      const d    = `M${a.x1},${a.y1} C${cx1},${cy1} ${cx2},${cy2} ${a.x2},${a.y2}`;
                      return(
                        <g key={i}>
                          <path d={d} stroke="rgba(150,150,160,.55)" strokeWidth="1.5"
                            fill="none" strokeLinecap="round" markerEnd="url(#arr)"/>
                        </g>
                      );
                    })}
                  </svg>
                </div>

              </div>
            </div>
          </div>
        </div>
      </div>

      {/* TASK DETAIL PANEL */}
      {panelId && panelTask && (()=>{
        const tc = comments[panelId] || [];
        const depNums2 = parseDeps(panelTask.depends_on).map(d=>numMap[d]??'?');
        const progColor = panelTask.prog>=100?'#22c55e':panelTask.prog>=50?'#f59e0b':'#3b82f6';
        return(
          <div className="panel-overlay" onClick={()=>setPanelId(null)}>
            <div className="panel" onClick={e=>e.stopPropagation()}>

              {/* color accent */}
              <div className="panel-color-bar" style={{background:panelTask.clr}}/>

              {/* header */}
              <div className="panel-hdr">
                <div>
                  <div style={{fontSize:11,fontFamily:'var(--mono)',color:'var(--muted)',marginBottom:3}}>
                    Задача #{numMap[panelId]}
                  </div>
                  <div className="panel-title">{panelTask.name}</div>
                </div>
                <button className="panel-close" onClick={()=>setPanelId(null)}>✕</button>
              </div>

              {/* body */}
              <div className="panel-body">

                {/* details grid */}
                <div className="panel-section">
                  <div className="panel-section-title">Детали</div>
                  <div className="panel-grid">
                    <div className="pfield">
                      <div className="pfield-label">Начало</div>
                      <div className="pfield-val mono">{dispD(panelTask.start)}</div>
                    </div>
                    <div className="pfield">
                      <div className="pfield-label">Конец</div>
                      <div className="pfield-val mono">{dispD(addD(panelTask.start,panelTask.dur))}</div>
                    </div>
                    <div className="pfield">
                      <div className="pfield-label">Длительность</div>
                      <div className="pfield-val mono">{panelTask.dur} дн.</div>
                    </div>
                    <div className="pfield">
                      <div className="pfield-label">Зависит от</div>
                      <div className="pfield-val mono">{depNums2.length?depNums2.map(n=>`#${n}`).join(', '):'—'}</div>
                    </div>
                    <div className="pfield" style={{gridColumn:'1/-1'}}>
                      <div className="pfield-label">Прогресс</div>
                      <div style={{display:'flex',alignItems:'center',gap:8,marginTop:2}}>
                        <div className="prog-big" style={{flex:1}}>
                          <div className="prog-big-fill" style={{width:panelTask.prog+'%',background:progColor}}/>
                        </div>
                        <span style={{fontFamily:'var(--mono)',fontSize:12,fontWeight:600,color:progColor}}>
                          {panelTask.prog}%
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* comments list */}
                <div className="panel-section">
                  <div className="panel-section-title">Комментарии ({tc.length})</div>
                  {tc.length===0
                    ? <div className="no-comments">Комментариев пока нет</div>
                    : <div className="comments">
                        {tc.map(c=>{
                          const rc = ROLES[c.role as RoleKey];
                          const initials = c.author.split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
                          return(
                            <div key={c.id} className="comment">
                              <div className="comment-hdr">
                                <div className="comment-avatar" style={{background:rc?.color??'#64748b'}}>{initials}</div>
                                <span className="comment-author">{c.author}</span>
                                <span className="comment-role"
                                  style={{background:`${rc?.color??'#64748b'}18`,color:rc?.color??'#64748b'}}>
                                  {rc?.label??c.role}
                                </span>
                                <span className="comment-ts">{c.ts}</span>
                              </div>
                              <div className="comment-text">{c.text}</div>
                            </div>
                          );
                        })}
                      </div>
                  }
                </div>
              </div>

              {/* comment input */}
              {can(role,'comment')
                ? <div className="comment-input-wrap">
                    <div style={{fontSize:11,color:'var(--muted)'}}>
                      Пишете как: <b>{({owner:'Директор',pm:'Козлов А.В.',foreman:'Прораб',supplier:'Снабженец',viewer:'Наблюдатель'})[role]}</b>
                    </div>
                    <textarea className="comment-textarea"
                      placeholder="Напишите комментарий..."
                      value={newComment}
                      onChange={e=>setNewComment(e.target.value)}
                      onKeyDown={e=>{if(e.key==='Enter'&&e.ctrlKey){e.preventDefault();submitComment();}}}
                      rows={3}
                    />
                    <button className="comment-submit"
                      onClick={submitComment}
                      disabled={!newComment.trim()}>
                      Отправить  <span style={{opacity:.6,fontSize:10}}>Ctrl+Enter</span>
                    </button>
                  </div>
                : <div style={{padding:'12px 20px',borderTop:'1px solid var(--border)',
                    fontSize:12,color:'var(--muted)',textAlign:'center'}}>
                    🔒 Роль «{ROLES[role].label}» не может оставлять комментарии
                  </div>
              }
            </div>
          </div>
        );
      })()}
    </>
  );
}