// Hand-typed against api/openapi.json and claysandbox/contracts (swap for a generated client, DD-036).
import { useEffect, useState } from 'react';

export type RunState = 'created' | 'running' | 'completed' | 'budget_stopped' | 'agent_failed' | 'infra_error' | 'infra_excluded' | 'skipped_eval_cap';

export interface RunRow {
  run_id: string;
  eval_id: string | null;
  trial_index: number | null;
  task_instance_id: string | null;
  template: string | null;
  model_id: string | null;
  harness_name: string | null;
  toolset_name: string | null;
  started_at: string | null;
  state: RunState | null;
  incomplete: boolean | null;
  totals: { input_tokens?: number | null; output_tokens?: number | null; cost_usd?: number | null; steps?: number | null; wall_ms?: number | null };
  scores: Partial<Record<Kind, number | null>>;
}

export interface ComponentRef { kind?: string; name: string; version?: string; params?: Record<string, unknown> }

export interface Manifest {
  run_id: string;
  eval_id?: string;
  trial_index?: number;
  task_instance_id: string;
  task_reference_version?: string;
  config_name?: string;
  model?: ComponentRef | null;
  harness?: ComponentRef | null;
  toolset?: ComponentRef | null;
  budget?: Record<string, unknown>;
  loop_guard?: Record<string, unknown>;
  seed?: number;
  started_at?: string | null;
}

export interface RunDetail {
  manifest: Manifest;
  status: { state: RunState; updated_at: string; attempt: number; incomplete: boolean } | null;
  summary: { claims: { claim: string; event_ids: string[] }[] } | null;
  report: unknown;
}

export interface ErrorInfo { source: string; kind: string; message: string; retryable?: boolean; related_event_id?: string | null }

export interface TraceEvent {
  type: 'run_start' | 'model_call' | 'tool_call' | 'guard_stop' | 'error' | 'final_output' | 'run_end';
  seq: number;
  event_id: string;
  parent_id: string | null;
  ts_start: string;
  latency_ms: number | null;
  error: ErrorInfo | null;
  cost_usd?: number;
  // model_call
  model_id?: string; input_tokens?: number; output_tokens?: number; stop_reason?: string | null;
  tool_use_requests?: unknown[]; text_preview?: string | null;
  // tool_call
  server?: string; tool?: string; capability?: string | null; args?: Record<string, unknown>;
  status?: 'ok' | 'error' | 'timeout' | 'rejected'; result_preview?: string | null;
  // guard_stop
  limit?: string; limit_value?: number; observed_value?: number;
  // final_output / run_end / run_start
  output?: unknown; state?: string; totals?: Record<string, number>; task_instance_id?: string; config_name?: string;
}

export interface Trace { run_id: string; events: TraceEvent[]; incomplete: boolean }

export type Kind = 'workflow' | 'output' | 'process';

export interface SubScore { name: string; value: number; weight: number; evidence: string[]; notes: string[] }

export interface Assessment {
  assessment_id: string;
  run_id: string;
  evaluator: ComponentRef;
  kind: Kind;
  task_reference_version: string;
  composite: number | null;
  subscores: SubScore[];
  metrics: Record<string, number>;
  success: boolean | null;
  evidence: string[];
  notes: string[];
  cost_usd: number;
  repeats?: number[] | null;
}

export interface AOI { id: string; name: string; state: string; bbox: number[]; geometry: { type: string; coordinates: unknown } | null }

export interface ReferenceResponse {
  exact: boolean;
  reference: { instance_id: string; version: string; output_reference: Record<string, unknown>; aoi: AOI | null };
}

export interface Interval { estimate: number | null; low: number | null; high: number | null; n: number; method: string }

export interface ConfigStats {
  config_name: string; runs_total: number; runs_used: number; excluded: Record<string, number>;
  instances: number; success_rate: Interval; metrics: Record<string, Interval>; warnings: string[];
}

export interface PairedComparison {
  baseline: string; variant: string; axis: string | null; metric: string; n_instances: number;
  effect: number | null; ci_low: number | null; ci_high: number | null; p_value: number | null;
  p_adjusted: number | null; higher_is_better: boolean; verdict: string; warnings: string[];
}

export interface MeasurementComparison {
  kind: 'evaluator' | 'tracer'; subjects: string[]; n_runs: number;
  values: Record<string, number | null>; details?: Record<string, unknown>; notes: string[];
}

