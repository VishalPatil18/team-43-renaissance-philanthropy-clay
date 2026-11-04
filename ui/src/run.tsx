import { useEffect } from 'react';
import { useApi, type Assessment, type RunDetail, type Trace, type TraceEvent } from './api.ts';
import { Chip, Empty, Link, Load, Score, fmt, useLocation } from './ui.tsx';
import { MapView } from './site-map.tsx';

export function RunScreen({runId,tab}:{runId:string;tab:string}) {
  const base = `/api/runs/${encodeURIComponent(runId)}`;
  const detail = useApi<RunDetail>(base);
  const trace = useApi<Trace>(base+'/trace');
  const assessments = useApi<Assessment[]>(base+'/assessments');
  return <section>
    <Link href="/runs" className="back-link">Back to runs</Link>
    <header className="page-head"><div className="heading-line"><h1>{runId}</h1><Chip value={detail.data?.status?.state}/></div><p className="muted">Inspect the recorded run, then follow each assessment back to its evidence.</p></header>
    <nav className="tabs" aria-label="Run sections">{['overview','trace','assessments','map'].map(t=><Link href={`/runs/${encodeURIComponent(runId)}/${t}`} key={t} aria-current={t===tab?'page':undefined}>{t[0].toUpperCase()+t.slice(1)}</Link>)}</nav>
    {tab==='overview' && <Load q={detail} what="run">{d=><OverviewView detail={d} trace={trace.data}/>}</Load>}
    {tab==='trace' && <Load q={trace} what="trace">{t=><TraceView trace={t}/>}</Load>}
    {tab==='assessments' && <Load q={assessments} what="assessments">{rows=><AssessmentsView rows={rows} runId={runId}/>}</Load>}
    {tab==='map' && <Load q={trace} what="trace">{t=><MapView runId={runId} trace={t}/>}</Load>}
  </section>;
}
export function OverviewView({detail,trace}:{detail:RunDetail;trace?:Trace}) {
  const m=detail.manifest, totals=trace?.events.find(e=>e.type==='run_end')?.totals;
  const tokens=trace?.events.filter(e=>e.type==='model_call').reduce((n,e)=>n+(e.input_tokens??0)+(e.output_tokens??0),0);
  return <div className="overview-layout"><section className="panel"><h2>Overview</h2><dl className="facts">
    <dt>Task instance</dt><dd>{m.task_instance_id}</dd><dt>Configuration</dt><dd>{m.config_name??'Not recorded'}</dd>
    <dt>Model</dt><dd>{String(m.model?.params?.model_id??m.model?.name??'Not recorded')}</dd>
    <dt>Harness</dt><dd>{m.harness?.name??'Not recorded'}</dd><dt>Tool set</dt><dd>{m.toolset?.name??'Not recorded'}</dd>
    <dt>Evaluation</dt><dd>{m.eval_id ? <Link href={`/report?eval=${encodeURIComponent(m.eval_id)}`}>{m.eval_id}</Link>:'Not grouped'}</dd>
    <dt>Reference version</dt><dd>{m.task_reference_version??'Not recorded'}</dd><dt>Seed</dt><dd>{m.seed??'Not recorded'}</dd>
  </dl><h3>Run limits</h3><pre>{JSON.stringify(m.budget??{},null,2)}</pre></section>
  <section className="panel"><h2>Recorded totals</h2><dl className="facts"><dt>Steps</dt><dd>{fmt.int(totals?.steps)}</dd><dt>Tokens</dt><dd>{fmt.int(tokens)}</dd><dt>Agent cost</dt><dd>{fmt.usd(totals?.cost_usd)}</dd><dt>Wall time</dt><dd>{fmt.ms(totals?.wall_ms)}</dd></dl>
  <p className="muted">A dash means the artifact did not record this value.</p><h3>Summary</h3>{detail.summary?.claims?.length ? <ul>{detail.summary.claims.map((c,i)=><li key={i}>{c.claim}<Evidence ids={c.event_ids} runId={m.run_id}/></li>)}</ul>:<p className="muted">No summary claims recorded.</p>}
  {detail.report != null && <details><summary>Stored run report</summary><pre>{JSON.stringify(detail.report,null,2)}</pre></details>}
  </section></div>;
}
export function Evidence({ids,runId}:{ids:string[];runId:string}) {
  return <div className="evidence-links">{ids.map(id=><Link key={id} data-evidence={id} href={`/runs/${encodeURIComponent(runId)}/trace?event=${encodeURIComponent(id)}`}>Event {id}</Link>)}</div>;
}
export function AssessmentsView({rows,runId}:{rows:Assessment[];runId:string}) {
  if (!rows.length) return <Empty title="No assessments recorded">Score this run with the CLI to add evaluator results.</Empty>;
  return <div className="assessment-list">{rows.map(a=><article className="panel" key={a.assessment_id}>
    <div className="section-heading"><div><h2>{a.kind[0].toUpperCase()+a.kind.slice(1)} assessment</h2><p className="muted">{a.evaluator.name} · version {a.evaluator.version??'unknown'}</p></div><div className="composite"><span>Composite</span><Score value={a.composite}/></div></div>
    <p className="muted">Reference: {a.task_reference_version}. Evaluator cost: {fmt.usd(a.cost_usd)}.</p>
    {a.notes.map((n,i)=><p className="note" key={i}>{n}</p>)}
    {a.subscores.map(s=><section className="subscore" key={s.name}><div className="section-heading"><h3>{s.name.replaceAll('_',' ')}</h3><Score value={s.value}/></div><p className="muted">Weight {fmt.num(s.weight)}</p>{s.notes.map((n,i)=><p key={i}>{n}</p>)}<Evidence ids={s.evidence} runId={runId}/></section>)}
    {Object.keys(a.metrics).length>0 && <dl className="facts metrics">{Object.entries(a.metrics).map(([key,v])=><div key={key}><dt>{key.replaceAll('_',' ')}</dt><dd>{fmt.num(v)}</dd></div>)}</dl>}
    <Evidence ids={a.evidence} runId={runId}/>
  </article>)}</div>;
}
function eventLabel(e:TraceEvent) { return e.type==='tool_call' ? `${e.server}.${e.tool}` : e.type.replaceAll('_',' '); }
export function TraceView({trace}:{trace:Trace}) {
  const {query}=useLocation(); const selected=query.get('event');
  useEffect(()=>{
    if (!selected) return;
    const element=document.getElementById(`event-${selected}`);
    if (element instanceof HTMLDetailsElement) {
      element.open=true; element.focus({preventScroll:true}); element.scrollIntoView({block:'start',behavior:'instant'});
    }
  },[selected,trace]);
  return <section><div className="section-heading"><h2>Trace</h2><span className="muted">{trace.events.length} recorded events</span></div>
  {trace.incomplete && <p className="note" role="status">This trace is incomplete. Some events may be missing.</p>}
  {selected && !trace.events.some(e=>e.event_id===selected) && <p role="alert" className="note">The cited event is missing from this trace.</p>}
  <ol className="timeline">{trace.events.map(e=><li key={e.event_id}><details id={`event-${e.event_id}`} data-event-id={e.event_id} data-selected={selected===e.event_id} open={selected===e.event_id||undefined} tabIndex={-1}>
    <summary><span className="event-seq">{e.seq}</span><span className="event-title">{eventLabel(e)}<small>{e.event_id}</small></span><span className="event-meta">{e.status || e.state ? <Chip value={e.status??e.state}/>:null}<span>{fmt.ms(e.latency_ms)}</span><span>{fmt.usd(e.cost_usd??e.totals?.cost_usd)}</span></span></summary>
    <div className="event-body"><dl className="facts"><dt>Started</dt><dd>{e.ts_start}</dd>{e.parent_id&&<><dt>Parent</dt><dd><Link href={`?event=${encodeURIComponent(e.parent_id)}`}>{e.parent_id}</Link></dd></>}</dl>
    {e.error&&<p className="note" role="status">{e.error.source} / {e.error.kind}: {e.error.message}</p>}
    <pre>{JSON.stringify(e,null,2)}</pre></div>
  </details></li>)}</ol>{!trace.events.length&&<Empty title="No trace events recorded">This run has no events to inspect.</Empty>}</section>;
}
