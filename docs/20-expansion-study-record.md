# Expansion Study: Design, Implementation, Experiments and Closure

Recorded November 21, 2026. Branch: `project-expansion`.

## Scope decision

The user decided to end this project's expansion exploration without merging PR #7. Preserve the branch, all implementation commits, saved experiments, corrections and unresolved questions as a research prototype. The original single-picker project remains the main deliverable. Closing the PR is not a deletion of the branch or a claim that the exploratory results have no value.

This is the current interpretation of the study. Where earlier reports conflict with this record, use the qualifications here. All percentages below are saved-data observations, not measured field productivity.

## 1. Why the extension was proposed

The original project studies one picker visiting required locations and finishing at one fixed conveyor endpoint. Shared Dijkstra distances support exact and heuristic visit-order algorithms, with workload-based comparison of distance and computation cost.

The initial extension idea was a much larger warehouse floor with a U-shaped conveyor near three outer walls and an open fourth side, ten or twenty pickers, and limited crowding at popular pickup locations. Aisle interaction was expected to be modest but required review. The desired contribution was a demonstrated algorithmic improvement, not merely the ability to animate more people.

Discussion refined this into a joint batching, assignment, route-ordering and waiting problem with repeated tasks. The main objective changed from individual route length to episode completion: the time until the last required basket is unloaded.

The idea of finding the best available route under a computation budget was discussed as an objective refinement. It did not establish a strict real-time guarantee or replace the original project's scope by itself.

## 2. Agreed model and its provenance

### Requests, tasks and episodes

A request specifies a location, quantity and item handling type. A task is one picker's departure, collection and single unloading trip. An episode processes a finite shared request set across all pickers.

The system knows all requests before execution, allowing next-task preplanning. An issued task receives no new requests and cannot be reassigned while running. Moves/swaps affect unissued work only. Pickers independently start new tasks after unloading; there is no global round barrier.

The original request that no requests arrive during a task but further work follows completion was modeled as advance knowledge of a finite queue. This is an information-availability assumption, not proof of how an operational system reveals orders.

### Conveyor and starting positions

The user specified an approximately 1 m wide conveyor along three outer walls, with no designated unloading ports. Workers collect the whole assigned task before unloading once. The basic policy ends at the nearest accessible conveyor position along walkable aisles.

All pickers initially share a staging location. Each subsequent task starts at the preceding unloading position; coincident positions are allowed. Unloading takes five seconds and task completion occurs afterward. Empty baskets are assumed immediately available. Basket replenishment and conveyor transport/occupancy are excluded.

The implementation discretizes accessible boundary positions. It does not model unrestricted travel through shelves or over belts. The default graph is still 36 by 40 m, with ten vertical aisles and three cross aisles. Later tests include 76 by 80 m geometry with twenty vertical aisles and a variant with extra cross aisles. These are synthetic layouts, not measured Coupang floor plans. Width is a configuration/model concept, not a full physical crowd simulation.

### Handling times and physical assumptions

- User-specified easy item collection: 10 seconds.
- User-specified wrapped item opening plus collection: 30 seconds, not 30 plus 10.
- Default easy/wrapped mix: 40/60, expected 22 seconds per item.
- Repeated requests at one position share a visit within a task; item handling times add.
- Walking speed 1.0 m/s is a model assumption. A 0.7 m/s case is a sensitivity condition.
- Every task is assumed to fit a basket; physical weight/volume constraints are absent.

The request cap is not an item-unit or distinct-location cap. Reconstructed cap24 workloads have a reported median of about 32 item units and nine unique locations per task. These statistics do not establish that such baskets are feasible in the field.

### Congestion

The intended pickup zone is one shelf side of an aisle over a 4 m segment, with three simultaneous collectors. Excess arrivals wait FIFO, worker ID breaks arrival ties, and completed service frees capacity before same-time arrivals are admitted.

The synthetic graph lacks real shelf-side data; the implementation assigns a side from location parity. This can make default zones effectively location-sized. Waiting workers do not block traffic. Two-way passing is assumed; edge overlap is observed, but aisle collisions, detours and single-person passages are not simulated.

The three-person rule limits active collectors, not all people physically near a shelf. Port queues, basket capacity and conveyor congestion are separate omitted constraints.

## 3. Algorithm and simulator architecture

