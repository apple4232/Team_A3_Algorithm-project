# Project Expansion: Progress and Follow-up

Updated November 20, 2026. Branch: `project-expansion`.

## Current status

This branch preserves the initial multi-picker implementation and its exploratory experiments. It is a work-in-progress research snapshot, not a validated production scheduler or a final algorithm recommendation.

현재 상태: 다중 작업자 시뮬레이터의 초기 구현과 실험 자료를 보존했다. 후속 피드백에 따른 보완 구현과 재실험은 아직 완료되지 않았다.

Read this status before interpreting the [initial design and results](15-multi-picker-simulation.md). That report records the first implementation; the qualifications below supersede broader conclusions in that report.

## Preserved implementation and history

The implementation was recovered from the local `multi-picker-simulation` branch. Its history is preserved:

- `782cce6`: simulation package and 26 new correctness tests.
- `dea2f1b`: initial design document.
- `213a076`: exploratory experiment records and analysis.
- Base: `code-verification` at `ff03681`.

The existing `picking/` package was not changed by these three commits. PR #4's single-picker improvement code was reviewed by the original implementation; the extension implements its own routing context rather than importing that branch.

## What is implemented

- Configurable graph warehouse and a U-shaped conveyor represented by accessible boundary points.
- One, ten, or twenty pickers, with subsequent tasks starting at the preceding unloading location.
- Open-item collection at 10 seconds, wrapped-item collection at 30 seconds, a 40/60 item mix, and 5-second unloading.
- Spatial task chunks, balancing, and moves/swaps restricted to unissued work.
- NN, 2-opt, reinsertion, both application orders, alternating search, and an optional segment-DP candidate.
- Event simulation, pickup-zone capacity and FIFO waiting, and a sequential planning resource with precomputation.
- Measured computation-delay mode and fixed-delay reproducibility mode.
- Experiment CLI, analysis code, and saved exploratory results.

The default warehouse remains 36 by 40 metres. It does not yet establish performance in a large real warehouse. Shelf-side labels are synthetic, conveyor access is discretized, and aisle crossings do not impose delay. The current improvement budget is an evaluation-count limit, not a proven wall-clock deadline.

## Verification performed while preparing this branch

- Ran `python -m unittest discover -s tests`: **63 tests passed**, including the 37 baseline tests and 26 extension tests.
- Ran `python -m simulation selfcheck`: 26 sampled locations, maximum reported error 0 m under the default 2 m access spacing.
- Parsed the saved results: 504 main, 156 sensitivity, 54 per-picker, 24 congestion, 24 concentrated-congestion, and 24 stress records: **786 records in total**.
- Confirmed that `simulation/analysis.py` currently computes per-run percentage improvements and bootstraps their mean. It does not yet implement the requested ratio-of-summed-completion-times metric as the primary result.

The HTTP demo test initially encountered local execution restrictions. After allowing local HTTP and clearing the process's SSL key-log environment setting, the full suite passed without changing application code.

The 786 performance runs were inherited, not rerun during this publication task. Passing the current tests does not resolve the coverage gaps listed below.

## Interpretation of the initial results

The initial report records a mean per-run completion-time improvement of about 1.14% for `nn-reinsert-2opt` in a ten-picker evaluation condition. This is exploratory evidence tied to the existing seeds, warehouse, batching, and timing environment. It is not yet the requested primary aggregate improvement metric.

The 240-request, 12-request-per-task main condition can yield only 20 task bundles. With 20 pickers, that does not adequately exercise repeated tasks and changing start positions. A lack of improvement there does not establish that route improvement is ineffective for twenty pickers in general.

Unchanged distances after heuristic search do not prove that NN routes are optimal. Explanations based on route density or chained starts need controlled comparisons before being presented as established causes.

Congestion-aware assignment remains an experimental candidate: the initial report records lower waiting in some stress conditions but inconsistent or worse overall completion times. It is not promoted as the preferred method. The segment-DP findings are likewise restricted to the measured setup.

## Required follow-up

### 1. Repeated tasks for twenty pickers

- [ ] Add enough requests to exercise multiple tasks per picker; report the distribution, not just the mean.
- [ ] Record initial versus subsequent tasks and start-location chaining.
- [ ] Separate fixed-total-demand, fixed-demand-per-picker, and repeated-task comparisons.
- [ ] Use identical request lists and item attributes within every paired algorithm comparison.

### 2. Correct the primary metric

- [ ] Report `100 * (sum(baseline completion times) - sum(candidate completion times)) / sum(baseline completion times)` for each homogeneous comparison cell.
- [ ] Also report the mean of paired per-run percentage improvements, under a different label.
- [ ] Bootstrap paired seed groups and recompute the primary ratio within every resample.
- [ ] Recalculate the inherited results and document any changes to the conclusions.
- [ ] Compare individual tasks only where the request bundles remain equivalent.

### 3. Establish practical value and timing stability

- [ ] Report seconds saved, absolute completion times, distance, waiting, computation and exposed planning delay.
- [ ] Repeat randomized method execution on the same workloads.
- [ ] Separate fixed-delay logic checks from machine-dependent measured timings.
- [ ] Expand the independent evaluation seed set after freezing development settings.
- [ ] Report deterioration and worst cases alongside average improvements.

### 4. Diagnose congestion-aware failures

- [ ] Trace predicted and realized completion/waiting, moves/swaps, and the final finishing picker.
- [ ] Check whether shorter waiting is offset by travel, load imbalance, shifted congestion, or forecast errors.
- [ ] Align candidate acceptance with the final objective and account for effects on other pickers.
- [ ] Preserve information availability: do not use actual future events in planning.
- [ ] Tune any correction on development data and evaluate it on separate seeds; retain negative results.

### 5. Strengthen correctness evidence

- [ ] Assert exactly zero extra planning wait when the plan is ready before work completes.
- [ ] Assert the exact excess delay when planning finishes late, including resource contention.
- [ ] Compare tiny exact solutions with enumeration and routing costs with hand calculations; do not confuse lower-bound checks with optimality proofs.
- [ ] Inject interruption at initialization, route improvement, reassignment, congestion evaluation, and final validation.
- [ ] Verify complete request ownership, preserved issued work, valid orders and paths, and discarded incomplete candidates.
- [ ] Verify event ordering, zone occupancy, FIFO waits and endpoint-cost updates.

### 6. Model coverage and documentation

- [ ] Check larger warehouse geometries and walking/picking-time sensitivity.
- [ ] Review the synthetic shelf-side and continuous-conveyor approximation assumptions.
- [ ] Separate observed facts, causal hypotheses, unmeasured claims and model assumptions in the final report.
- [ ] Update the design and result report after the checks above; do not label the extension complete before then.

## Reproduction

From the repository root with Python 3.12 and the standard library:

```text
python -m unittest discover -s tests
python -m simulation selfcheck
python -m simulation run --pickers 10 --combo nn-reinsert-2opt --seed 1
python -m simulation.analysis results/multi
```

To rerun the existing exploratory matrix, choose a new output directory:

```text
python -m simulation experiment --suite all --out results/multi-rerun
```

That command reproduces the existing matrix; it does not automatically implement the follow-up experimental design above. The separately saved stress results use [hot_congestion.py](../simulation/hot_congestion.py); inspect its output paths before running so the inherited evidence is preserved.

## Evidence index

- [Simulation source](../simulation/)
- [Extension tests](../tests/test_simulation.py)
- [Initial design and results](15-multi-picker-simulation.md)
- [Saved exploratory records](../results/multi/)
- [Current analysis](../simulation/analysis.py)

This branch publishes progress and its limitations. It does not create a PR or merge the extension into the baseline.
