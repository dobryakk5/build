// frontend/lib/dateUtils.ts
// Зеркало Python date_utils.py — единая логика рабочих дней

export function addWorkingDays(
  start: Date,
  workingDays: number,
  holidays: Set<string> = new Set(),
): Date {
  if (workingDays <= 0) return new Date(start);
  let current = new Date(start);
  let added = 0;
  while (added < workingDays) {
    current.setDate(current.getDate() + 1);
    const iso = current.toISOString().split("T")[0];
    if (current.getDay() !== 0 && current.getDay() !== 6 && !holidays.has(iso)) added++;
  }
  return current;
}

export function taskEndDate(startDate: string, workingDays: number): string {
  return addWorkingDays(new Date(startDate), workingDays).toISOString().split("T")[0];
}

export function workingDaysBetween(start: Date, end: Date): number {
  let count = 0;
  const cur = new Date(start);
  while (cur < end) {
    cur.setDate(cur.getDate() + 1);
    if (cur.getDay() !== 0 && cur.getDay() !== 6) count++;
  }
  return count;
}

export function fmtDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${String(d.getDate()).padStart(2,"0")}.${String(d.getMonth()+1).padStart(2,"0")}`;
}

export function fmtDateTime(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${fmtDate(iso)} ${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
}

export function fmtMoney(n: number): string {
  return n?.toLocaleString("ru-RU", { maximumFractionDigits: 0 }) ?? "—";
}