export interface EvalReport {
  eval_id: string;
  baseline: string;
  variants: { variant: string; axis: string | null; changed: string[]; warning: string | null }[];
  stats: { configs: ConfigStats[]; comparisons: PairedComparison[]; alpha: number; seed?: number; bootstrap_iterations?: number };
  warnings: string[];
  paired_instances?: string[];
  paired_instances_by_variant?: Record<string, string[]>;
  exclusions?: Record<string, Record<string, number>>;
  verdicts?: Record<string, string[]>;
  run_links?: Record<string, string[]>;
  tracer_comparison?: MeasurementComparison | null;
  evaluator_comparison?: MeasurementComparison | null;
}

export interface FlawResult {
  template: string; flaw: string; expected_drops: string[]; detected: boolean;
  good_value: Record<string, number | null>; bad_value: Record<string, number | null>;
  missing: string[]; unchecked: string[]; notes: string[];
}

export interface ValidationResponse {
  source: string;
  report: {
    evaluators: string[]; flaws: FlawResult[]; detection_rate: Record<string, number>;
    margin: number | null; margins: Record<string, number | null>; ci_halfwidth: number | null;
    margin_exceeds_ci: boolean | null; llm_agreement: number | null; notes: string[];
  };
}

export interface EvalDetail {
  eval_id: string;
  runs: { run_id: string; task_instance_id: string; state: RunState | null; trial_index: number }[];
  assessments: { assessment_id: string; run_id: string; kind: Kind; composite: number | null; evaluator_name: string; evaluator_version: string; task_instance_id: string; metrics: string | Record<string, number> }[];
  report: EvalReport | null;
  spec: string | null;
}

export interface Component { kind: string; name: string; version: string }
export interface TaskInstance { id: string; template: string; aoi: string; title: string }

export class ApiError extends Error {
  status: number;
  kind: string | null;
  constructor(status: number, message: string, kind: string | null = null) { super(message); this.status = status; this.kind = kind; }
}

function detailText(detail: unknown): string | null {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => (typeof d?.msg === 'string' ? `${(d.loc ?? []).join('.')}: ${d.msg}` : JSON.stringify(d))).join('; ');
  return null;
}

/** POST JSON and return the parsed reply; errors carry the API's ``kind`` when it sends one. */
export async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, detailText(data?.detail) ?? `${res.status} ${res.statusText}`, typeof data?.kind === 'string' ? data.kind : null);
  return data as T;
}

export interface Estimate {
  runs: number; total_usd: number; per_config: Record<string, number>; exceeds_eval_cap: boolean;
  eval_cap_usd: number | null; notes: string[]; warnings: string[];
}
export interface LaunchResponse { eval_id: string; runs: number; status_url: string; events_url: string }
export type PlanState = 'planned' | 'running' | 'infra_retry' | 'completed' | 'budget_stopped' | 'agent_failed' | 'infra_excluded' | 'skipped_eval_cap';
export interface PlanRow { run_id: string; config_name: string; task_instance_id: string; trial_index: number; attempt: number; state: PlanState; error_kind?: string | null; cost_usd?: number; retry_of?: string }
export interface EvalLiveStatus { eval_id: string; runs: PlanRow[]; counts: Record<string, number>; done: boolean; error: string | null; report: boolean }

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, { signal, headers: { Accept: 'application/json' } });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, detailText(body?.detail) ?? `${res.status} ${res.statusText}`, typeof body?.kind === 'string' ? body.kind : null);
  }
  return res.json() as Promise<T>;
}

export type Loaded<T> = { data?: T; error?: ApiError | Error; loading: boolean };

/** GET `path` (null skips the request); refetches when the path changes. */
export function useApi<T>(path: string | null): Loaded<T> {
  const [state, setState] = useState<Loaded<T> & {path?: string | null}>({ loading: path !== null });
  useEffect(() => {
    if (path === null) return;
    const ctl = new AbortController();
    setState({path, loading: true});
    get<T>(path, ctl.signal).then(
      (data) => { if (!ctl.signal.aborted) setState({ path, data, loading: false }); },
      (error: Error) => { if (!ctl.signal.aborted) setState({ path, error, loading: false }); },
    );
    return () => ctl.abort();
  }, [path]);
  return state.path === path ? state : { loading: path !== null };
}
