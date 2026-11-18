# -*- coding: utf-8 -*-
"""Independent reproduction & verification of GitHub issue #3 (segment DP on NN+2-opt).

NOT the original prototype: the issue's prototype was run locally and never
committed. This script re-implements the spec from the issue text on top of the
repository's picking package (commit 9c03abd, tree == Sichan 7a9ab03):

  - secure an NN+2-opt route from the shared shortest-distance table
  - windows of 6 consecutive visited locations, both boundaries fixed
    (left = S or order[i-1], right = C or order[j+1]), subset DP inside the
    window including the entry distance (boundary->first) and exit distance
    (last->boundary); adopt a reorder only if the FULL route distance improves
  - step 3, single pass, last 6-location window always included
  - total budget 200 ms from preprocessing through reconstruction+validation,
    cooperative deadline checks, secured route returned on abort

Usage: python -I issue3_verify.py <repo_root> <out_dir>
Writes per-task JSONL and summary JSON into out_dir. Stdlib + repo code only.
"""
import json
import sys
import time
from pathlib import Path
from statistics import mean, median
from collections import defaultdict
import random

repo = sys.argv[1]
outdir = Path(sys.argv[2])
outdir.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, repo)

from picking.algorithms import solve, two_opt  # noqa: E402
from picking.distances import (Task, prepare_distances, DeadlineExceeded,  # noqa: E402
                               check_deadline)
from picking.graph import build_warehouse  # noqa: E402

EPS = 1e-9
WINDOW, STEP, BUDGET = 6, 3, 0.2
GRAPH = build_warehouse()
ENV = {"platform": sys.platform, "python": sys.version, "machine": "independent-repro",
       "window": WINDOW, "step": STEP, "budget_seconds": BUDGET,
       "baseline_commit": "9c03abd (= Sichan 7a9ab03 tree)",
       "note": "independent reproduction of issue #3 spec; not the original prototype"}


# ---------------------------------------------------------------- segment DP
def window_starts(n, window=WINDOW, step=STEP):
    """Window start indices: 0, step, 2*step, ... plus the final window [n-window, n)."""
    if n <= window:
        return [0] if n else []
    starts = list(range(0, n - window + 1, step))
    if starts[-1] != n - window:
        starts.append(n - window)
    return starts


def window_dp(table, nodes, left, right, deadline=None):
    """Exact reorder of `nodes` as an open path left -> perm(nodes) -> right.

    Entry distance d(left, first) and exit distance d(last, right) are part of
    the objective. Returns (best_tuple, best_total).
    """
    k = len(nodes)
    if k == 0:
        return (), table.d(left, right)
    if k == 1:
        p = nodes[0]
        return (p,), table.d(left, p) + table.d(p, right)
    cells = k << k
    inf = float("inf")
    costs = [inf] * cells
    parent = [-1] * cells
    for j, p in enumerate(nodes):
        costs[(1 << j) * k + j] = table.d(left, p)
    for mask in range(1, 1 << k):
        check_deadline(deadline)
        for j in range(k):
            if not mask & (1 << j):
                continue
            prev = mask ^ (1 << j)
            if prev == 0:
                continue
            base = prev * k
            best, arg = inf, -1
            m = prev
            while m:
                bit = m & -m
                i = bit.bit_length() - 1
                c = costs[base + i] + table.d(nodes[i], nodes[j])
                if c < best:
                    best, arg = c, i
                m ^= bit
            costs[mask * k + j], parent[mask * k + j] = best, arg
    full = (1 << k) - 1
    last = min(range(k), key=lambda j: (costs[full * k + j] + table.d(nodes[j], right), j))
    total = costs[full * k + last] + table.d(nodes[last], right)
    seq, mask = [], full
    while last != -1:
        seq.append(nodes[last])
        nxt = parent[mask * k + last]
        mask ^= 1 << last
        last = nxt
    return tuple(reversed(seq)), total


