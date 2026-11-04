import { useApi, type EvalDetail, type EvalReport } from './api.ts';
import { Empty, Link, Load, fmt, navigate, useLocation } from './ui.tsx';

export function EvalScreen({comparison}:{comparison:boolean}) {
  const {query}=useLocation();
  const evals=useApi<{eval_id:string;runs:number}[]>('/api/evals');
  const id=query.get('eval')??evals.data?.[0]?.eval_id;
  const detail=useApi<EvalDetail>(id ? `/api/evals/${encodeURIComponent(id)}`:null);
  return <section><header className="page-head"><h1>{comparison?'Comparison':'Report'}</h1><p className="muted">{comparison?'Paired variant effects relative to the baseline. Uncertainty stays visible.':'Per-configuration results, with workflow, output and process metrics kept separate.'}</p></header>
  <Load q={evals} what="evaluations">{rows=>!rows.length ? <Empty title="No evaluations in this store">Seed the demo store or select a store with an evaluation report.</Empty>:<>
    <label className="field eval-picker"><span>Evaluation</span><select value={id} onChange={e=>navigate(`${comparison?'/comparison':'/report'}?eval=${encodeURIComponent(e.target.value)}`)}>{rows.map(e=><option key={e.eval_id} value={e.eval_id}>{e.eval_id} ({e.runs} runs)</option>)}</select></label>
    <Load q={detail} what="evaluation">{d=>comparison ? <ComparisonView report={d.report}/> : <ReportView detail={d}/>}</Load>
  </>}</Load></section>;
}
export function ReportView({detail}:{detail:EvalDetail}) {
  const report=detail.report;
  return <>{report ? <>
    <p className="note">Baseline: {report.baseline}. Confidence intervals reflect recorded samples; a small demo is not evidence of model quality.</p>
    {report.warnings.map((w,i)=><p className="note" key={i}>{w}</p>)}
    {report.stats.configs.map(c=><section className="panel report-config" key={c.config_name}><h2>{c.config_name}</h2><p className="muted">{c.runs_used} of {c.runs_total} runs used across {c.instances} task instances.</p>
      {c.warnings.map((w,i)=><p className="note" key={i}>{w}</p>)}
      {Object.entries(c.excluded).map(([state,n])=><p key={state}>Excluded: {n} {state.replaceAll('_',' ')} runs</p>)}
      <div className="table-wrap" tabIndex={0} role="region" aria-label={`${c.config_name} metrics`}><table><thead><tr><th scope="col">Metric</th><th scope="col">Estimate</th><th scope="col">Confidence interval</th><th scope="col">Sample size</th><th scope="col">Method</th></tr></thead><tbody>{Object.entries({'workflow.success_rate':c.success_rate,...c.metrics}).map(([name,v])=><tr key={name}><th scope="row">{name}</th><td>{fmt.num(v.estimate)}</td><td>{fmt.num(v.low)} to {fmt.num(v.high)}</td><td>{v.n}</td><td>{v.method.replaceAll('_',' ')}</td></tr>)}</tbody></table></div>
    </section>)}
  </>:<Empty title="No aggregate report stored">Run-level assessments are available below. Build an evaluation report with the CLI to see configuration statistics.</Empty>}
  <section className="panel"><h2>Runs in this evaluation</h2><ul className="run-links">{detail.runs.map(r=><li key={r.run_id}><Link href={`/runs/${encodeURIComponent(r.run_id)}`}>{r.run_id}</Link><span className="muted">{r.state?.replaceAll('_',' ')??'Unknown state'}</span></li>)}</ul><p className="muted">{detail.assessments.length} recorded assessments. Open a run for evaluator notes and trace evidence.</p></section></>;
}
export function ComparisonView({report}:{report:EvalReport|null}) {
  const rows=report?.stats.comparisons??[];
  if(!rows.length) return <Empty title="No paired comparisons yet">{report ? <>This evaluation contains the baseline only. Add a variant and paired task instances, then build a comparison report with the CLI.</> : <>No comparison report is stored for this evaluation. Build one with the CLI to see effects, confidence intervals and p-values.</>}</Empty>;
  return <section className="panel"><h2>Variant against baseline</h2><p className="muted">Effect = variant − baseline. Positive values favor the variant only when higher is better. CI level: {((1-(report?.stats.alpha??.05))*100).toFixed(0)}%.</p>{report?.warnings.map((w,i)=><p className="note" key={i}>{w}</p>)}
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Paired comparisons"><table><thead><tr>{['Variant','Baseline','Metric','Effect','Confidence interval','p-value','Adjusted p','Pairs','Direction','Verdict'].map(h=><th scope="col" key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={i}><td>{r.variant}</td><td>{r.baseline}</td><th scope="row">{r.metric}</th><td>{fmt.num(r.effect)}</td><td>{fmt.num(r.ci_low)} to {fmt.num(r.ci_high)}</td><td>{fmt.num(r.p_value)}</td><td>{fmt.num(r.p_adjusted)}</td><td>{r.n_instances}</td><td>{r.higher_is_better?'Higher is better':'Lower is better'}</td><td>{r.verdict}{r.warnings.map((w,j)=><p className="muted" key={j}>{w}</p>)}</td></tr>)}</tbody></table></div>
  </section>;
}
