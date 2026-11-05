import { useMemo, useState } from 'react';
import { ApiError, post, useApi, type Component, type Estimate, type LaunchResponse, type TaskInstance } from './api.ts';
import { Empty, Load, fmt, navigate } from './ui.tsx';
import { buildSpec, previewSpec, slug, splitLines } from './spec.ts';

export function NewRunScreen() {
  const components=useApi<Component[]>('/api/components');
  const tasks=useApi<TaskInstance[]>('/api/tasks');
  return <section><header className="page-head"><h1>New Run</h1><p className="muted">Run a library task or your own question on one or more models. Check the cost, then launch. Runs call real models and tools, within the limits you set.</p></header>
    <Load q={components} what="components">{c=><Load q={tasks} what="tasks">{t=>t.length ? <SpecBuilder components={c} tasks={t}/> : <Empty title="No tasks available">Add a task instance to the task library before preparing a spec.</Empty>}</Load>}</Load>
  </section>;
}

const errorText=(e:unknown)=>e instanceof ApiError ? `${e.message}${e.kind ? ` (${e.kind})` : ''}` : e instanceof Error ? e.message : String(e);
const num=(v:string,min:number,int=false)=>{const n=Number(v);if(!Number.isFinite(n))return min;return Math.max(min,int?Math.floor(n):n);};