def segment_dp_pass(table, order, deadline, window=WINDOW, step=STEP):
    """One sweep; adopt a window reorder only when the full route distance drops."""
    order = list(order)
    n = len(order)
    adopted = timeouts = 0
    for s in window_starts(n, window, step):
        try:
            check_deadline(deadline)
        except DeadlineExceeded:
            timeouts += 1
            break
        e = min(s + window, n)
        seg = order[s:e]
        left = table.task.start if s == 0 else order[s - 1]
        right = table.task.conveyor if e == n else order[e]
        best_seg, best_seg_total = window_dp(table, seg, left, right, deadline)
        candidate = order[:s] + list(best_seg) + order[e:]
        if table.route_distance(tuple(candidate)) < table.route_distance(tuple(order)) - EPS:
            order = candidate
            adopted += 1
    return order, adopted, timeouts


# ------------------------------------------------------- reinsertion baseline
def reinsertion_pass(table, order, deadline):
    """Single-pass single-location reinsertion: remove order[i], best-delta reinsert."""
    order = list(order)
    n = len(order)
    adopted = timeouts = 0

    def d(a, b):
        return table.d(a, b)

    for i in range(n):
        try:
            check_deadline(deadline)
        except DeadlineExceeded:
            timeouts += 1
            break
        p = order[i]
        prev_n = order[i - 1] if i else table.task.start
        next_n = order[i + 1] if i + 1 < n else table.task.conveyor
        removal_gain = d(prev_n, p) + d(p, next_n)  # removed edge d(prev,next) added back below
        best_gain, best_j = -EPS, None
        rest = order[:i] + order[i + 1:]
        a = table.task.start
        for j in range(len(rest) + 1):
            b = rest[j] if j < len(rest) else table.task.conveyor
            insert_cost = d(a, p) + d(p, b) - d(a, b)
            if insert_cost - (removal_gain - d(prev_n, next_n)) < best_gain:
                best_gain = insert_cost - (removal_gain - d(prev_n, next_n))
                best_j = j
            a = b
        if best_j is not None:
            candidate = rest[:best_j] + [p] + rest[best_j:]
            if table.route_distance(tuple(candidate)) < table.route_distance(tuple(order)) - EPS:
                order = candidate
                adopted += 1
    return order, adopted, timeouts


# ------------------------------------------------------------------ pipeline
def run_pipeline(task_rec, phase, budget=BUDGET, window=WINDOW, step=STEP):
    """prep -> NN -> 2-opt -> phase(segdp|reinsert|none|dp) -> reconstruct+validate.

    Mirrors run_request semantics: one deadline for everything, cooperative
    checks, secured route returned on abort, validation always run on a route.
    """
    started = time.perf_counter()
    deadline = started + budget
    rec = {"task_id": task_rec["id"], "group": task_rec["group"], "phase": phase,
           "n": len(task_rec["required"]), "pattern": task_rec["pattern"]}
    status = "completed"
    timings = {}
    try:
        t = time.perf_counter()
        task = Task.create(GRAPH, tuple(task_rec["start"]), [tuple(p) for p in task_rec["required"]])
        table = prepare_distances(GRAPH, task, deadline)
        timings["preprocess"] = time.perf_counter() - t
        rec["internal_n"] = len(task.internal)
        t = time.perf_counter()
        nn = solve(table, "nn", deadline=deadline)
        timings["initial_nn"] = time.perf_counter() - t
        if nn.order is None:
            raise DeadlineExceeded("NN route not secured within budget")
        t = time.perf_counter()
        base = two_opt(table, nn, deadline=deadline)
        timings["two_opt"] = time.perf_counter() - t
        secured = base if base.order is not None else nn
        rec["nn2opt_distance"] = table.route_distance(tuple(secured.order))
        rec["nn2opt_status"] = base.status
        if phase in ("segdp", "reinsert", "none"):
            t = time.perf_counter()
            if phase == "segdp":
                order, adopted, aborted = segment_dp_pass(table, secured.order, deadline, window, step)
            elif phase == "reinsert":
                order, adopted, aborted = reinsertion_pass(table, secured.order, deadline)
            else:
                order, adopted, aborted = list(secured.order), 0, 0
            timings["phase"] = time.perf_counter() - t
            rec["adopted"] = adopted
            rec["phase_aborted"] = aborted > 0
        elif phase == "dp":
            t = time.perf_counter()
            exact = solve(table, "dp", deadline=deadline)
            timings["phase"] = time.perf_counter() - t
            order, adopted = exact.order, 0
            rec["exact_status"] = exact.status
            if order is None or exact.status != "completed":
                order = secured.order  # fallback to secured NN+2-opt route
                rec["dp_fallback"] = True
        final_order = tuple(order)
        t = time.perf_counter()
        path = table.reconstruct(final_order)
        table.validate_path(final_order, path, table.route_distance(final_order))
        timings["reconstruct_validate"] = time.perf_counter() - t
        rec["final_distance"] = table.route_distance(final_order)
        rec["saving_vs_nn2opt"] = rec["nn2opt_distance"] - rec["final_distance"]
        rec["never_worse_ok"] = rec["final_distance"] <= rec["nn2opt_distance"] + EPS
        total = time.perf_counter() - started
        rec["total_seconds"] = total
        rec["budget_exceeded"] = total > budget
        if rec.get("phase_aborted") or rec.get("dp_fallback"):
            status = "timeout_route_returned"
        elif rec["budget_exceeded"]:
            status = "timeout_budget_exceeded"
        rec["status"] = status
        rec["timings"] = timings
        return rec
    except DeadlineExceeded:
        total = time.perf_counter() - started
        rec["status"] = "timeout_no_route" if "nn2opt_distance" not in rec else "timeout_route_returned"
        rec.setdefault("final_distance", rec.get("nn2opt_distance"))
        rec.setdefault("saving_vs_nn2opt", 0.0)
        rec["total_seconds"] = total
        rec["budget_exceeded"] = total > budget
        rec["timings"] = timings
        return rec


