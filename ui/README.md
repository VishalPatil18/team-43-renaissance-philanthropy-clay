# Clay sandbox UI prototype

React + Vite + TypeScript screens over the existing local run store: Runs, Run detail
(Overview / Trace / Assessments / Map), Report, Comparison and a read-only New Run spec
preview. This prototype never starts a run. No external fonts, maps, assets or model calls.

## Run the demo

From the repository root (Python 3.12+, uv, Node 22.18+ or 24):

```bash
uv sync --group dev --extra api
npm --prefix ui ci
npm --prefix ui run build
uv run python scripts/make_demo_store.py --out /tmp/claysandbox-demo/store
uv run python -m claysandbox.api --store /tmp/claysandbox-demo/store
```

Open <http://127.0.0.1:8765>. The output folder must be new; the seeder refuses to overwrite
an existing folder. Use a different temporary path when rerunning. It creates exactly three
committed T1 fixture runs, each scored by the registered workflow and output evaluators,
plus a baseline-only evaluation report. Fixture results are not physical measurements or
live model results.

For frontend development, keep the API running and use `npm --prefix ui run dev`, then open
<http://127.0.0.1:5173>. Vite proxies `/api` to port 8765. Both servers use loopback only;
foreign or malformed Host/Origin headers are rejected by the API.

## Checks

```bash
uv run pytest -q
uv run ruff check .
uv run python scripts/export_openapi.py --check
npm --prefix ui test
npm --prefix ui run build
```

`npm test` runs coordinate/spec tests and rendered-component checks using Node's test
runner and the existing Vite toolchain. These verify trace evidence URLs and selected
markup, assessment separation, missing data, map fallback, comparison uncertainty, spec
preview escaping, and loading/error states. They do not simulate browser layout or effects.

`npm run test:browser` requires Playwright to be available locally or through `NODE_PATH`,
and an available Chromium. Set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` if needed. Start the API
against the three-run demo above, then:

```bash
cd ui
UPDATE_SCREENSHOTS=1 npm run test:browser  # capture initial evidence; inspect before accepting
npm run test:browser                       # compare screenshots byte-for-byte
```

`BASE_URL` defaults to `http://127.0.0.1:8765`. The script checks all screens at 1440 and
390 px, evidence scrolling/focus/selection, filters, keyboard skip link, absence of external
requests or browser writes, and light mode. It also covers map sites and populated
comparison rows using explicitly intercepted test data: the real fixture runs have no
predicted site coordinates and no variants. Keep the Chromium version and platform fixed
for byte-exact screenshots. First-run baselines have **not** been captured in this host:
loopback binding returns EPERM and native Chrome launch aborts. The script fails when a
baseline is missing; it does not silently accept an image. Browser, screenshot, keyboard,
zoom and screen-reader acceptance remain pending on a host with those capabilities.

## Contract and limits

- `api/openapi.json` comes from FastAPI; `src/api.ts` is hand-typed for this prototype.
  Replace it with the architecture's generated client when that integration lands.
- Missing recorded metrics display a dash, never zero. Workflow, output and process scores
  are separate. Trace links use `?event=` to open, focus, scroll to and highlight the event.
- Runs fetch up to 500 rows. The API supports limit/offset; pagination is a follow-up for
  larger stores. The existing query layer returns the full fixture task instance as its
  `template` filter value; the UI uses that value without changing core store code.
- Map sketches use lon/lat, not a distance-preserving projection. Red points are predictions;
  reference geometries use outlines, and the coordinate table remains available. Polygon
  and MultiPolygon rings are outlined; table entries use recorded centres or representative
  points, not distance measurements. Missing or mismatched
  reference versions are explained; demo references preserve the actual fixture version.
- New Run produces YAML 1.2 in JSON syntax using the platform serializer. Enter a real
  runtime model ID before using it. Component-specific advanced parameters, validation,
  estimates, SSE and run execution are outside this approved prototype.
- Dark tokens match `dev-docs/DESIGN.md`; light tokens follow the same roles. Focus rings,
  44 px controls, native keyboard disclosure, reduced motion and coordinate tables are
  implemented. No claim of screen-reader or physical-device validation is made.

## Result

Skills loaded: frontend-design, ui-ux-pro-max, impeccable, emil-design-eng,
accessibility-review, ponytail (lite), test-driven-development, systematic-debugging,
verification-before-completion, modern-web-guidance, karpathy-guidelines.

Design skills loaded: frontend-design, ui-ux-pro-max, impeccable, emil-design-eng,
accessibility-review.

- frontend-design: preserved the approved graphite/cobalt hierarchy and restrained type.
- ui-ux-pro-max: native controls, labels, keyboard reachability and responsive structure.
- impeccable: token-based light/dark surfaces and explicit loading, empty and error states.
- emil-design-eng: brief press feedback; instant evidence jumps; reduced-motion override.
- accessibility-review: focus rings, 44 px targets, labeled SVG and coordinate table fallback.

Implementation and non-browser checks are complete. Browser evidence remains blocked by
host permissions; initial screenshot baselines and manual accessibility checks are pending.
No commit, push, merge or deployment was performed.

Accessibility checks available in this host (calculated from CSS tokens):

| Pair | Contrast |
| --- | ---: |
| Dark body / graphite | 14.13:1 |
| Dark secondary / control surface | 8.40:1 |
| Light body / white surface | 16.08:1 |
| Light secondary / control surface | 6.01:1 |
| Primary button white / cobalt | 4.71:1 |
| Input outline / canvas (dark, light) | 3.64:1, 4.45:1 |
| Predicted markers / canvas (dark, light) | 8.05:1, 6.05:1 |

These checks cover the specified text/control pairs, not a complete WCAG conformance audit.
Keyboard navigation, 200% zoom, screen-reader announcements, forced colors and actual mobile
layout still need browser review. The SVG uses a labeled image and a semantic coordinate table;
reference outlines and P/R labels make site kinds identifiable without color.

Modern Web Guidance was searched for responsive tables and navigation; its offline package
was unavailable, so no guide was applied. The implementation follows the official
[React effect cleanup guidance](https://react.dev/reference/react/useEffect) for cancelling
stale requests and the [W3C table guidance](https://www.w3.org/WAI/tutorials/tables/tips/) for
semantic tables inside keyboard-scrollable containers. The synced Impeccable helper scripts
and register references were absent; its loaded design rules and the committed tokens were used.
