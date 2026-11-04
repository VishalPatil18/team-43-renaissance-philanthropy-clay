import { useState } from 'react';
import { useApi, type Component, type TaskInstance } from './api.ts';
import { Empty, Load } from './ui.tsx';
import { previewSpec } from './spec.ts';

export function NewRunScreen() {
  const components=useApi<Component[]>('/api/components');
  const tasks=useApi<TaskInstance[]>('/api/tasks');
  return <section><header className="page-head"><h1>New Run</h1><p className="muted">Prepare an evaluation specification. This prototype previews configuration only; start evaluations with the CLI.</p></header>
    <Load q={components} what="components">{c=><Load q={tasks} what="tasks">{t=>t.length ? <SpecBuilder components={c} tasks={t}/> : <Empty title="No tasks available">Add a task instance to the task library before preparing a spec.</Empty>}</Load>}</Load>
  </section>;
}
export function SpecBuilder({components,tasks}:{components:Component[];tasks:TaskInstance[]}) {
  const names=(kind:string)=>components.filter(c=>c.kind===kind).map(c=>c.name);
  const [name,setName]=useState('local-evaluation'),[taskId,setTaskId]=useState(tasks[0]?.id??'');
  const [model,setModel]=useState(names('model')[0]??''),[modelId,setModelId]=useState('');
  const [harness,setHarness]=useState(names('harness')[0]??''),[toolset,setToolset]=useState(names('toolset')[0]??'');
  const [trials,setTrials]=useState(1),[steps,setSteps]=useState(25),[copied,setCopied]=useState('');
  const task=tasks.find(t=>t.id===taskId)??tasks[0];
  const spec=previewSpec({name,template:task.template,aoi:task.aoi,model,modelId,harness,toolset,trials,steps});
  const choices=(label:string,value:string,set:(s:string)=>void,options:string[])=><label className="field"><span>{label}</span><select value={value} onChange={e=>set(e.target.value)}>{options.map(n=><option key={n}>{n}</option>)}</select></label>;
  return <div className="builder-layout"><form className="panel" onSubmit={e=>e.preventDefault()}><h2>Configuration</h2>
    <div className="form-fields"><label className="field"><span>Evaluation name</span><input value={name} required onChange={e=>setName(e.target.value)}/></label>
    <label className="field"><span>Task instance</span><select value={taskId} onChange={e=>setTaskId(e.target.value)}>{tasks.map(t=><option value={t.id} key={t.id}>{t.id} — {t.title}</option>)}</select></label>
    {choices('Model adapter',model,setModel,names('model'))}
    <label className="field"><span>Model ID</span><input value={modelId} required onChange={e=>setModelId(e.target.value)} aria-describedby="model-help"/><small id="model-help">Enter a model ID available to your runtime before using this spec.</small></label>
    {choices('Harness',harness,setHarness,names('harness'))}{choices('Tool set',toolset,setToolset,names('toolset'))}
    <label className="field"><span>Trials</span><input type="number" min="1" step="1" value={trials} onChange={e=>setTrials(Math.max(1,Math.floor(Number(e.target.value)||1)))}/></label>
    <label className="field"><span>Maximum steps per run</span><input type="number" min="1" step="1" value={steps} onChange={e=>setSteps(Math.max(1,Math.floor(Number(e.target.value)||1)))}/></label></div>
  </form><section className="panel spec-panel"><div className="section-heading"><h2>EvalSpec preview</h2><button type="button" className="btn-primary" onClick={async()=>{try{await navigator.clipboard.writeText(spec);setCopied('Copied specification.');}catch{setCopied('Copy unavailable. Select the preview and copy it manually.');}}}>Copy spec</button></div>
    <p className="muted">YAML 1.2 in JSON syntax. Copy to a <code>.yaml</code> file. Workflow and output evaluators remain separate.</p>
    {!modelId.trim()&&<p className="note">Add a model ID to complete the preview.</p>}
    <label className="sr-only" htmlFor="spec-preview">Read-only evaluation specification</label><textarea id="spec-preview" readOnly value={spec} spellCheck={false}/><p role="status" aria-live="polite">{copied}</p>
    <p className="muted">No run is created here. Review runtime access, tool configuration and costs before running the spec.</p>
  </section></div>;
}
