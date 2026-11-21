# 15. Continuous Multi-Picker Simulation: Design and Experiments

> **Exploration closed; records preserved.** This document records the initial model and second-round follow-up. Read the [complete expansion record](20-expansion-study-record.md) for cumulative history and current interpretation. The final preserved suite has 88 tests; counts such as 74 below describe earlier stages. Saved data were checked without new performance simulations. General performance and budget compliance were not established.

Original report date: November 20, 2026. Implementation branch: `multi-picker-simulation`, based on `code-verification` at `ff03681`. Source: `simulation/`; tests: `tests/test_simulation.py`; follow-up data: `results/multi2/`; initial data preserved in `results/multi/`.

The original `picking/` package was unchanged. The extension runs separately through `python -m simulation ...`; the 37 baseline tests were retained.

## 1. Problem and units

- **Request:** a location, quantity and item handling types (easy collection or opening a wrapper).
- **Task:** one picker's departure from the previous unloading location, collection of all assigned requests and unloading at the nearest accessible conveyor position.
- **Episode:** completion of a finite request set by 1, 10 or 20 pickers through successive tasks. All requests are known in advance. Issued tasks cannot receive additions or be reassigned; moves/swaps affect unissued work only.

The default task cap is **12 requests**, with no default quantity cap. This is an initial synthetic setting, not a measured basket limit. At 240 requests it creates 20 tasks, insufficient to exercise repeated tasks with 20 pickers. Caps 8 and 16 would create 30 and 15 tasks. Section 9 separately examines 480 and 960 requests.

## 2. Warehouse and U-shaped conveyor

The default graph matches the baseline: ten vertical aisles spaced 4 m apart, nodes every 2 m in depth, three cross aisles at y=0/20/40, and dimensions 36 by 40 m. `WarehouseConfig` separates dimensions, aisle count and spacing.

- **Conveyor:** left (x=0), back (y=40) and right (x=36) boundaries, approximately 1 m wide, with the front open. No fixed ports; unloading takes five seconds at an accessible point.
- **No crossings:** the belt lies outside the boundary and graph edges follow aisle segments; geometric tests reject belt/shelf crossings.
- **Access approximation:** boundary access nodes are placed along adjacent aisles. Unloading cost is minimum traversable shortest-path distance. Default 2 m spacing matches graph nodes, giving zero error for those nodes. The stated general spacing-s bound is s/2; 3 m spacing was checked against a 0.5 m reference. Intermediate access nodes preserve existing node distances.
- **End cost:** `routes.RouteContext.cost` uses aisle distance and recalculates the conveyor cost if the final visit changes.

## 3. Handling, unloading and congestion assumptions

| Parameter | Value |
|---|---|
| Easy collection | 10 seconds per item; default share 40% |
| Wrapped collection | 30 seconds per item including opening and collection; share 60% |
| Unloading | 5 seconds after conveyor arrival |
| Pickup zone | One shelf side of an aisle over a 4 m segment |
| Concurrent service | At most 3 pickers; FIFO waiting, worker-ID arrival tie-break |
| Same-time events | Complete collection/unloading before admitting new service |

Multiple requests at the same position share one visit within a task; item handling times add. Item types are fixed in workload data for all paired methods.

**Synthetic side assumption:** the graph has no measured left/right shelf labels. Side alternates by `(y//2)%2`, with zone key `(aisle x, side, floor(y/L))`. Same-side neighbours are 4 m apart, so L=4 m is effectively location-level and L=8 m groups two same-side positions. Zone-length sensitivity studies reflect this granularity.

Assume two-way passing. Single-person aisles, blocked traffic and detour delays are excluded. Same/opposite-direction edge overlap is recorded only. Waiting workers do not block traffic. Basket capacity, empty-basket supply and conveyor transport/loading congestion are excluded.

**Walking speed 1.0 m/s is an assumption, not a field measurement.** A systematic distance-to-time sensitivity study was not completed at this stage.

## 4. Algorithms: distance preparation versus visit order

Preparation uses Dijkstra distances/paths, reusing `picking.distances.dijkstra`, plus conveyor end cost. Visit ordering is implemented in `simulation/routes.py`.

1. Prepare location distances, paths and conveyor end costs.
2. Spatial assignment: sort requests by `(x,y)` and split into capped consecutive chunks.
3. Balance: adjust chunk boundaries using NN travel plus collection-time estimates.
4. NN route with coordinate tie-breaks.
5. 2-opt first improvement with restart; reinsertion visits locations in pass-start order and chooses the best insertion for each.
6. Move/swap unissued requests to reduce predicted completion; exclude issued/reserved tasks.
7. Congestion-aware evaluation using predicted completion, waiting and distance lexicographically. Forecast overlap uses planning-time information only.

Compare `nn`, `nn-2opt`, `nn-reinsert`, `nn-2opt-reinsert`, `nn-reinsert-2opt`, and `alt` (alternate until no improvement or budget exhaustion). The later segment-DP candidate `nn-2opt-reinsert-segdp` uses windows of six, stride three, one sweep, final window included and boundary entry/exit costs.

