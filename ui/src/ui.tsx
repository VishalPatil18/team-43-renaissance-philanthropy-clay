// URL routing over the history API (no router dependency) plus small shared pieces.
import { useEffect, useState, type AnchorHTMLAttributes, type ReactNode } from 'react';
import type { Loaded } from './api.ts';

const NAV_EVENT = 'app:navigate';

export function navigate(to: string, replace = false) {
  if (to === location.pathname + location.search + location.hash) return;
  history[replace ? 'replaceState' : 'pushState'](null, '', to);
  window.dispatchEvent(new Event(NAV_EVENT));
}

export function useLocation() {
  const read = () => ({ path: location.pathname, query: new URLSearchParams(location.search) });
  const [loc, setLoc] = useState(read);
  useEffect(() => {
    const on = () => setLoc(read());
    window.addEventListener('popstate', on);
    window.addEventListener(NAV_EVENT, on);
    return () => { window.removeEventListener('popstate', on); window.removeEventListener(NAV_EVENT, on); };
  }, []);
  return loc;
}

/** An ordinary link that navigates in-app on a plain left click. */
export function Link({ href, children, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  return (
    <a
      href={href}
      {...rest}
      onClick={(e) => {
        rest.onClick?.(e);
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        navigate(href);
      }}
    >
      {children}
    </a>
  );
}

const STATE_TONE: Record<string, string> = {
  completed: 'good', ok: 'good', running: 'info', created: 'info',
  budget_stopped: 'warn', timeout: 'warn', rejected: 'warn',
  agent_failed: 'bad', infra_error: 'bad', error: 'bad',
};

export function Chip({ value, label }: { value: string | null | undefined; label?: string }) {
  const v = value ?? 'unknown';
  return <span className={`chip chip-${STATE_TONE[v] ?? 'plain'}`}>{label ?? v.replace(/_/g, ' ')}</span>;
}

export const fmt = {
  score: (v: number | null | undefined) => (v == null ? '–' : v.toFixed(2)),
  usd: (v: number | null | undefined) => (v == null ? '–' : `$${v < 0.01 ? v.toFixed(4) : v.toFixed(2)}`),
  int: (v: number | null | undefined) => (v == null ? '–' : Math.round(v).toLocaleString()),
  ms: (v: number | null | undefined) => (v == null ? '–' : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`),
  num: (v: number | null | undefined, d = 3) => (v == null ? '–' : Number.isInteger(v) ? String(v) : v.toFixed(d)),
};

export function Score({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="muted">–</span>;
  return (
    <span className="score">
      <span className="score-bar" aria-hidden="true"><span style={{ width: `${Math.round(value * 100)}%` }} /></span>
      <span className="score-num">{value.toFixed(2)}</span>
    </span>
  );
}

/** Loading, error and empty handling for one request; renders children only with data. */
export function Load<T>({ q, what, children }: { q: Loaded<T>; what: string; children: (d: T) => ReactNode }) {
  if (q.error) return <p className="note note-bad" role="alert">Could not load {what}: {q.error.message}</p>;
  if (q.loading || q.data === undefined) return <p className="note" aria-live="polite">Loading {what}…</p>;
  return <>{children(q.data)}</>;
}

export function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      <div className="muted">{children}</div>
    </div>
  );
}

/** A confidence interval drawn to scale: a line from low to high and a dot at the estimate. */
export function IntervalBar({ low, high, estimate, min = 0, max = 1, label }: {
  low: number | null; high: number | null; estimate: number | null; min?: number; max?: number; label: string;
}) {
  if (estimate == null || !(max > min)) return <span className="muted">–</span>;
  const W = 160, H = 18, pad = 6, x = (v: number) => pad + ((Math.min(max, Math.max(min, v)) - min) / (max - min)) * (W - 2 * pad);
  const lo = low ?? estimate, hi = high ?? estimate;
  return (
    <svg className="ci-bar" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
      aria-label={`${label}: ${fmt.num(estimate)}, 95% interval ${fmt.num(low)} to ${fmt.num(high)}`}>
      <line className="ci-track" x1={pad} x2={W - pad} y1={H / 2} y2={H / 2} />
      <line className="ci-range" x1={x(lo)} x2={x(hi)} y1={H / 2} y2={H / 2} />
      <circle className="ci-dot" cx={x(estimate)} cy={H / 2} r={4} />
    </svg>
  );
}

/** A paired effect against a zero line: left of centre favours the baseline, right the variant. */
export function EffectBar({ effect, low, high, span, label }: {
  effect: number | null; low: number | null; high: number | null; span: number; label: string;
}) {
  if (effect == null || !(span > 0)) return <span className="muted">–</span>;
  const W = 180, H = 18, pad = 6, mid = W / 2, x = (v: number) => mid + (Math.max(-span, Math.min(span, v)) / span) * (mid - pad);
  return (
    <svg className="ci-bar" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
      aria-label={`${label}: effect ${fmt.num(effect)}, 95% interval ${fmt.num(low)} to ${fmt.num(high)}`}>
      <line className="ci-track" x1={pad} x2={W - pad} y1={H / 2} y2={H / 2} />
      <line className="ci-zero" x1={mid} x2={mid} y1={2} y2={H - 2} />
      <line className="ci-range" x1={x(low ?? effect)} x2={x(high ?? effect)} y1={H / 2} y2={H / 2} />
      <circle className="ci-dot" cx={x(effect)} cy={H / 2} r={4} />
    </svg>
  );
}