def jl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def fmt(x, k=3):
    return None if x is None else round(x, k)


def summarize(runs, label, handle):
    by = defaultdict(list)
    for r in runs:
        by[r["n"]].append(r)
    out = {"label": label, "machine": ENV}
    for n in sorted(by):
        rows = by[n]
        savings = [r.get("saving_vs_nn2opt", 0.0) or 0.0 for r in rows]
        improved = [r for r in rows if (r.get("saving_vs_nn2opt") or 0) > EPS]
        worsened = [r for r in rows if (r.get("saving_vs_nn2opt") or 0) < -EPS]
        totals = sorted(r["total_seconds"] for r in rows)
        p95 = totals[min(len(totals) - 1, int(0.95 * len(totals)))]
        out[str(n)] = {
            "tasks": len(rows), "improved": len(improved), "same": len(rows) - len(improved) - len(worsened),
            "worsened": len(worsened),
            "mean_saving_all_m": fmt(mean(savings), 4),
            "mean_saving_improved_only_m": fmt(mean(r["saving_vs_nn2opt"] for r in improved), 4) if improved else None,
            "median_total_ms": fmt(1000 * median(totals), 3),
            "p95_total_ms": fmt(1000 * p95, 3),
            "budget_exceeded": sum(1 for r in rows if r["budget_exceeded"]),
            "timeout_route_returned": sum(1 for r in rows if r["status"] == "timeout_route_returned"),
            "timeout_no_route": sum(1 for r in rows if r["status"] == "timeout_no_route"),
            "never_worse_violations": sum(1 for r in rows if not r.get("never_worse_ok", True)),
        }
    handle(json.dumps(out, ensure_ascii=False))


def bootstrap_groups(runs):
    groups = defaultdict(list)
    for r in runs:
        groups[r["group"]].append(r.get("saving_vs_nn2opt", 0.0) or 0.0)
    g = list(groups.values())
    rng = random.Random(0)
    samples = sorted(mean(v for grp in (g[rng.randrange(len(g))] for _ in g) for v in grp) for _ in range(1000))
    return fmt(samples[25], 4), fmt(samples[974], 4)


