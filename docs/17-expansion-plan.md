# Multi-Picker Simulation Expansion Plan

Recorded November 20, 2026. This document puts the expansion plan discussed in PR #5 into a tracked repository file. It describes intended behavior and acceptance criteria; inclusion here does not certify that every item is implemented or validated.

계획 문서를 저장소 파일로 추가했다. 초기 구현과 실험은 존재하지만 보완 검증은 남아 있다. 현재 완료 범위는 [진행 상황](16-project-expansion-status.md)을 우선 참조한다.

## 1. Objective and workflow

Extend the original single-picker, fixed-endpoint study to multiple pickers collecting assigned requests, unloading at a U-shaped conveyor, and starting subsequent tasks at their previous unloading positions.

The main objective is lower completion time for the entire finite request set, including exposed planning delay, pickup waiting, collection and unloading. Preserve travel distance and computation cost as additional measures.

Follow the sequence: freeze the model and experiment specification; implement and verify correctness; select candidates on development data; measure final effects on independent evaluation groups. Do not claim a globally optimal schedule or a proven real-world improvement.

## 2. Requests and continuous work

- A request identifies a pickup location, quantity and item handling types.
- A task contains one picker's assigned requests from departure to completed unloading.
- An episode completes the same finite request set across all pickers.
- Compare 1, 10 and 20 pickers. Initially all start at the same staging location.
- Each picker starts the next task independently after unloading, at the preceding unloading position.
- The system knows the full request list in advance. It may plan future tasks during current work, but cannot add requests to or reassign issued tasks.
- Move and swap only unissued requests. Each request must retain exactly one owner.
- Configure a task-size cap and report actual task counts per picker. Ensure repeated-task experiments really contain subsequent tasks, especially at 20 pickers.

Assume each issued task fits in one basket. No mid-task unloading or picker-to-picker transfer is allowed. Empty baskets are immediately available at the next starting point; replenishment is outside this model.

## 3. Warehouse and conveyor

Represent a conveyor approximately 1 m wide beside three outer walls, leaving the fourth side open. Unloading is allowed anywhere along its accessible inner boundary, without designated ports.

Walking follows connected aisles. Neither shelves nor the belt can be crossed. End cost is the shortest traversable distance from the final pickup to an accessible conveyor point, not Euclidean distance.

Keep geometry configurable and verify continuous-boundary representation or discretization error. Recompute end cost whenever the last visit changes. The default policy chooses the nearest unloading point for the current task; choosing a farther point to benefit future tasks is outside the initial policy.

Treat the model as a synthetic environment informed by field experience. Do not identify its geometry as a measured Coupang facility. The current 36 by 40 m implementation is an initial test environment; larger layouts require separate experiments.

## 4. Collection and unloading

- Easy item: 10 seconds, 40% of items by default.
- Wrapped item: 30 seconds including opening and collection, 60% by default.
- Expected default handling time: 22 seconds per item.
- Unloading: 5 seconds after conveyor arrival; completion occurs after this interval.
- Merge visits to the same location within a task, while summing item handling times.
- Keep item types identical across paired algorithm comparisons.

These are user-specified assumptions, not calibrated public statistics. Vary wrapped-item share at 30%, 60% and 90%, and assess walking/handling-time sensitivity before generalizing.

## 5. Pickup congestion

Use pickup-zone identifiers distinct from graph locations. The target model groups one shelf side of an aisle into 4 m segments, with at most three pickers collecting simultaneously per zone.

Queue excess arrivals FIFO, break simultaneous-arrival ties by picker ID, and release completed service before admitting new arrivals at the same timestamp. Occupancy lasts for the collection interval. Waiting does not block aisle traffic in this simplified model.

This limits concurrent collection, not the total physical crowd including waiting pickers. Assume two-way passing; exclude single-person aisles and detailed collision avoidance. Record aisle occupancy/overlap without inventing uncalibrated detour delays.

Explore zone lengths 2/4/8 m and capacities 2/3/4. The existing synthetic shelf-side labeling needs review; do not mistake it for measured shelf geometry.

## 6. Planning algorithms

Keep shortest-path preparation separate from visit ordering. Use Dijkstra for aisle distances and reconstruction; compute nearest-conveyor costs with an appropriate multi-source or equivalent graph method.

