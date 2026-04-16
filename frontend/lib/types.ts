export type DashboardStatus = "green" | "yellow" | "red";

export interface Task {
  id: string;
  estimate_batch_id?: string | null;
  estimate_id?: string | null;
  pid: string | null;
  name: string;
  start: string;
  dur: number;
  is_group?: boolean;
  workers_count?: number | null;
  labor_hours?: number | null;
  fer_labor_hours?: number | null;
  hours_per_day?: number | null;
  req_hidden_work_act?: boolean;
  req_intermediate_act?: boolean;
  req_ks2_ks3?: boolean;
  prog: number;
  clr: string;
  depends_on: string | null;
  materials?: EstimateMaterial[];
  who?: string;
}

export interface Project {
  id: string;
  name: string;
  address?: string | null;
  status?: string;
  dashboard_status: DashboardStatus;
  budget?: number | null;
  color?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  tasks_count?: number;
  members_count?: number;
  my_role?: string | null;
  created_at?: string;
}

export interface EstimateBatch {
  id: string;
  project_id: string;
  name: string;
  estimate_kind: number;
  source_filename?: string | null;
  estimates_count: number;
  gantt_tasks_count: number;
  fer_matched_count: number;
  fer_words_matched_count: number;
  total_price: number;
  created_at: string;
}

export interface EstimateMaterial {
  name: string;
  unit?: string | null;
  quantity?: number | null;
  unit_price?: number | null;
  total_price?: number | null;
}

export interface EstimateRow {
  id: string;
  estimate_batch_id?: string | null;
  section?: string | null;
  work_name: string;
  unit?: string | null;
  quantity?: number | null;
  unit_price?: number | null;
  total_price?: number | null;
  materials?: EstimateMaterial[];
  enir_code?: string | null;
  fer_table_id?: number | null;
  fer_work_type?: string | null;
  fer_match_score?: number | null;
  fer_group_kind?: "section" | "collection" | null;
  fer_group_ref_id?: number | null;
  fer_group_title?: string | null;
  fer_group_collection_id?: number | null;
  fer_group_collection_num?: string | null;
  fer_group_collection_name?: string | null;
  fer_group_match_score?: number | null;
  fer_group_is_ambiguous?: boolean;
  fer_group_candidates?: FerGroupCandidate[] | null;
  fer_words_entry_id?: number | null;
  fer_words_code?: string | null;
  fer_words_name?: string | null;
  fer_words_human_hours?: number | null;
  fer_words_machine_hours?: number | null;
  fer_words_match_score?: number | null;
  fer_words_match_count?: number | null;
  req_hidden_work_act?: boolean;
  req_intermediate_act?: boolean;
  req_ks2_ks3?: boolean;
}

export interface UserRef {
  id: string;
  name: string;
}

export interface FerGroupCandidate {
  kind: "section" | "collection";
  ref_id: number;
  title: string;
  collection_id: number;
  collection_num: string | null;
  collection_name: string | null;
  score: number;
}

export interface FerGroupOptionSection {
  id: number;
  title: string;
}

export interface FerGroupOptionCollection {
  id: number;
  num: string;
  name: string;
  sections: FerGroupOptionSection[];
}

export interface WorkJournalEntry {
  entry_type: "work";
  id: string;
  report_id: string | null;
  task_id: string;
  task_name: string;
  work_done: string;
  man_hours: number | null;
  workers_count: number | null;
  volume_done: number | null;
  volume_unit: string | null;
  event_date: string;
  report_date: string;
}

export interface MaterialDelayJournalEntry {
  entry_type: "material_delay";
  id: string;
  material_id: string;
  material_name: string;
  old_delivery_date: string | null;
  new_delivery_date: string;
  days_shifted: number | null;
  reason: string;
  reporter?: UserRef | null;
  event_date: string;
  report_date: string;
}

