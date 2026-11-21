# 18. Evidence Experiments: Which Combination Improved What?

> **Historical exploratory report with corrections.** The expansion is closed and preserved in the [complete study record](20-expansion-study-record.md). These are synthetic-condition observations. Evaluation seed IDs were reused across stages, so this is not a fresh project-wide independent evaluation. Observed improvement and computation-budget compliance are separate; the budget criterion was not met.

Original report: November 21, 2026, branch `multi-picker-evidence`, based on `project-expansion` at `340db77`; implementation `5b9ca79`. Data: `results/multi3-dev/` (220 runs), `results/multi3-eval/` (420). Reported environment: Windows 10, Python 3.12.2, standard library. Development seeds: four even IDs 202-208, plus 210/212 for congestion screening. Evaluation: ten odd IDs 203-221, not used for that stage's candidate choice. Execution order was randomized.

## 1. Predeclared success criteria

- Practical target: at p=10/R=480 in the default warehouse, aggregate improvement **at least 1.0% and 10 seconds per run**.
- Deterioration tolerance: condition-specific CI lower bound above -0.5%; worst single deterioration at most 2%.
- Computation: planning wall time at most 15 seconds per run; worker planning waiting at most 2% of makespan.
- Rationale: bottleneck analysis suggested about 98% utilization and collection/travel ratio 6.6:1; 1% was selected as a practical threshold above the reported approximately 0.3% variation.

The worker-wait ratio sums time across workers and is not the fraction of elapsed makespan directly caused by planning. Randomized ordering alone does not validate the stated timing-variation estimate through repeated trials.

## 2. Bottleneck analysis

`simulation/bottleneck.py` examined 168 NN records from multi2. The report approximated completion as maximum worker load plus initial planning and a 5-40-second residual. Utilization was 95-99%, except p20/R240 at about 85%. Collection/travel was approximately 6.6:1; one last-finisher example had 236 seconds travel and 1,454 collection.

The proposed hypothesis was a 1-2% default-layout improvement opportunity based on travel share (about 14%), distance reduction and imbalance. Larger gains were observed in high-travel conditions, but layout, volume and density changed together; causal confirmation was not established.

## 3. References, candidates and decomposition

References share estimated-duration-descending release, FIFO service and physical rules:

- **L0 rr:** sort by staging distance and coordinates, then assign round-robin to K slots. This is a weak reference without spatial clustering.
- **L1 sp:** coordinate-sorted consecutive chunks, cap12; primary reference.
- **L2 bal:** adjust L1 chunks to reduce estimated-time dispersion.

Ladder: L3=balanced+n2r; L4=L3+move/swap; L5=L4+auto congestion; L6=spatial+n2r. Here n2r means NN -> 2-opt -> reinsertion.

Cap candidates: **C1=cap24+spatial+NN; C2=cap24+balanced+NN; C3=cap24+balanced+n2r**.

C3 was frozen after development screening and before the recorded evaluation. Move/swap, congestion and lookahead are off for that candidate; see Section 5.

## 4. Evaluation-set comparisons

Ten evaluation seeds; the primary statistic is aggregate completion improvement.

| Condition | C3 versus L1 | 95% interval | Seconds saved per run | Distance |
|---|---|---|---|---|
| Default p1, R480 | **+6.11%** | [5.87,6.34] | **1017.5** | -923 m |
| Default p10, R480 | **+3.84%** | [3.32,4.33] | **64.7** | -849 m |
| Default p20, R480 | **-2.28%** | [-3.68,-0.80] | -19.8 | -982 m |
| Large, 20 aisles, 76 by 80 m, p10/R960 | **+10.94%** | [10.23,11.64] | 422.0 | 8601 to 4941 m |
| Large plus additional cross aisles, p10/R960 | **+10.47%** | [9.75,11.21] | 400.5 | About -43% |
| Hotspot 0.6, duplicates 0.2, p10 | +3.67% | [2.96,4.32] | 61.2 | Not listed |
| Wrapped share 70%, p10 | +3.63% | [2.96,4.37] | 66.0 | Not listed |
| Walking speed 0.7 m/s, p10 | +6.55% | [5.86,7.23] | 117.9 | Not listed |

The stage report found per-run mean percentages approximately 0.01-0.1 percentage points from aggregate values; raw data support separate recalculation.

At p10/default, all ladder percentages use common baseline L1. Cap expansion C1 contributes a **+3.807 percentage-point difference**, C2-C1 is **-0.081**, and C3-C2 is **+0.112**. Their sum matches approximately +3.839%.

The correct interpretation is: **in this application order (batch size, balance, route), cap expansion explains most of the observed ladder difference**. This is not a unique causal contribution. Balance differs at cap12 (-0.25%) and cap24 (-0.08%); p1 has a similar pattern, with C1 about +6.05%.

The cap counts requests. Cap24 tasks have a reported median of 32 item units and nine unique locations (maximum 14). Basket capacity is excluded; field feasibility of carrying that batch is unverified. The cap12 ladder gives small +0.1-0.4% estimates with intervals including zero or small gains. Cap6 deteriorates about 11.8% in development.

## 5. Rejected or inconclusive development candidates

- **Move/swap:** L4-L3 approximately -3.9 to +0.8 seconds; insufficient stable increment, excluded.
- **Congestion/auto:** uniform p10 about -9.9% at threshold 30 seconds; stress p20 about -12.6%. Thresholds 15/60 gave unchanged stress decisions because estimates exceeded both; retained as experimental only.
- **Unloading lookahead:** about 30 decisions per run, 2-4 non-default choices and 6 ms computation, but p10 about +0.13% and p20 about zero. Retain as an experimental option and trace facility, not a preferred policy.
- **Round-robin:** about -24 to -51% relative results illustrate the importance of spatial grouping under these conditions; they do not make it the only adequate benchmark.

## 6. Scope and limitations

- Cap24 improves observed p10/R480 cases but deteriorates at p20/R480 by 2.28%. Chaining, load spread and planning waiting change together; no isolated causal experiment was performed. A tasks-per-picker >=2 selection rule remains unverified.
- C3 at p20/R960 was unmeasured in this stage; see document 19 for later comparisons. Cap>24 and optimal caps for other aisle structures remain unverified.
- Lower cost than another method does **not** meet the 15-second target. Claim verification found C3 maxima around 21.2 seconds (p10) and 35.5 seconds (p1). The 8.27% summed-worker-wait/makespan diagnostic must not be interpreted as direct elapsed delay.
- Collection time is fixed by the model; possible gains are in travel, unloading frequency and load alignment.
- All layouts and workloads are synthetic, with uncalibrated speed and handling assumptions.

## 7. Reproduction

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m unittest discover -s tests
python -I simulation/bottleneck.py results/multi2
python -m simulation.experiments3 results dev-all
python -m simulation.experiments3 results eval-ladder eval-large eval-workload
python -I simulation/analysis3.py results/multi3-eval
```

The suite had 80 tests at this stage; the final archive has 88. Full experiment commands run simulations; analysis commands read saved records. Preserve existing data when reproducing.

## 8. Corrected conclusion

> In the default synthetic warehouse with 480 requests and ten pickers, C3 reduced completion by 64.7 seconds, or an aggregate 3.84%, relative to cap12/spatial/NN. Batch expansion accounts for most of the tested ladder difference (+3.81 percentage points), with a small route-improvement increment. Basket-capacity omission, adverse conditions, computation-budget failures and reused evaluation seeds limit the conclusion. Twenty pickers/480 requests deteriorated 2.28%; no general application rule was validated. Preserve the result as an exploratory prototype, not an operational scheduling recommendation.