# ------------------------------------------------------------------- execute
tasks_all = jl(f"{repo}/results/full/tasks.jsonl")
dev_large = [t for t in tasks_all if t["split"] == "dev" and len(t["required"]) in (15, 20, 50)]
eval_large = [t for t in tasks_all if t["split"] == "eval" and len(t["required"]) in (15, 20, 50)]
eval_small = [t for t in tasks_all if t["split"] == "eval" and len(t["required"]) <= 12]
print(f"dev large={len(dev_large)} eval large={len(eval_large)} eval small={len(eval_small)}")

# --- 1. dev reproduction (nn2opt baseline + segdp) + stored-baseline cross-check
stored_dev = {}
for r in jl(f"{repo}/results/full/dev-request.jsonl"):
    if r["algorithm"] == "nn+2opt":
        stored_dev[r["task"]["id"]] = r["result"]["distance"]

dev_runs, mismatch = [], 0
for i, t in enumerate(dev_large):
    base = run_pipeline(t, "none")
    if base.get("nn2opt_distance") is None or abs(base["nn2opt_distance"] - stored_dev[t["id"]]) > EPS:
        mismatch += 1
    dev_runs.append(base)
    dev_runs.append(run_pipeline(t, "segdp"))
print("dev baseline mismatches vs stored dev-request nn+2opt:", mismatch, "/", len(dev_large))

with open(outdir / "dev-repro.jsonl", "w", encoding="utf-8") as f:
    for r in dev_runs:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
with open(outdir / "dev-repro-summary.json", "w", encoding="utf-8") as f:
    summarize([r for r in dev_runs if r["phase"] == "none"], "dev nn+2opt baseline (repro)", f.write)
    summarize([r for r in dev_runs if r["phase"] == "segdp"], "dev nn+2opt + segment DP (repro)", f.write)

# --- 2. eval independent comparison: none / segdp / reinsert on large, dp on small
eval_runs = []
for t in eval_large:
    for phase in ("none", "segdp", "reinsert"):
        eval_runs.append(run_pipeline(t, phase))
for t in eval_small:
    eval_runs.append(run_pipeline(t, "dp"))
    eval_runs.append(run_pipeline(t, "segdp"))
with open(outdir / "eval-compare.jsonl", "w", encoding="utf-8") as f:
    for r in eval_runs:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
with open(outdir / "eval-compare-summary.json", "w", encoding="utf-8") as f:
    for phase in ("none", "segdp", "reinsert", "dp"):
        summarize([r for r in eval_runs if r["phase"] == phase], f"eval {phase}", f.write)
    for phase in ("segdp", "reinsert"):
        large = [r for r in eval_runs if r["phase"] == phase and r["n"] >= 15]
        lo, hi = bootstrap_groups(large)
        f.write(json.dumps({"label": f"eval {phase} large-task saving CI95 (seed-group bootstrap)",
                            "mean_m": fmt(mean(r.get("saving_vs_nn2opt", 0) or 0 for r in large), 4),
                            "ci95": [lo, hi]}, ensure_ascii=False) + "\n")

