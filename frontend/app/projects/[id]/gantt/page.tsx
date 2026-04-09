"use client";
import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import type { KeyboardEvent, MouseEvent } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { estimates, gantt as ganttApi, projects } from "@/lib/api";
import type { BaselineStatus, EstimateBatch, Task } from "@/lib/types";

const DEFAULT_DAY_W = 24;
const DEFAULT_HOURS_PER_DAY = 8;
const MIN_DAY_W = 12;
const MAX_DAY_W = 56;
const MOBILE_BREAKPOINT = 980;
const MIN_RIGHT_PANEL_W = 520;
const ROW_H = 32;

type TaskRow = Task & {
  depth: number;
  hasKids: boolean;
  isOpen: boolean;
};

type EditingField = "name" | "workers" | "start" | "prog" | "depends_on";

type EditingState = {
  id: string;
  field: EditingField;
};

type ApiTask = {
  id: string;
  estimate_batch_id?: string | null;
  estimate_id?: string | null;
  parent_id: string | null;
  name: string;
  start_date: string;
  working_days: number;
  is_group?: boolean;
  workers_count?: number | null;
  labor_hours?: number | null;
  hours_per_day?: number | null;
  req_hidden_work_act?: boolean;
  req_intermediate_act?: boolean;
  req_ks2_ks3?: boolean;
  progress: number;
  color?: string | null;
  assignee?: {
    name?: string | null;
  } | null;
  depends_on?: string | null;
};

type DepArrow = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

type PanelFormState = {
  name: string;
  start: string;
  labor: string;
  norm: string;
  workers: string;
  prog: string;
  depends_on: string;
  color: string;
};

