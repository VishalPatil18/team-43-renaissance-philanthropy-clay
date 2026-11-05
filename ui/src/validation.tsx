import { useApi, type ValidationResponse } from './api.ts';
import { Chip, Empty, Load, fmt } from './ui.tsx';

/** Planted-trace validation (J6): deliberately flawed runs must score below their good twin. */
export function ValidationScreen() {
  const q = useApi<ValidationResponse>('/api/validation');
  return <section aria-labelledby="validation-h">
    <header className="page-head"><h1 id="validation-h">Validation</h1>
      <p className="muted">Proof that the scorers catch what they should: each planted flaw must lower the expected scores against the good run of the same task.</p></header>
    <Load q={q} what="validation">{d => <ValidationView data={d} />}</Load>
  </section>;
}

export function ValidationView({ data }: { data: ValidationResponse }) {
  const r = data.report;
  if (!r.flaws.length) return <Empty title="No planted traces found">Add planted runs under samples/planted with scripts/make_planted.py.</Empty>;
  const detected = r.flaws.filter(f => f.detected).length;
  return <>
    <section className="panel">
      <div className="section-heading"><h2>{detected} of {r.flaws.length} planted flaws detected</h2><Chip value={detected === r.flaws.length ? 'ok' : 'error'} label={detected === r.flaws.length ? 'all detected' : 'missed flaws'} /></div>
      <p className="muted">Evaluators: {r.evaluators.join(', ')} · planted set: <code>{data.source}</code></p>
      <dl className="facts">
        {Object.entries(r.margins ?? {}).map(([kind, m]) => <div key={kind} className="fact-row"><dt>{kind} margin (good − flawed)</dt><dd>{fmt.num(m)}</dd></div>)}
        {r.ci_halfwidth != null && <div className="fact-row"><dt>Live eval CI half-width</dt><dd>{fmt.num(r.ci_halfwidth)} {r.margin_exceeds_ci ? '(margin is larger)' : '(margin is not larger)'}</dd></div>}
        {r.llm_agreement != null && <div className="fact-row"><dt>LLM judge mean spread</dt><dd>{fmt.num(r.llm_agreement)}</dd></div>}
      </dl>
      {r.notes.map((n, i) => <p className="note" key={i}>{n}</p>)}
    </section>
    <section className="panel">
      <h2>Detection by flaw</h2>
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Planted flaws"><table>
        <thead><tr><th scope="col">Task</th><th scope="col">Flaw</th><th scope="col">Result</th><th scope="col">Expected to drop</th><th scope="col">Good → flawed</th><th scope="col">Missed</th></tr></thead>
        <tbody>{r.flaws.map(f => <tr key={`${f.template}/${f.flaw}`}>
          <td>{f.template}</td><th scope="row">{f.flaw.replaceAll('_', ' ')}</th>
          <td><Chip value={f.detected ? 'ok' : 'error'} label={f.detected ? 'detected' : 'missed'} /></td>
          <td>{f.expected_drops.join(', ')}</td>
          <td>{f.expected_drops.map(m => <div key={m}><code>{m}</code> {fmt.num(f.good_value[m])} → {fmt.num(f.bad_value[m])}</div>)}</td>
          <td>{f.missing.length ? f.missing.join(', ') : <span className="muted">none</span>}{f.unchecked.length > 0 && <p className="muted">not checked: {f.unchecked.join(', ')}</p>}</td>
        </tr>)}</tbody>
      </table></div>
    </section>
  </>;
}
