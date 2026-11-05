import { useApi, type ConfigStats, type EvalDetail, type EvalReport, type Interval, type MeasurementComparison } from './api.ts';
import { EffectBar, Empty, IntervalBar, Link, Load, fmt, navigate, useLocation } from './ui.tsx';

export function EvalScreen({comparison}:{comparison:boolean}) {
  const {query}=useLocation();
  const evals=useApi<{eval_id:string;runs:number}[]>('/api/evals');
  const id=query.get('eval')??evals.data?.[0]?.eval_id;
  const detail=useApi<EvalDetail>(id ? `/api/evals/${encodeURIComponent(id)}`:null);
  return <section><header className="page-head"><h1>{comparison?'Comparison':'Report'}</h1><p className="muted">{comparison?'Paired variant effects relative to the baseline. Uncertainty stays visible.':'Per-configuration results, with workflow, output and process metrics kept separate.'}</p></header>
  <Load q={evals} what="evaluations">{rows=>!rows.length ? <Empty title="No evaluations in this store">Seed the demo store or select a store with an evaluation report.</Empty>:<>
    <label className="field eval-picker"><span>Evaluation</span><select value={id} onChange={e=>navigate(`${comparison?'/comparison':'/report'}?eval=${encodeURIComponent(e.target.value)}`)}>{rows.map(e=><option key={e.eval_id} value={e.eval_id}>{e.eval_id} ({e.runs} runs)</option>)}</select></label>
    <Load q={detail} what="evaluation">{d=>comparison ? <ComparisonView report={d.report} evalId={d.eval_id}/> : <ReportView detail={d}/>}</Load>
  </>}</Load></section>;
}

const UNIT_SCALE=/composite|precision|recall|f1|rate|validity|coverage|ordering|recovery|efficiency|condition|forbidden|constraints|pass/;

/** Scores share a 0–1 scale; other metrics (cost, steps, latency) share one scale per metric across configurations. */
function scaleFor(name:string, configs:ConfigStats[]):[number,number] {
  if (name==='workflow.success_rate' || UNIT_SCALE.test(name)) return [0,1];
  const highs=configs.map(c=>c.metrics[name]?.high??c.metrics[name]?.estimate??0);
  return [0,Math.max(...highs,1e-9)];
}

export function ReportView({detail}:{detail:EvalDetail}) {
  const report=detail.report;
  const configs=report?.stats.configs??[];
  const evalId=detail.eval_id;
  return <>{report ? <>
    <p className="note">Baseline: {report.baseline}. Confidence intervals reflect recorded samples; a small demo is not evidence of model quality.</p>
    {report.warnings.map((w,i)=><p className="note" key={i}>{w}</p>)}
    {report.stats.seed!=null && <p className="muted">Statistics: seed {report.stats.seed}, {fmt.int(report.stats.bootstrap_iterations)} bootstrap iterations, α = {report.stats.alpha}.</p>}
    {configs.map(c=>{
      const metrics:[string,Interval][]=Object.entries({'workflow.success_rate':c.success_rate,...c.metrics});
      const runs=report.run_links?.[c.config_name];
      return <section className="panel report-config" key={c.config_name}>
        <div className="section-heading"><h2>{c.config_name}{c.config_name===report.baseline && <span className="muted"> · baseline</span>}</h2>
          <Link href={`/runs?eval=${encodeURIComponent(evalId)}&config=${encodeURIComponent(c.config_name)}`}>View {runs?.length ?? c.runs_total} runs</Link></div>
        <p className="muted">{c.runs_used} of {c.runs_total} runs used across {c.instances} task instances.</p>
        {c.warnings.map((w,i)=><p className="note" key={i}>{w}</p>)}
        {Object.entries(c.excluded).map(([state,n])=><p key={state}>Excluded: {n} {state.replaceAll('_',' ')} runs</p>)}
        <div className="table-wrap" tabIndex={0} role="region" aria-label={`${c.config_name} metrics`}><table><thead><tr><th scope="col">Metric</th><th scope="col">Estimate</th><th scope="col">95% interval</th><th scope="col">Confidence interval</th><th scope="col">Sample size</th><th scope="col">Method</th></tr></thead>
        <tbody>{metrics.map(([name,v])=>{const [lo,hi]=scaleFor(name,configs);return <tr key={name}><th scope="row">{name}</th><td>{fmt.num(v.estimate)}</td><td><IntervalBar low={v.low} high={v.high} estimate={v.estimate} min={lo} max={hi} label={name}/></td><td>{fmt.num(v.low)} to {fmt.num(v.high)}</td><td>{v.n}</td><td>{v.method.replaceAll('_',' ')}</td></tr>;})}</tbody></table></div>
      </section>;})}
    <MeasurementSection report={report}/>
  </>:<Empty title="No aggregate report stored">The report is written when the evaluation finishes. If it is still running, <Link href={`/evals/${encodeURIComponent(evalId)}`}>open its live progress</Link>. Run-level assessments are available below.</Empty>}
  <section className="panel"><h2>Runs in this evaluation</h2><ul className="run-links">{detail.runs.map(r=><li key={r.run_id}><Link href={`/runs/${encodeURIComponent(r.run_id)}`}>{r.run_id}</Link><span className="muted">{r.state?.replaceAll('_',' ')??'Unknown state'}</span></li>)}</ul><p className="muted">{detail.assessments.length} recorded assessments. Open a run for evaluator notes and trace evidence.</p></section></>;
}

