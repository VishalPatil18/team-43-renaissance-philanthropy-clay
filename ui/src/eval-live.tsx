import { useEffect, useState } from 'react';
import { ApiError, type EvalLiveStatus } from './api.ts';
import { Chip, Empty, Link, fmt } from './ui.tsx';

const FINISHED = new Set(['completed', 'budget_stopped', 'agent_failed', 'infra_excluded', 'skipped_eval_cap']);

/** Progress over the plan: retried attempts are replaced by their retry, so they count once. */
export function summarize(status: EvalLiveStatus) {
  const rows = status.runs.filter((r) => r.state !== 'infra_retry');
  const finished = rows.filter((r) => FINISHED.has(r.state)).length;
  const active = rows.filter((r) => r.state === 'running').length;
  const cost = status.runs.reduce((n, r) => n + (r.cost_usd ?? 0), 0);
  return { finished, total: rows.length, active, cost };
}

/** Live status over Server-Sent Events, falling back to polling when EventSource is unavailable. */
function useEvalStatus(evalId: string) {
  const [status, setStatus] = useState<EvalLiveStatus | null>(null);
  const [error, setError] = useState<string>('');
  const [mode, setMode] = useState<'live' | 'polling' | 'connecting'>('connecting');
  useEffect(() => {
    const base = `/api/evals/${encodeURIComponent(evalId)}`;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      setMode('polling');
      try {
        const res = await fetch(`${base}/status`, { headers: { Accept: 'application/json' } });
        if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => null))?.detail ?? res.statusText);
        const s = (await res.json()) as EvalLiveStatus;
        if (stopped) return;
        setStatus(s); setError('');
        if (!s.done) timer = setTimeout(poll, 2000);
      } catch (e) {
        if (stopped) return;
        setError(e instanceof Error ? e.message : String(e));
        timer = setTimeout(poll, 4000);
      }
    };
    if (typeof EventSource === 'undefined') { void poll(); return () => { stopped = true; clearTimeout(timer); }; }
    const es = new EventSource(`${base}/events`);
    const take = (e: MessageEvent) => { try { setStatus(JSON.parse(e.data)); setMode('live'); setError(''); } catch { /* ignore a malformed frame */ } };
    es.addEventListener('status', take as EventListener);
    es.addEventListener('done', ((e: MessageEvent) => { take(e); es.close(); }) as EventListener);
    es.onerror = () => { es.close(); if (!stopped) void poll(); };
    return () => { stopped = true; es.close(); clearTimeout(timer); };
  }, [evalId]);
  return { status, error, mode };
}

export function EvalLiveScreen({ evalId }: { evalId: string }) {
  const { status, error, mode } = useEvalStatus(evalId);
  return <section aria-labelledby="live-h">
    <Link href="/runs" className="back-link">Back to runs</Link>
    <header className="page-head"><div className="heading-line"><h1 id="live-h">{evalId}</h1>{status && <Chip value={status.done ? (status.error ? 'error' : 'completed') : 'running'} label={status.done ? (status.error ? 'failed' : 'finished') : 'running'} />}</div>
      <p className="muted">Live progress of a launched evaluation. {mode === 'live' ? 'Updates stream from the server.' : mode === 'polling' ? 'Refreshing every 2 seconds.' : 'Connecting…'}</p></header>
    {error && <p className="note" role="alert">Could not read the evaluation: {error}</p>}
    {!status ? <p className="note" aria-live="polite">Connecting to the evaluation…</p> : <EvalLiveView status={status} />}
  </section>;
}

export function EvalLiveView({ status }: { status: EvalLiveStatus }) {
  const s = summarize(status);
  const id = encodeURIComponent(status.eval_id);
  return <>
    <section className="panel">
      <div className="section-heading"><h2 role="status" aria-live="polite">{s.finished} of {s.total} runs finished{s.active ? ` · ${s.active} running` : ''}</h2></div>
      <label className="field"><span>Progress</span><progress max={Math.max(1, s.total)} value={s.finished}>{s.finished} of {s.total}</progress></label>
      <div className="evidence-links" aria-label="Runs per state">{Object.entries(status.counts).map(([state, n]) => <Chip key={state} value={state} label={`${state.replaceAll('_', ' ')}: ${n}`} />)}</div>
      <p className="muted">Agent cost so far: {fmt.usd(s.cost)}</p>
      {status.error && <p className="note" role="alert">The evaluation stopped with an error: {status.error}</p>}
      {status.done && <div className="launch-actions">
        {status.report ? <><Link href={`/report?eval=${id}`}>Open report</Link><Link href={`/comparison?eval=${id}`}>Open comparison</Link></> : <span className="muted">No evaluation report was written.</span>}
        <Link href={`/runs?eval=${id}`}>Open these runs</Link>
      </div>}
    </section>
    {status.runs.length === 0 ? <Empty title="No runs planned yet">The plan appears here as soon as the evaluation starts.</Empty> :
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Planned runs"><table>
      <thead><tr><th scope="col">Run</th><th scope="col">Configuration</th><th scope="col">Task</th><th scope="col" className="num">Trial</th><th scope="col" className="num">Attempt</th><th scope="col">State</th><th scope="col" className="num">Cost</th></tr></thead>
      <tbody>{status.runs.map((r) => <tr key={r.run_id}>
        <th scope="row">{FINISHED.has(r.state) && r.state !== 'skipped_eval_cap' ? <Link href={`/runs/${encodeURIComponent(r.run_id)}`}>{r.run_id}</Link> : r.run_id}</th>
        <td>{r.config_name}</td><td>{r.task_instance_id}</td><td className="num">{r.trial_index + 1}</td><td className="num">{r.attempt}</td>
        <td><Chip value={r.state} />{r.error_kind && <p className="muted">{r.error_kind}</p>}</td><td className="num">{fmt.usd(r.cost_usd)}</td>
      </tr>)}</tbody>
    </table></div>}
  </>;
}
