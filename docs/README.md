# MVP Rubric (index) — Clay Earth Dataset Foundry (ADB agentic eval)

> **For agents — what this file is:** Entry point and index for the whole folder. Read this first. It holds the scope note, event logistics and judging, the Day-1 build order, the file list, and the stretch order. Reading order for a new agent: README → SCOPE → OPEN-QUESTIONS → 01 → 02 → 04 → 05 → 06 → 03 → EXTERNAL-DEPENDENCIES → FUTURE-WORK.

Source: Clay's vision doc and the AWS event guide, narrowed to our team's scope. The PDFs aren't in the repo; ask the team for a copy. The team's own scope and decisions are in [SCOPE.md](SCOPE.md), and terms are defined in its [glossary](SCOPE.md#glossary).

**Our scope:** the **ADB agentic eval only**. The caption-generation task is a later stretch, attempted only after the ADB stretch goals (see the end of this file). Any caption-specific line in the vision doc (five-criterion caption rubric, VLM GPU-cost comparison, fixed/change caption tasks) is **not MVP** for us.

**Loop under test:** harness (Bedrock) → MCP tools → trace capture → summarize → score → report.

**Event deadlines (AWS Breaking Barriers DC):** official build time ends **Wed Nov 4, 5:30 pm**, but the team can build outside those hours (SCOPE D18). Prelim presentations run **Thu Nov 5, 10:00 am–12:00 pm**. The public GitHub repo must be up before judging.

## Event logistics and judging (AWS Breaking Barriers DC)

| | |
|---|---|
| Days 1–2 (Nov 3–4) | **WAS16, 1770 Crystal Drive, Arlington VA 22202**. Enter from 18th St (main) or Crystal Dr. Reception is on the 2nd floor. Garage costs about $24/day, first come first served, using the "1770" elevator bay |
| Day 3 (Nov 5) | **WAS17, 510 14th Street South, Arlington VA**. Reception is on the 2nd floor. Park at the Costco lot on S Fern St (about a 3 min walk) |
| Bring | **Government-issued photo ID**, a laptop and charger, and optionally a water bottle |
| Day 1 | 9:00 check-in · 10:00 kickoff (rules and **point system**) · 11:00 keynote · **1:00–5:30 build** |
| Day 2 | 8:30 doors · **9:30–12:30 and 1:00–5:30 build** (build ends Wed 5:30 pm) |
| Day 3 | 8:00 arrival · 10:00–12:00 **prelim presentations** · 2:10–2:50 DC finals · 3:30 prizes |
| Sandbox | AWS Workshop Studio. **$500 cap**, wiped after the event. Use infrastructure as code where it applies. Publish as open source in a **public GitHub repo before judging** |
| Judging | Four **equally weighted** criteria: **Technological Implementation** (execution and AWS service integration) · **Design** (UX, interface, architecture) · **Potential Impact** · **Quality of Idea** (innovation, creativity, feasibility). The top 3 per location go to finals, judged by new judges on the same criteria. The winning beneficiary gets $50K in AWS credits |
| Support | AWS SMEs onsite, AWS Builder Center online, breaking-barriers-us-2026@amazon.com |

## Build order (Day 1, from the source)

Harness on Bedrock + RODA MCP + 1–2 shortlist servers → **one trace captured end to end before adding any scoring** → prove observe → summarize → score on one synthetic task before adding swaps, comparisons and statistics.

## Files

- [Team Scope](SCOPE.md): the team's own problem, constraints, and solution requirements
- [Future Work](FUTURE-WORK.md): post-build features we'd implement with more time (kept current during the build)
- [Open Build Questions](OPEN-QUESTIONS.md): build-time questions, not yet decided, each with a recommended default
- [MVP Features in Scope](01-features-in-scope.md)
- [MVP Success Criteria](02-success-criteria.md)
- [MVP Features Explicitly Out of Scope](03-out-of-scope.md)
- [MVP User Journeys as Tests](04-user-journeys-tests.md)
- [MVP Definition of Done](05-definition-of-done.md)
- [MVP Risks and Dependencies](06-risks-and-dependencies.md)
- [External Dependencies](EXTERNAL-DEPENDENCIES.md)

---

## Stretch order (after MVP done)

Full list, plus anything cut during the build: [FUTURE-WORK.md](FUTURE-WORK.md).

1. Sensitivity analysis: vary the inputs, prompts, tool selection, and model, then compare traces and scores across the variants to see how stable both the workflow and the eval are.
2. Multi-agent traces (planner, executor, and checker).
3. Dynamic MCP tool discovery across Clay's catalog.
4. A richer trace-summary dashboard.
5. **Then** a second task: caption generation, using the five-criterion caption rubric. The caption sections of the vision doc apply only at this point.
