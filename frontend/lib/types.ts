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
  workers_count?: number | null;
  my_role?: string | null;
  created_at?: string;
}

export interface EstimateBatch {
  id: string;
  project_id: string;
  name: string;
  estimate_kind: number;
  start_date?: string | null;
  workers_count?: number | null;
  hours_per_day?: number | null;
  source_filename?: string | null;
  estimate_type_id?: string | null;
  estimate_type_title?: string | null;
  estimate_type_number?: string | null;
  project_variant_id?: string | null;
  project_variant_title?: string | null;
  project_variant_number?: string | null;
  taxonomy_dictionary_version?: string | null;
  clarification_answers?: Record<string, unknown> | null;
  estimates_count: number;
  gantt_tasks_count: number;
  fer_matched_count: number;
  fer_words_matched_count: number;
  total_price: number;
  created_at: string;
}

export type ParserProfile =
  | "auto"
  | "pdf_materials_labor"
  | "excel_typed_journal"
  | "manual_mapping";

export type EstimateItemType = "work" | "material" | "mechanism" | "overhead" | "unknown";

export interface EstimateSourceParent {
  block_id?: string | null;
  title?: string | null;
  description?: string | null;
}

export interface PreviewRow {
  index?: number | null;
  row_order: number | null;
  section: string | null;
  section_block_id?: string | null;
  section_title?: string | null;
  section_description?: string | null;
  section_parent_context?: string | null;
  source_parent?: EstimateSourceParent | null;
  item_type: EstimateItemType;
  name: string;
  spec?: string | null;
  unit?: string | null;
  quantity?: number | null;
  total_price?: number | null;
  confidence?: number | null;
  reason?: string | null;
  macro_id?: number | null;
  subtype_code?: string | null;
  subtype_name?: string | null;
  work_section_code?: string | null;
  work_section_name?: string | null;
  work_subtype_code?: string | null;
  work_subtype_name?: string | null;
  classification_score?: number | null;
  classification_confidence?: string | null;
  classification_needs_review?: boolean | null;
  classification_source?: string | null;
  classification_candidates?: Array<Record<string, unknown>> | null;
  classification_matched_terms?: Record<string, string[]> | null;
  operator_review_required?: boolean | null;
  work_stage_number?: string | null;
  work_stage_title?: string | null;
  canonical_stage_id?: string | null;
  stage_occurrence_index?: number | null;
  stage_occurrence_label?: string | null;
  stage_options_mode?: string | null;
  stage_option_id?: string | null;
  stage_option_title?: string | null;
  stage_confidence?: string | null;
  stage_match_type?: string | null;
  stage_match_score_json?: Record<string, unknown> | null;
  work_type_match_score_json?: Record<string, unknown> | null;
  row_role?: string | null;
  section_id?: string | null;
  subtype_id?: string | null;
  needs_review?: boolean | null;
  review_reason?: string | null;
  work_type_confidence?: string | null;
  row_hash?: string | null;
  materials?: PreviewRow[];
}

export interface PreviewTypeOverride {
  index: number;
  row_hash: string;
  item_type: EstimateItemType;
}

export interface PreviewAddedRow {
  section?: string | null;
  name: string;
  item_type: EstimateItemType;
  unit?: string | null;
  quantity?: number | null;
  total_price?: number | null;
}

export interface PreviewStageOverride {
  index: number;
  row_hash: string;
  work_stage_number?: string | null;
  work_stage_title?: string | null;
  canonical_stage_id?: string | null;
  stage_occurrence_index?: number | null;
  stage_occurrence_label?: string | null;
  stage_options_mode?: string | null;
  stage_option_id?: string | null;
  stage_option_title?: string | null;
  section_id?: string | null;
  subtype_id?: string | null;
  row_role?: string | null;
}

export interface PreviewEdits {
  type_overrides: PreviewTypeOverride[];
  added_rows: PreviewAddedRow[];
  stage_overrides?: PreviewStageOverride[];
}

export interface PreviewGroup {
  section: string;
  totals: Record<EstimateItemType, { count: number; total: number }>;
  works: PreviewRow[];
  materials: PreviewRow[];
  mechanisms: PreviewRow[];
  overhead: PreviewRow[];
  unknown: PreviewRow[];
}

