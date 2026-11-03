# MVP Features Explicitly Out of Scope

> **For agents — what this file is:** What we are NOT building in the MVP, and why. It also holds the caption-task stretch reference (rubric, answer key, risks), so that material isn't lost. Check this before adding any feature.

> Scope: **ADB agentic eval only**. Captions are a stretch after the ADB stretch goals. Index: [README.md](README.md)

| Out of scope | Why |
|---|---|
| Caption-generation task: the five-criterion caption rubric, the fixed/change caption tasks, the VLM GPU-cost comparison, retrieval answer keys | Team decision. It's a stretch, attempted only after the ADB stretch goals |
| Training the Clay v2 model | The hackathon evaluates workflows. It doesn't train models |
| Running Clay's whole eval backlog | One representative eval proves the loop |
| Partner-account (ADB) deployment, multi-account or cross-account setups | We use a single sandbox account only |
| Continental-scale builds, SageMaker HyperPod or large Trainium clusters | Too big for a 2-day sandbox and on the disallow list |
| Full production observability or warehouse stack (Snowflake/Iceberg/Athena, Managed Grafana) | A lightweight trace/metadata store is enough |
| Any private or sensitive customer data | Public or synthetic data only |
| Integrating with Clay's production systems | Greenfield sandbox, but the shapes should map back cleanly |

## Stretch reference: caption-generation task (recorded here, not MVP)

These come from the vision doc and only apply once the ADB stretch goals are done.

**Task types**

| Type | Input | Caption must get right |
|---|---|---|
| Fixed | One image of a place at one date | Position, counts and relationality (how objects sit relative to each other, e.g. a road between two fields) |
| Change | Two images of the same place at different dates | Changes in position, counts and relationality between the dates |

**Five-criterion caption rubric.** Weighting is still to be decided, so score and report each criterion on its own and apply weights later.

| Criterion | Checks | How to measure |
|---|---|---|
| Retrieval quality | A caption can be found from a text query alone, with no image | Embed captions and queries with any off-the-shelf text model, then record how often the right caption is in the top results |
| **Grounding (most important)** | The caption matches what is on the ground: objects, attributes, counts | Compare caption claims with reference labels (GRW, USGS, OSM, Vantor vectors, or human-labeled datasets) |
| Fidelity | The caption represents the image accurately overall | An LLM judge compares the caption with the image and gives a score |
| Cost | Throughput and time to output across VLMs | Same images and prompt for each VLM. Record GPU time and GPU count or size, **not token cost** |
| Label preparation time | How long labels take to prepare | Record the time taken to prepare each label set |

- **Retrieval answer key (suggested by Kinzah at ADB):** train on one region of Global Renewables Watch v1.0 or USGS USPVDB/USWTDB, then test on another region that already has an LGND collection, using GRW, USGS or OSM there as the answer key.
- **Inputs:** NAIP high-res imagery plus sample Vantor data. LGND embeddings for captioning and retrieval (reuse them rather than train). Optional auxiliary caption datasets.
- **Needed from Clay:** example captions and the retrieval evaluation set.
- **Should-have from the source:** a caption cost comparison (more than one VLM on the same images and prompt).
- **Caption risks:**
  - Rubric weights not yet set (High / Medium). Report each criterion on its own.
  - Auxiliary datasets may have unclear licenses or few human labels (Medium / Medium). Check each license, and score only against human-labeled subsets (e.g. in RSCC).
- Links: [EXTERNAL-DEPENDENCIES.md](EXTERNAL-DEPENDENCIES.md) §2–4.
