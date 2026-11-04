export interface PreviewFields {name:string; template:string; aoi:string; model:string; modelId:string; harness:string; toolset:string; trials:number; steps:number}
/** JSON is a YAML 1.2 subset; platform serialization safely quotes free text. */
export function previewSpec(f: PreviewFields): string {
  return JSON.stringify({
    spec_version:1, name:f.name,
    tasks:{templates:[f.template],aois:[f.aoi]},
    baseline:{name:'baseline',model:{name:f.model,params:{model_id:f.modelId}},harness:{name:f.harness,params:{}},toolset:f.toolset,tracer:{name:'jsonl'}},
    evaluators:[{name:'workflow',version:'1'},{name:'output',version:'1'}],
    trials:f.trials,seed:42,budget:{run:{max_steps:f.steps}},executor:{name:'local'},
  },null,2)+'\n';
}