# --- 3. timing stability: 25 sampled dev tasks x 20 reps
rng = random.Random(7)
sample = rng.sample(dev_large, 25)
stab = {"none": [], "segdp": []}
for t in sample:
    for phase in ("none", "segdp"):
        meds = sorted(run_pipeline(t, phase)["total_seconds"] for _ in range(20))
        stab[phase].append(meds[len(meds) // 2])
with open(outdir / "timing-stability.json", "w", encoding="utf-8") as f:
    for phase, vals in stab.items():
        vals = sorted(1000 * v for v in vals)
        f.write(json.dumps({"phase": phase, "reps": 20, "tasks": len(vals),
                            "median_of_medians_ms": fmt(median(vals), 3),
                            "p95_of_medians_ms": fmt(vals[min(len(vals) - 1, int(0.95 * len(vals)))], 3),
                            "min_ms": fmt(vals[0], 3), "max_ms": fmt(vals[-1], 3)}, ensure_ascii=False) + "\n")

# --- 4. correctness micro-suite
micro = []
# 4a. window DP == brute force on all windows of sampled tasks
from itertools import permutations  # noqa: E402
brute_windows = 0
for t in rng.sample(eval_large, 20):
    task = Task.create(GRAPH, tuple(t["start"]), [tuple(p) for p in t["required"]])
    table = prepare_distances(GRAPH, task)
    nn = solve(table, "nn")
    base = two_opt(table, nn)
    order = list(base.order)
    n = len(order)
    for s in window_starts(n):
        e = min(s + WINDOW, n)
        seg = order[s:e]
        left = task.start if s == 0 else order[s - 1]
        right = task.conveyor if e == n else order[e]
        dp_seg, dp_total = window_dp(table, seg, left, right)
        brute_total = min(table.d(left, p[0]) + sum(table.d(a, b) for a, b in zip(p, p[1:])) + table.d(p[-1], right)
                          for p in permutations(seg))
        if abs(dp_total - brute_total) > EPS:
            micro.append({"check": "window_dp_vs_bruteforce", "task": t["id"], "start": s, "FAIL": True})
        brute_windows += 1
micro.append({"check": "window_dp_vs_bruteforce", "windows_checked": brute_windows, "failures": len([m for m in micro if m.get("FAIL")])})
# 4b. last-window inclusion sweep coverage
for n in (15, 20, 50, 7, 6, 5, 3):
    st = window_starts(n)
    ok = st[0] == 0 and (n <= WINDOW or st[-1] == n - WINDOW)
    micro.append({"check": "sweep_coverage", "n": n, "starts": st, "first_at_0_last_covers_end": ok})
# 4c. small n (<=6): single-window segdp == exact dp distance
tiny = [t for t in eval_small if len(t["required"]) <= 6]
agree = compared = 0
for t in rng.sample(tiny, min(40, len(tiny))):
    task = Task.create(GRAPH, tuple(t["start"]), [tuple(p) for p in t["required"]])
    table = prepare_distances(GRAPH, task)
    exact = solve(table, "dp")
    nn = solve(table, "nn")
    base = two_opt(table, nn)
    order, _, _ = segment_dp_pass(table, base.order, None)
    compared += 1
    if abs(table.route_distance(tuple(order)) - exact.distance) <= EPS:
        agree += 1
    else:
        micro.append({"check": "single_window_optimal", "task": t["id"], "FAIL": True})
micro.append({"check": "single_window_optimal_n<=6", "compared": compared, "agreements": agree})
# 4d. duplicates & S/C requests
edge = Task.create(GRAPH, (0, 0), [(4, 38), (4, 38), (8, 14), (0, 0), (36, 0)])
rec_edge = run_pipeline({"id": "edge:dups+SC", "group": "edge", "start": [0, 0],
                         "required": [[4, 38], [4, 38], [8, 14], [0, 0], [36, 0]], "pattern": "edge"}, "segdp")
micro.append({"check": "duplicate_and_SC_requests", "internal_n": rec_edge.get("internal_n"),
              "status": rec_edge["status"], "validated": rec_edge.get("final_distance") is not None})
# 4e. forced timeout (0.5 ms budget) on n=50
forced = [run_pipeline(t, "segdp", budget=0.0005) for t in rng.sample(eval_large, 20)]
micro.append({"check": "forced_timeout_0.5ms_n50",
              "no_route": sum(1 for r in forced if r["status"] == "timeout_no_route"),
              "route_returned": sum(1 for r in forced if r["status"] == "timeout_route_returned"),
              "completed": sum(1 for r in forced if r["status"] == "completed"),
              "never_worse_violations": sum(1 for r in forced if not r.get("never_worse_ok", True))})
with open(outdir / "correctness-micro.json", "w", encoding="utf-8") as f:
    json.dump(micro, f, ensure_ascii=False, indent=1)

with open(outdir / "environment.json", "w", encoding="utf-8") as f:
    json.dump(ENV, f, ensure_ascii=False, indent=1)
print("ALL DONE ->", outdir)
