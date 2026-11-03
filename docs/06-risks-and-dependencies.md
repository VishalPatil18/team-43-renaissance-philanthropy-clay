# MVP Risks and Dependencies

> **For agents — what this file is:** Known risks with their mitigations, the things we depend on (and who owes them), and the questions to ask Clay at kickoff. Check it at the start of each work session.

> Scope: **ADB agentic eval only**. Captions are a stretch after the ADB stretch goals. Index: [README.md](README.md)

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| No ADB inputs are coming (SCOPE D13), and an ADB rubric is unconfirmed, so we have no external reference to score against | Certain | High | We generate synthetic tasks (D19), each with a task reference (expected-workflow spec plus output reference from public data, e.g. USPVDB as the answer key). Ask Clay to review them, and whether an ADB rubric exists. The source had asked for these to be secured before the event |
| Live agent is flaky during the 2-day build or the demo | Medium | High | Recorded-trace replay (J2). Record good traces early on Day 1 |
| MCP server coverage or maturity gaps | Medium | Medium | RODA MCP is the known-good tool. Pick shortlist servers marked "active" in the catalog. Test each one before wiring it into the agent |
| NAIP Requester-Pays costs | Medium | Medium | Pre-stage a small NAIP sample in us-west-2. Watch the **$500 sandbox cap** |
| Scope creep into captions or the other tasks | Medium | Medium | ADB fully working first. Captions only after the ADB stretch goals |
| LLM-based evaluator scores (if one is used, OQ1/OQ12) are noisy | Medium | Medium | Fixed prompt and temperature 0. Score several times and report the spread. Keep deterministic metrics separate |
| Too few trials for statistics to show real differences (F10) | Medium | High | Choose N from the measured per-run cost on Day 1. Report uncertainty honestly. Prefer fewer configurations with more trials |
| License mismatch: Clay requires Apache-2.0, but the repo LICENSE is MIT | Certain | Medium | **Team decision:** swap LICENSE to Apache-2.0 (one file) before submission |
| Bedrock model access not enabled in the sandbox account or region | Medium | High | Request model access in the first hour of Day 1 and confirm with a one-line test call |
| Sandbox wiped after the event | Certain | Medium | Everything that matters goes in the public repo: infrastructure as code, sample traces, reports |

### Dependencies

| Dependency | From | Status |
|---|---|---|
| Synthetic tasks with task references | Our team (D19) | Team generates them. Current state unconfirmed (OQ14) |
| Harnesses under test (at least 2, for comparison) | Our team | Strands (D7) plus a second one: choice pending (OQ4) |
| Free/priority MCP shortlist | Clay | Catalog saved at [reference/geomcp-catalog.csv](reference/geomcp-catalog.csv). Confirm which servers are on the shortlist |
| AWS sandbox account (Workshop Studio) with Bedrock access | AWS team lead | Provisioned at the event, capped at $500 |
| LGND Geo MCP whitelist | Clay/LGND | Commercial tool. Confirm our access |
| Open-source repo | Team | Created: [VishalPatil18/team-43-renaissance-philanthropy-clay](https://github.com/VishalPatil18/team-43-renaissance-philanthropy-clay) (public). License decision pending |
| Data and tool links | — | See [EXTERNAL-DEPENDENCIES.md](EXTERNAL-DEPENDENCIES.md) |

### Ask Clay at kickoff (gaps in the source doc itself)

1. **The kickoff confirmation list is missing.** The doc's intro says "a short list of items to confirm with Clay at kickoff is at the end", but the doc ends with Stretch Goals and has no such list. Ask Clay for it.
2. **The third task is undefined.** "The Three Tasks" defines only two: the ADB agentic eval and caption generation. Ask what the third one is.
3. **What a concrete ADB task looks like:** the actual "how to use AI / build datasets" prompt or brief, and what a good output is.
4. Ask Clay to review our synthetic tasks and task references, and whether an ADB rubric exists (we get no ADB inputs, D13).
5. Which servers in the geoMCP catalog are on the free/priority shortlist.
6. Whether our team is whitelisted for LGND Geo MCP.
