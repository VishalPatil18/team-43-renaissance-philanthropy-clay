import assert from 'node:assert/strict';
import { renderToStaticMarkup as render } from 'react-dom/server';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { OverviewView, AssessmentsView, TraceView } from '../src/run.tsx';
import { SiteMap } from '../src/site-map.tsx';
import { ReportView, ComparisonView } from '../src/eval.tsx';
import { SpecBuilder } from '../src/new-run.tsx';
import { Load } from '../src/ui.tsx';
import type { Assessment, EvalDetail, EvalReport, ReferenceResponse, RunDetail, Trace } from '../src/api.ts';

const fixture = (file:string) => readFileSync(`../tests/fixtures/traces/good_t1/${file}`,'utf8');
const trace:Trace={run_id:'fixture-good_t1',events:fixture('trace.jsonl').trim().split('\n').map(line=>JSON.parse(line)),incomplete:false};
const reference:ReferenceResponse={exact:true,reference:JSON.parse(fixture('reference.json'))};
const detail:RunDetail={manifest:JSON.parse(fixture('manifest.json')),status:null,summary:null,report:null};
const assessment:Assessment={assessment_id:'test',run_id:trace.run_id,evaluator:{name:'workflow',version:'1'},kind:'workflow',task_reference_version:reference.reference.version,composite:.8,subscores:[{name:'tool_order',value:.8,weight:1,evidence:['fixture-good_t1:2'],notes:['Geocode before imagery.']}],metrics:{},success:true,evidence:[],notes:[],cost_usd:0};
const report:EvalReport={eval_id:'test-eval',baseline:'test-baseline',variants:[],warnings:[],stats:{configs:[],comparisons:[],alpha:.05}};
Object.defineProperty(globalThis,'location',{value:{pathname:'/runs/fixture-good_t1/trace',search:'?event=fixture-good_t1%3A2'},configurable:true});

test('overview shows manifest provenance and keeps missing values explicit',()=>{
 const html=render(<OverviewView detail={detail} trace={trace}/>);
 assert.match(html,/T1@us-ca-kern/);assert.match(html,/Not recorded/);assert.match(html,/1,350/);
});
test('trace citation opens and highlights the matching event',()=>{
 const html=render(<TraceView trace={trace}/>);
 assert.match(html,/data-event-id="fixture-good_t1:2" data-selected="true" open=""/);
 assert.match(html,/osm.geocode/);assert.match(html,/&quot;query&quot;/);
});
test('assessments keep evaluator kinds separate and evidence points to a deep trace URL',()=>{
 const html=render(<AssessmentsView rows={[assessment]} runId={trace.run_id}/>);
 assert.match(html,/Workflow assessment/);assert.match(html,/Geocode before imagery/);
 assert.match(html,/trace\?event=fixture-good_t1%3A2/);assert.doesNotMatch(html,/overall score/i);
});
test('map does not turn imagery identifiers into predicted sites',()=>{
 const html=render(<SiteMap reference={reference} output={{items:['imagery']}}/>);
 assert.match(html,/No predicted site coordinates/);assert.match(html,/aria-label="Site coordinates"/);
 assert.doesNotMatch(html,/class="predicted-site"/);
});
test('map marks predictions separately from reference outlines and preserves table coordinates',()=>{
 const r={...reference,exact:false,reference:{...reference.reference,output_reference:{sites:[{lat:35.3,lon:-119.2}]}}};
 const html=render(<SiteMap reference={r} output={{sites:[{lat:35.2,lon:-119.1}]}}/>);
 assert.match(html,/class="predicted-site"/);assert.match(html,/class="reference-site"/);
 assert.match(html,/>35.2<\/td>/);assert.match(html,/does not match the version/);
});
test('comparison distinguishes absent data from real effect estimates',()=>{
 assert.match(render(<ComparisonView report={report}/>),/No paired comparisons yet/);
 const r={...report,stats:{...report.stats,comparisons:[{baseline:'test-baseline',variant:'variant',axis:'model',metric:'workflow.composite',n_instances:1,effect:.1,ci_low:-.2,ci_high:.3,p_value:.5,p_adjusted:.5,higher_is_better:true,verdict:'insufficient evidence',warnings:[]}]}};
 const html=render(<ComparisonView report={r}/>);assert.match(html,/-0.200 to 0.300/);assert.match(html,/insufficient evidence/);
});
test('report without aggregate data retains run assessment access',()=>{
 const d:EvalDetail={eval_id:'test',runs:[{run_id:trace.run_id,task_instance_id:'T1@us-ca-kern',state:'completed',trial_index:0}],assessments:[],report:null,spec:null};
 const html=render(<ReportView detail={d}/>);assert.match(html,/No aggregate report stored/);assert.match(html,/href="\/runs\/fixture-good_t1"/);
});
test('spec builder labels configuration and preview with no execution control',()=>{
 const html=render(<SpecBuilder components={[{kind:'model',name:'bedrock',version:'1'},{kind:'harness',name:'strands',version:'1'},{kind:'toolset',name:'T1',version:'1'}]} tasks={[{id:'T1@us-ca-kern',template:'T1',aoi:'us-ca-kern',title:'Test task'}]}/>);
 assert.match(html,/Evaluation name/);assert.match(html,/readOnly=""/);assert.match(html,/Add a model ID/);assert.doesNotMatch(html,/>Launch|>Execute/);
});
test('load suppresses stale rows while a new request is pending and reports failures',()=>{
 const loading=render(<Load q={{loading:true,data:['stale']}} what="runs">{rows=><p>{rows[0]}</p>}</Load>);
 assert.match(loading,/Loading runs/);assert.doesNotMatch(loading,/stale/);
 assert.match(render(<Load q={{loading:false,error:new Error('Unavailable')}} what="runs">{()=>null}</Load>),/role="alert"/);
});
test('SVG accessible names render without React warnings',()=>{
 const original=console.error;
 console.error=(...messages)=>{throw new Error(messages.join(' '));};
 try {render(<SiteMap reference={reference} output={{sites:[{lat:35.2,lon:-119.1}]}}/>);} finally {console.error=original;}
});
