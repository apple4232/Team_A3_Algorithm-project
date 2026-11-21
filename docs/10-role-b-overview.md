# Role B Overview: What Was Built and Why

## 1. The problem

A picker starts at **S**, visits every required item location, and finishes at conveyor **C**.

```text
Start S -> collect required items -> conveyor C
```

The visit order changes walking distance. The project asks:

> Which algorithm should be selected for a workload to obtain a shorter route within a limited computation time?

The value `n` counts distinct required locations, not item units. Several items at one location require one visit.

Role A provides the warehouse model and routing algorithms. **Role B generates workloads, compares those algorithms fairly, and interprets the results.**

## 2. Work completed in this stage

```text
Generate synthetic tasks
    -> calculate features
    -> run algorithms on identical tasks
    -> record distance, computation time and failures
    -> train selection rules on development data
    -> evaluate frozen rules on held-out data
    -> produce tables and plots
```

The implemented pipeline generated and tested **4,050 synthetic tasks**. These are computer-generated workloads, not orders collected from a real warehouse.

## 3. Workload conditions

The warehouse and conveyor remain fixed while item locations and starts vary, separating workload effects from layout changes.

| Variable | Settings | Purpose |
|---|---|---|
| Required locations | 3, 5, 7, 8, 10, 12, 15, 20, 50 | Compare runtime and route quality at different scales. |
| Spatial pattern | Clustered, Random-Stow-like, directional | Compare concentrated and distributed locations. |
| Start | Three positions near the front, centre and edge | Examine start-position effects on the same item set. |
| Conveyor relationship | Mirrored far/near item sets | Examine placement while retaining related inter-item structure. |

Clustered tasks draw locations from three adjacent aisles. Random-Stow-like tasks sample shelves throughout the warehouse; they do not reproduce a company's inventory policy. Directional tasks sample the rear area. Far/near pairs mirror locations left to right. Mirroring also changes start distances, so differences cannot be attributed solely to conveyor distance.

```text
9 sizes x (3 base patterns + 2 mirrored patterns) x 3 starts x 30 seeds
= 4,050 tasks
```

A seed initializes random generation. Matching seeds and configurations reproduce the same workloads and support later checking.

## 4. Why calculate features?

Selecting an algorithm requires a numerical or categorical description of the task.

| Feature | Meaning | Research question |
|---|---|---|
| `n` | Number of distinct required locations | How does exact-method cost grow with size? |
| `dispersion` | Mean distance between item locations | Does local improvement help dispersed tasks? |
| `start_mean` | Mean start-to-item distance | Does the start affect suitable routing choices? |
| `conveyor_mean` | Mean item-to-conveyor distance | Does the endpoint relationship affect routing? |
| `pattern` | Generator-assigned pattern | Do patterns capture differences beyond mean distances? |

Distances follow the shortest traversable aisle route, not straight lines through shelves. `pattern` is generator metadata; automatically inferring it from real order coordinates is not implemented.

## 5. Algorithms compared

| Method | Operation | Role |
|---|---|---|
| Given Order | Follow input order. | Simple reference, not measured human performance. |
| NN | Repeatedly visit the nearest remaining location. | Fast baseline. |
| Exhaustive Search | Check all visit orders. | Proves optimality when complete; factorial growth limits size. |
| DP | Reuse subproblem results to find an exact route. | Optimal when complete, with growing time and memory costs. |
| CA-plus / CA-minus | Combine next-visit distance with item-to-conveyor distance using opposite signs. | Test conveyor-aware directionality. |
| NN or CA + 2-opt | Improve an initial order by changing segments. | Measure distance gains against added computation. |

There are **nine candidates**, tested on identical tasks using common distance information where applicable.

The CA coefficient controls the weight of conveyor distance. The full experiment uses **0.5**, selected from values examined in a small development pilot. It is not claimed to be universally best.

## 6. Development and evaluation separation

Using evaluation answers to construct a rule would compromise evidence of generalization.

- **2,025 development tasks:** build and tune selection rules.
- **2,025 evaluation tasks:** apply frozen rules without modification.

Splits are grouped by seed. Related starts, sizes, patterns and mirror pairs remain together. The evaluation set contains **15 seed groups**, not 2,025 independent real orders. Uncertainty calculations respect those groups.

## 7. Two timing modes

### Candidate comparison

Prepare inter-location distances once, then let candidates use the same information. This isolates visit-order quality and computation from shared preparation.

