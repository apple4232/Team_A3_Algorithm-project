# -*- coding: utf-8 -*-
"""results/multi/*.jsonl 요약: 조합·배정·민감도별 개선율과 seed 그룹 신뢰구간.

Usage: python -m simulation.analysis <results_dir>   (또는 python -I analysis.py)
기준(비교 대상)은 같은 (pickers, assignment, seed)의 NN 종료시간이다.
"""
import json
import random
import sys
from collections import defaultdict
from statistics import mean
from pathlib import Path


def group_interval(values_by_group, seed=0, repetitions=1000):
    groups = list(values_by_group.values())
    if len(groups) < 2:
        return None
    rng = random.Random(seed)
    samples = []
    for _ in range(repetitions):
        picked = [groups[rng.randrange(len(groups))] for _ in groups]
        samples.append(mean(v for g in picked for v in g))
    samples.sort()
    return [samples[int(.025 * repetitions)], samples[int(.975 * repetitions) - 1]]


def load(results_dir):
    rows = []
    for path in sorted(Path(results_dir).glob("*.jsonl")):
        suite = path.stem
        for line in open(path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                r["suite"] = suite
                rows.append(r)
    return rows


def key_of(r, axes):
    return tuple(_get(r, a) for a in axes)


def _get(r, axis):
    if axis == "pickers":
        return r["config"]["sim"]["pickers"]
    if axis == "combo":
        return r["config"]["plan"]["route_combo"]
    if axis == "assignment":
        return r["config"]["plan"]["assignment"]
    if axis == "congestion":
        return r["config"]["plan"]["congestion_aware"]
    if axis == "easy_ratio":
        return r["config"]["pick"]["easy_ratio"]
    if axis == "zone_length":
        return r["config"]["pick"]["zone_length_m"]
    if axis == "zone_capacity":
        return r["config"]["pick"]["zone_capacity"]
    if axis == "requests":
        return r["config"]["total_requests"]
    raise KeyError(axis)


def main(results_dir="results/multi", out=sys.stdout):
    rows = load(results_dir)
    print(f"loaded {len(rows)} runs", file=out)

    def summarize(name, subset, baseline_axes, candidate_axes, extra_label=""):
        """baseline_axes로 기준(NN 등)을 정하고 candidate 축별 개선율 집계."""
        by = defaultdict(dict)
        for r in subset:
            k = (key_of(r, baseline_axes), r["config"]["sim"]["seed"], r["split"])
            by[k][key_of(r, candidate_axes) if candidate_axes else ""] = r
        results = defaultdict(lambda: defaultdict(list))  # cell -> seed -> improvements
        details = defaultdict(lambda: {"imp": 0, "same": 0, "worse": 0,
                                       "walk": [], "wait": [], "p95": [], "n": 0})
        for (bk, seed, split), cells in by.items():
            base = cells.get("nn") or cells.get((False,)) or None
            if base is None:
                continue
            for ckey, r in cells.items():
                if r is base:
                    continue
                imp = 100 * (base["metrics"]["makespan_s"] - r["metrics"]["makespan_s"]) \
                    / base["metrics"]["makespan_s"]
                results[(split,) + (ckey if isinstance(ckey, tuple) else (ckey,))][seed].append(imp)
                d = details[(split,) + (ckey if isinstance(ckey, tuple) else (ckey,))]
                d["imp" if imp > 1e-9 else "same" if imp >= -1e-9 else "worse"] += 1
                d["walk"].append(r["metrics"]["total_walk_m"])
                d["wait"].append(r["metrics"]["total_zone_wait_s"])
                d["p95"].append(r["metrics"]["makespan_s"])
                d["n"] += 1
        for cell in sorted(results):
            groups = results[cell]
            all_vals = [v for g in groups.values() for v in g]
            ci = group_interval(groups)
            d = details[cell]
            print(f"{name}{extra_label} {cell}: n={d['n']} mean_improvement={mean(all_vals):+.2f}% "
                  f"ci95=[{ci[0]:+.2f}, {ci[1]:+.2f}] imp/same/worse={d['imp']}/{d['same']}/{d['worse']} "
                  f"walk_mean={mean(d['walk']):.0f}m wait_mean={mean(d['wait']):.1f}s",
                  file=out)

    # 1) 주 실험: (pickers, assignment) 기준 셀에서 조합별 개선율
    main_rows = [r for r in rows if r["suite"] == "main"]
    summarize("main", main_rows, ["pickers", "assignment"], ["combo"])

    # 2) 배정 효과: 같은 (pickers, combo=nn)에서 spatial vs balanced
    nn_rows = [r for r in main_rows if _get(r, "combo") == "nn"]
    by = defaultdict(dict)
    for r in nn_rows:
        k = (_get(r, "pickers"), r["config"]["sim"]["seed"], r["split"])
        by[k][_get(r, "assignment")] = r["metrics"]["makespan_s"]
    diffs = defaultdict(lambda: defaultdict(list))
    for (p, seed, split), cells in by.items():
        if "spatial" in cells and "balanced" in cells:
            diffs[(split, p)][seed].append(100 * (cells["spatial"] - cells["balanced"])
                                           / cells["spatial"])
    for cell in sorted(diffs):
        vals = [v for g in diffs[cell].values() for v in g]
        ci = group_interval(diffs[cell])
        print(f"assignment {cell}: balanced vs spatial mean={mean(vals):+.2f}% ci95=[{ci[0]:+.2f},{ci[1]:+.2f}]",
              file=out)

    # 3) 민감도: 요인·값별 NN 대비 개선율(개발 seed)
    sens = [r for r in rows if r["suite"].startswith("sens")]
    for factor in ("easy_ratio", "zone_length", "zone_capacity"):
        part = [r for r in sens if r["suite"] == f"sens-{factor}"]
        if part:
            summarize(f"sens-{factor}", part,
                      [factor, "pickers", "assignment"], ["combo"])

    # 4) 작업자당 고정
    pp = [r for r in rows if r["suite"] == "per-picker"]
    summarize("per-picker", pp, ["pickers", "assignment"], ["combo"])

    # 5) 혼잡 고려 on/off (eval, balanced+nn-2opt-reinsert)
    cong = [r for r in rows if r["suite"] == "congestion"]
    by = defaultdict(dict)
    for r in cong:
        k = (_get(r, "pickers"), r["config"]["sim"]["seed"])
        by[k][_get(r, "congestion")] = r["metrics"]
    diffs = defaultdict(lambda: defaultdict(list))
    detail = {"imp": 0, "same": 0, "worse": 0}
    for (p, seed), cells in by.items():
        if False in cells and True in cells:
            base, cand = cells[False], cells[True]
            imp = 100 * (base["makespan_s"] - cand["makespan_s"]) / base["makespan_s"]
            diffs[p][seed].append(imp)
            detail["imp" if imp > 1e-9 else "same" if imp >= -1e-9 else "worse"] += 1
    for p in sorted(diffs):
        vals = [v for g in diffs[p].values() for v in g]
        ci = group_interval(diffs[p])
        print(f"congestion-aware p={p}: mean={mean(vals):+.2f}% ci95=[{ci[0]:+.2f},{ci[1]:+.2f}] "
              f"imp/same/worse={detail['imp']}/{detail['same']}/{detail['worse']}", file=out)

    # 6) 계획 계산 부담 요약(measured)
    if main_rows:
        wall = [r["metrics"]["plan"]["wall_seconds"] for r in main_rows]
        delay = [r["metrics"]["plan"]["sim_delay_seconds"] for r in main_rows]
        wait = [r["metrics"]["plan_wait_total_s"] for r in main_rows]
        makespans = [r["metrics"]["makespan_s"] for r in main_rows]
        print(f"plan wall mean={mean(wall):.3f}s sim-delay mean={mean(delay):.3f}s "
              f"picker-plan-wait mean={mean(wait):.2f}s makespan mean={mean(makespans):.0f}s",
              file=out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/multi")