- `warehouse.py`: graph construction, conveyor access, aisle distance/path calculations and pickup-zone identifiers.
- `requests.py`: seeded request generation and item properties.
- `config.py`: geometry, handling times, task caps, search settings and simulation timing mode.
- `routes.py`: NN, 2-opt, reinsertion, alternating improvement and segment DP with variable start and conveyor termination costs.
- `assignment.py`: coordinate chunks, round-robin reference, balancing, inter-task moves/swaps, congestion forecasts, savings bundling and completion scheduling.
- `planner.py`: initial grouping/assignment, route computation, timing and valid-plan ownership.
- `simulator.py`: event ordering, issued work, pickup queues, next-task release, planning resource and logged metrics.
- `lns.py`: experimental destroy/repair search with request ownership and cap checks.
- `experiments2.py`, `experiments3.py`, `experiments4.py`: successive saved experiment matrices.
- `analysis2.py`, `analysis3.py`, `bottleneck.py`, `verify_claims.py`: analysis and claim checks.
- `archive_summary.py`: this archive's inventory and paired round-four reaggregation; it runs no simulation.

The original `picking/` package remains unchanged relative to the expansion base. Single-picker code in PR #4 was reviewed for semantics; the extension has its own route context instead of depending on that unmerged branch.

The common routing sequence is NN followed by local improvement. Reinsertion moves one visit among all insertion positions; 2-opt reverses a route segment. A window-DP candidate exactly optimizes its internal visits conditional on fixed boundaries. None proves global optimality of a multi-picker schedule.

The event simulator has one sequential planning resource. The first planning delay is exposed; subsequent computation overlaps current work where possible. Fixed mode supplies model delays; measured mode exposes machine-dependent wall time. Evaluation-count search limits and cooperative checkpoints are not strict deadlines.

## 4. Research stages and development history

### Stage A: extension design and first implementation

The [tracked plan](17-expansion-plan.md) defines the problem, inputs/outputs, routing combinations, assignment changes, pickup queues, time accounting, comparisons and implementation sequence. Initial implementation added spatial chunks, balancing, NN/local improvement, inter-task changes, congestion estimation and event simulation.

The first suite comprised 37 baseline plus 26 extension tests. A first exploratory matrix preserved 786 records. The review found that the 240-request, cap12, twenty-picker condition supplies only twenty bundles, so it does not exercise repeated tasks. It also found that mean per-run improvement had been presented without the requested aggregate-ratio distinction.

The original report's assertion that unchanged NN routes were optimal was withdrawn. Failed improvement search does not prove optimality.

### Stage B: correctness defect and follow-up evidence

Strengthened timing tests found overlapping planning operations despite the intended single planning resource. The fix marks that resource occupied until the operation ends. Task/picker records had also not been persisted in the first dataset; the writer was updated.

Congestion v1 assumed simultaneous starts and added estimated waiting into an inconsistent score. V2 uses staggered LPT-based start estimates and lexicographic predicted completion/wait/distance evaluation. Checkpoints, candidate discard and adoption logging were strengthened.

Eleven additional tests brought the suite to 74. The follow-up matrix contains 474 records. Dual-formula analysis separates aggregate completion improvement from the mean per-run improvement and bootstraps paired seed groups using each formula.

Integration corrected second-round rows being labeled as first-round defective data, distinguished summed chained starts from per-run means, and downgraded positive-only waiting/distance comparisons from causal proof to descriptive observations.

### Stage C: bottleneck-led search and cap24 result

The study shifted from adding heuristics to identifying what determines completion. Handling time dominated travel in the examined default workloads. Aggregate worker time was useful diagnostically, but must not be equated with elapsed makespan.

Round-robin was added as a weak reference. Existing `balanced` reduces independent task-time dispersion; it does not fully forecast worker availability and successive starts. Route combinations, task caps 6/12/24, moves/swaps, conditional congestion and one-step unloading lookahead were screened.

A plumbing defect initially left lookahead disabled because its flag was not forwarded through `make_run_args`. A zero-decision trace exposed it; the flag and prerouted-task selection were corrected. After activation, lookahead had small, inconsistent benefits and was not selected. Inter-task moves and congestion/auto did not establish stable additional value.

The screened candidate C3 was cap24 plus coordinate chunks/balancing and NN → 2-opt → reinsertion, with moves/swaps, congestion and lookahead off. Development settings were frozen before the recorded third-round comparison. Tests increased to 80.

### Stage D: claim verification and unmet criteria

Saved-data verification checked cap semantics, component differences, twenty-picker records and computation budgets. The central change was interpretive: the reported distance/time improvements did not imply that every predeclared success condition had passed.

The 15-second planning-cost threshold was exceeded in some third-round cases (reported maxima about 21.2 s at ten pickers and 35.5 s at one picker). The worker-summed planning-wait/makespan diagnostic reached about 8.27%; that ratio is not the fraction by which the episode was delayed. The earlier blanket budget-success claim was incorrect.

