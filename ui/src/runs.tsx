import { useApi, type EvalDetail, type RunRow } from './api.ts';
import { Chip, Empty, Link, Load, Score, fmt, navigate, useLocation } from './ui.tsx';

const FILTERS = [
  { key: 'template', label: 'Task' },
  { key: 'model_id', label: 'Model' },
  { key: 'harness_name', label: 'Harness' },
  { key: 'toolset_name', label: 'Tool set' },
  { key: 'state', label: 'State' },
] as const;

export function RunsScreen() {
  const { query } = useLocation();
  const active = new URLSearchParams();
  for (const f of FILTERS) { const v = query.get(f.key); if (v) active.set(f.key, v); }
  // Optional evaluation scope (?eval=…&config=…), set by the Report and Comparison links.
  const evalId = query.get('eval');
  const config = query.get('config');
  const scope = new URLSearchParams(active);
  if (evalId) scope.set('eval_id', evalId);
  const all = useApi<RunRow[]>('/api/runs?limit=500');
  const runs = useApi<RunRow[]>(`/api/runs?limit=500&${scope}`);
  const evalDetail = useApi<EvalDetail>(evalId && config ? `/api/evals/${encodeURIComponent(evalId)}` : null);
  const configRuns = config ? evalDetail.data?.report?.run_links?.[config] : undefined;
  const missingRunList = !!(config && evalDetail.data && !configRuns);

  const keepScope = (next: URLSearchParams) => {
    if (evalId) next.set('eval', evalId);
    if (config) next.set('config', config);
    return next;
  };
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(active);
    if (value) next.set(key, value); else next.delete(key);
    keepScope(next);
    navigate(`/runs${next.size ? `?${next}` : ''}`, true);
  };
  const shown = (rows: RunRow[]) => (configRuns ? rows.filter((r) => configRuns.includes(r.run_id)) : rows);

  return (
    <section aria-labelledby="runs-h">
      <header className="page-head">
        <h1 id="runs-h">Runs</h1>
        <p className="muted">Every run in the store, newest first. Pick a run to see its trace, scores and map.</p>
      </header>

      <form className="filters" onSubmit={(e) => e.preventDefault()} aria-label="Filter runs">
        {FILTERS.map((f) => {
          const options = [...new Set((all.data ?? []).map((r) => r[f.key]).filter((v): v is NonNullable<typeof v> => !!v))].sort();
          return (
            <label key={f.key} className="field">
              <span>{f.label}</span>
              <select value={active.get(f.key) ?? ''} onChange={(e) => setFilter(f.key, e.target.value)}>
                <option value="">Any</option>
                {options.map((o) => <option key={o} value={o}>{o.replace(/_/g, ' ')}</option>)}
              </select>
            </label>
          );
        })}
        {(active.size > 0 || evalId) && (
          <button type="button" className="btn-ghost" onClick={() => navigate('/runs', true)}>Clear filters</button>
        )}
      </form>

      {evalId && (
        <p className="note" role="status">
          {config ? <>Showing runs of <b>{config}</b> in evaluation <b>{evalId}</b>.</> : <>Showing runs in evaluation <b>{evalId}</b>.</>}
          {missingRunList && <> This report has no run list for {config}, so all of the evaluation's runs are shown.</>}
          {' '}<Link href="/runs">Show all runs</Link>
        </p>
      )}

      <Load q={runs} what="runs">
        {(loaded) => { const rows = shown(loaded); return rows.length === 0 ? (
          <Empty title={active.size || evalId ? 'No runs match these filters' : 'No runs in this store yet'}>
            {active.size || evalId
              ? 'Clear a filter to widen the list.'
              : <>Build the demo store with <code>uv run python scripts/make_demo_store.py --out &lt;dir&gt;</code> and start the API with <code>--store &lt;dir&gt;</code>.</>}
          </Empty>
        ) : (
          <div className="table-wrap" tabIndex={0} aria-label="Runs table, scrolls sideways on small screens">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Run</th><th scope="col">Task</th><th scope="col">Model</th>
                  <th scope="col">Harness</th><th scope="col">Tool set</th><th scope="col">State</th>
                  <th scope="col">Workflow</th><th scope="col">Output</th>
                  <th scope="col" className="num">Steps</th><th scope="col" className="num">Tokens</th>
                  <th scope="col" className="num">Cost</th><th scope="col" className="num">Wall time</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.run_id}>
                    <th scope="row"><Link href={`/runs/${encodeURIComponent(r.run_id)}`}>{r.run_id}</Link></th>
                    <td>{r.task_instance_id ?? '–'}</td>
                    <td>{r.model_id ?? '–'}</td>
                    <td>{r.harness_name ?? '–'}</td>
                    <td>{r.toolset_name ?? '–'}</td>
                    <td><Chip value={r.state} />{r.incomplete && <Chip value="error" label="incomplete" />}</td>
                    <td><Score value={r.scores.workflow} /></td>
                    <td><Score value={r.scores.output} /></td>
                    <td className="num">{fmt.int(r.totals.steps)}</td>
                    <td className="num">{r.totals.input_tokens == null ? '–' : fmt.int((r.totals.input_tokens ?? 0) + (r.totals.output_tokens ?? 0))}</td>
                    <td className="num">{fmt.usd(r.totals.cost_usd)}</td>
                    <td className="num">{fmt.ms(r.totals.wall_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ); }}
      </Load>
    </section>
  );
}
