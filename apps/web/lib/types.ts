export type RunState =
  | "CREATED"
  | "RESEARCHING"
  | "HYPOTHESIS_GENERATION"
  | "EXPERIMENT_DESIGN"
  | "CODE_GENERATION"
  | "RUNNING"
  | "ANALYZING"
  | "DECISION"
  | "COMPLETED"
  | "FAILED"
  | "PAUSED";

export type AgentName =
  | "SCOUT"
  | "SCIENTIST"
  | "EXPERIMENTALIST"
  | "ENGINEER"
  | "RUNNER"
  | "ANALYST"
  | "PI"
  | "SYSTEM";

export type EventStatus = "info" | "success" | "warning" | "error";

export interface AgentEvent {
  id?: string;
  seq: number;
  agent: AgentName;
  action: string;
  status: EventStatus;
  message: string;
  meta: Record<string, unknown>;
  timestamp: string | null;
}

export interface Paper {
  id: string;
  title: string;
  authors: string[];
  abstract: string;
  url: string;
  published: string;
  source: string;
  relevance: number;
  concepts: string[];
}

export interface Hypothesis {
  id: string;
  index: number;
  title: string;
  description: string;
  rationale: string;
  expected_outcome: string;
  assumptions: string[];
  approach: string;
  difficulty: string;
  expected_improvement: number;
  confidence: number;
  status: string;
  origin: string;
  created_at: string;
}

export interface ExperimentDesign {
  name?: string;
  dataset?: string;
  approach?: string;
  feature_set?: string;
  baseline?: string;
  variables?: string[];
  parameters?: Record<string, unknown>;
  metrics?: string[];
  train_test_split?: string;
  threshold_strategy?: string;
  expected_result?: string;
}

export interface Analysis {
  hypothesis_supported: boolean;
  verdict: string;
  key_findings: string[];
  failure_modes: string[];
  recommendations: string[];
  comparison: string;
  confidence: number;
}

export interface Experiment {
  id: string;
  index: number;
  name: string;
  status: string;
  is_baseline: boolean;
  hypothesis_id: string | null;
  design: ExperimentDesign;
  analysis: Analysis | null;
  hypothesis_supported: boolean | null;
  repair_attempts: number;
  created_at: string;
}

export interface Decision {
  id: string;
  index: number;
  kind: string;
  decision: string;
  evidence: string[];
  confidence: number;
  selected_hypothesis_id: string | null;
  expected_value: number;
  estimated_cost: string;
  created_at: string;
}

export interface FinalSummary {
  recommendation: string;
  what_was_learned: string[];
  future_work: string[];
  confidence: number;
  best_experiment_id: string | null;
  best_experiment_name: string | null;
  best_f1: number | null;
  best_fpr: number | null;
  improvement_pct: number;
  fpr_change_pct: number;
  experiments_run: number;
  papers_analysed: number;
}

export interface RunDetail {
  id: string;
  state: RunState;
  demo_mode: boolean;
  max_experiments: number;
  experiments_completed: number;
  llm_provider: string;
  sandbox_backend: string;
  best_experiment_id: string | null;
  final_summary: FinalSummary | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  question: string;
  project: { id: string; name: string; domain: string };
  papers: Paper[];
  hypotheses: Hypothesis[];
  experiments: Experiment[];
  decisions: Decision[];
  is_running: boolean;
}

export type GraphNodeKind =
  | "question"
  | "hypothesis"
  | "experiment"
  | "result_success"
  | "result_failed";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  data: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
}

export interface ResearchGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  bestExperimentId: string | null;
}

export interface ComparisonRow {
  id: string;
  primaryMetric?: string;
  primaryValue?: number;
  index: number;
  name: string;
  approach: string;
  featureSet: string;
  thresholdStrategy: string;
  isBaseline: boolean;
  isBest: boolean;
  hypothesisSupported: boolean | null;
  metrics: Record<string, number>;
  executionTime: number;
  f1Delta: number;
  f1ImprovementPct: number;
  fprDelta: number;
  fprChangePct: number;
}

export interface Comparison {
  rows: ComparisonRow[];
  baseline: ComparisonRow | null;
  best: ComparisonRow | null;
  /** The metric this run is ranked by; not every domain reports F1. */
  primaryMetric?: string;
  metricDirection?: "maximize" | "minimize";
}

export interface ExperimentResults {
  id: string;
  name: string;
  status: string;
  metrics: Record<string, number>;
  analysis: Analysis | null;
  hypothesis_supported: boolean | null;
  artifacts: { name: string; kind: string; content: string }[];
  stdout: string;
  stderr: string;
  execution_time: number;
  attempts: number;
}

export interface SystemStatus {
  llm_provider: string;
  llm_model: string;
  sandbox_backend: string;
  database: string;
  arxiv_enabled: boolean;
}

export type SocketMessage =
  | { type: "snapshot"; state: RunState; experimentsCompleted: number; maxExperiments: number; isRunning: boolean; events: AgentEvent[] }
  | { type: "agent_event" } & AgentEvent
  | { type: "state"; state: RunState }
  | { type: "experiment_output"; experiment_id: string; line: string }
  | { type: "graph_update" }
  | { type: "complete"; summary: FinalSummary }
  | { type: "ping" }
  | { type: "error"; message: string };