The '99% contribution' wording was corrected: along the tested ladder, cap expansion accounts for approximately 3.81 percentage points of a 3.84% common-baseline improvement. This is sequence-dependent attribution, not a unique causal decomposition.

### Stage E: savings bundling, completion scheduling and limited LNS

The next implementation targeted batch structure and assignment rather than longer route search. Savings bundling groups identical positions and merges candidates using approximate route/unloading savings, with candidate pruning and a virtual staging start. It performed poorly in the saved development conditions, where tightly packed groups were unbalanced in size/work.

Completion scheduling predicts worker availability and previous unloading position and assigns tasks by predicted finish. Its named-worker assignment is respected by the simulator. It is meaningfully different from the earlier independent-time balancing rule.

The experimental variable-batch rule only splits when the number of tasks is below the number of pickers. It is not a fully adaptive task-duration batching policy. Its trigger did not fire in the saved evaluation; effectiveness is untested there.

Limited LNS removes requests and repairs batches using predicted completion, caps, iteration and wall-time checks. The implementation includes estimate caching. A development report describes incremental repair; the preserved `lns.py` still calls `expected_makespan` for insertion candidates. Do not repeat the stronger efficiency claim without checking actual call counts.

The suite increased to 88 tests. Twenty development and 360 follow-up comparison records were preserved. Completion scheduling showed conditional benefits; savings was rejected within the development screen, while variable splitting and LNS did not establish an additional execution-time benefit.

### Stage F: archive and stop decision

The user chose to retain this as extension potential and a documented research prototype, rather than spend the remaining project time seeking a broadly valid improvement. The subsequent packaging imports all remaining local commits, preserves the raw records, corrects interpretation and closes PR #7 without merging it. No new performance simulations are part of packaging.

## 5. Evidence inventory

| Dataset | Records | Role |
|---|---:|---|
| `results/multi/` | 786 | First implementation: 762 JSONL plus 24 in a stress JSON array; planner defect present |
| `results/multi2/` | 474 | Serialization fix, repeated-task checks, dual formulas and congestion v1/v2 |
| `results/multi3-dev/` | 220 | Task-cap and component development screen |
| `results/multi3-eval/` | 420 | Ladder, larger layouts and workload variants |
| `results/multi4-dev/` | 20 | Savings/completion/LNS development screen |
| `results/multi4-eval/` | 360 | 240 fixed-mode and 120 measured-mode comparisons |
| **Total saved records** | **2,280** | Not 2,280 independent workloads or repeated timing trials |

[Archive summary and file checksums](../results/expansion-archive-summary.json) identify raw files, counts and saved-data round-four comparisons. SHA-256 digests normalize CRLF to LF for cross-platform comparison. Test counts are not part of the experiment-record count.

The first round is historical only: a shared scheduling defect can influence competing algorithms differently. Do not reuse its absolute times or rankings as current evidence.

The second through fourth rounds reuse evaluation seed IDs 203,205,…,221 in successive analyses. Reusing seed IDs does not necessarily produce identical requests when geometry or demand changes, but familiar settings and results have been observed. The later rounds are held-out from their stated local development subset, not a fresh project-wide independent test. A final novel-seed evaluation was not completed.

Imported reports contain inconsistent date labels, including a future November 22 label in document 19. This archive records integration on November 21 using client time. Imported timestamps/labels alone do not establish experiment execution dates; the commit chain and record provenance are the reproducible reference.

## 6. Results that can be reported, with conditions

### Repeated-task checks after the scheduler fix

At twenty pickers, cap12 and request counts 240/480/960 yield one/two/four tasks per picker in the recorded NN conditions. At 480 requests the saved aggregate estimates include about +0.23% in fixed mode and +0.27–0.30% for measured local-improvement comparisons. At 960 requests the fixed estimate is about +0.06%, with an interval containing zero.

This corrects the original one-task-only evaluation gap. It does not establish that two or more tasks guarantees improvement or that a one-task route cannot improve.

### Cap24 versus cap12 in round three

The reported ten-picker, 480-request, default-layout comparison is approximately **+3.84% and 64.7 seconds per run** versus cap12/spatial/NN. Its common-baseline ladder gives cap expansion +3.807 percentage points, balance -0.081 and routing +0.112. Describe the result as batch-configuration improvement with a small route-improvement increment, not a 3.84% contribution from 2-opt alone.

The large-layout, 960-request comparison reports approximately **+10.94% and 422 seconds**; an added-cross-aisle variant reports +10.47%. Both compare algorithms within the same condition. Default-versus-large comparisons also change demand, density and task counts, so 'warehouse size caused the increase' remains a hypothesis.

