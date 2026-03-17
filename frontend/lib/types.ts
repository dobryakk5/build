export interface Task {
  id: string;
  pid: string | null;
  name: string;
  start: string;
  dur: number;
  prog: number;
  clr: string;
  depends_on: string | null;
}

export interface Project {
  id: string;
  name: string;
  address?: string;
  dashboard_status: 'green' | 'yellow' | 'red';
  budget?: number;
}