const z = (n: number | string) => String(n).padStart(2, "0");
const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n));
const clampDayWidth = (n: number) => clamp(n, MIN_DAY_W, MAX_DAY_W);
const pd = (s: string) => {
  const [y, m, d] = s.split("-");
  return new Date(Number(y), Number(m) - 1, Number(d));
};
const fd = (d: Date) => `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
const addD = (s: string, n: number) => {
  const d = new Date(pd(s));
  d.setDate(d.getDate() + n);
  return fd(d);
};
const diff = (a: string, b: string) => Math.round((pd(b).getTime() - pd(a).getTime()) / 86400000);
const roundTo = (value: number, digits = 2) => Number(value.toFixed(digits));
const normalizeWorkersCount = (value: number | null | undefined) => Math.max(1, Number(value) || 1);
const normalizeHoursPerDay = (value: number | null | undefined) => {
  const parsed = Number(value);
  return parsed > 0 ? parsed : DEFAULT_HOURS_PER_DAY;
};
const calculateDurationDays = (
  laborHours: number | null | undefined,
  workersCount: number | null | undefined,
  hoursPerDay: number | null | undefined,
  fallback = 1,
) => {
  const labor = Number(laborHours);
  if (!Number.isFinite(labor) || labor <= 0) return Math.max(1, fallback);
  return Math.max(1, Math.ceil(labor / (normalizeWorkersCount(workersCount) * normalizeHoursPerDay(hoursPerDay))));
};
const deriveLaborHours = (
  workingDays: number,
  workersCount: number | null | undefined,
  hoursPerDay: number | null | undefined,
) => roundTo(Math.max(1, workingDays) * normalizeWorkersCount(workersCount) * normalizeHoursPerDay(hoursPerDay));
const formatHoursValue = (value: number | null | undefined) => {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const normalized = roundTo(Number(value));
  return Number.isInteger(normalized) ? String(normalized) : normalized.toString();
};
const syncTaskDerivedFields = (task: Task): Task => {
  if (task.is_group) return task;
  const workers = normalizeWorkersCount(task.workers_count);
  const hoursPerDay = normalizeHoursPerDay(task.hours_per_day);
  const laborHours = task.labor_hours != null
    ? roundTo(Number(task.labor_hours))
    : deriveLaborHours(task.dur, workers, hoursPerDay);

  return {
    ...task,
    workers_count: workers,
    hours_per_day: hoursPerDay,
    labor_hours: laborHours,
    dur: calculateDurationDays(laborHours, workers, hoursPerDay, task.dur),
  };
};
const dispD = (s: string) => {
  const d = pd(s);
  return `${z(d.getDate())}.${z(d.getMonth() + 1)}`;
};
const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"] as const;
const getTouchDistance = (a: Touch, b: Touch) => Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);

let _uid = 300;
const uid = () => String(++_uid);

// ─── Topological date propagation ────────────────────────────────────────────
// depends_on = comma-separated task IDs. Start = max(end of all predecessors).
function parseDeps(depends_on: string | null | undefined): string[] {
  if (!depends_on) return [];
  return depends_on.split(",").map((s) => s.trim()).filter(Boolean);
}

function resolveDependencyInput(raw: string, taskId: string, rows: TaskRow[], tasks: Task[]): string | null {
  const value = raw.trim();
  if (value === "" || value === "-" || value === "—") return null;
  const parts = value.split(",").map((s) => s.trim()).filter(Boolean);
  const resolved = parts
    .map((part) => {
      const num = parseInt(part, 10);
      if (!Number.isNaN(num) && num >= 1 && num <= rows.length) return rows[num - 1].id;
      if (tasks.some((t) => t.id === part)) return part;
      return null;
    })
    .filter((item): item is string => Boolean(item) && item !== taskId);
  return resolved.length > 0 ? resolved.join(",") : null;
}

function resolveDates(tasks: Task[]): Task[] {
  const resMap: Record<string, Task> = Object.fromEntries(tasks.map((t) => [t.id, { ...t }]));
  const result = tasks.map((t) => resMap[t.id]);
  const visited = new Set<string>();
  const resolving = new Set<string>();

  const resolve = (id: string) => {
    if (visited.has(id) || resolving.has(id)) return;
    resolving.add(id);
    const task = resMap[id];
    const depIds = parseDeps(task?.depends_on);
    depIds.forEach((depId) => {
      if (resMap[depId]) {
        resolve(depId);
        const predEnd = addD(resMap[depId].start, resMap[depId].dur);
        if (diff(task.start, predEnd) > 0) task.start = predEnd;
      }
    });
    resolving.delete(id);
    visited.add(id);
  };

  result.forEach((t) => resolve(t.id));
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
function getDepth(tasks: Task[], id: string, d = 0): number {
  const task = tasks.find((x) => x.id === id);
  if (!task?.pid) return d;
  return getDepth(tasks, task.pid, d + 1);
}

function getVisibleRows(tasks: Task[], collapsed: Set<string>): TaskRow[] {
  const rows: TaskRow[] = [];
  // Build children map for fast lookup
  const childMap: Record<string, Task[]> = {};
  tasks.forEach((t) => {
    const p = t.pid ?? "__root__";
    if (!childMap[p]) childMap[p] = [];
    childMap[p].push(t);
  });
  // Depth-first traversal — children always appear right after parent
  const visit = (id: string, depth: number) => {
    const t = tasks.find((x) => x.id === id);
    if (!t) return;
    const kids = childMap[id] ?? [];
    rows.push({ ...t, depth, hasKids: kids.length > 0, isOpen: !collapsed.has(id) });
    if (!collapsed.has(id)) kids.forEach((k) => visit(k.id, depth + 1));
  };
  (childMap["__root__"] ?? []).forEach((t) => visit(t.id, 0));
  return rows;
}

function getAllDescendants(tasks: Task[], id: string): string[] {
  const res: string[] = [];
  const q: string[] = [id];
  while (q.length) {
    const current = q.shift();
    tasks
      .filter((t) => t.pid === current)
      .forEach((k) => {
        res.push(k.id);
        q.push(k.id);
      });
  }
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

type CommentItem = {
  id: string;
  author: string;
  role: RoleKey;
  text: string;
  ts: string;
};

type CommentsByTask = Record<string, CommentItem[]>;

// ─── MOCK COMMENTS ────────────────────────────────────────────────────────────
// { taskId → [{id, author, role, text, ts}] }
const INIT_COMMENTS: CommentsByTask = {
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

const COMMENT_AUTHORS: Record<RoleKey, string> = {
  owner: "Директор",
  pm: "Козлов А.В.",
  foreman: "Прораб",
  supplier: "Снабженец",
  viewer: "Наблюдатель",
};

function updateTaskField(task: Task, field: EditingField, value: string | number | null): Task {
  switch (field) {
    case "name":
      return { ...task, name: String(value ?? "") };
    case "workers":
      return syncTaskDerivedFields({ ...task, workers_count: Number(value) });
    case "start":
      return { ...task, start: String(value ?? "") };
    case "prog":
      return { ...task, prog: Number(value) };
    case "depends_on":
      return { ...task, depends_on: value === null ? null : String(value) };
  }
}

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
.split-vp{flex:1;overflow:hidden;position:relative;}
.split-vp.narrow{overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;}
.split{display:flex;flex:1;overflow:hidden;min-height:100%;position:relative;}
.splitter{width:4px;min-width:4px;background:#e2e8f0;cursor:col-resize;flex-shrink:0;transition:background .15s;}
.splitter:hover,.splitter.drag{background:var(--blue);}
.splitter.disabled{cursor:default;background:#cbd5e1;opacity:.55;pointer-events:none;}

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
.zoom-bar{
  display:flex;align-items:center;gap:8px;padding:8px 10px;background:#f8fafc;
  border-bottom:1px solid var(--border);flex-shrink:0;
}
.zoom-btn{
  min-width:32px;height:32px;padding:0 10px;border-radius:8px;border:1px solid var(--border);
  background:#fff;color:var(--text);font:600 13px var(--sans);cursor:pointer;
}
.zoom-btn:hover{border-color:#93c5fd;color:#1d4ed8;}
.zoom-val{margin-left:auto;font-size:11px;color:var(--muted);font-family:var(--mono);}
.ghdr{height:52px;min-height:52px;overflow:hidden;background:var(--hdr2);border-bottom:1px solid var(--hdr3);flex-shrink:0;}
.mr{display:flex;height:26px;border-bottom:1px solid var(--hdr3);}
.mc{display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:#cbd5e1;border-right:1px solid var(--hdr3);flex-shrink:0;}
.wr{display:flex;height:26px;}
.wc{display:flex;align-items:center;justify-content:center;font-size:10px;color:#64748b;border-right:1px solid #1e293b;flex-shrink:0;font-family:var(--mono);}
.gbw{flex:1;overflow:scroll;position:relative;}
.gbw.zoomable{touch-action:pan-x pan-y;overscroll-behavior:contain;}
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
.pfield-input{
  width:100%;margin-top:6px;padding:8px 10px;border:1px solid var(--border);border-radius:6px;
  font:inherit;color:var(--text);background:#fff;outline:none;
}
.pfield-input:focus{border-color:var(--blue);}
.panel-actions{display:flex;align-items:center;gap:10px;justify-content:flex-end;margin-top:12px;}
.panel-save-error{margin-right:auto;font-size:12px;color:#dc2626;line-height:1.4;}
.panel-save-btn{
  padding:8px 14px;background:var(--blue);color:#fff;border:none;border-radius:6px;cursor:pointer;
  font-size:12px;font-weight:600;font-family:var(--sans);
}
.panel-save-btn:disabled{opacity:.5;cursor:not-allowed;}
.panel-readonly-note{font-size:12px;color:var(--muted);line-height:1.5;}
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
.batch-bar{
  display:flex;align-items:center;gap:8px;padding:8px 12px;background:#f8fafc;border-bottom:1px solid var(--border);
  flex-wrap:wrap;
}
.batch-chip{
  padding:6px 10px;border-radius:999px;border:1px solid var(--border);background:#fff;cursor:pointer;
  font-size:11px;font-weight:600;color:var(--text);
}
.batch-chip.active{border-color:var(--blue);background:rgba(59,130,246,.08);color:#1d4ed8;}
.batch-chip-meta{font-size:10px;color:var(--muted);font-family:var(--mono);}
.baseline-bar{
  display:flex;align-items:center;gap:10px;padding:8px 12px;background:#f8fafc;border-bottom:1px solid var(--border);
  flex-wrap:wrap;
}
.baseline-meta{font-size:11px;color:var(--muted);}
.baseline-btn{
  padding:6px 12px;border-radius:8px;border:1px solid rgba(15,23,42,.12);background:#fff;cursor:pointer;
  font-size:12px;font-weight:600;color:#0f172a;
}
.baseline-btn.primary{background:#0f172a;color:#fff;border-color:#0f172a;}
.baseline-btn:disabled{opacity:.55;cursor:not-allowed;}
.act-grid{display:grid;gap:8px;margin-top:8px;}
.act-item{display:flex;gap:10px;align-items:flex-start;font-size:12px;line-height:1.4;color:var(--text);}
.act-item input{margin-top:2px;}
.act-hint{font-size:11px;color:var(--muted);line-height:1.45;}
/* locked overlay */
.locked{opacity:.45;pointer-events:none;cursor:not-allowed!important;}
`;