export interface PreviewResult {
  preview_id: string;
  filename: string;
  parser_profile: string;
  detected_format?: string | null;
  strategy?: string | null;
  confidence?: number | null;
  type_breakdown: Record<EstimateItemType, { count: number; total: number }>;
  computed_total_all_rows: number;
  declared_total?: number | null;
  difference?: number | null;
  difference_reason?: string | null;
  unknown_count: number;
  unknown_rows: PreviewRow[];
  low_confidence_rows: PreviewRow[];
  sample_rows: PreviewRow[];
  rows: PreviewRow[];
  ignored_subtotal_rows_count: number;
  groups: PreviewGroup[];
  stage_groups?: Array<{
    work_stage_number?: string | null;
    work_stage_title?: string | null;
    canonical_stage_id?: string | null;
    stage_options_mode?: string | null;
    rows_count: number;
    needs_review_count: number;
    total: number;
    rows: PreviewRow[];
  }>;
  hierarchy_suggestions?: {
    estimate_types: Array<Record<string, unknown>>;
    project_variants: Array<Record<string, unknown>>;
  } | null;
  stage_review_count?: number;
  truncated: boolean;
  no_section_count: number;
  warnings?: string[];
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
  item_type?: "work" | "mechanism";
  section?: string | null;
  section_block_id?: string | null;
  section_title?: string | null;
  section_description?: string | null;
  section_parent_context?: string | null;
  source_parent?: EstimateSourceParent | null;
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
  labor_hours?: number | null;
  work_section_code?: string | null;
  work_section_name?: string | null;
  work_subtype_code?: string | null;
  work_subtype_name?: string | null;
  estimate_type_id?: string | null;
  estimate_type_number?: string | null;
  project_variant_id?: string | null;
  project_variant_number?: string | null;
  canonical_stage_id?: string | null;
  work_stage_number?: string | null;
  work_stage_title?: string | null;
  stage_occurrence_index?: number | null;
  stage_occurrence_label?: string | null;
  stage_options_mode?: string | null;
  stage_option_id?: string | null;
  stage_option_title?: string | null;
  section_id?: string | null;
  subtype_id?: string | null;
  row_role?: string | null;
  parent_row_id?: string | null;
  inherited_from_row_id?: string | null;
  stage_confidence?: string | null;
  work_type_confidence?: string | null;
  autofill_enabled?: boolean | null;
  needs_review?: boolean;
  review_reason?: string | null;
  stage_match_type?: string | null;
  stage_match_score_json?: Record<string, unknown> | null;
  work_type_match_score_json?: Record<string, unknown> | null;
  classification_score?: number | null;
  classification_confidence?: string | null;
  classification_needs_review?: boolean;
  classification_source?: string | null;
  classification_candidates?: Array<Record<string, unknown>> | null;
  classification_matched_terms?: Record<string, string[]> | null;
  operator_review_required?: boolean;
  operator_review_status?: string | null;
  operator_review_reason?: string | null;
  dictionary_version?: string | null;
  manual_override?: boolean;
  fer_multiplier?: number | null;
  req_hidden_work_act?: boolean;
  req_intermediate_act?: boolean;
  req_ks2_ks3?: boolean;
}

export interface UserRef {
  id: string;
  name: string;
}