export interface ScheduleBaselineJournalEntry {
  entry_type: "schedule_baseline";
  id: string;
  kind: string;
  baseline_year: number;
  baseline_week: number;
  reason: string | null;
  created_by?: UserRef | null;
  event_date: string;
  report_date: string;
}

export type JournalEntry =
  | WorkJournalEntry
  | MaterialDelayJournalEntry
  | ScheduleBaselineJournalEntry;

export interface BaselineStatus {
  can_accept: boolean;
  accepted_this_week: boolean;
  current_year: number;
  current_week: number;
  has_overdue_tasks: boolean;
  overdue_tasks_count: number;
  latest: {
    id: string;
    kind: string;
    baseline_year: number;
    baseline_week: number;
    reason: string | null;
    created_at: string;
    created_by?: UserRef | null;
  } | null;
}

export interface EstimateSummary {
  total: number;
  sections: Array<{
    name: string;
    subtotal: number;
    items: number;
  }>;
}

export interface FerKnowledgeImportResponse {
  batch_id: string;
  total_matched_rows: number;
  imported_count: number;
  skipped_duplicates: number;
  embedding_job_id?: string | null;
  status: string;
  reason?: string | null;
}

export interface FerKnowledgeImportJobStatus {
  job_id: string;
  batch_id: string;
  status: "pending" | "processing" | "done" | "failed";
  total: number;
  embedded: number;
  failed_rows: number;
  imported_count: number;
  total_matched_rows: number;
  skipped_duplicates: number;
  created_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
}

export interface User {
  id: string;
  email: string;
  name: string;
  avatar_url?: string | null;
  role?: string | null;
  email_verified: boolean;
  is_superadmin?: boolean;
}

export interface CurrentUser extends User {
  projects: Array<{
    project_id: string;
    role: string;
  }>;
}

export interface EnirCollectionSummary {
  id: number;
  code: string;
  title: string;
  description: string | null;
  issue: string | null;
  issue_title: string | null;
  source_file: string | null;
  source_format: string | null;
  sort_order: number;
  paragraph_count: number;
}

export interface EnirStructureRef {
  id: number;
  source_id: string;
  title: string;
}

export interface EnirParagraphShort {
  id: number;
  collection_id: number;
  source_paragraph_id: string | null;
  code: string;
  title: string;
  unit: string | null;
  html_anchor: string | null;
  section: EnirStructureRef | null;
  chapter: EnirStructureRef | null;
  structure_title: string | null;
  is_technical: boolean;
}

export interface EnirWorkComposition {
  condition: string | null;
  operations: string[];
}

export interface EnirCrewMember {
  profession: string;
  grade: number | null;
  count: number;
}

export interface EnirNorm {
  row_num: number | null;
  work_type: string | null;
  condition: string | null;
  thickness_mm: number | null;
  column_label: string | null;
  norm_time: number | null;
  price_rub: number | null;
}

export interface EnirNote {
  num: number;
  text: string;
  coefficient: number | null;
  pr_code: string | null;
}

export interface EnirParagraphTextBlock {
  sort_order: number;
  raw_text: string;
}

export interface EnirApplicationNote {
  sort_order: number;
  text: string;
}

export interface EnirParagraphRef {
  sort_order: number;
  ref_type: string;
  link_text: string | null;
  href: string | null;
  abs_url: string | null;
  context_text: string | null;
  is_meganorm: boolean | null;
}

export interface EnirSourceCrewItem {
  sort_order: number;
  profession: string | null;
  grade: number | null;
  count: number | null;
  raw_text: string | null;
}

export interface EnirSourceNote {
  sort_order: number;
  code: string | null;
  text: string;
  coefficient: number | null;
}

export interface EnirNormCellValue {
  value_type: string;
  value_text: string | null;
}

export interface EnirNormTableColumn {
  column_key: string;
  header: string;
  label: string | null;
}

export interface EnirNormTableRowCell {
  column_key: string;
  header: string;
  label: string | null;
  values: EnirNormCellValue[];
}

