# MVP Definition of Done

> **For agents — what this file is:** The MVP is done when every box here is ticked. Each item links to the journey test in [04](04-user-journeys-tests.md) that proves it. Use it as the final gate before demo and submission.

> Scope: **ADB agentic eval only**. Captions are a stretch after the ADB stretch goals. Index: [README.md](README.md)

- [ ] One synthetic task runs end to end: harness → MCP tools → trace capture → summarize → score → report (**J1**).
- [ ] Scoring covers the workflow (the main judgment) and the output metric, against each task's task reference (**J1**).
- [ ] Every error (tool, model, budget, infra) is logged and shown in the summary (**J4**).
- [ ] Model, harness, tracer and trace evaluator are each hot-swappable through config (**J3**).
- [ ] Recorded-trace replay verified, including re-scoring with a swapped evaluator (**J2**, **J3**).
- [ ] Harnesses, agents and tooling are compared on the same tasks (**J5**).
- [ ] Evaluation is statistically verifiable: repeated trials, uncertainty, and good-vs-bad separation (**J6**).
- [ ] Optional budget guard works when on and is absent when off (**J7**).
- [ ] Every parameter is exposed through the run/eval spec and API (**J9**).
- [ ] A teammate reproduces it on a fresh machine from the README (**J8**).
- [ ] Code in a **public, open-source GitHub repo** that Clay can access after the event, with infrastructure as code where it applies. **License: Clay's doc requires Apache-2.0, but the repo currently has MIT. Team decision needed** (see [06](06-risks-and-dependencies.md)).
- [ ] At least one recorded trace and its report committed to the repo, so the demo works even after the sandbox is wiped.
- [ ] [FUTURE-WORK.md](FUTURE-WORK.md) lists every feature cut or deferred during the build.
- [ ] README explains how to run live, replay, swap components, run a comparison, and set a budget.

Journeys: [04-user-journeys-tests.md](04-user-journeys-tests.md).