export interface ActivityEvent {
  id: string;
  organization_id: string;
  project_id: string | null;
  user_id: string | null;
  user: (UserRef & { email?: string | null }) | null;
  session_id: string | null;
  event_type: string;
  entity_type: string | null;
  entity_id: string | null;
  path: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
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

export interface ForemanTaskReportEntry {
  entry_type: "foreman_report";
  id: string;
  report_date: string;
  event_date: string;
  status: "pending" | "done_as_planned" | "done_not_as_planned" | "not_done";
  status_label: string;
  note: string | null;
  task_id: string;
  task_name: string | null;
  foreman_id: string;
  foreman_name: string | null;
  email_sent_at: string | null;
  responded_at: string | null;
}

export type JournalEntry =
  | WorkJournalEntry
  | MaterialDelayJournalEntry
  | ScheduleBaselineJournalEntry
  | ForemanTaskReportEntry;

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

export interface KtpGroup {
  id: string;
  project_id: string;
  estimate_batch_id: string;
  group_key: string;
  title: string;
  row_count: number;
  total_price: number | null;
  sort_order: number;
  status: "new" | "questions_required" | "generated" | "failed";
  ktp_card_id: string | null;
  wt_code?: string | null;
  wt_name?: string | null;
  wt_match_reason?: string | null;
  wt_match_confidence?: number | null;
  wt_match_candidates?: Array<{ wt_code: string; wt_name: string }> | null;
}

export interface KtpQuestion {
  key: string;
  label: string;
  type: "text" | "textarea" | "number" | "select";
  hint?: string | null;
  options?: string[] | null;
}

export interface KtpStep {
  no: number;
  stage: string;
  work_details: string;
  control_points: string;
}

export interface KtpCard {
  id: string;
  title: string | null;
  goal: string | null;
  steps: KtpStep[];
  recommendations: string[];
  status: string;
  questions_json?: KtpQuestion[] | null;
}

export type KtpGenerateResponse =
  | {
      sufficient: false;
      questions: KtpQuestion[];
      ktp_card_id: null;
      ktp: null;
    }
  | {
      sufficient: true;
      questions: [];
      ktp_card_id: string;
      ktp: KtpCard;
    };

// ─────────────── КТП по смете (AI-flow) ───────────────

export type KtpEstimateStatus =
  | "stage1_pending"
  | "stage1_processing"
  | "stage1_review"
  | "stage1_failed"
  | "stage2_review"
  | "prod_pending"
  | "prod_review"
  | "fer_pending"
  | "fer_processing"
  | "fer_review"
  | "fer_failed"
  | "gpr_pending"
  | "gpr_sequence_review"
  | "gpr_ready"
  | "gpr_processing"
  | "gpr_done"
  | "gpr_failed";

export interface KtpEstimateSession {
  id: string;
  project_id: string;
  estimate_batch_id: string;
  status: KtpEstimateStatus;
  error_message?: string | null;
  stage1_job_id?: string | null;
  gpr_job_id?: string | null;
  stage1_grouping_mode?: string | null;
  preserve_estimate_structure?: boolean;
}

export interface KtpWbsItem {
  id: string;
  group_id: string;
  name: string;
  sort_order: number;
  origin: "from_estimate" | "ai_added" | "manual";
  estimate_id?: string | null;
  unit?: string | null;
  quantity?: number | null;
  quantity_source?: string | null;
  review_status: "pending" | "accepted" | "rejected";
  ai_reason?: string | null;
  norm_source?: string | null;
  norm_kind?: string | null;
  norm_value?: number | null;
  norm_unit?: string | null;
  brigade_size?: number | null;
  labor_hours?: number | null;
  duration_days?: number | null;
  fer_table_id?: number | null;
  fer_row_id?: number | null;
  fer_match_source?: string | null;
  fer_match_score?: number | null;
  fer_h_hour?: number | null;
  fer_unit?: string | null;
  fer_unit_multiplier?: number | null;
  fer_match_label?: string | null;
  work_section_code?: string | null;
  work_section_name?: string | null;
  work_subtype_code?: string | null;
  work_subtype_name?: string | null;
  work_type_confidence?: string | null;
  work_type_needs_review: boolean;
  work_type_candidates: Array<Record<string, unknown>>;
  work_type_source?: string | null;
  section_block_id?: string | null;
  section_title?: string | null;
  section_description?: string | null;
  section_parent_context?: string | null;
  source_parent?: EstimateSourceParent | null;
  stage_needs_review: boolean;
  stage_review_reason?: string | null;
  stage_confidence_percent?: number | null;
  operator_review_required: boolean;
  manual_override: boolean;
  gpr_confirmed: boolean;
  gpr_blocker: boolean;
}

export interface KtpWbsGroup {
  id: string;
  title: string;
  sort_order: number;
  wt_code?: string | null;
  wt_name?: string | null;
  work_section_code?: string | null;
  work_section_name?: string | null;
  work_type_confidence?: string | null;
  work_type_source?: string | null;
  status: "draft" | "card_questions" | "card_generated" | "card_failed";
  start_date?: string | null;
  duration_days?: number | null;
  items: KtpWbsItem[];
}

export interface KtpWbsGroupDependency {
  group_id: string;
  depends_on_group_id: string;
}

export interface KtpSessionSubtype {
  id: string;
  subtype_code: string;
  subtype_name: string;
  work_subtype_code?: string | null;
  work_subtype_name?: string | null;
  taxonomy_code?: string | null;
  item_id?: string | null;
  session_subtype_key?: string | null;
  macro_name?: string | null;
  unit?: string | null;
  volume?: number | null;
  output_per_day?: number | null;
  crew_size?: number | null;
  lag_after_days: number;
  output_source: "catalog" | "manual" | "none" | "default";
  // "estimate" — размер бригады взят из загрузки сметы (workers_count)
  crew_source: "default" | "manual" | "estimate" | "none";
  lag_source: "default" | "manual";
  selected_rate_item_id?: string | null;
  selected_rate_mapping_id?: string | null;
  rate_unit_code?: string | null;
  item_unit_code?: string | null;
  unit_conversion_factor?: number | null;
  labor_hours_per_unit_min?: number | null;
  labor_hours_per_unit_avg?: number | null;
  labor_hours_per_unit_max?: number | null;
  effective_labor_hours_per_unit_min?: number | null;
  effective_labor_hours_per_unit_avg?: number | null;
  effective_labor_hours_per_unit_max?: number | null;
  session_calculated_labor_hours_min?: number | null;
  session_calculated_labor_hours_avg?: number | null;
  session_calculated_labor_hours_max?: number | null;
  rate_auto_applicable?: boolean;
  rate_needs_review?: boolean;
  rate_review_reason?: string | null;
  resolved_labor_source?: string | null;
  resolved_labor_hours?: number | null;
  rate_catalog_version?: string | null;
  rate_catalog_file?: string | null;
}

export interface KtpWbs {
  session: KtpEstimateSession;
  groups: KtpWbsGroup[];
  group_dependencies: KtpWbsGroupDependency[];
  session_subtypes: KtpSessionSubtype[];
}

export interface KtpEstimateCard {
  id: string;
  title: string | null;
  goal: string | null;
  steps: KtpStep[];
  recommendations: string[];
  status: string;
  questions_json?: KtpQuestion[] | null;
}

export type KtpEstimateCardResponse =
  | { sufficient: false; questions: KtpQuestion[]; group_id: null; card: null }
  | { sufficient: true; questions: []; group_id: string; card: KtpEstimateCard };

// ─────────────── JSON v6 work taxonomy ───────────────

export interface WorkTaxonomyExample {
  work_subtype_code: string;
  work_subtype_name: string;
  taxonomy_code?: string | null;
  display_code?: string | null;
}

export interface WorkTaxonomyTermSummary {
  strong_terms: number;
  weak_terms: number;
  action_object_pairs: number;
  negative_terms?: number;
}

export interface WorkTaxonomyTermsJson {
  section?: {
    strong_terms?: string[];
    weak_terms?: string[];
    action_terms?: string[];
    object_terms?: string[];
    material_terms?: string[];
    document_terms?: string[];
    unit_hints?: string[];
    negative_terms?: string[];
  };
  subtype?: {
    strong_terms?: string[];
    weak_terms?: string[];
    action_object_pairs?: string[][];
    negative_terms?: string[];
  };
}

export interface WorkTaxonomySection {
  section_code: string;
  section_name: string;
  taxonomy_code?: string | null;
  scope?: string | null;
  subtypes_count: number;
  examples: WorkTaxonomyExample[];
  dictionary_version?: string | null;
}

export interface WorkTaxonomySubtype {
  work_subtype_code: string;
  work_subtype_name: string;
  section_code: string;
  section_name: string;
  taxonomy_code?: string | null;
  display_code?: string | null;
  legacy_csv_codes: string[];
  term_summary: WorkTaxonomyTermSummary;
  terms_json?: WorkTaxonomyTermsJson | null;
  dictionary_version?: string | null;
}

export interface WorkProjectVariant {
  id: string;
  number: string;
  title: string;
  stages_count: number;
  stages?: WorkStage[];
}

export interface WorkStage {
  id: string;
  number: string;
  title: string;
  canonical_stage_id?: string | null;
  stage_role?: string | null;
  stage_options_mode: string;
  stage_options: WorkStageOption[];
  detail_lines: string[];
  occurrence_index?: number | null;
  occurrence_label?: string | null;
  autofill_enabled: boolean;
  primary_work_type?: WorkTypeRef | null;
  related_work_types: WorkTypeRef[];
}

export interface WorkTypeRef {
  section_id?: string | null;
  subtype_id?: string | null;
  mapping_confidence?: string | null;
  mapping_source?: string | null;
  mapping_note?: string | null;
}

export interface WorkStageOption extends WorkTypeRef {
  id?: string | null;
  number?: string | null;
  title: string;
  required?: boolean | null;
  autofill_enabled: boolean;
}

export interface WorkEstimateType {
  id: string;
  number: string;
  title: string;
  estimate_kind: number;
  estimate_profile_id: string;
  project_variants: WorkProjectVariant[];
}

export interface WorkProjectHierarchy {
  dictionary_version: string;
  estimate_types: WorkEstimateType[];
}

// ─────────────── NW (нормализованные виды работ) ───────────────

export interface NwWorkType {
  code: string;
  name: string;
  description: string | null;
  sort_order: number;
  items_count: number;
}

export interface NwDictEntry {
  code: string;
  name?: string;
  description?: string;
  sort_order: number;
}

export interface NwDictionaries {
  object_types: NwDictEntry[];
  building_technologies: NwDictEntry[];
  location_scopes: NwDictEntry[];
  stages: NwDictEntry[];
  repair_classes: NwDictEntry[];
}

export interface NwItem {
  code: string;
  unique_label: string;
  work_type_code: string;
  work_type_name: string;
  subtype: string | null;
  object_type_codes: string[];
  building_technology_codes: string[];
  location_scope_codes: string[];
  stage_codes: string[];
  repair_class_codes: string[];
  is_capital_repair: boolean | null;
  requires_permit_review: boolean;
  notes: string | null;
  sort_order: number;
  primary_fer_refs: string[] | null;
}

export interface NwItemDetail extends NwItem {
  work_type_description: string | null;
  fer_mappings: NwFerMapping[];
  work_type_fer_mappings?: NwFerMapping[];
}

export interface NwFerMapping {
  fer_collection_num: number;
  fer_section_num: number;
  mapping_type: "direct" | "partial" | "composite_part" | "out_of_scope_subscope";
  confidence: "high" | "medium" | "low";
  is_primary: boolean;
  notes: string | null;
  // в /nw/items/{code}.fer_mappings подтягиваются названия из fer.collections/sections:
  collection_id?: number | null;
  collection_name?: string | null;
  section_id?: number | null;
  section_title?: string | null;
  // в /nw/mapping добавляются поля:
  id?: number;
  nw_item_code?: string;
  nw_label?: string;
  nw_work_type?: string;
}

// ─────────── ProjectWorkPlan (КТП проекта) ───────────

export type WorkPlanStatus =
  | "auto_proposed"
  | "confirmed"
  | "removed"
  | "custom_added"
  | "fer_mapped"
  | "scheduled"
  | "needs_volume"
  | "needs_review";

export interface WorkPlanCard {
  id: number;
  parent_id: number | null;
  nw_item_code: string;
  nw_label: string;
  work_type_code: string;
  work_type_name: string;
  unit: string | null;
  quantity: number | null;
  status: WorkPlanStatus;
  object_type_code: string | null;
  building_technology_code: string | null;
  location_scope_code: string | null;
  stage_code: string | null;
  is_capital_repair: boolean | null;
  fer_table_id: number | null;
  fer_table_title: string | null;
  fer_table_code: string | null;
  fer_match_score: number | null;
  fer_match_source: string | null;
  fer_candidates: WorkPlanFerCandidate[] | null;
  fer_row_id: number | null;
  fer_row_clarification: string | null;
  fer_row_h_hour: number | null;
  fer_row_m_hour: number | null;
  human_hours_per_unit: number | null;
  workers_count: number | null;
  duration_days: number | null;
  notes: string | null;
  source_label: string | null;
  source_section: string | null;
  created_at: string;
  confirmed_at: string | null;
  estimate_links_count: number;
}

export interface WorkPlanFerCandidate {
  id: number;
  title: string;
  coll_num: string | number | null;
  section_title: string | null;
  mapping_type: string;
  confidence: string;
  is_primary: boolean;
}

export interface WorkPlanEstimateRow {
  id: string;
  row_order: number | null;
  section: string | null;
  work_name: string;
  unit: string | null;
  quantity: number | null;
  unit_price: number | null;
  total_price: number | null;
  labor_hours: number | null;
  share: number;
}

export interface WorkPlanCardDetail {
  card: WorkPlanCard;
  estimate_rows: WorkPlanEstimateRow[];
}

export interface FerRowOption {
  id: number;
  position: number;
  clarification: string;
  h_hour: number | null;
  m_hour: number | null;
  row_slug: string | null;
}

export interface WorkPlanResponse {
  items: WorkPlanCard[];
  total: number;
}

export interface WorkPlanPalette {
  estimate_kind: number;
  wt_codes: string[];
  nw_items: Array<{
    nw_item_code: string;
    unique_label: string;
    subtype: string | null;
    work_type_code: string;
    work_type_name: string;
    stage_code: string | null;
  }>;
}

export interface WorkPlanFerScope {
  collection_id: number;
  collection_num: string;
  collection_name: string;
  section_id: number;
  section_title: string;
}

export interface WorkPlanAutoSummary {
  batch_id: string;
  estimate_kind: number;
  estimate_rows_total: number;
  matched_rows: number;
  unmatched_rows: number;
  unmatched_examples: Array<{ id: string; work_name: string; section: string | null }>;
  cards_created: number;
  expected_added: number;
  aggregate_decomposed: Array<{ parent_id: number; children: number[] }>;
  palette_size: number;
}

export type WorkPlanCardPatch = Partial<{
  object_type_code: string | null;
  building_technology_code: string | null;
  location_scope_code: string | null;
  stage_code: string | null;
  is_capital_repair: boolean | null;
  unit: string | null;
  quantity: number | null;
  workers_count: number | null;
  status: WorkPlanStatus;
  notes: string | null;
}>;
