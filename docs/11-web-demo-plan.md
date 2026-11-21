# Scenario-Based Algorithm Comparison: Web Demo Plan

**Implementation status:** a local demo has been added. See [README instructions](../README.md#local-demonstration). This document preserves its original design and acceptance criteria.

## 1. Intended screen

Build a local presentation tool to **choose a scenario, compare algorithms on the same task, and replay differences in warehouse routes**.

Initially display saved evaluation records. Presenters may recalculate with the same input and settings without changing historical evidence or rerunning the full experiment.

```text
Warehouse picking comparison [Saved results / Recalculate]
    A-H scenario, location count, pattern, start, seed, task ID
    Presentation example, condition description and task features
    Algorithm A map | Algorithm B map (same task and warehouse)
    Play / Pause / Reset, progress slider and playback speed
    Nine-candidate table: distance, time, status, returned method, optimality
    Saved selection rule and its decision conditions
    Filtered aggregates: distance, time, completion rate and sample count
    Explanation separating one example from overall trends
```

The product UI is designed in Korean, with readable translations of `completed` and `timeout` and access to original status codes where needed. Translating this specification does not change the UI language.

## 2. Presentation flow

1. **Small task:** compare NN and DP visit orders; mark optimality only for completed exact results.
2. **Route improvement:** compare NN and NN+2-opt on the same task, replay separately and optionally overlay.
3. **Large task:** select sizes 15, 20 and 50 to show DP timeout or size guards. Request mode also shows the NN fallback actually returned.
4. **Start change:** use H pairs with the same item set and different starts.
5. **Selection:** compare always-NN+2-opt with the saved count policy and explain its `n <= 13.5` split.

Example buttons reference verified saved tasks. Label curated examples as illustrations, not representative overall performance. Allow selection of cases with no improvement.

## 3. Mapping scenarios A-H

A-H are overlapping analytical perspectives. Selecting one sets default filters and methods, while users can change details.

| Scenario | Question | Default comparison |
|---|---|---|
| A: Small-task correctness | Do exact methods agree? | Exhaustive / DP |
| B: DP scaling | How do time and status change with size? | DP / NN+2-opt |
| C: Large tasks | How do fast methods trade distance for computation? | NN / NN+2-opt and all-candidate table |
| D: Clusters | Does improvement help concentrated items? | NN / NN+2-opt |
| E: Dispersion | How does gain vary with realized dispersion? | NN / NN+2-opt |
| F: Conveyor relationship | What changes in mirrored pairs with matching seed, size and start? | Same method on far / near tasks |
| G: Directionality and pattern | How do pattern and realized distances relate to results? | NN / CA-minus and pattern aggregates |
| H: Start position | What changes when only the start changes? | Same method, different starts |

Automatically find F/H partners and show matching size, seed and conditions. If no partner exists, explain that the comparison is unavailable.

Show the actual numeric dispersion for E. If using an evaluation-median split, label it a descriptive analytical partition. F also changes start distances and is not a causal isolation of conveyor distance.

## 4. Result fields

| Field | Display rule |
|---|---|
| Distance | Aisle distance from S through required visits to C, in metres. |
| Computation time | Milliseconds; identify candidate-search versus full-request timing. |
| Status | Preserve completion, timeout, size/memory limits and errors. |
| Termination | Distinguish 2-opt local optimum from evaluation-count exhaustion. |
| Requested / returned method | Show both when DP fails and NN is returned. |
| Optimality | Claim only when an exact method completed and proved it. |
| Difference from NN | Use a valid NN result on the same task. |
| Gap to optimum | Show only when that task has a completed exact solution. |
| Settings | Expose coefficient, budget, size limits and measurement source. |

Aggregates first show attempts, completions and status proportions. Identify the completed sample behind distance/time medians. Do not rank algorithms using best distances from different inputs.

Default to evaluation data and visibly label development mode. Read saved rules; do not retrain them from evaluation results in the UI.

## 5. Map and playback

Render an SVG map from existing `build_warehouse()` coordinates and edges. Distinguish S, C and required shelf locations, numbering their planned visits.

Use stored request `path` directly. Candidate records contain visit order, so prepare the selected task's distance table and call `DistanceTable.reconstruct()`. This visualization preparation is not added to historical algorithm timing. Validate the route with `validate_path()` and check recorded distance. Show a mismatch message instead of an invalid route.

Animate a marker along real aisle segments, with progress proportional to distance. This replays the route, not the algorithm's historical search. Playback speed is not a measured worker speed or an estimate of operational completion time.

The first version has two maps, playback/pause/reset and a slider. Support keyboard controls; distinguish methods by labels and line styles as well as colour.

## 6. Saved records and live calculation

**Saved results** read `results/full` and retain original measurement settings and times. A different live outcome must not replace historical evidence.

**Recalculate** sequentially runs the two selected candidates on the selected task, not all 4,050 workloads. Validate input/settings and retain existing time, size and memory-estimate limits.

Label live results as remeasured in the current demo, including time and settings. Keep them in the session without overwriting records. Show running state, block duplicate submissions and preserve saved results after errors.

Do not execute candidates concurrently because that would change timing meaning. Default to the study's 0.2-second budget and CA coefficient 0.5; visibly identify changes from those settings.

## 7. Implementation and files

The first implementation uses **a Python standard-library local server, HTML/CSS/JavaScript and SVG**. Python is already used and Streamlit was not installed in the design environment. This small setup calls existing calculation functions without additional installation.

```text
python3 -m demo
    -> localhost web page
       -> saved-result lookup, filters and aggregates
       -> task route rendering and playback
       -> recalculation of two selected methods
```

Bind to `127.0.0.1` by default. Public deployment is outside this local presentation scope. Accept fixed task IDs and allowed algorithm/settings only; never execute arbitrary file paths or commands from requests.

| File | Responsibility |
|---|---|
| `demo/__main__.py` | Local server, result index, query/recalculation API. |
| `demo/index.html` | Korean UI, accessible controls and comparison table. |
| `demo/app.js` | Filters, API calls, SVG routes and playback. |
| `demo/style.css` | Presentation layout, paired maps and narrow-screen support. |
| `tests/test_demo.py` | Normalization, pairing, route and input validation. |
| `README.md` | Startup and missing-data preparation instructions. |

Reuse `picking/`, `experiments/` and raw evidence. Isolate new UI code in `demo/` to preserve baseline code fingerprints and findings.

Do not reread large raw files on every click or send them wholesale to the browser. Load necessary fields once and index by task, measurement kind and algorithm. Return filters, aggregates and selected results only. Cache visualization distance tables per selected task. Explain missing/corrupt data and preparation steps on screen.

## 8. Implementation sequence and acceptance

| Step | Deliverable | Acceptance |
|---|---|---|
| 1 | Saved data and one-task table | UI distance/time/status match JSONL records. |
| 2 | Paired maps and playback | Correct endpoints, no shelf crossings, reconstructed distance matches. |
| 3 | A-H filters and paired tasks | Correct F/H partners and empty-result handling. |
| 4 | Aggregates and rule explanation | Failures remain visible; samples and matching inputs are clear. |
| 5 | Recalculation | Preserve records; separate new timings and fallback. |
| 6 | Presentation flow and instructions | Launch from a fresh terminal and complete the five example steps. |

Automated checks cover record-to-display normalization, invalid IDs/settings, F/H pairing, distance validation and the returned method after timeout. Run baseline regressions too.

Manual browser checks cover filters, method changes, playback, keyboard controls, narrow screens, missing data and recalculation failures. Run the presentation examples end to end with the actual server and UI connected.

## 9. Scope

The first version is a **presentation tool showing different routes and outcomes on identical tasks**. Login, cloud hosting, layout editing, manual item placement, multiple pickers and 3D maps are excluded from this baseline demo.

Complete saved-result lookup and paired-route viewing first, then add recalculation. This document records the implementation-stage plan and acceptance criteria.