export function ComparisonView({report,evalId:shownId}:{report:EvalReport|null;evalId?:string}) {
  const rows=report?.stats.comparisons??[];
  if(!rows.length) return <>
    <Empty title="No paired comparisons yet">{report ? <>This evaluation ran one configuration ({report.baseline}), so there is nothing to compare it with. Comparisons are made inside one evaluation: on New Run, list more models under “Compare with models” (or add variants to a spec), and each runs the same task alongside the baseline.</> : <>This evaluation has no report yet. It is written when the evaluation finishes{shownId ? <>; <Link href={`/evals/${encodeURIComponent(shownId)}`}>open its live progress</Link></> : null}.</>}</Empty>
    {report && <MeasurementSection report={report}/>}
  </>;
  const span:Record<string,number>={};
  for (const r of rows) span[r.metric]=Math.max(span[r.metric]??0,Math.abs(r.effect??0),Math.abs(r.ci_low??0),Math.abs(r.ci_high??0));
  const variants=report?.variants??[];
  const evalId=report?.eval_id??'';
  return <>
    {variants.length>0 && <section className="panel"><h2>What each variant changes</h2>
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Variant axes"><table><thead><tr><th scope="col">Variant</th><th scope="col">Axis</th><th scope="col">Changed settings</th><th scope="col">Paired task instances</th><th scope="col">Runs</th></tr></thead>
      <tbody>{variants.map(v=><tr key={v.variant}><th scope="row">{v.variant}</th><td>{v.axis ?? <span className="muted">none</span>}{v.warning && <p className="muted">{v.warning}</p>}</td><td>{v.changed.length ? v.changed.join(', ') : <span className="muted">no overrides</span>}</td><td>{report?.paired_instances_by_variant?.[v.variant]?.length ?? '–'}</td><td><Link href={`/runs?eval=${encodeURIComponent(evalId)}&config=${encodeURIComponent(v.variant)}`}>View runs</Link></td></tr>)}</tbody></table></div>
    </section>}
    <section className="panel"><h2>Variant against baseline</h2><p className="muted">Effect = variant − baseline. Positive values favor the variant only when higher is better. CI level: {((1-(report?.stats.alpha??.05))*100).toFixed(0)}%.</p>{report?.warnings.map((w,i)=><p className="note" key={i}>{w}</p>)}
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Paired comparisons"><table><thead><tr>{['Variant','Baseline','Metric','Effect','Effect vs zero','Confidence interval','p-value','Adjusted p','Pairs','Direction','Verdict'].map(h=><th scope="col" key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={i}><td>{r.variant}</td><td>{r.baseline}</td><th scope="row">{r.metric}</th><td>{fmt.num(r.effect)}</td><td><EffectBar effect={r.effect} low={r.ci_low} high={r.ci_high} span={span[r.metric]} label={`${r.variant} ${r.metric}`}/></td><td>{fmt.num(r.ci_low)} to {fmt.num(r.ci_high)}</td><td>{fmt.num(r.p_value)}</td><td>{fmt.num(r.p_adjusted)}</td><td>{r.n_instances}</td><td>{r.higher_is_better?'Higher is better':'Lower is better'}</td><td>{r.verdict}{r.warnings.map((w,j)=><p className="muted" key={j}>{w}</p>)}</td></tr>)}</tbody></table></div>
    </section>
    {report?.verdicts && Object.keys(report.verdicts).length>0 && <section className="panel"><h2>Verdicts in plain words</h2>
      {Object.entries(report.verdicts).map(([variant,lines])=><div key={variant}><h3>{variant}</h3><ul>{lines.map((l,i)=><li key={i}>{l}</li>)}</ul></div>)}</section>}
    {report && <MeasurementSection report={report}/>}
  </>;
}

/** Evaluator agreement and tracer overhead: measurements about the sandbox itself, kept apart from agent results. */
export function MeasurementSection({report}:{report:EvalReport}) {
  const items:[string,MeasurementComparison|null|undefined,string][]=[
    ['Evaluator agreement',report.evaluator_comparison,'Run two or more evaluators of one kind (for example workflow@0 and workflow@1, or the LLM judge) in the same evaluation.'],
    ['Tracer comparison',report.tracer_comparison,'Run the evaluation with the tee tracer to compare capture overhead and fidelity.'],
  ];
  return <section className="panel"><h2>Measurement comparisons</h2><p className="muted">How much the measuring tools agree, kept separate from agent results.</p>
    <div className="measure-grid">{items.map(([title,m,hint])=><div key={title} className="measure">
      <h3>{title}</h3>
      {m ? <><p className="muted">{m.subjects.join(' vs ')} · {m.n_runs} runs</p>
        <dl className="facts">{Object.entries(m.values).map(([k,v])=><div key={k} className="fact-row"><dt>{k.replaceAll('_',' ')}</dt><dd>{fmt.num(v)}</dd></div>)}</dl>
        {m.notes.map((n,i)=><p className="note" key={i}>{n}</p>)}</>
      : <p className="muted">Not recorded for this evaluation. {hint}</p>}
    </div>)}</div>
  </section>;
}
