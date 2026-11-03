# MVP Success Criteria

> **For agents — what this file is:** MVP success criteria (SC1–SC12). These are the outcomes the build must show. SC1–SC7 come from Clay's vision doc (adjusted for team decisions), and SC8–SC12 come from the team's scope ([SCOPE.md](SCOPE.md)). Each one is proven by a journey test in [04](04-user-journeys-tests.md). Terms are in the [SCOPE glossary](SCOPE.md#glossary).

> Scope: **ADB agentic eval only**. Captions are a stretch after the ADB stretch goals. Index: [README.md](README.md)

- [ ] **SC1.** An LLM harness performs a synthetic ADB-style task by calling geospatial tools over MCP, using public or synthetic data. *(J1)*
- [ ] **SC2.** The agent's activity, **including every error**, is captured as traces and summarized into a human-readable view. *(J1, J4)*
- [ ] **SC3.** Each run is scored on two dimensions: *(J1)*
  - **Workflow**, from the trace: tool-call correctness and order, failures and recovery, steps, latency and cost. This is the main judgment (D9).
  - **Output**, as an evaluation metric against the task's output reference (D16). We get no ADB inputs (D13); whether Clay sends an ADB rubric is unconfirmed.
- [ ] **SC4.** The sandbox produces an evaluation report for every run. *(J1)*
- [ ] **SC5.** The **model, harness, tracer, and trace evaluator** are each swappable behind an abstraction, with no code changes. *(J3)*
- [ ] **SC6.** If the live agent fails, recorded traces replay through scoring and still produce a report. *(J2)*
- [ ] **SC7.** Trust and provenance: every scored run keeps its trace, its inputs, the full context the agent was given (prompt, system prompt, tools and schemas, model, harness, budget settings), and the task-reference version it was judged against. *(J1)*
- [ ] **SC8.** The sandbox **compares harnesses, agents (models), and tooling** on the same tasks. *(J5)*
- [ ] **SC9.** The evaluation is **statistically verifiable**: repeated trials give statistics with uncertainty, and the evaluator separates good from bad runs by a margin larger than that uncertainty. *(J6)*
- [ ] **SC10.** An **optional budget guard** can be set per run or per eval, and it stops runs that exceed it. *(J7)*
- [ ] **SC11.** **Every parameter** is exposed through one run/eval spec and API, so a UI can be built later without backend changes. *(J9)*
- [ ] **SC12.** **Reproducible beyond its builders:** a teammate on a different machine can set it up and run it from the README. *(J8)*
