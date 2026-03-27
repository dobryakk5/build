export type DashboardStatus = "green" | "yellow" | "red";

export interface Task {
  id: string;
  pid: string | null;
  name: string;
  start: string;
  dur: number;
  prog: number;
  clr: string;
  depends_on: string | null;
  who?: string;
}

export interface Project {
  id: string;
  name: string;
  address?: string | null;
  dashboard_status: DashboardStatus;
  budget?: number | null;
  tasks_count?: number;
  members_count?: number;
}

export interface User {
  id: string;
  email: string;
  name: string;
  role?: string | null;
}