// ─── Component ────────────────────────────────────────────────────────────────
export default function App() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const pid = params?.id ?? "";
  const batchFromUrl = searchParams.get("batch");
  const TODAY = "2026-03-13";

  // Map API fields -> local field names used in Gantt
  const apiToLocal = useCallback((t: ApiTask): Task => ({
    ...t,
    estimate_batch_id: t.estimate_batch_id ?? null,
    estimate_id: t.estimate_id ?? null,
    pid: t.parent_id,
    is_group: t.is_group ?? false,
    dur: t.working_days,
    workers_count: t.workers_count ?? null,
    labor_hours: t.labor_hours ?? null,
    hours_per_day: t.hours_per_day ?? DEFAULT_HOURS_PER_DAY,
    req_hidden_work_act: t.req_hidden_work_act ?? false,
    req_intermediate_act: t.req_intermediate_act ?? false,
    req_ks2_ks3: t.req_ks2_ks3 ?? false,
    start: t.start_date,
    prog: t.progress,
    clr: t.color ?? "#3b82f6",
    who: t.assignee?.name ?? "—",
    depends_on: t.depends_on ?? "",
  }), []);

  const [tasks, setTasks] = useState<Task[]>([]);
  const [apiLoaded, setApiLoaded] = useState(false);
  const [batches, setBatches] = useState<EstimateBatch[]>([]);
  const [batchesLoaded, setBatchesLoaded] = useState(false);
  const [activeBatchId, setActiveBatchId] = useState<string | null>(batchFromUrl);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [taskError, setTaskError] = useState<string | null>(null);
  const [coll, setColl] = useState<Set<string>>(new Set());
  const [sel, setSel] = useState<string | null>("1");
  const [editing, setEditing] = useState<EditingState | null>(null);
  const [editVal, setEditVal] = useState("");
  const [leftW, setLeftW] = useState(620);
  const [dayWidth, setDayWidth] = useState(DEFAULT_DAY_W);
  const [viewportW, setViewportW] = useState(1280);
  const [isTouchDevice, setIsTouchDevice] = useState(false);
  const [pname, setPname] = useState("Объект");
  const [editP, setEditP] = useState(false);
  const [role, setRole] = useState<RoleKey>("pm");
  const [panelId, setPanelId] = useState<string | null>(null);
  const [comments, setComments] = useState<CommentsByTask>(INIT_COMMENTS);
  const [newComment, setNewComment] = useState("");
  const [splitDate, setSplitDate] = useState("");
  const [splitWorkers, setSplitWorkers] = useState("2");
  const [panelForm, setPanelForm] = useState<PanelFormState | null>(null);
  const [panelSaving, setPanelSaving] = useState(false);
  const [panelSaveError, setPanelSaveError] = useState<string | null>(null);
  const [baselineStatus, setBaselineStatus] = useState<BaselineStatus | null>(null);
  const [baselineLoading, setBaselineLoading] = useState(false);
  const [baselineReason, setBaselineReason] = useState("");
  const [actsSaving, setActsSaving] = useState(false);

  const lbRef = useRef<HTMLDivElement | null>(null);
  const rbRef = useRef<HTMLDivElement | null>(null);
  const rhRef = useRef<HTMLDivElement | null>(null);
  const splRef = useRef<HTMLDivElement | null>(null);
  const drg = useRef(false);
  const ssync = useRef(false);
  const inpRef = useRef<HTMLInputElement | null>(null);
  const dayWidthRef = useRef(DEFAULT_DAY_W);
  const pinchRef = useRef<{ startDistance: number; startDayWidth: number } | null>(null);

  useEffect(() => {
    dayWidthRef.current = dayWidth;
  }, [dayWidth]);

  useEffect(() => {
    const syncViewport = () => {
      setViewportW(window.innerWidth);
      setIsTouchDevice(window.matchMedia("(pointer: coarse)").matches || navigator.maxTouchPoints > 0);
    };
    syncViewport();
    window.addEventListener("resize", syncViewport);
    return () => window.removeEventListener("resize", syncViewport);
  }, []);

  const loadBaselineStatus = useCallback(async () => {
    if (!pid) return;
    try {
      const data = await ganttApi.baselineStatus(pid);
      setBaselineStatus(data);
    } catch {
      setBaselineStatus(null);
    }
  }, [pid]);

  const loadTasks = useCallback(async (preferredTaskId?: string | null, batchIdOverride?: string | null) => {
    if (!pid) return;
    const targetBatchId = batchIdOverride !== undefined ? batchIdOverride : activeBatchId;
    setTasks([]);
    setColl(new Set());
    setSel(null);
    setApiLoaded(false);
    setTaskError(null);
    try {
      const data = await ganttApi.list(pid, targetBatchId);
      const apiTasks = (data?.tasks ?? []) as ApiTask[];
      if (apiTasks.length > 0) {
        setTasks(resolveDates(apiTasks.map((task) => syncTaskDerivedFields(apiToLocal(task)))));
        setSel(preferredTaskId ?? apiTasks[0]?.id ?? null);
      } else {
        setTasks([]);
      }
    } catch (error: unknown) {
      setTasks([]);
      setTaskError(error instanceof Error ? error.message : "Не удалось загрузить задачи Ганта.");
    } finally {
      setApiLoaded(true);
    }
  }, [activeBatchId, apiToLocal, pid]);

  useEffect(() => {
    if (!pid) return;
    projects.get(pid).then((project) => {
      if (project?.name) setPname(project.name);
      if (project?.my_role && ["owner", "pm", "foreman", "supplier", "viewer"].includes(project.my_role)) {
        setRole(project.my_role as RoleKey);
      }
    }).catch(() => {});
    loadBaselineStatus().catch(() => {});
    setBatchError(null);
    estimates.batches(pid).then((data) => {
      setBatches(data);
      const latestBatchId = data.length ? data[data.length - 1]?.id : null;
      const nextBatchId = batchFromUrl ?? latestBatchId ?? null;
      setActiveBatchId(nextBatchId);
    }).catch(() => {
      setBatches([]);
      setActiveBatchId(batchFromUrl ?? null);
      setBatchError("Не удалось загрузить блоки сметы для Ганта. Проверьте backend и миграции БД.");
    }).finally(() => setBatchesLoaded(true));
  }, [batchFromUrl, loadBaselineStatus, pid]);

  useEffect(() => {
    if (!batchesLoaded) return;
    loadTasks(undefined, activeBatchId);
  }, [activeBatchId, batchesLoaded, loadTasks]);

  const selectBatch = useCallback((batchId: string | null) => {
    setActiveBatchId(batchId);
    router.replace(`/projects/${pid}/gantt${batchId ? `?batch=${batchId}` : ""}`);
  }, [pid, router]);

  const submitComment = useCallback(() => {
    if (!newComment.trim() || !panelId) return;
    const now = new Date();
    const ts = `${z(now.getDate())}.${z(now.getMonth() + 1)} ${z(now.getHours())}:${z(now.getMinutes())}`;
    setComments((current) => ({
      ...current,
      [panelId]: [
        ...(current[panelId] ?? []),
        {
          id: cuid(),
          author: COMMENT_AUTHORS[role],
          role,
          text: newComment.trim(),
          ts,
        },
      ],
    }));
    setNewComment("");
  }, [newComment, panelId, role]);

  const panelTask = tasks.find((t) => t.id === panelId) ?? null;
  useEffect(() => {
    if (!panelTask) return;
    const splitOffset = Math.max(1, Math.floor(panelTask.dur / 2));
    setSplitDate(addD(panelTask.start, splitOffset));
    setSplitWorkers(String(Math.max(1, (panelTask.workers_count ?? 1) + 1)));
  }, [panelTask]);

  const rows = useMemo(() => getVisibleRows(tasks, coll), [tasks, coll]);

  const numMap = useMemo<Record<string, number>>(() => {
    const map: Record<string, number> = {};
    rows.forEach((row, index) => {
      map[row.id] = index + 1;
    });
    return map;
  }, [rows]);

  useEffect(() => {
    if (!panelTask) {
      setPanelForm(null);
      setPanelSaveError(null);
      return;
    }
    const depNums = parseDeps(panelTask.depends_on)
      .map((depId) => rows.findIndex((row) => row.id === depId) + 1)
      .filter((num) => num > 0);
    setPanelForm({
      name: panelTask.name,
      start: panelTask.start,
      labor: panelTask.labor_hours != null ? formatHoursValue(panelTask.labor_hours) : "",
      norm: formatHoursValue(panelTask.hours_per_day ?? DEFAULT_HOURS_PER_DAY),
      workers: panelTask.workers_count != null ? String(panelTask.workers_count) : "",
      prog: String(panelTask.prog),
      depends_on: depNums.join(","),
      color: panelTask.clr ?? "#3b82f6",
    });
    setPanelSaveError(null);
  }, [panelTask, rows]);

  const { origin, totalDays } = useMemo(() => {
    if (!tasks.length) return { origin: "2026-01-01", totalDays: 180 };
    const starts = tasks.map((t) => t.start);
    const ends = tasks.map((t) => addD(t.start, t.dur));
    const minStart = starts.reduce((a, b) => (a < b ? a : b));
    const maxEnd = ends.reduce((a, b) => (a > b ? a : b));
    const originDate = fd(new Date(pd(minStart).getTime() - 7 * 86400000));
    return { origin: originDate, totalDays: diff(originDate, maxEnd) + 14 };
  }, [tasks]);

  const isCompactLayout = isTouchDevice || viewportW < MOBILE_BREAKPOINT;
  const effectiveLeftW = isCompactLayout ? clamp(Math.round(viewportW * 0.42), 300, 360) : leftW;
  const splitMinWidth = isCompactLayout ? effectiveLeftW + MIN_RIGHT_PANEL_W : 0;
  const showZoomControls = isTouchDevice || viewportW < MOBILE_BREAKPOINT;
  const canResizeSplit = !isCompactLayout;
  const W = totalDays * dayWidth;

  const { mb, wb } = useMemo(() => {
    const months: Array<{ label: string; x: number; w: number }> = [];
    const weeks: Array<{ x: number; w: number; label: string }> = [];
    const od = pd(origin);
    let current = new Date(od.getFullYear(), od.getMonth(), 1);
    while (true) {
      const next = new Date(current.getFullYear(), current.getMonth() + 1, 1);
      const start = Math.max(0, diff(origin, fd(current)));
      const end = Math.min(totalDays, diff(origin, fd(next)));
      if (start < end) {
        months.push({
          label: `${MONTHS[current.getMonth()]} ${current.getFullYear()}`,
          x: start * dayWidth,
          w: (end - start) * dayWidth,
        });
      }
      current = next;
      if (diff(origin, fd(current)) >= totalDays) break;
    }
    for (let day = 0; day < totalDays; day += 7) {
      weeks.push({ x: day * dayWidth, w: 7 * dayWidth, label: dispD(addD(origin, day)) });
    }
    return { mb: months, wb: weeks };
  }, [dayWidth, origin, totalDays]);

  const gridLines = useMemo(() => {
    const lines: Array<{ x: number; m: boolean }> = [];
    for (let day = 0; day < totalDays; day += 7) lines.push({ x: day * dayWidth, m: false });
    const od = pd(origin);
    let current = new Date(od.getFullYear(), od.getMonth(), 1);
    while (true) {
      const next = new Date(current.getFullYear(), current.getMonth() + 1, 1);
      const dx = diff(origin, fd(next));
      if (dx >= totalDays) break;
      if (dx > 0) lines.push({ x: dx * dayWidth, m: true });
      current = next;
    }
    return lines;
  }, [dayWidth, origin, totalDays]);

  const todayX = diff(origin, TODAY) * dayWidth;

  const arrows = useMemo(() => {
    const result: DepArrow[] = [];
    rows.forEach((row, rowIndex) => {
      parseDeps(row.depends_on).forEach((depId) => {
        const predIndex = rows.findIndex((r) => r.id === depId);
        if (predIndex < 0) return;
        const pred = rows[predIndex];
        result.push({
          x1: (diff(origin, pred.start) + pred.dur) * dayWidth,
          y1: predIndex * ROW_H + ROW_H / 2,
          x2: diff(origin, row.start) * dayWidth,
          y2: rowIndex * ROW_H + ROW_H / 2,
        });
      });
    });
    return result;
  }, [dayWidth, origin, rows]);

  const onRS = useCallback(() => {
    if (ssync.current || !rbRef.current) return;
    ssync.current = true;
    if (lbRef.current) lbRef.current.scrollTop = rbRef.current.scrollTop;
    if (rhRef.current) rhRef.current.scrollLeft = rbRef.current.scrollLeft;
    ssync.current = false;
  }, []);

  const onLS = useCallback(() => {
    if (ssync.current || !lbRef.current) return;
    ssync.current = true;
    if (rbRef.current) rbRef.current.scrollTop = lbRef.current.scrollTop;
    ssync.current = false;
  }, []);

  const syncTimelineScroll = useCallback((nextScrollLeft: number) => {
    if (!rbRef.current) return;
    const maxScroll = Math.max(0, rbRef.current.scrollWidth - rbRef.current.clientWidth);
    const clampedScroll = clamp(nextScrollLeft, 0, maxScroll);
    ssync.current = true;
    rbRef.current.scrollLeft = clampedScroll;
    if (rhRef.current) rhRef.current.scrollLeft = clampedScroll;
    ssync.current = false;
  }, []);

  const zoomTimeline = useCallback((nextWidth: number, anchorClientX?: number) => {
    const clampedWidth = clampDayWidth(nextWidth);
    const container = rbRef.current;
    if (!container) {
      setDayWidth(clampedWidth);
      return;
    }
    if (Math.abs(clampedWidth - dayWidthRef.current) < 0.01) return;
    const rect = container.getBoundingClientRect();
    const anchorX = anchorClientX == null
      ? container.clientWidth / 2
      : clamp(anchorClientX - rect.left, 0, container.clientWidth);
    const anchorDay = (container.scrollLeft + anchorX) / dayWidthRef.current;
    setDayWidth(clampedWidth);
    requestAnimationFrame(() => {
      syncTimelineScroll(anchorDay * clampedWidth - anchorX);
    });
  }, [syncTimelineScroll]);

  useEffect(() => {
    const mv = (e: globalThis.MouseEvent) => {
      if (!drg.current) return;
      setLeftW(Math.max(280, Math.min(900, e.clientX)));
    };
    const up = () => {
      drg.current = false;
      splRef.current?.classList.remove("drag");
    };
    window.addEventListener("mousemove", mv);
    window.addEventListener("mouseup", up);
    return () => {
      window.removeEventListener("mousemove", mv);
      window.removeEventListener("mouseup", up);
    };
  }, []);

  useEffect(() => {
    if (canResizeSplit) return;
    drg.current = false;
    splRef.current?.classList.remove("drag");
  }, [canResizeSplit]);

  useEffect(() => {
    const container = rbRef.current;
    if (!container) return;

    const clearPinch = () => {
      pinchRef.current = null;
    };

    const handleTouchStart = (event: TouchEvent) => {
      if (event.touches.length !== 2) {
        clearPinch();
        return;
      }
      const [firstTouch, secondTouch] = [event.touches[0], event.touches[1]];
      pinchRef.current = {
        startDistance: getTouchDistance(firstTouch, secondTouch),
        startDayWidth: dayWidthRef.current,
      };
    };

    const handleTouchMove = (event: TouchEvent) => {
      if (event.touches.length !== 2 || !pinchRef.current) return;
      const [firstTouch, secondTouch] = [event.touches[0], event.touches[1]];
      const currentDistance = getTouchDistance(firstTouch, secondTouch);
      if (!currentDistance || !pinchRef.current.startDistance) return;
      event.preventDefault();
      const scale = currentDistance / pinchRef.current.startDistance;
      const centerClientX = (firstTouch.clientX + secondTouch.clientX) / 2;
      const nextDayWidth = clampDayWidth(pinchRef.current.startDayWidth * scale);
      zoomTimeline(nextDayWidth, centerClientX);
      pinchRef.current = {
        startDistance: currentDistance,
        startDayWidth: nextDayWidth,
      };
    };

    container.addEventListener("touchstart", handleTouchStart, { passive: true });
    container.addEventListener("touchmove", handleTouchMove, { passive: false });
    container.addEventListener("touchend", clearPinch);
    container.addEventListener("touchcancel", clearPinch);
    return () => {
      container.removeEventListener("touchstart", handleTouchStart);
      container.removeEventListener("touchmove", handleTouchMove);
      container.removeEventListener("touchend", clearPinch);
      container.removeEventListener("touchcancel", clearPinch);
    };
  }, [zoomTimeline]);

  const startEdit = (id: string, field: EditingField, value: string | number | null | undefined) => {
    setEditing({ id, field });
    setEditVal(String(value ?? ""));
    setTimeout(() => {
      inpRef.current?.focus();
      inpRef.current?.select();
    }, 10);
  };

  const applyAndClose = useCallback((id: string, field: EditingField, raw: string) => {
    let value: string | number | null = raw;
    if (field === "workers") value = Math.max(1, parseInt(raw, 10) || 1);
    if (field === "prog") value = Math.max(0, Math.min(100, parseInt(raw, 10) || 0));
    if (field === "depends_on") {
      value = resolveDependencyInput(raw, id, rows, tasks);
    }
    setTasks((current) => resolveDates(current.map((task) => (task.id === id ? updateTaskField(task, field, value) : task))));
    setEditing(null);
    if (pid) {
      if (field === "depends_on") {
        const currentTask = tasks.find((task) => task.id === id);
        const before = new Set(parseDeps(currentTask?.depends_on));
        const after = new Set(parseDeps(typeof value === "string" ? value : null));
        before.forEach((depId) => {
          if (!after.has(depId)) {
            ganttApi.removeDep(pid, id, depId).catch(() => {});
          }
        });
        after.forEach((depId) => {
          if (!before.has(depId)) {
            ganttApi.addDep(pid, id, depId).catch(() => {});
          }
        });
        return;
      }
      const apiField: Record<Exclude<EditingField, "depends_on">, string> = {
        name: "name",
        workers: "workers_count",
        start: "start_date",
        prog: "progress_override",
      };
      ganttApi.update(pid, id, { [apiField[field as Exclude<EditingField, "depends_on">]]: value }).catch(() => {});
    }
  }, [pid, rows, tasks]);

  const commit = useCallback(() => {
    if (!editing) return;
    applyAndClose(editing.id, editing.field, editVal);
  }, [applyAndClose, editVal, editing]);

  const addAfter = useCallback((afterId: string) => {
    const src = tasks.find((t) => t.id === afterId);
    const newTask: Task = {
      id: uid(),
      pid: src?.pid ?? null,
      is_group: false,
      depends_on: null,
      name: "Новая задача",
      start: src ? addD(src.start, src.dur) : TODAY,
      dur: 5,
      workers_count: src?.workers_count ?? 1,
      labor_hours: src?.labor_hours ?? deriveLaborHours(5, src?.workers_count ?? 1, src?.hours_per_day ?? DEFAULT_HOURS_PER_DAY),
      hours_per_day: src?.hours_per_day ?? DEFAULT_HOURS_PER_DAY,
      prog: 0,
      clr: src?.clr ?? "#3b82f6",
    };
    setTasks((current) => {
      const idx = current.findIndex((t) => t.id === afterId);
      const descs = getAllDescendants(current, afterId);
      const last = descs.reduce((mx, did) => {
        const i = current.findIndex((t) => t.id === did);
        return i > mx ? i : mx;
      }, idx);
      const next = [...current];
      next.splice(last + 1, 0, newTask);
      return resolveDates(next);
    });
    setSel(newTask.id);
    setTimeout(() => startEdit(newTask.id, "name", "Новая задача"), 40);
  }, [tasks]);

  const onKD = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    if (!editing) return;
    if (e.key === "Escape") {
      setEditing(null);
      return;
    }
    if (e.key === "Tab") {
      e.preventDefault();
      commit();
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const saved = editing;
      const value = editVal;
      setEditing(null);
      applyAndClose(saved.id, saved.field, value);
      setTimeout(() => addAfter(saved.id), 20);
    }
  }, [addAfter, applyAndClose, commit, editVal, editing]);

  const addSubtask = () => {
    if (!sel) return;
    const src = tasks.find((t) => t.id === sel);
    const newTask: Task = {
      id: uid(),
      pid: sel,
      is_group: false,
      depends_on: null,
      name: "Подзадача",
      start: src?.start ?? TODAY,
      dur: 3,
      workers_count: src?.workers_count ?? 1,
      labor_hours: src?.labor_hours ?? deriveLaborHours(3, src?.workers_count ?? 1, src?.hours_per_day ?? DEFAULT_HOURS_PER_DAY),
      hours_per_day: src?.hours_per_day ?? DEFAULT_HOURS_PER_DAY,
      prog: 0,
      clr: src?.clr ?? "#3b82f6",
    };
    setTasks((current) => {
      const idx = current.findIndex((t) => t.id === sel);
      const descs = getAllDescendants(current, sel);
      const last = descs.reduce((mx, did) => {
        const i = current.findIndex((t) => t.id === did);
        return i > mx ? i : mx;
      }, idx);
      const next = [...current];
      next.splice(last + 1, 0, newTask);
      return resolveDates(next);
    });
    setColl((current) => {
      const next = new Set(current);
      next.delete(sel);
      return next;
    });
    setSel(newTask.id);
    setTimeout(() => startEdit(newTask.id, "name", "Подзадача"), 40);
  };

  const delTask = () => {
    if (!sel) return;
    const descs = getAllDescendants(tasks, sel);
    const rm = new Set([sel, ...descs]);
    const nextTasks = tasks.filter((t) => !rm.has(t.id));
    setTasks(resolveDates(nextTasks));
    setSel(nextTasks[0]?.id ?? null);
  };

  const indent = () => {
    if (!sel) return;
    const idx = tasks.findIndex((t) => t.id === sel);
    if (idx < 1) return;
    const current = tasks[idx];
    const currentDepth = getDepth(tasks, current.id);
    for (let i = idx - 1; i >= 0; i--) {
      const candidate = tasks[i];
      if (getDepth(tasks, candidate.id) === currentDepth && candidate.pid === current.pid) {
        setTasks((allTasks) => resolveDates(allTasks.map((t) => (t.id === sel ? { ...t, pid: candidate.id } : t))));
        setColl((currentColl) => {
          const next = new Set(currentColl);
          next.delete(candidate.id);
          return next;
        });
        return;
      }
    }
  };

  const outdent = () => {
    if (!sel) return;
    const current = tasks.find((t) => t.id === sel);
    if (!current?.pid) return;
    const parent = tasks.find((t) => t.id === current.pid);
    setTasks((allTasks) => resolveDates(allTasks.map((t) => (t.id === sel ? { ...t, pid: parent?.pid ?? null } : t))));
  };

  const toggle = (id: string, e: MouseEvent<HTMLElement>) => {
    e.stopPropagation();
    setColl((current) => {
      const next = new Set(current);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const selTask = tasks.find((t) => t.id === sel) ?? null;
  const canSplitPanelTask = Boolean(panelTask && !tasks.some((t) => t.pid === panelTask.id) && panelTask.dur > 1);
  const canEditPanelTask = Boolean(panelTask && can(role,'edit'));
  const panelTaskHasKids = Boolean(panelTask && tasks.some((t) => t.pid === panelTask.id));

  const savePanelTask = useCallback(async () => {
    if (!pid || !panelTask || !panelForm || !can(role,'edit')) return;

    const trimmedName = panelForm.name.trim();
    if (!trimmedName) {
      setPanelSaveError("Укажите название задачи.");
      return;
    }

    const workers = Math.max(1, parseInt(panelForm.workers, 10) || 1);
    const laborHours = Number(panelForm.labor);
    const hoursPerDay = Number(panelForm.norm);
    const progress = Math.max(0, Math.min(100, parseInt(panelForm.prog, 10) || 0));
    const normalizedColor = panelForm.color.trim() || "#3b82f6";
    const resolvedDeps = resolveDependencyInput(panelForm.depends_on, panelTask.id, rows, tasks);
    const prevDeps = new Set(parseDeps(panelTask.depends_on));
    const nextDeps = new Set(parseDeps(resolvedDeps));

    const payload: Record<string, string | number | null> = {
      name: trimmedName,
      start_date: panelForm.start,
      color: normalizedColor,
    };

    if (!panelTaskHasKids) {
      if (!Number.isFinite(laborHours) || laborHours < 0) {
        setPanelSaveError("Укажите корректную трудоемкость.");
        return;
      }
      if (!Number.isFinite(hoursPerDay) || hoursPerDay <= 0) {
        setPanelSaveError("Укажите корректную норму часов в день.");
        return;
      }
      payload.workers_count = workers;
      payload.labor_hours = roundTo(laborHours);
      payload.hours_per_day = roundTo(hoursPerDay);
      payload.progress_override = progress;
    }

    setPanelSaving(true);
    setPanelSaveError(null);
    try {
      await ganttApi.update(pid, panelTask.id, payload);

      for (const depId of prevDeps) {
        if (!nextDeps.has(depId)) await ganttApi.removeDep(pid, panelTask.id, depId);
      }
      for (const depId of nextDeps) {
        if (!prevDeps.has(depId)) await ganttApi.addDep(pid, panelTask.id, depId);
      }

      await loadTasks(panelTask.id, activeBatchId);
    } catch (error) {
      setPanelSaveError(error instanceof Error ? error.message : "Не удалось сохранить задачу.");
    } finally {
      setPanelSaving(false);
    }
  }, [activeBatchId, loadTasks, panelForm, panelTask, panelTaskHasKids, pid, role, rows, tasks]);

  const saveTaskActs = useCallback(async (patch: {
    req_hidden_work_act?: boolean;
    req_intermediate_act?: boolean;
    req_ks2_ks3?: boolean;
  }) => {
    if (!pid || !panelTask?.estimate_id) return;
    setActsSaving(true);
    setPanelSaveError(null);
    try {
      const result = await estimates.updateActs(pid, panelTask.estimate_id, patch);
      setTasks((current) => current.map((task) => (
        task.id === panelTask.id ? { ...task, ...result } : task
      )));
    } catch (error) {
      setPanelSaveError(error instanceof Error ? error.message : "Не удалось обновить флаги актов.");
    } finally {
      setActsSaving(false);
    }
  }, [panelTask, pid]);

  const acceptBaseline = useCallback(async () => {
    if (!pid) return;
    setBaselineLoading(true);
    try {
      await ganttApi.acceptOverdue(pid, { reason: baselineReason.trim() || null });
      setBaselineReason("");
      await loadBaselineStatus();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Не удалось принять просроченный график");
    } finally {
      setBaselineLoading(false);
    }
  }, [baselineReason, loadBaselineStatus, pid]);

  const splitPanelTask = useCallback(async () => {
    if (!pid || !panelTask || !canSplitPanelTask) return;
    const nextWorkers = Math.max(1, parseInt(splitWorkers, 10) || 1);
    try {
      const result = await ganttApi.split(pid, panelTask.id, {
        split_date: splitDate,
        new_workers_count: nextWorkers,
      });
      await loadTasks(result?.created_task?.id ?? panelTask.id, activeBatchId);
      setPanelId(result?.created_task?.id ?? panelTask.id);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Не удалось разделить задачу");
    }
  }, [activeBatchId, canSplitPanelTask, loadTasks, panelTask, pid, splitDate, splitWorkers]);

  return(
    <>
      <style>{CSS}</style>
      <div className="root">

        {/* TOOLBAR */}
        <div className="tb">
          <button className={`btn p${!can(role,'edit')?' locked':''}`} onClick={() => { if (sel) addAfter(sel); }}>＋ Задача</button>
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
              onClick={() => setRole(key as RoleKey)}
            >{cfg.label}</button>
          ))}
          <span className="role-access-hint">
            {ROLES[role].can.map(a=>a).join(' · ')}
          </span>
        </div>

        <div className="baseline-bar">
          <span className="baseline-meta">
            {baselineStatus
              ? baselineStatus.has_overdue_tasks
                ? `Просроченных задач: ${baselineStatus.overdue_tasks_count}`
                : "Просроченных задач нет"
              : "Статус baseline недоступен"}
          </span>
          {baselineStatus?.latest && (
            <span className="baseline-meta">
              Последний baseline: W{baselineStatus.latest.baseline_week}/{baselineStatus.latest.baseline_year}
              {baselineStatus.latest.created_by?.name ? ` · ${baselineStatus.latest.created_by.name}` : ""}
            </span>
          )}
          {role === "pm" && (
            <>
              <input
                value={baselineReason}
                onChange={(e) => setBaselineReason(e.target.value)}
                placeholder="Причина принятия просроченного графика"
                style={{
                  minWidth: 260,
                  flex: "1 1 260px",
                  padding: "7px 10px",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                  fontFamily: "var(--sans)",
                }}
              />
              <button
                className="baseline-btn primary"
                onClick={acceptBaseline}
                disabled={baselineLoading || !baselineStatus?.can_accept}
              >
                {baselineLoading ? "Фиксируем..." : "Принять просроченный график как текущий"}
              </button>
            </>
          )}
        </div>

        {batches.length > 0 && (
          <div className="batch-bar">
            {batches.map((batch) => (
              <button
                key={batch.id}
                className={`batch-chip${activeBatchId === batch.id ? " active" : ""}`}
                onClick={() => selectBatch(batch.id)}
              >
                {batch.name}
              </button>
            ))}
            {activeBatchId && (
              <span className="batch-chip-meta">
                Отдельный гант по выбранной смете
              </span>
            )}
          </div>
        )}

        {batchError && (
          <div style={{ padding: "10px 12px", background: "rgba(239,68,68,.06)", borderBottom: "1px solid rgba(239,68,68,.18)", color: "var(--red)", fontSize: 12 }}>
            {batchError}
          </div>
        )}

        {taskError && (
          <div style={{ padding: "10px 12px", background: "rgba(239,68,68,.06)", borderBottom: "1px solid rgba(239,68,68,.18)", color: "var(--red)", fontSize: 12 }}>
            {taskError}
          </div>
        )}

        {/* SPLIT */}
        <div className={`split-vp${isCompactLayout ? " narrow" : ""}`}>
        <div
          className="split"
          style={isCompactLayout ? { width: splitMinWidth, minWidth: splitMinWidth } : undefined}
        >

          {/* LOADING STATE */}
        {!apiLoaded && (
          <div style={{position:'absolute',inset:0,display:'flex',alignItems:'center',
            justifyContent:'center',zIndex:10,background:'var(--surface)',opacity:.9}}>
            <span style={{color:'var(--muted)',fontSize:13,fontFamily:'var(--mono)'}}>Загрузка задач...</span>
          </div>
        )}

      {/* LEFT */}
          <div className="left" style={{width:effectiveLeftW}}>
            <div className="thead" style={{width:effectiveLeftW}}>
              <div className="th rn">#</div>
              <div className="th g">Наименование работ</div>
              <div className="th" style={{width:48,justifyContent:'center'}}>Дней</div>
              <div className="th" style={{width:60,justifyContent:'center'}}>Люди</div>
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
                    <div className="td mn c" style={{width:48,color:'var(--muted)'}}>
                      {row.dur+'д'}
                    </div>

                    {/* Workers */}
                    <div className={`td mn c${isEd&&editing.field==='workers'?' ed':''}`}
                      style={{width:60}}
                      onDoubleClick={() => !row.hasKids && startEdit(row.id,'workers',row.workers_count ?? 1)}>
                      {row.hasKids
                        ? <span style={{color:'var(--muted)'}}>—</span>
                        : isEd&&editing.field==='workers'
                          ? <input ref={inpRef} style={{width:36,textAlign:'center'}}
                              value={editVal} onChange={e=>setEditVal(e.target.value)}
                              onBlur={commit} onKeyDown={onKD}/>
                          : `${row.workers_count ?? 1} чел`
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
          <div className={`splitter${canResizeSplit ? "" : " disabled"}`} ref={splRef}
            onMouseDown={()=>{
              if (!canResizeSplit) return;
              drg.current=true;
              splRef.current?.classList.add('drag');
            }}/>

          {/* RIGHT GANTT */}
          <div className="right" style={isCompactLayout ? { minWidth: MIN_RIGHT_PANEL_W } : undefined}>
            {showZoomControls && (
              <div className="zoom-bar">
                <button className="zoom-btn" onClick={() => zoomTimeline(dayWidthRef.current / 1.2)} aria-label="Уменьшить масштаб">−</button>
                <button className="zoom-btn" onClick={() => zoomTimeline(DEFAULT_DAY_W)} aria-label="Сбросить масштаб">100%</button>
                <button className="zoom-btn" onClick={() => zoomTimeline(dayWidthRef.current * 1.2)} aria-label="Увеличить масштаб">+</button>
                <span className="zoom-val">{Math.round((dayWidth / DEFAULT_DAY_W) * 100)}%</span>
              </div>
            )}
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

            <div className={`gbw${showZoomControls ? " zoomable" : ""}`} ref={rbRef} onScroll={onRS}>
              <div className="gb" style={{width:W,minHeight:rows.length*ROW_H+120}}>

                {/* Rows — plain flow, no other siblings so nth-child is clean */}
                {rows.map((row,ri)=>{
                  const bx=diff(origin,row.start)*dayWidth;
                  const bw=Math.max(4,row.dur*dayWidth);
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
      </div>

      {/* TASK DETAIL PANEL */}
      {panelId && panelTask && (()=>{
        const tc = comments[panelId] || [];
        const depNums2 = parseDeps(panelTask.depends_on).map(d=>numMap[d]??'?');
        const progColor = panelTask.prog>=100?'#22c55e':panelTask.prog>=50?'#f59e0b':'#3b82f6';
        const panelWorkers = panelForm && !panelTaskHasKids
          ? normalizeWorkersCount(Number(panelForm.workers))
          : normalizeWorkersCount(panelTask.workers_count);
        const panelLaborHours = panelForm && !panelTaskHasKids
          ? (Number.isFinite(Number(panelForm.labor)) ? Number(panelForm.labor) : 0)
          : Number(panelTask.labor_hours ?? 0);
        const panelHoursPerDay = panelForm && !panelTaskHasKids
          ? normalizeHoursPerDay(Number(panelForm.norm))
          : normalizeHoursPerDay(panelTask.hours_per_day);
        const computedPanelDuration = panelTaskHasKids
          ? panelTask.dur
          : calculateDurationDays(panelLaborHours, panelWorkers, panelHoursPerDay, panelTask.dur);
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
                    <div className="pfield" style={{gridColumn:'1/-1'}}>
                      <div className="pfield-label">ID</div>
                      <div className="pfield-val mono">{panelTask.id}</div>
                    </div>
                    <div className="pfield" style={{gridColumn:'1/-1'}}>
                      <div className="pfield-label">Название</div>
                      {canEditPanelTask && panelForm
                        ? <input
                            className="pfield-input"
                            value={panelForm.name}
                            onChange={e=>setPanelForm(current => current ? { ...current, name: e.target.value } : current)}
                          />
                        : <div className="pfield-val">{panelTask.name}</div>
                      }
                    </div>
                    <div className="pfield">
                      <div className="pfield-label">Начало</div>
                      {canEditPanelTask && panelForm
                        ? <input
                            type="date"
                            className="pfield-input"
                            value={panelForm.start}
                            onChange={e=>setPanelForm(current => current ? { ...current, start: e.target.value } : current)}
                          />
                        : <div className="pfield-val mono">{dispD(panelTask.start)}</div>
                      }
                    </div>
                    <div className="pfield">
                      <div className="pfield-label">Конец</div>
                      <div className="pfield-val mono">{dispD(addD(panelTask.start,computedPanelDuration))}</div>
                    </div>
                    <div className="pfield">
                      <div className="pfield-label">Длительность</div>
                      <div className="pfield-val mono">{computedPanelDuration} дн.</div>
                    </div>
                    <div className="pfield">
                      <div className="pfield-label">Трудоемкость</div>
                      {canEditPanelTask && panelForm && !panelTaskHasKids
                        ? <input
                            type="number"
                            min={0}
                            step="0.1"
                            className="pfield-input"
                            value={panelForm.labor}
                            onChange={e=>setPanelForm(current => current ? { ...current, labor: e.target.value } : current)}
                          />
                        : <div className="pfield-val mono">{panelTaskHasKids ? "—" : `${formatHoursValue(panelTask.labor_hours)} ч`}</div>
                      }
                    </div>
                    <div className="pfield">
                      <div className="pfield-label">Исполнители</div>
                      {canEditPanelTask && panelForm && !panelTaskHasKids
                        ? <input
                            type="number"
                            min={1}
                            className="pfield-input"
                            value={panelForm.workers}
                            onChange={e=>setPanelForm(current => current ? { ...current, workers: e.target.value } : current)}
                          />
                        : <div className="pfield-val mono">{panelTask.workers_count ?? "—"}</div>
                      }
                    </div>
                    <div className="pfield">
                      <div className="pfield-label">Норма</div>
                      {canEditPanelTask && panelForm && !panelTaskHasKids
                        ? <input
                            type="number"
                            min={0.1}
                            step="0.1"
                            className="pfield-input"
                            value={panelForm.norm}
                            onChange={e=>setPanelForm(current => current ? { ...current, norm: e.target.value } : current)}
                          />
                        : <div className="pfield-val mono">{panelTaskHasKids ? "—" : `${formatHoursValue(panelTask.hours_per_day ?? DEFAULT_HOURS_PER_DAY)} ч/день`}</div>
                      }
                    </div>
                    <div className="pfield">
                      <div className="pfield-label">Зависит от</div>
                      {canEditPanelTask && panelForm
                        ? <input
                            className="pfield-input"
                            placeholder="№,№…"
                            value={panelForm.depends_on}
                            onChange={e=>setPanelForm(current => current ? { ...current, depends_on: e.target.value } : current)}
                          />
                        : <div className="pfield-val mono">{depNums2.length?depNums2.map(n=>`#${n}`).join(', '):'—'}</div>
                      }
                    </div>
                    <div className="pfield">
                      <div className="pfield-label">Цвет</div>
                      {canEditPanelTask && panelForm
                        ? <input
                            className="pfield-input"
                            value={panelForm.color}
                            onChange={e=>setPanelForm(current => current ? { ...current, color: e.target.value } : current)}
                          />
                        : <div className="pfield-val mono">{panelTask.clr}</div>
                      }
                    </div>
                    <div className="pfield" style={{gridColumn:'1/-1'}}>
                      <div className="pfield-label">Прогресс</div>
                      {canEditPanelTask && panelForm && !panelTaskHasKids
                        ? <div style={{display:'flex',alignItems:'center',gap:10,marginTop:6}}>
                            <input
                              type="range"
                              min={0}
                              max={100}
                              value={panelForm.prog}
                              onChange={e=>setPanelForm(current => current ? { ...current, prog: e.target.value } : current)}
                              style={{flex:1,accentColor:'var(--blue)'}}
                            />
                            <span style={{fontFamily:'var(--mono)',fontSize:12,fontWeight:600,color:progColor,minWidth:44,textAlign:'right'}}>
                              {panelForm.prog}%
                            </span>
                          </div>
                        : <div style={{display:'flex',alignItems:'center',gap:8,marginTop:2}}>
                            <div className="prog-big" style={{flex:1}}>
                              <div className="prog-big-fill" style={{width:panelTask.prog+'%',background:progColor}}/>
                            </div>
                            <span style={{fontFamily:'var(--mono)',fontSize:12,fontWeight:600,color:progColor}}>
                              {panelTask.prog}%
                            </span>
                          </div>
                      }
                    </div>
                    <div className="pfield" style={{gridColumn:'1/-1'}}>
                      <div className="pfield-label">Формула</div>
                      <div className="pfield-val mono">
                        {panelTaskHasKids
                          ? "Для групповой задачи длительность задается дочерними работами."
                          : `${formatHoursValue(panelLaborHours)} ч / ${panelWorkers} чел / ${formatHoursValue(panelHoursPerDay)} ч/день = ${computedPanelDuration} дн.`}
                      </div>
                    </div>
                  </div>
                  {canEditPanelTask
                    ? <div className="panel-actions">
                        {panelSaveError && <div className="panel-save-error">{panelSaveError}</div>}
                        <button className="panel-save-btn" onClick={savePanelTask} disabled={panelSaving || !panelForm}>
                          {panelSaving ? "Сохранение..." : "Сохранить"}
                        </button>
                      </div>
                    : <div className="panel-readonly-note" style={{marginTop:12}}>
                        Карточка доступна только для просмотра в текущей роли.
                      </div>
                  }
                </div>

                <div className="panel-section">
                  <div className="panel-section-title">Акты</div>
                  {panelTask.estimate_id
                    ? <>
                        <div className="act-grid">
                          {[
                            ["req_hidden_work_act", "Акты скрытых работ с приглашением технадзора"],
                            ["req_intermediate_act", "Акты промежуточного выполнения работ"],
                            ["req_ks2_ks3", "КС-2, КС-3 и исполнительная съемка по этапу"],
                          ].map(([key, label]) => (
                            <label key={key} className="act-item">
                              <input
                                type="checkbox"
                                checked={Boolean(panelTask[key as keyof Task])}
                                disabled={!canEditPanelTask || actsSaving}
                                onChange={(e) => saveTaskActs({ [key]: e.target.checked })}
                              />
                              <span>{label}</span>
                            </label>
                          ))}
                        </div>
                        <div className="act-hint">
                          Флаги сохраняются на строке сметы и отображаются в карточке связанной задачи.
                        </div>
                      </>
                    : <div className="act-hint">
                        У этой задачи нет связанной строки сметы, поэтому флаги актов недоступны.
                      </div>
                  }
                </div>

                <div className="panel-section">
                  <div className="panel-section-title">Разделить задачу</div>
                  {canSplitPanelTask
                    ? <div style={{display:'grid',gridTemplateColumns:'1fr 1fr auto',gap:10,alignItems:'end'}}>
                        <label className="pfield" style={{margin:0}}>
                          <div className="pfield-label">Дата начала 2-й части</div>
                          <input
                            type="date"
                            value={splitDate}
                            onChange={e=>setSplitDate(e.target.value)}
                            style={{marginTop:6,padding:'10px 12px',border:'1px solid var(--border)',borderRadius:10,font:'inherit'}}
                          />
                        </label>
                        <label className="pfield" style={{margin:0}}>
                          <div className="pfield-label">Исполнителей во 2-й части</div>
                          <input
                            type="number"
                            min={1}
                            value={splitWorkers}
                            onChange={e=>setSplitWorkers(e.target.value)}
                            style={{marginTop:6,padding:'10px 12px',border:'1px solid var(--border)',borderRadius:10,font:'inherit'}}
                          />
                        </label>
                        <button
                          className="comment-submit"
                          style={{height:42,marginTop:20}}
                          onClick={splitPanelTask}
                          disabled={!splitDate || !splitWorkers}
                        >
                          Разделить
                        </button>
                      </div>
                    : <div className="no-comments">
                        Разделение доступно только для листовой задачи длительностью больше 1 дня.
                      </div>
                  }
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
