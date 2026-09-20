/**
 * Response shapes of the EduPath backend (`backend/app/schemas/*`). Kept in
 * one file so the UI has a single place that mirrors the API contract
 * (docs/ARCHITECTURE_CONTRACTS.md §6, §20). Status enums keep the backend's
 * own casing.
 */

export type GapStatus = "MET" | "WEAK" | "UNVERIFIED" | "MISSING" | "BLOCKED";
export type EvidenceTier = "E0" | "E1" | "E2" | "E3";

export interface HealthStatus {
  status: "ok" | "degraded";
  database: { ok: boolean; error: string | null };
  orchestration: { ok: boolean; error: string | null };
}

export interface Role {
  role_id: string;
  title: string;
  description: string;
  required_skill_count: number;
}

export interface Skill {
  skill_id: string;
  label: string;
  kind: string;
  area: string;
  description: string;
}

export interface Resource {
  resource_id: string;
  title: string;
  url: string;
  provider: string;
  type: string;
  difficulty: number;
  duration_min: number;
  modality: "watch" | "read" | "do" | string;
  learning_objective_text: string;
  cost: string;
  link_status: string;
  curation_tier: string;
}

export interface LearnerPreferences {
  modality_order: Array<"watch" | "read" | "do">;
  language: string;
  session_length_min: number | null;
}

export interface IntakeRequest {
  current_skills: string[];
  experience_summary: string;
  target_role_id: string;
  career_goal: string;
  weekly_hours: number;
  preferences: LearnerPreferences;
  constraints?: Record<string, unknown>;
}

export interface LearnerProfile {
  learner_id: string;
  target_role_id: string;
  career_goal: string;
  experience_summary: string;
  weekly_hours: number;
  preferences: Partial<LearnerPreferences>;
  constraints: Record<string, unknown>;
  mapped_skill_count: number;
  unmapped_skills: Array<{ label: string; reason: string }>;
}

export interface RunClaimsSummary {
  run_id: string;
  extracted: number;
  dropped_unverified: number;
  dropped_injection: number;
  pending: number;
  degraded: boolean;
}

export interface DocumentUploadResponse {
  document_id: string;
  run_id: string;
  parse_status: string;
  claims_summary: RunClaimsSummary;
}

export interface PendingClaim {
  claim_id: string;
  skill_label: string;
  category: string;
  context_type: string;
  claimed_level_cue: string | null;
  verbatim_span: string;
  span_offsets: { start: number; end: number };
  tier: EvidenceTier;
  document_id: string | null;
  normalized_skill_id: string | null;
  normalization_method: string;
  normalization_confidence: number;
}

export interface ClaimDecision {
  claim_id: string;
  action: "confirm" | "remove" | "edit";
  skill_id_override?: string | null;
}

export interface ConfirmationSummary {
  confirmed: number;
  removed: number;
  skipped_no_skill: number;
  evidence_created: string[];
}

export interface Evidence {
  evidence_id: string;
  skill_id: string;
  skill_label: string;
  tier: EvidenceTier;
  source_type: "intake" | "document" | "github" | "assessment" | string;
  document_id: string | null;
  document_label: string | null;
  span_text: string;
  span_offsets: { start: number; end: number } | null;
  verified: boolean;
  created_at: string;
}

export interface SkillGap {
  skill_id: string;
  label: string;
  status: GapStatus;
  gap_type: string;
  required_level: number;
  current_level: number;
  blocked_by: string[];
  root_of: string[];
  priority: number;
  ordering_layer: number;
  evidence_ids: string[];
  audit_flags: string[];
}

export interface Strength {
  skill_id: string;
  label: string;
  required_level: number;
  current_level: number;
  tier_max: string;
  mastery: number;
  evidence_ids: string[];
}

export interface AuditFlag {
  flag_type: string;
  skill_id: string;
  message: string;
  related_skill_ids: string[];
}

export interface LearningObjective {
  objective_id: string;
  skill_id: string;
  from_status: string;
  objective_type: "probe" | "lesson";
  target_level: number;
  priority: number;
  prerequisite_objective_ids: string[];
  acceptance_criteria: Record<string, unknown>;
  est_minutes_low: number | null;
  est_minutes_high: number | null;
  reason_ref: string;
}

export interface GapReport {
  role_id: string;
  graph_version: string;
  gaps: SkillGap[];
  strengths: Strength[];
  audit_flags: AuditFlag[];
  objectives: LearningObjective[];
  layers: string[][];
  prerequisite_edges: Array<{ from_skill_id: string; to_skill_id: string }>;
}

export interface PlanItemReason {
  evidence_ids: string[];
  graph_path: string[] | null;
  decision_id: string | null;
  text: string;
}

export interface PlanItem {
  item_id: string;
  type: "resource" | "practice" | "project" | "probe" | "review";
  objective_id: string;
  skill_id: string;
  resource_id: string | null;
  practice_item_ids: string[];
  est_minutes: number;
  difficulty: number;
  day_slot: number;
  depends_on: string[];
  reason: PlanItemReason;
  status: "planned" | "done" | "skipped";
}

export interface WeeklyPlan {
  plan_id: string;
  learner_id: string;
  week_index: number;
  hours_budget: number;
  revision_no: number;
  status: string;
  degraded: boolean;
  items: PlanItem[];
  overall_reason: string;
}