The single-picker `improve_route` on `feature/two-stage-route` depends on a fixed-conveyor `DistanceTable`; this extension reused semantics rather than that implementation. Here each task may have a different preceding unload start and a final-visit-dependent conveyor endpoint.

## 5. Time simulation and computation budgets

The event heap orders by `(time, priority, sequence)` and processes movement, collection, waiting, unloading and task release. One non-preemptive sequential planner resource is intended.

- Include initial planning in episode time from t=0.
- Subsequent planning overlaps current work. Issuing ROUTE operations take priority over PREROUTE and IMPROVE. Ready plans create zero extra planning wait; late plans expose only their excess delay.
- `measured` uses real computation duration once; `fixed` uses configured delays for reproducibility. Physical simulation time and computer runtime are distinct.
- Forecasts do not read actual future congestion. Record predicted-versus-realized task completion.
- Secure a complete request partition first. Evaluate candidates on copies and commit atomically. On `BudgetExceeded` or changed targets, discard the candidate and retain a valid plan.

Later strengthened tests found and fixed a planner-occupancy defect in the initial version. Current resource handling marks the operation occupied through completion. Search count limits and cooperative checkpoints do not prove a strict wall-clock deadline.

## 6. Correctness checks at the follow-up stage

Initial extension tests: 26. Follow-up tests: 11. With 37 original tests, the then-current full suite **passed 74 tests** on Python 3.12.2; the final archive later reached 88.

Verified properties at this stage included:

- Request ownership exactly once before/after improvement and interruption.
- Duplicate-location visit merging with summed handling time, checked by hand.
- Route-distance consistency and zero prediction error in a no-congestion single-picker case.
- Conveyor approximation bound, intermediate-node distance preservation and geometric no-crossing checks.
- Exact 10/30-second collection and five-second unloading in hand-calculated makespan cases.
- Zone capacity, FIFO and completion-first ties; a four-picker example checks ten seconds of waiting.
- Shared first start and subsequent starts from recorded unload positions.
- Exact planning overlap/late-delay and sequential resource cases strengthened in the follow-up.
- Empty episode (zero makespan), simultaneous events and invalid coordinates producing `ValueError`.
- Valid-plan preservation under evaluation/interruption limits and fixed-mode replay equality.
- Issued-work exclusion and congestion-mode partition invariants.
- Tiny exhaustive route comparisons, whole-route agreement for small segment-DP cases, and no worsening relative to NN in examined cases.
- Alternating-search termination/idempotence and updated end cost after changing the last visit.
- Concentrated-demand stress with positive waiting and prediction error.
- Original single-picker regressions and direct `picking` execution.

These tests verify specific cases, not all schedules or every interruption point.

## 7. Initial experiment design

Workload fields include size, spatial pattern, start/conveyor relationships, item mix (`easy_ratio`), hotspot share (`hot_aisle_share`), duplicate share, task-time imbalance and chained start locations.

Initial factor studies used wrapped shares 30/60/90%, zone lengths 2/4/8 m, capacities 2/3/4 and a small zone-length/capacity interaction. This is not a full Cartesian product.

Compare assignment (`spatial`/`balanced`), route combinations and congestion awareness while using identical requests, handling types and physical queue rules. The U-shaped conveyor is the extension's base setting rather than an isolated factor in these runs.

Separate fixed total demand R=240 from fixed per-picker demand (24 times picker count). Initial development/evaluation used six even/six odd seed groups. Record randomized execution order, status, makespan, distance, waiting, imbalance, idle time, planning cost/delay, validity and budget outcomes. Later rounds reused evaluation IDs; see the final archive for qualifications.

## 8. References versus assumptions