At twenty pickers and 480 requests C3 worsens completion by about 2.28%, while reducing distance. The task distribution, balance and planning delay change together. No controlled attribution to chained-start loss alone was established.

### Completion scheduling versus the cap24 candidate in round four

The following values were reaggregated from saved records during archiving; no simulation was rerun. Baseline S1-C3 and candidate S3b share cap24/chunk construction and NN → 2-opt → reinsertion; assignment changes from balanced to completion. Moves/swaps, congestion and lookahead are off.

| Condition | Fixed-mode aggregate change | Measured-mode aggregate change |
|---|---|---|
| Default layout, ten pickers, 480 requests | **+0.845%, 13.6 s**; bootstrap interval approximately 0.30–1.33% | **+2.912%, 47.4 s** |
| Large layout, ten pickers, 960 requests | **+0.574%, 19.6 s**; interval approximately 0.02–1.10% | **+1.724%, 59.4 s** |
| Twenty pickers, 960 requests | +0.228%, 3.6 s; interval includes zero | +2.034%, 32.6 s |
| Twenty pickers, 480 requests | **-4.865%, 42.8 s worse** | **-3.363%, 30.0 s worse** |

Fixed and measured modes have different time models; do not merge their percentages or interpret their difference as a clean causal estimate of computational savings. Repeated same-input machine timing is absent. Each recorded method-condition uses ten seed cases.

The measured large-layout candidate reaches about **79.4 seconds** of planning wall time. A similar cost in the baseline does not waive the predeclared 15-second criterion. These observations therefore do not satisfy the full performance-and-budget target.

### Negative and inconclusive observations

- Congestion v2: lower waiting/forecast error in some cases but unstable completion; in the second-round evaluation mean per-run change is about +0.12% at ten and -2.97% at twenty pickers. Distance changes are -4 and +7 m respectively, not universally lower.
- Conditional congestion: thresholds did not produce a stable successful selector in the tested screen.
- Lookahead unloading: activated after fixing flag/candidate handling, but small inconsistent extra benefit in tested conditions; not a general failure proof.
- Savings bundling: roughly -19.7% with balanced assignment and -12.0% with completion in the development screen, versus the cap24 candidate; limited seeds and assumptions restrict generalization.
- Variable splitting: inactive in evaluated conditions. Call this **not evaluated**, not 'proved ineffective'.
- LNS: saved fixed-mode S4b results match S3b, but this does not establish LNS's algorithmic ineffectiveness. End-to-end propagation and planning/execution alignment need inspection.

## 7. Outstanding implementation risks found in archive review

This packaging does not attempt new optimization or silently repair prototype semantics.

In `Planner.initial_plan`, completion scheduling produces an ordered group list and `assign` before optional LNS. LNS can then replace groups without recomputing that assignment. This is a static consistency risk; no claim is made that it caused all unchanged saved outcomes. In `lns_improve`, `completion_schedule` returns an order along with assignment/finish values, but bottleneck selection uses finish indices against another list order. That mapping also requires explicit validation.

The broad `except Exception` in the LNS prototype can turn unexpected errors into abort statistics, so a returned valid plan is not proof that the intended neighborhood ran successfully. Wall-time checks at iteration boundaries are cooperative and can overshoot during expensive repair. A claim that LNS was end-to-end disproved would therefore be unjustified.

These risks are preserved and disclosed, rather than fixed with unmeasured consequences while closing the study. Confirm changed request groups, named owners, final issued tasks and exception causes before any future LNS evaluation.

The stored `claim-verification.txt` contains corrupted non-ASCII text in the imported artifact. Preserve it as supplied; prefer the readable numeric archive summary, source script and contextual report. Do not treat its damaged labels as additional evidence. `verify_claims.py` writes to that artifact's fixed path, so do not run it blindly over the archive.

## 8. Measurements, claims and corrections

Use aggregate ratio `100 * (sum baseline completion - sum candidate completion) / sum baseline completion` within homogeneous paired cells. Report mean per-run percentages separately. Bootstrap seed groups and recompute the chosen formula in each resample; seeds are not multiplied into independent samples by rerunning timings.

Worker-summed waiting is a worker-time diagnostic. Dividing it by one elapsed makespan does not give the fraction of elapsed time directly caused by planning. Explain overlap and last-finisher exposure separately.

Do not assert:

- All budgets passed because net completion improved.
- A defect common to both methods cancels out.
- NN is optimal because local search did not change it.
- Every multi-task case improves, or one-task cases cannot improve.
- Larger warehouses necessarily increase the benefit.
- Exactly 99% of effect is an order-independent causal contribution of cap24.
- Twenty-four requests are twenty-four units or physical proof of basket feasibility.
- An inactive feature was evaluated and rejected.
- LNS unchanged completion proves no useful LNS exists.
- Evaluation seeds reused across rounds are a fresh independent final test.
- Simulated percentages are measured real-facility productivity gains.

## 9. Complete commit trail and artifact map

| Commit(s) | Development step |
|---|---|
| `ff03681` | Expansion base on code-verification |
| `782cce6`, `dea2f1b`, `213a076` | Initial simulator, design and first experiment archive |
| `914c9a8`, `4b43d61` | Status and tracked plan; PR #5 replaced by #7 |
| source `371df70` → `81a0a68` | Serialization fix, congestion v2, checkpoints and stronger tests |
| source `61d49ba` → `028bf35` | 474 follow-up records and dual-formula analysis |
| `340db77` | Integration corrections, status and interpretation |
| `5b9ca79` | Baselines, lookahead, auto congestion and development screen |
| `3f865d1` | Third-round comparison records and report 18 |
| `c693cee` | Claim verification and partial interpretation corrections |
| `c5e8df3` | Completion/savings/LNS implementation, fourth-round evidence and report 19 |

The last four commits were imported by fast-forward so their IDs and parent history are preserved. Additional archive documentation is a later commit on this branch. Original author-provided reports are evidence of reported work; present integration statements are limited to checks actually performed here.

Read documents in this order:

1. This archive for the current conclusion and complete progression.
2. [Status](16-project-expansion-status.md) for concise closure status.
3. [Plan](17-expansion-plan.md) for the target specification, not universal completion.
4. [Initial model and follow-up](15-multi-picker-simulation.md).
5. [Batch-size experiments](18-evidence-experiments.md).
6. [Completion/savings/LNS experiments](19-completion-assignment-lns.md).

Raw records are in `results/multi*`; test implementation is `tests/test_simulation.py`; CLI starts in `simulation/__main__.py`. Keep these separate from the baseline's `results/full` and original single-picker conclusions.

## 10. Checks performed during final packaging

- Imported the four local commits through `c5e8df333b963271b31eb48b7172d336ab4b8907` without duplicate application.
- Ran the full suite: **88 tests passed** (37 baseline and 51 extension tests).
- Parsed all six round directories and the first-round stress array: **2,280 experiment records**.
- Ran saved-data archive reaggregation for paired fourth-round comparisons and disclosed reused evaluation seed IDs.
- Checked documentation links, source syntax and diff whitespace before publication.
- Did not run new optimization experiments, parameter searches, novel-seed evaluations or repeated timing trials.

Passing tests does not erase the identified LNS mapping risks, model omissions, budget failures or final-evaluation limitations. Original performance environments were reported by their producer; this packaging does not independently certify their wall-clock timing or date labels.

## 11. What would be required to resume

No further experiments are required merely to preserve and describe this exploratory study. If the team later wants a stronger performance claim:

1. Fix and test LNS group/order/owner propagation and expose unexpected failures.
2. Set a realistic physical basket constraint or clearly continue with an unlimited-basket abstraction.
3. Freeze endpoint, batching, assignment, information and computation-budget policies.
4. Measure stage costs; reduce duplicate work or search before considering parallel planning.
5. Repeat same-input timings and report exposed delay separately from summed worker waiting.
6. Use new evaluation seeds; validate any task-per-worker application rule without selecting it on the test results.
7. Isolate geometry from demand/density when investigating warehouse-scale causes.
8. Trace congestion/LNS accepted predictions into actual issued tasks and downstream events.

Keep full ALNS, regret insertion, physical aisle avoidance, learned selectors, conveyor capacity and multi-stop unloading as future proposals, not completed features. The original discussion also proposed VNS-style multi-neighborhood search and batching/assignment interaction studies; only the concrete implemented neighborhoods listed above are claimed here.

## 12. Final project positioning

Recommended report wording:

> We designed and implemented a multi-picker extension with continuous conveyor access, repeated tasks and pickup-zone waiting. Exploratory synthetic experiments observed conditional gains from larger spatial batches and availability-aware assignment. Some worker/demand conditions worsened, computation budgets were exceeded, and fresh independent validation and repeated timing were not completed. We therefore preserve the extension as a research prototype and future direction, rather than a generally validated scheduling recommendation. The original single-picker study remains the primary project contribution.

This is a scope decision, not proof that multi-picker optimization is impossible. Time spent using AI is development context, not an algorithmic lower bound or a performance measure.
