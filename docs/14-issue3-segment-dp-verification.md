# Issue 3: Segment DP Verification

Prepared on November 18, 2026 from the supplied verification report, its independent reproduction script, and the available task-level outputs.

## Verification scope

The review covers reproduction of the development counts, fixed-boundary segment optimization, sweep coverage, route-distance checks, and comparison with a one-pass reinsertion search. The repository implementation used by the reproduction is `9c03abd`, with the same tree as `Sichan` at `7a9ab03`.

검증 범위는 구간 DP의 예비 수치 재현, 구간 경계와 순회 방식, 경로 검증, 시간 중단 처리, 재삽입 탐색과의 비용·효과 비교입니다.

The numerical tables below were checked against the available per-task JSONL outputs during preparation of this document. The complete performance experiment was not rerun during this documentation task. The implementation and measurements are an independent reproduction of the issue specification. The issue author's prototype source and per-task measurements were unavailable to that review.

[Issue 3](https://github.com/apple4232/Team_A3_Algorithm-project/issues/3) · [Reproduction script](../verification/issue3/issue3_verify.py) · [Environment](../verification/issue3/environment.json)

## Setup and evidence

The independent run used Windows with Python 3.12.2. Segment size was 6, stride was 3, and the route was swept once. Each pipeline had a cooperative 200 ms budget, starting before task preparation and ending after reconstruction and validation on the normal return path.

The inputs were the repository's saved workloads. Development reproduction used 675 large tasks, with 225 each at n=15, 20, and 50. Evaluation reused the existing 2,025 evaluation tasks, including the 675 large tasks. These are distinct from the development groups, while remaining previously inspected evaluation data.

The reproduction ran each main task-method pair once. A separate timing sample repeated 25 development tasks 20 times. The reported timing-stability p95 is a percentile across task-level medians, while the main tables report per-run p95.

Evidence is available in [verification/issue3](../verification/issue3/). The development file contains 1,350 rows and the evaluation file 4,725 rows. The original summary exports contained consecutive JSON objects. Their published copies are valid JSON arrays preserving the values. Task-level files and the script were copied byte-for-byte, and [SHA-256 checksums](../verification/issue3/sha256.json) identify the published files.

## 1. Development result reproduction

The reproduced NN+2-opt baseline distances matched the stored development baseline for all 675 large tasks, as recorded in the supplied review. The copied task records reproduce the following improvement counts and mean savings, including unchanged tasks.

| Locations | Improved / attempted | Unchanged | Mean saving across all tasks | Mean saving among improved tasks |
|---|---:|---:|---:|---:|
| 15 | 39 / 225 | 186 | 1.2978 m | 7.4872 m |
| 20 | 35 / 225 | 190 | 0.8711 m | 5.6000 m |
| 50 | 9 / 225 | 216 | 0.2667 m | 6.6667 m |

There were 83 improved tasks, 592 ties, and zero longer routes. The issue's rounded counts and distances are reproduced. Aggregate agreement does not establish task-by-task equivalence with the unavailable original prototype.

| Locations | NN+2-opt median | Segment DP median | NN+2-opt p95 | Segment DP p95 |
|---|---:|---:|---:|---:|
| 15 | 9.102 ms | 10.912 ms | 15.428 ms | 17.939 ms |
| 20 | 11.277 ms | 13.671 ms | 19.316 ms | 22.227 ms |
| 50 | 29.852 ms | 37.414 ms | 48.010 ms | 58.397 ms |

These timings belong to the independent Windows execution. Its code measures preprocessing, initial NN, 2-opt, segment search, and final reconstruction/validation. The original author's timing boundaries require the original source for direct verification.

[Development records](../verification/issue3/dev-repro.jsonl) · [Development summaries](../verification/issue3/dev-summary.json)

## 2. Correctness and interruption checks

`window_dp()` initializes each first visit with distance from the fixed left boundary and terminates with distance to the fixed right boundary. `segment_dp_pass()` also recomputes the full candidate route and accepts only a decrease greater than the numerical tolerance.

`window_starts()` includes the last window even when the stride does not land on it. For n=20 the starts are 0, 3, 6, 9, 12, 14. For n=50 the final start is 44. A task with at most six internal locations uses a single window.

The supplied microtest output records 124 window-DP comparisons with exhaustive search and zero mismatches. Forty cases with at most six locations agreed with full exact DP. Duplicate requests and requests at S/C were also exercised.

All 6,075 main task-method records have completed status, with zero recorded budget violations or distance-increase flags. The microtest's 0.5 ms interruption sample contains 20 cases ending before a route was secured.

Interruption coverage still needs strengthening. The supplied narrative also mentions a 32 ms sample, but that sample's task-level output is absent from the published evidence. In the reproduction script, the outer `DeadlineExceeded` handler can return a distance-only record without passing through the normal reconstruction and validation block. This record cannot demonstrate that a complete validated route was returned. Production integration must return the secured order/path and verify interruption after a route exists, during window search, and during finalization.

The existing repository request runner has its own behavior. The reproduction script's exact-method comparison also runs NN and 2-opt before full DP. Its timing therefore describes that reproduction pipeline.

[Microtest output](../verification/issue3/correctness-micro.json) · [Reproduction implementation](../verification/issue3/issue3_verify.py)

## 3. Evaluation against reinsertion

The comparison uses the same 675 large evaluation tasks. Positive savings below are relative to each pipeline's NN+2-opt baseline.

| Locations | Segment DP improved | Reinsertion improved | Segment DP mean saving | Reinsertion mean saving |
|---|---:|---:|---:|---:|
| 15 | 34 / 225 | 38 / 225 | 1.3689 m | 1.3333 m |
| 20 | 33 / 225 | 43 / 225 | 1.0667 m | 1.5467 m |
| 50 | 7 / 225 | 17 / 225 | 0.1956 m | 0.4444 m |
| All large tasks | 74 / 675 | 98 / 675 | 0.8770 m | 1.1081 m |

The stored seed-group bootstrap intervals for mean savings versus NN+2-opt are 0.6933–1.0667 m for segment DP and 0.8415–1.3748 m for reinsertion. These intervals describe each method versus the baseline. A direct paired interval is needed to quantify uncertainty in the difference between the two enhancements.

Against reinsertion on individual tasks, segment DP won 38 times, tied 584, and lost 53. Reinsertion was shorter by 0.2311 m on average. Median paired added time was 2.602 ms for segment DP and 0.683 ms for reinsertion.

| Locations | NN+2-opt median / p95 | Segment DP median / p95 | Reinsertion median / p95 |
|---|---:|---:|---:|
| 15 | 7.554 / 11.901 ms | 9.198 / 14.713 ms | 7.797 / 11.816 ms |
| 20 | 11.128 / 18.683 ms | 13.491 / 22.362 ms | 11.561 / 20.116 ms |
| 50 | 29.570 / 51.110 ms | 37.144 / 61.893 ms | 32.626 / 55.388 ms |

Under this single configuration, reinsertion has the more favorable observed average distance and added-time trade-off. The methods, settings, and execution environment define the scope of that observation.

[Evaluation records](../verification/issue3/eval-compare.jsonl) · [Evaluation summaries and intervals](../verification/issue3/eval-summary.json)

## 4. Whole-workload distance comparison

Combining full DP for the 1,350 small tasks with an enhancement for the 675 large tasks gives the following arithmetic policy-distance comparison.

| Route choice | Mean distance across 2,025 tasks |
|---|---:|
| NN+2-opt for every task | 168.2904 m |
| Full DP for small tasks, NN+2-opt for large tasks | 166.8642 m |
| Full DP for small tasks, segment DP enhancement for large tasks | 166.5719 m |
| Segment DP enhancement at every size | 167.2810 m |

Adding segment DP to the large-task branch saves another 0.2923 m per task across the workload. The copied runs supply these distances through separate pipelines. An integrated selector with end-to-end latency measurement remains a follow-up.

## 5. Follow-up requested

- Share the original prototype source, task-level records, and environment to enable direct comparison with the issue author's implementation.
- Integrate the enhancement with the request runner and exercise forced interruption after securing a route, preserving the returned order/path, status, and validation.
- Add a paired seed-group interval for segment DP versus reinsertion and compare repeated timings with randomized execution order.
- Freeze any changes to window size, stride, or pass count on development data, then use fresh evaluation groups for the final claim.
- Report both global distance and computation cost. The window optimum is conditional on its fixed boundaries.

The available evidence reproduces the issue's development improvement counts and shows additional distance reduction on evaluation tasks. In the measured comparison, one-pass reinsertion achieves greater average reduction with less added time. These findings support retaining it as a comparison baseline before choosing an enhancement for integration.
