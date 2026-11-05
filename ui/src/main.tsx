import { StrictMode, useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { RunsScreen } from './runs.tsx';
import { RunScreen } from './run.tsx';
import { EvalScreen } from './eval.tsx';
import { NewRunScreen } from './new-run.tsx';
import { ValidationScreen } from './validation.tsx';
import { EvalLiveScreen } from './eval-live.tsx';
import { Empty, Link, useLocation } from './ui.tsx';
import './styles.css';

function App() {
  const {path, query} = useLocation();
  const run = /^\/runs\/([^/]+)(?:\/(overview|trace|assessments|map))?\/?$/.exec(path);
  const live = /^\/evals\/([^/]+)\/?$/.exec(path);
  let runId: string | undefined;
  try { runId = run ? decodeURIComponent(run[1]) : undefined; } catch { runId = undefined; }
  const active = path.startsWith('/runs') || path === '/' ? '/runs' : path.startsWith('/evals/') ? '/new-run' : path;
  const previousPath = useRef(path);
  useEffect(() => {
    document.title = `${run ? 'Run detail' : active.slice(1).replaceAll('-',' ')} · Clay sandbox`;
    // The trace owns focus when opening a cited event.
    if (previousPath.current !== path && !query.has('event')) document.getElementById('content')?.focus({preventScroll:true});
    previousPath.current = path;
  },[path]);
  return <>
    <a className="skip-link" href="#content">Skip to content</a>
    <header className="app-header">
      <Link href="/runs" className="brand"><svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5" fill="none" stroke="currentColor"/><path d="M8 8h8v8H8z" fill="none" stroke="currentColor"/></svg>Clay sandbox</Link>
      <nav aria-label="Main navigation">{[['/runs','Runs'],['/report','Report'],['/comparison','Comparison'],['/validation','Validation'],['/new-run','New Run']].map(([href,label])=><Link key={href} href={href} aria-current={active===href?'page':undefined}>{label}</Link>)}</nav>
      <span className="prototype-label">Local sandbox</span>
    </header>
    <main id="content" tabIndex={-1}>
      {path==='/' || path==='/runs' ? <RunsScreen/> : run && runId ? <RunScreen key={runId} runId={runId} tab={run[2]??'overview'}/> : path==='/report' || path==='/comparison' ? <EvalScreen comparison={path==='/comparison'}/> : live ? <EvalLiveScreen key={live[1]} evalId={decodeURIComponent(live[1])}/> : path==='/validation' ? <ValidationScreen/> : path==='/new-run' ? <NewRunScreen/> : <Empty title="Page not found"><Link href="/runs">Back to runs</Link></Empty>}
    </main>
    <footer className="app-footer"><span>Clay agent evaluation sandbox</span><span>Local store · Local API only</span></footer>
  </>;
}
createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