The original report referred to a [field account](https://m.blog.naver.com/skantlrpp/222902163328) for tote-to-conveyor workflow, a [process overview](https://namu.wiki/w/%EC%BF%A0%ED%8C%A1%ED%92%80%ED%95%84%EB%A8%BC%ED%8A%B8%EC%84%9C%EB%B9%84%EC%8A%A4/%EA%B3%B5%EC%A0%95) and the [Coupang newsroom](https://news.coupang.com/archives/19485) for examples of automation. Those references are contextual, not measured layout or timing calibration.

The U shape, 1 m width, unrestricted accessible unloading, 10/30-second handling, five-second unloading, 4 m/three-picker zones, 1.0 m/s speed and two-person passing are model assumptions. This is **not a replica of an actual centre**, and simulated gains are not measured field productivity.

## 9. Follow-up results

Round one (`results/multi`, 786 records) predates the planner-serialization fix. It is historical; even relative rankings need not survive a shared defect. Current comparisons at this stage use `results/multi2`, 474 runs: fixed-total 126, per-picker 84, continuous20 84, fixed20 84 and congestion 96.

The producing environment was reported as Windows 10 and Python 3.12.2, code `371df70` or later. Evaluation used ten odd seeds 203-221 and development used four to six groups, with randomized order.

```text
python -I simulation/analysis2.py results/multi2
```

### Two improvement formulas

- Primary aggregate: `100 * (sum baseline completion - sum candidate completion) / sum baseline completion`.
- Secondary: mean paired per-run percentage improvement.
- Bootstrap seed groups and recompute each formula within every resample. Keep condition cells separate and do not interchange their intervals.

### Twenty-picker repeated tasks

NN task records show:

| Requests | Tasks per run | Tasks per picker: min/median/max | Chained starts per run | Idle pickers |
|---|---:|---|---:|---:|
| 240 | 20 | 1/1/1 | 0 | 0 |
| 480 | 40 | 2/2/2 | 20 | 0 |
| 960 | 80 | 4/4/4 | 60 | 0 |

At R=240 fixed-mode completion improvement is zero (0 improved, 10 tied, 0 worse); measured improvement is about -0.02%. This isolates the earlier lack of repeated tasks, not route optimality.

At R=480, aggregate evaluation estimates are fixed +0.23% [0.05,0.55], measured alternating +0.30% [0.13,0.52] and measured `nn-2opt-reinsert` +0.27% [0.09,0.48]. At R=960 fixed is +0.06% [-0.17,0.26], while measured is approximately zero. A more balanced repeated-work allocation is a possible explanation, not an established cause.

Do not infer that repeated tasks always help or a single task cannot improve.

### Separate comparison designs

- Fixed demand R=480, p=5/10/20: mixed results, development -0.28 to +0.18%, evaluation +0.09 to +0.67%.
- Fixed per-picker demand of 48 requests (four tasks): evaluation approximately +0.67/+0.09/-0.00% for p=5/10/20. Parallel dilution is an interpretation requiring caution.
- Repeated-task comparison at p=20, R=240/480/960: use the table above. Do not pair different demand volumes as if they were identical workloads.

### Routing versus computation delay

Fixed mode supports an R=480 route-related benefit under fixed computation delays. Measured mode also exposes sequential planning waits. At p=20/R=960, summed worker planning wait averages 209.9 seconds versus 2.35 seconds in fixed mode. This is worker-time, not an additional elapsed 209.9 seconds to add to makespan. Causal contributions to runtime variation remain unresolved; worst observed deterioration was -1.36%.

### Absolute example

Evaluation p=20/R=480, measured `nn-2opt-reinsert`, ten seeds: NN completion 869.8 seconds versus 867.5, a 2.3-second mean saving; distance 2076 to 2057 m; no zone wait; 7 improved/0 tied/3 worse; worst -0.12% at seed 211. Measured planning is 5.68 seconds, exposed planning delay 3.48 and summed worker planning wait 69.2.

### Congestion v1 and v2

Stress: hotspot 0.8, duplicates 0.3, zone length 8 m, capacity two; six development and ten evaluation groups.

| Method / population | Mean per-run completion improvement | Waiting saving (positive means less) | Distance change (positive means more) | Prediction MAE |
|---|---|---|---|---|
| v1 evaluation p10 / p20 | -5.07% / -3.76% | -20 / +48 s | +18 / +26 m | Condition-dependent |
| v2 evaluation p10 / p20 | +0.12% / -2.97% | +54 / +61 s | -4 / +7 m | 8.6 to 5.9 / 34.8 to 31.8 s |
| v2 development p10 / p20 | -0.42% / -12.62% | +54 / -65 s | -25 / -2 m | Improved or similar |

V1's simultaneous-start approximation and additive objective differed from the intended completion/wait/distance order. V2 corrects the evaluation structure and staggers start forecasts. Its evaluation waiting and prediction errors improve, but distance does not improve in every condition, and development p20 deteriorates. Stable completion gains remain unestablished; evaluation p20's worst case is -14.15%.

Some workers wait less while others wait more; the last finisher can wait longer. These are observations, not causal proof. Summing positive waiting reductions and positive distance increases across different cases cannot establish why makespan worsened. Adoption-to-execution matching remains needed.

Keep v2 experimental and congestion off by default until stable benefit is verified.

### Historical reanalysis

Run `python -I simulation/analysis2.py results/multi` separately; see [historical output](../results/multi/analysis2-historical.txt). A label bug that treated second-round per-picker rows as first-round evidence was corrected. The old 1.14% ten-picker/balanced claim is retained as a pre-fix per-run observation, not a current selection basis.

## 10. Remaining limitations at this stage

- Historical README wording called the UI planned despite an implemented local demo; the branch's current header clarifies this.
- Synthetic side assignment lacks real shelf-side data.
- Walking, unloading and collection-time sensitivity was incomplete.
- Aisle interaction is observed but does not affect schedules.
- Congestion forecasts use planning-time overlap estimates without learning/updating from observed errors.
- Measured planning times depend on the machine.

Later experiments and closure do not remove these assumptions; read the final study record for the current conclusions.