export function SpecBuilder({components,tasks}:{components:Component[];tasks:TaskInstance[]}) {
  const names=(kind:string)=>components.filter(c=>c.kind===kind).map(c=>c.name);
  const [name,setName]=useState('local-evaluation'),[taskId,setTaskId]=useState(tasks[0]?.id??'');
  const [model,setModel]=useState(names('model')[0]??''),[modelId,setModelId]=useState('');
  const [harness,setHarness]=useState(names('harness')[0]??''),[toolset,setToolset]=useState(names('toolset').includes('T1')?'T1':names('toolset')[0]??'');
  const [mode,setMode]=useState<'library'|'custom'>('library'),[prompt,setPrompt]=useState(''),[expectText,setExpectText]=useState(''),[compareText,setCompareText]=useState('');
  const [nameTouched,setNameTouched]=useState(false);
  const [trials,setTrials]=useState(1),[steps,setSteps]=useState(25),[copied,setCopied]=useState('');
  const [maxUsd,setMaxUsd]=useState(0.1),[maxSeconds,setMaxSeconds]=useState(240),[evalCapUsd,setEvalCapUsd]=useState(2);
  const task=tasks.find(t=>t.id===taskId)??tasks[0];
  const custom=mode==='custom'?{prompt,expect:splitLines(expectText)}:null;
  const evalName=nameTouched||mode==='library'?name:(prompt.trim()?`query-${slug(prompt)}`.slice(0,60):name);
  const fields={name:evalName,template:task.template,aoi:task.aoi,model,modelId:modelId.trim(),harness,toolset,trials,steps,maxUsd,maxSeconds,evalCapUsd,compareModelIds:splitLines(compareText),custom};
  const spec=previewSpec(fields);
  const specObject=useMemo(()=>buildSpec(fields),[spec]); // eslint-disable-line react-hooks/exhaustive-deps

  // The estimate is only valid for the exact spec it was made for.
  const [estimate,setEstimate]=useState<{spec:string;value:Estimate}|null>(null);
  const [busy,setBusy]=useState<'estimate'|'launch'|null>(null);
  const [error,setError]=useState('');
  const [confirmed,setConfirmed]=useState(false);
  const current=estimate && estimate.spec===spec ? estimate.value : null;
  const missing=!modelId.trim()?'Add a model ID':mode==='custom'&&!prompt.trim()?'Write your question':'';
  const ready=!missing && !!current && !current.exceeds_eval_cap;
  const canLaunch=ready && confirmed && busy===null;

  const runEstimate=async()=>{
    setBusy('estimate');setError('');setConfirmed(false);
    try{setEstimate({spec,value:await post<Estimate>('/api/estimate',{spec:specObject})});}
    catch(e){setEstimate(null);setError(errorText(e));}
    finally{setBusy(null);}
  };
  const launch=async()=>{
    setBusy('launch');setError('');
    try{const r=await post<LaunchResponse>('/api/evals',{spec:specObject,confirm:true});navigate(`/evals/${encodeURIComponent(r.eval_id)}`);}
    catch(e){setError(errorText(e));setBusy(null);}
  };

  const choices=(label:string,value:string,set:(s:string)=>void,options:string[])=><label className="field"><span>{label}</span><select value={value} onChange={e=>set(e.target.value)}>{options.map(n=><option key={n}>{n}</option>)}</select></label>;
  const spend=current ? Math.min(current.total_usd*1.5, evalCapUsd) : evalCapUsd;
  return <div className="builder-layout"><form className="panel" onSubmit={e=>e.preventDefault()}><h2>Configuration</h2>
    <div className="form-fields">
    <fieldset className="field mode-switch"><legend>What to run</legend>
      <label><input type="radio" name="mode" checked={mode==='library'} onChange={()=>setMode('library')}/> Library task</label>
      <label><input type="radio" name="mode" checked={mode==='custom'} onChange={()=>setMode('custom')}/> Custom query</label>
    </fieldset>
    <label className="field"><span>Evaluation name</span><input value={evalName} required onChange={e=>{setName(e.target.value);setNameTouched(true);}}/></label>
    {mode==='library' ? <label className="field"><span>Task instance</span><select value={taskId} onChange={e=>setTaskId(e.target.value)}>{tasks.map(t=><option value={t.id} key={t.id}>{t.id} — {t.title}</option>)}</select></label> : <>
      <label className="field"><span>Your question</span><textarea className="query-input" value={prompt} required onChange={e=>setPrompt(e.target.value)} placeholder="Find NAIP imagery over Kern County, California from 2022 and list the item IDs." aria-label="Your question" aria-describedby="prompt-help"/><small id="prompt-help">The agent answers it with the chosen tool set. There is no reference answer, so only the expected answers below are scored.</small></label>
      <label className="field"><span>Expected answers (optional)</span><textarea className="query-input short" value={expectText} onChange={e=>setExpectText(e.target.value)} placeholder={'m_3511901_ne_11_060_20220511\nBakersfield'} aria-label="Expected answers" aria-describedby="expect-help"/><small id="expect-help">One per line or comma-separated. The score is the share of these the answer contains (case-insensitive).</small></label>
    </>}
    {choices('Model adapter',model,setModel,names('model'))}
    <label className="field"><span>Model ID</span><input value={modelId} required onChange={e=>setModelId(e.target.value)} aria-label="Model ID" aria-describedby="model-help" placeholder="us.amazon.nova-pro-v1:0"/><small id="model-help">A Bedrock model ID your account can call, for example us.amazon.nova-pro-v1:0.</small></label>
    <label className="field"><span>Compare with models (optional)</span><textarea className="query-input short" value={compareText} onChange={e=>setCompareText(e.target.value)} placeholder="us.anthropic.claude-sonnet-4-6" aria-label="Compare with models" aria-describedby="compare-help"/><small id="compare-help">More model IDs, one per line. Each runs the same task, and the report compares it with the first model.</small></label>
    {choices('Harness',harness,setHarness,names('harness'))}{choices('Tool set',toolset,setToolset,names('toolset'))}
    <label className="field"><span>Trials</span><input type="number" min="1" step="1" value={trials} onChange={e=>setTrials(num(e.target.value,1,true))}/></label>
    <label className="field"><span>Maximum steps per run</span><input type="number" min="1" step="1" value={steps} onChange={e=>setSteps(num(e.target.value,1,true))}/></label>
    <label className="field"><span>Maximum $ per run</span><input type="number" min="0.01" step="0.01" value={maxUsd} onChange={e=>setMaxUsd(num(e.target.value,0.01))}/></label>
    <label className="field"><span>Maximum seconds per run</span><input type="number" min="10" step="10" value={maxSeconds} onChange={e=>setMaxSeconds(num(e.target.value,10,true))}/></label>
    <label className="field"><span>Evaluation cap ($, all runs)</span><input type="number" min="0.01" step="0.5" value={evalCapUsd} onChange={e=>setEvalCapUsd(num(e.target.value,0.01))}/></label></div>
  </form>
  <div className="form-fields">
    <section className="panel" aria-labelledby="launch-h"><h2 id="launch-h">Launch</h2>
      <div className="launch-actions">
        <button type="button" onClick={runEstimate} disabled={!!missing||busy!==null}>{busy==='estimate'?'Estimating…':'Estimate cost'}</button>
        <button type="button" className="btn-primary" onClick={launch} disabled={!canLaunch}>{busy==='launch'?'Launching…':'Launch evaluation'}</button>
      </div>
      {missing&&<p className="muted">{missing}, then estimate the cost before launching.</p>}
      {estimate && !current && <p className="muted">The configuration changed since the last estimate. Estimate again.</p>}
      {current && <div role="status" aria-live="polite">
        <dl className="facts"><dt>Planned runs</dt><dd>{current.runs}</dd><dt>Estimated cost</dt><dd>{fmt.usd(current.total_usd)}</dd>
          {Object.entries(current.per_config).map(([k,v])=><div key={k} className="fact-row"><dt>{k}</dt><dd>{fmt.usd(v)}</dd></div>)}
          <dt>Evaluation cap</dt><dd>{current.eval_cap_usd==null?'none':fmt.usd(current.eval_cap_usd)}</dd></dl>
        {current.exceeds_eval_cap && <p className="note" role="alert">The estimate exceeds the evaluation cap. Raise the cap or reduce trials before launching.</p>}
        {[...current.warnings,...current.notes].map((n,i)=><p className="muted" key={i}>{n}</p>)}
      </div>}
      {ready && <label className="confirm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/> <span>I confirm this calls real models and may spend up to {fmt.usd(spend)}.</span></label>}
      {error && <p className="note" role="alert">{error}</p>}
    </section>
    <section className="panel spec-panel"><div className="section-heading"><h2>EvalSpec preview</h2><button type="button" onClick={async()=>{try{await navigator.clipboard.writeText(spec);setCopied('Copied specification.');}catch{setCopied('Copy unavailable. Select the preview and copy it manually.');}}}>Copy spec</button></div>
      <p className="muted">YAML 1.2 in JSON syntax. The same spec runs from the terminal with <code>clay-sandbox eval spec.yaml --confirm</code>.</p>
      <label className="sr-only" htmlFor="spec-preview">Evaluation specification</label><textarea id="spec-preview" readOnly value={spec} spellCheck={false}/><p role="status" aria-live="polite">{copied}</p>
    </section>
  </div></div>;
}