### Full-request comparison

Measure input validation, distance preparation, algorithm execution and route reconstruction as an end-to-end request.

The request runner first secures an NN route as fallback. If DP times out, it may return NN instead:

```text
Requested method: DP
Requested-method status: timeout
Returned route: NN
```

Returning NN does not mean DP succeeded. Requested status, returned method and fallback use are recorded separately.

## 8. Why impose a time budget?

A short route may be impractical if planning takes too long. The exploratory budget is **0.2 seconds per request**, not a calibrated warehouse service requirement.

Candidate mode gives search 0.2 seconds after shared preparation. Request mode applies 0.2 seconds to the full request. Machine performance and other running work affect timing.

Timeouts and size-limit results remain in the records. Reporting only successful distances could make an unreliable method look better than it is.

## 9. Selection rules

Four policies were trained on development data:

1. Fixed algorithm for every task.
2. Count-based selection using `n`.
3. Numeric selection using `n`, dispersion and start/conveyor distances.
4. Numeric-plus-pattern selection.

The fixed policy selected **NN+2-opt**. The other three selected the same rule:

```text
At most 13 required locations -> DP
At least 14 required locations -> NN+2-opt
```

The stored split is `n <= 13.5`. This is a rule fitted to the development data and 0.2-second setting, not a universal boundary. Seed-group cross-validation was used within development before evaluation.

## 10. Reading the evaluation results

All four policies returned routes within the budget for the 2,025 evaluation tasks in this stage.

| Policy | Median route distance | Median full-request time |
|---|---:|---:|
| Always NN+2-opt | 156 m | About 2.41 ms |
| Count-based | 152 m | About 3.47 ms |
| Numeric features | 152 m | About 3.47 ms |
| Numeric features plus pattern | 152 m | About 3.48 ms |

A millisecond is one thousandth of a second. A median is the middle ordered observation.

Paired task comparison gives a **1.43 m mean saving** for the count rule over fixed NN+2-opt, with a **1.23–1.63 m** 95% seed-group bootstrap interval. Fifteen synthetic seed groups do not establish real-warehouse performance.

The difference of medians, `156 - 152 = 4 m`, differs from the mean paired saving of 1.43 m: these are different statistics.

Numeric-plus-pattern policies selected the same rule as count alone. **Additional features did not establish an improvement in this study.**

Exhaustive Search and DP agreed on 675 evaluation tasks where both completed. With the 0.2-second search budget, all 225 size-15 DP tasks timed out; sizes 20 and 50 hit configured size guards. Size 15 completed in a separate two-second memory sample. Distinguish time budgets from program size limits.

## 11. Files and execution

| Location | Responsibility |
|---|---|
| [workloads.py](../experiments/workloads.py) | Workloads and five features. |
| [benchmark.py](../experiments/benchmark.py) | Candidate and request measurements. |
| [analysis.py](../experiments/analysis.py) | Summaries and rule training. |
| [Experiment CLI](../experiments/__main__.py) | Generation, benchmarking, training and evaluation. |
| [Analysis scripts](../analysis/) | A–H comparisons, policy comparisons and memory samples. |
| [Experiment tests](../tests/test_experiments.py) | Generation, features, failure recording and evaluation separation. |
| [Full results](../results/full/) | Workloads, raw records, rules, tables and figures. |
| [Frozen rules](../results/full/rules.json) | Rules fixed before evaluation. |
| [Candidate plot](../results/full/eval-candidate.svg) | Candidate distances by size. |
| [Policy comparison](../results/full/eval-policy-comparison.json) | Paired policy results. |

See [experimental methods](08-role-b-experiments.md) and [results](09-role-b-results.md). Use a new output directory when rerunning because result files are protected against overwrite.

```bash
python3 -m unittest discover -s tests -v
```

At the time of this original Role B stage, **33 tests passed**. The recorded results folder was approximately 190 MB; coordinate storage practices with the team. These historical figures are not the final expansion test count.

## 12. Completed and remaining work at this stage

The offline pipeline covers generation, feature extraction, algorithm comparison, rule training, held-out evaluation and plots/tables.

The selector was not automatically integrated into the request runner. Evaluation prepared distances for features and again within the runner; service integration should remove duplicate work and remeasure full latency. A Streamlit UI was a separate proposed task at this stage; the repository subsequently gained a local demo.

Real warehouse data, other geometries, other budgets and more independent seed groups remain necessary for broader claims.