Compare distance-oriented assignment and workload-balanced assignment using predicted travel plus handling. Define request ordering and deterministic tie breaks. Review the existing spatial-chunk baseline against this intent.

With assignment held fixed, compare:

1. NN.
2. NN followed by 2-opt.
3. NN followed by reinsertion.
4. NN, 2-opt, then reinsertion.
5. NN, reinsertion, then 2-opt.
6. NN followed by alternating 2-opt and reinsertion until no improvement or budget exhaustion.

Reinsertion visits locations in the order captured at pass start and chooses the best improving insertion position for each. 2-opt uses a fixed candidate order and restarts after the first accepted improvement. Include end-position changes and their conveyor cost.

After basic correctness, evaluate segment DP as an additional candidate. Preserve fixed-boundary semantics and distinguish local exactness from whole-route optimality.

Add inter-picker moves/swaps of unissued requests, recalculating affected routes. Evaluate distance-oriented and congestion-aware policies separately. The latter prioritizes predicted episode completion, then waiting and distance, and must account for effects on other pickers.

## 7. Simulation, computation and interruption

Use event simulation for arrival, queue entry, collection start/end, unloading and task release. Use one sequential planning resource by default.

Include the first planning delay. For subsequent planning, charge only time exposed after a picker is ready: zero when the next plan is already ready, otherwise the exact excess delay including planner contention.

Separate physical simulation time from measured computer runtime. Provide fixed-delay mode for deterministic checks and measured mode for machine-specific timing. State whether warehouse preprocessing is charged or reused. Do not use actual future event outcomes in planning forecasts.

Secure a complete feasible plan first. Evaluate changes in a separate candidate and commit atomically only after ownership and route validation. Interruption must preserve issued work and the last complete valid plan. An evaluation-count cap is not a wall-clock guarantee; distinguish and test these limits.

## 8. Workloads and fair comparisons

Include request quantity, unique locations, dispersion, start/conveyor distances, spatial pattern, wrapping share, hotspot concentration, duplicate-location demand, workload imbalance, successive-task similarity and previous-unload-to-next-request distance.

Separate fixed-total-demand, demand-per-picker and repeated-task experiments. Separate conveyor layout, assignment, routing order, cross-picker reassignment and congestion-awareness effects. Evaluate all methods under the same physical congestion rules.

Compare fixed search effort and equal total planning-time budgets separately. Randomize method execution order and repeat timing measurements. Select settings on development groups and freeze them before evaluation with independent seed groups. Use factor-wise studies and selected interactions rather than an uncontrolled full product.

## 9. Metrics

The primary episode measure runs from initial planning start to final unloading completion. Within each homogeneous paired comparison, report:

`aggregate improvement (%) = 100 * (sum(baseline completion times) - sum(candidate completion times)) / sum(baseline completion times)`

Also report mean paired per-episode percentage improvement separately. Bootstrap paired seed groups and recalculate the aggregate ratio within each resample. Report task-level improvements only where bundles are equivalent.

Include absolute seconds saved, travel, waiting, imbalance, idle time, planning cost, exposed planning delay, valid-plan rate, budget violations and improved/tied/worse cases. Explain contributions from assignment, route ordering, conveyor access and congestion separately.

## 10. Acceptance and implementation sequence

- [ ] Freeze schemas, geometry, speed, task cap, demand, compute budgets and seed protocol.
- [ ] Verify conveyor access and single-picker repeated-task chaining.
- [ ] Verify assignment and no-congestion event timings.
- [ ] Verify pickup capacities, FIFO queues and simultaneous events.
- [ ] Verify precomputation overlap and exact late-plan waiting.
- [ ] Verify routing combinations, unissued-request moves/swaps and congestion evaluation.
- [ ] Compare tiny exact cases against enumeration; test heuristic validity without assuming optimality.
- [ ] Inject interruptions in initialization, routing, reassignment, congestion evaluation and finalization.
- [ ] Preserve original single-picker regression coverage and fixed-delay reproducibility.
- [ ] Perform development selection followed by independent evaluation and sensitivity studies.

The initial 786 records are preserved as historical evidence predating a planner-serialization fix. Follow-up changes and 474 post-fix records are now integrated; 74 tests passed during integration. This acceptance checklist remains the target specification rather than a blanket completion claim. See [current status](16-project-expansion-status.md) for addressed checks, new findings and remaining validation.