export interface PlanRevision {
  revision_id: string;
  plan_id: string;
  revision_no: number;
  parent_revision_id: string | null;
  cause_type: "initial" | "reflection" | "user_override" | string;
  cause_ref: string;
  operators: Array<{ op: string; params?: Record<string, unknown> }>;
  diff: {
    inserted?: string[];
    deferred?: string[];
    removed?: string[];
    replaced?: unknown[];
    split?: unknown[];
    reverted_revision_id?: string;
    restored_from_revision_id?: string;
  };
  degraded: boolean;
  overall_reason: string;
  created_at: string;
  reverted_by: string | null;
  is_current: boolean;
  decision_id: string | null;
}

export interface PlanRevisionDetail extends PlanRevision {
  items: PlanItem[];
}

export interface PracticeItem {
  item_id: string;
  skill_id: string;
  difficulty: "easy" | "medium" | "hard" | string;
  stem: string;
  options: string[];
}

export interface PracticeSet {
  set_id: string;
  skill_id: string;
  purpose: string;
  items: PracticeItem[];
}

export interface SubmitPracticeRequest {
  answers: Array<{ item_id: string; chosen_option: number; time_sec?: number }>;
  self_reported_overload?: boolean;
}

export interface AssessmentItemResult {
  item_id: string;
  skill_id: string;
  difficulty: string;
  chosen_option: number;
  correct: boolean;
  misconception_id: string | null;
  time_sec: number | null;
  attempt_no: number;
}

export interface AssessmentResult {
  assessment_id: string;
  learner_id: string;
  skill_id: string;
  purpose: string;
  items: AssessmentItemResult[];
  score: number;
  prereq_block_score: number | null;
  submitted_at: string;
}

export interface StruggleSignal {
  signal_id: string;
  learner_id: string;
  signal_class:
    | "low_score"
    | "repeated_misconception"
    | "missing_prerequisite"
    | "excessive_difficulty"
    | "cognitive_overload"
    | "insufficient_practice"
    | string;
  skill_id: string;
  confidence: "low" | "medium" | "high" | string;
  evidence_ids: string[];
  counts: Record<string, unknown>;
  thresholds_used: Record<string, unknown>;
  status: string;
}

export interface ReflectionOutcome {
  root_cause_skill_id: string | null;
  root_cause_class: string | null;
  misconception_id: string | null;
  misconception_status: string | null;
  remediation_resource_ids: string[];
  operators: Array<{ op: string; params?: Record<string, unknown> }>;
  plan_revision_id: string | null;
  degraded: boolean;
  needs_attention: boolean;
  rounds: number;
  explanation: string;
  decision_id: string | null;
  reflection_id: string | null;
}

export interface SubmitPracticeResponse {
  result: AssessmentResult;
  signals: StruggleSignal[];
  reflection: ReflectionOutcome | null;
}

export interface ProgressSkillEntry {
  skill_id: string;
  label: string;
  status: string;
  mastery: number;
  band: string;
  tier_max: string;
  evidence_ids: string[];
}

export interface StruggleAreaEntry {
  skill_id: string;
  status: string;
  signal_id: string | null;
  signal_class: string | null;
  confidence: string | null;
  misconception_id: string | null;
}

export interface ProgressActivityEntry {
  item_id: string;
  skill_id: string;
  type: string;
  est_minutes: number;
  day_slot: number;
  status: string;
}

export interface ProgressReport {
  learner_id: string;
  role_id: string;
  period: string;
  graph_version: string;
  acquired: ProgressSkillEntry[];
  in_progress: ProgressSkillEntry[];
  remaining_gaps: SkillGap[];
  struggle_areas: StruggleAreaEntry[];
  completed_work: ProgressActivityEntry[];
  next_steps: ProgressActivityEntry[];
  narrative: string;
}

export interface ChatResponse {
  answer: string;
  citations: string[];
  degraded: boolean;
  conservative: boolean;
}

export interface DecisionRecord {
  decision_id: string;
  learner_id: string;
  type: string;
  inputs: Record<string, unknown>;
  evidence_ids: string[];
  graph_paths: string[][];
  rules_fired: string[];
  scores: Record<string, unknown>;
  graph_version: string;
  output_ref: string;
}

export interface SkillDetail {
  skill: Skill;
  gap: SkillGap | null;
  mastery: { estimate: number; band: string; confidence: string; tier_max: string; n_obs: number } | null;
  role_requirement: { role_id: string; required_level: number; weight: number } | null;
  evidence: Evidence[];
  prerequisites: Array<{ skill_id: string; label: string; status: GapStatus | null; min_level: number | null }>;
  dependents: Array<{ skill_id: string; label: string; status: GapStatus | null; min_level: number | null }>;
  resources: Resource[];
  misconceptions: Array<{
    misconception_id: string;
    description: string;
    signature: string;
    root_skill_id: string;
    root_skill_label: string;
    learner_status: string | null;
  }>;
  plan_items: Array<{ item_id: string; type: string; status: string; day_slot: number; est_minutes: number }>;
}

export type TraceKind =
  | "input"
  | "tool_call"
  | "graph_query"
  | "retrieval"
  | "decision"
  | "validation"
  | "reflection"
  | "replan"
  | "output"
  | "degraded"
  | "error";

export interface TraceEvent {
  run_id: string;
  step_id: string;
  ts: string;
  agent_or_service: string;
  kind: TraceKind;
  summary: string;
  refs: string[];
  extra?: Record<string, unknown>;
}