export interface EnirNormTableRow {
  source_row_id: string;
  source_row_num: number | null;
  cells: EnirNormTableRowCell[];
}

export interface EnirNormTable {
  source_table_id: string;
  title: string | null;
  row_count: number | null;
  columns: EnirNormTableColumn[];
  rows: EnirNormTableRow[];
}

export interface EnirCollectionRef {
  id: number;
  code: string;
  title: string;
  description: string | null;
  issue: string | null;
  issue_title: string | null;
  source_file: string | null;
  source_format: string | null;
}

export interface EnirParagraphFull extends EnirParagraphShort {
  collection: EnirCollectionRef;
  work_compositions: EnirWorkComposition[];
  crew: EnirCrewMember[];
  norms: EnirNorm[];
  notes: EnirNote[];
  technical_characteristics: EnirParagraphTextBlock[];
  application_notes: EnirApplicationNote[];
  refs: EnirParagraphRef[];
  source_work_items: EnirParagraphTextBlock[];
  source_crew_items: EnirSourceCrewItem[];
  source_notes: EnirSourceNote[];
  norm_tables: EnirNormTable[];
  has_legacy_norms: boolean;
  has_tabular_norms: boolean;
}

export interface FerCollectionSummary {
  id: number;
  num: string;
  name: string;
  ignored: boolean;
  effective_ignored: boolean;
  sections_count: number;
  subsections_count: number;
  total_tables_count: number;
  root_tables_count: number;
}

export interface FerBreadcrumbItem {
  kind: "collection" | "section" | "subsection" | "table";
  id: number;
  label: string;
  num?: string;
  ignored?: boolean;
  effective_ignored?: boolean;
}

export interface FerCollectionRef {
  id: number;
  num: string;
  name: string;
  ignored?: boolean;
  effective_ignored?: boolean;
}

export interface FerSectionRef {
  id: number;
  title: string;
  ignored?: boolean;
  effective_ignored?: boolean;
}

export interface FerBrowseItem {
  kind: "section" | "subsection" | "table";
  id: number;
  title: string;
  ignored: boolean;
  effective_ignored: boolean;
  subsection_count?: number;
  table_count?: number;
  row_count?: number;
  table_url?: string;
  common_work_name?: string | null;
}

export interface FerBrowseResponse {
  level: "collection" | "section" | "subsection";
  collection: FerCollectionRef;
  section: FerSectionRef | null;
  subsection: FerSectionRef | null;
  breadcrumb: FerBreadcrumbItem[];
  items: FerBrowseItem[];
}

export interface FerSearchResult {
  table_id: number;
  table_title: string;
  row_count: number;
  table_url: string;
  common_work_name: string | null;
  ignored: boolean;
  effective_ignored: boolean;
  collection: FerCollectionRef;
  section: FerSectionRef | null;
  subsection: FerSectionRef | null;
  match_scope: "collection" | "section" | "subsection" | "table_title" | "common_work_name" | "row_slug" | "clarification";
  matched_text: string | null;
  matching_rows_count: number;
}

export interface FerTableRow {
  id: number;
  row_slug: string | null;
  clarification: string | null;
  h_hour: number | null;
  m_hour: number | null;
}

export interface FerTableDetail {
  id: number;
  table_title: string;
  table_url: string;
  row_count: number;
  common_work_name: string | null;
  ignored: boolean;
  effective_ignored: boolean;
  collection: FerCollectionRef;
  section: FerSectionRef | null;
  subsection: FerSectionRef | null;
  breadcrumb: FerBreadcrumbItem[];
  rows: FerTableRow[];
}

export interface FerWordsCandidate {
  entry_id: number;
  fer_code: string;
  display_name: string;
  human_hours: number | null;
  machine_hours: number | null;
  matched_tokens: number;
  exact_matches: number;
  numeric_matches: number;
  average_ratio: number;
  score: number;
  matched_words: string[];
}
