import { useApi, type ReferenceResponse, type Trace } from './api.ts';
import { Empty, Load } from './ui.tsx';
import { readSites, type Site } from './sites.ts';

export function MapView({runId,trace}:{runId:string;trace:Trace}) {
  const reference=useApi<ReferenceResponse>(`/api/runs/${encodeURIComponent(runId)}/reference`);
  const output=[...trace.events].reverse().find(e=>e.type==='final_output')?.output;
  return <Load q={reference} what="task reference">{r=><SiteMap reference={r} output={output}/>}</Load>;
}
export function SiteMap({reference,output}:{reference:ReferenceResponse;output:unknown}) {
  const predicted=readSites(output), refs=readSites(reference.reference.output_reference);
  const bbox=reference.reference.aoi?.bbox;
  const all=[...predicted,...refs];
  const validBBox=bbox?.length===4 && bbox.every(Number.isFinite) && bbox[0]<bbox[2] && bbox[1]<bbox[3];
  const bounds=validBBox ? bbox : all.length ? [Math.min(...all.map(s=>s.lon))-.01,Math.min(...all.map(s=>s.lat))-.01,Math.max(...all.map(s=>s.lon))+.01,Math.max(...all.map(s=>s.lat))+.01] : null;
  const rows=[...predicted.map((s,i)=>({...s,label:`Predicted ${i+1}`,kind:'Predicted'})),...refs.map((s,i)=>({...s,label:`Reference ${i+1}`,kind:'Reference'}))];
  const positions=all.flatMap(s=>[s,...[s.outline,...(s.additionalOutlines??[])].flatMap(r=>r?.map(p=>({lon:p[0],lat:p[1]}))??[])]);
  let plot=null;
  if(bounds) {
    const minX=Math.min(bounds[0],...positions.map(s=>s.lon)),maxX=Math.max(bounds[2],...positions.map(s=>s.lon));
    const minY=Math.min(bounds[1],...positions.map(s=>s.lat)),maxY=Math.max(bounds[3],...positions.map(s=>s.lat));
    const x=(n:number)=>48+(n-minX)/(maxX-minX)*704;
    const y=(n:number)=>350-(n-minY)/(maxY-minY)*300;
    const mark=(s:Site,i:number,prediction:boolean)=><g key={`${prediction}-${i}`} className={prediction?'predicted-site':'reference-site'}><title>{`${prediction?'Predicted':'Reference'} ${i+1}: ${s.lat}, ${s.lon}`}</title>{!prediction&&s.outline ? [s.outline,...(s.additionalOutlines??[])].map((ring,j)=><polygon key={j} points={ring.map(p=>`${x(p[0])},${y(p[1])}`).join(' ')} fill="none" stroke="currentColor" strokeWidth="2"/>) : <circle cx={x(s.lon)} cy={y(s.lat)} r={prediction?6:10} fill={prediction?'var(--site-red)':'none'} stroke={prediction?'var(--site-red)':'currentColor'} strokeWidth="2"/>}<text x={x(s.lon)+13} y={y(s.lat)+5}>{prediction?'P':'R'}{i+1}</text></g>;
    plot=<svg viewBox="0 0 800 410" role="img" aria-labelledby="map-title map-description"><title id="map-title">{`Site coordinates in ${reference.reference.aoi?.name??'the recorded area'}`}</title><desc id="map-description">Red filled points are predictions. Outlines are references. Coordinates follow in a table. This is a longitude and latitude sketch without map tiles.</desc>
      {[0,.25,.5,.75,1].map(n=><g key={n} className="map-grid"><path d={`M48 ${50+n*300}H752 M${48+n*704} 50V350`}/></g>)}
      {validBBox&&<rect className="aoi-bounds" x={x(bbox[0])} y={y(bbox[3])} width={x(bbox[2])-x(bbox[0])} height={y(bbox[1])-y(bbox[3])} fill="none" stroke="currentColor" strokeDasharray="6 5"/>}
      {refs.map((s,i)=>mark(s,i,false))}{predicted.map((s,i)=>mark(s,i,true))}
      <text x="48" y="386">{minX.toFixed(3)}° lon</text><text x="628" y="386">{maxX.toFixed(3)}° lon</text><text x="48" y="28">{maxY.toFixed(3)}° lat</text>
    </svg>;
  }
  return <section className="panel"><div className="section-heading"><h2>Site map</h2><span className="muted">{reference.reference.aoi?.name??reference.reference.instance_id}</span></div>
    {!reference.exact&&<p className="note">This is the current library reference. It does not match the version used to score this run; use the assessment’s recorded version for provenance.</p>}
    <p className="map-legend"><span><i className="legend-predicted"/>Predicted sites ({predicted.length})</span><span><i className="legend-reference"/>Reference outlines ({refs.length})</span><span>Dashed boundary: area of interest</span></p>
    <div className="map-plot">{plot??<Empty title="No geographic coordinates recorded">The trace and task reference contain no locations to plot.</Empty>}</div>
    {!predicted.length&&<p className="note">No predicted site coordinates in this output. Imagery item identifiers are not site predictions.</p>}
    <p className="muted">Longitude / latitude sketch. No basemap or distance measurement. Polygon table entries use recorded centres or representative points. P labels identify predictions; R labels identify references.</p>
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Site coordinates table"><table aria-label="Site coordinates"><thead><tr><th scope="col">Site</th><th scope="col">Kind</th><th scope="col">Latitude</th><th scope="col">Longitude</th></tr></thead><tbody>{rows.map(s=><tr key={s.label}><th scope="row">{s.label}</th><td>{s.kind}</td><td>{s.lat}</td><td>{s.lon}</td></tr>)}{!rows.length&&<tr><td colSpan={4}>No site coordinates recorded.</td></tr>}</tbody></table></div>
  </section>;
}
