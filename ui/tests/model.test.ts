import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readSites} from '../src/sites.ts';
import {previewSpec} from '../src/spec.ts';

test('site output preserves longitude latitude order and rejects invalid coordinates', () => {
  assert.deepEqual(readSites({sites:[{lat:35.2,lon:-119.1},[-119.2,35.3],{lat:91,lon:0},null,{lat:'35',lon:1}]}), [{lon:-119.1,lat:35.2},{lon:-119.2,lat:35.3}]);
  assert.deepEqual(readSites({items:['imagery']}),[]);
});
test('GeoJSON reference polygon keeps outline and centre', () => {
  const outline = [[-120,34],[-119,34],[-119,35],[-120,34]];
  assert.deepEqual(readSites({sites:[{type:'Feature',properties:{lat:34.5,lon:-119.5},geometry:{type:'Polygon',coordinates:[outline]}}]}),[{lon:-119.5,lat:34.5,outline}]);
});
test('spec preview uses EvalSpec schema and quotes user input safely', () => {
  const text = previewSpec({name:'test:\nname',template:'T3',aoi:'us-ca-kern',model:'bedrock',modelId:'example-model',harness:'strands',toolset:'T3',trials:2,steps:25});
  // JSON is a YAML 1.2 subset and avoids hand-built YAML escaping.
  const spec = JSON.parse(text);
  assert.equal(spec.name,'test:\nname');
  assert.deepEqual(spec.tasks,{templates:['T3'],aois:['us-ca-kern']});
  assert.equal(spec.baseline.model.params.model_id,'example-model');
  assert.equal(spec.budget.run.max_steps,25);
  assert.deepEqual(spec.evaluators.map((e: {name:string})=>e.name),['workflow','output']);
  assert.equal(spec.trials,2);
});
test('site parser accepts evaluator coordinate aliases, JSON and MultiPolygon outlines', () => {
  assert.deepEqual(readSites(JSON.stringify({locations:[{longitude:-119,latitude:35},{lng:-118,lat:34}]})),[{lon:-119,lat:35},{lon:-118,lat:34}]);
  const ring=[[-120,34],[-119,34],[-119,35],[-120,34]];
  const sites=readSites({sites:[{type:'MultiPolygon',coordinates:[[ring]]}]});
  assert.equal(sites.length,1);
  assert.deepEqual(sites[0].outline,ring);
});
test('map retains disjoint MultiPolygon regions and interior rings', () => {
 const a=[[-120,34],[-119,34],[-119,35],[-120,34]], b=[[-118,34],[-117,34],[-117,35],[-118,34]];
 const hole=[[-119.8,34.1],[-119.5,34.1],[-119.5,34.2],[-119.8,34.1]];
 const [site]=readSites({sites:[{type:'MultiPolygon',coordinates:[[a,hole],[b]]}]});
 assert.deepEqual(site.additionalOutlines,[hole,b]);
});
