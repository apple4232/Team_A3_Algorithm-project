# -*- coding: utf-8 -*-
"""simulation 패키지 CLI: 단일 실행, 셀프체크(벨트 근사), 실험 매트릭스.

사용 예:
  python -m simulation run --pickers 10 --combo nn-2opt-reinsert --seed 1
  python -m simulation selfcheck
  python -m simulation experiment --suite main --out results/multi
기존 1인 기능(picking)과 분리되어 별도 실행된다.
"""
import argparse
import json
import random
import sys
from dataclasses import replace
from pathlib import Path
from statistics import mean

from .config import PickConfig, PlanConfig, RunConfig, SimConfig, WarehouseConfig
from .requests import generate_requests, request_features
from .simulator import simulate
from .warehouse import build_warehouse

COMBOS = ("nn", "nn-2opt", "nn-reinsert", "nn-2opt-reinsert", "nn-reinsert-2opt",
          "alt", "nn-2opt-reinsert-segdp")


def make_run(args) -> RunConfig:
    plan = PlanConfig(route_combo=args.combo, assignment=args.assignment,
                      bundling=args.bundling, variable_cap=args.variable_cap,
                      lns=args.lns, lns_iters=args.lns_iters,
                      lns_time_budget_s=args.lns_time_budget_s,
                      lns_remove_q=args.lns_remove_q,
                      move_swap=not args.no_move_swap,
                      congestion_aware=args.congestion_aware,
                      congestion_mode=args.congestion_mode,
                      congestion_threshold_s=args.congestion_threshold_s,
                      dropoff_lookahead=args.dropoff_lookahead,
                      lookahead_candidates=args.lookahead_candidates,
                      requests_per_task=args.requests_per_task)
    sim = SimConfig(pickers=args.pickers, seed=args.seed, compute_mode=args.compute_mode)
    pick = PickConfig()
    if args.easy_ratio is not None:
        pick = replace(pick, easy_ratio=args.easy_ratio)
    if args.zone_length is not None:
        pick = replace(pick, zone_length_m=args.zone_length)
    if args.zone_capacity is not None:
        pick = replace(pick, zone_capacity=args.zone_capacity)
    return RunConfig(plan=plan, sim=sim, pick=pick,
                     total_requests=args.requests,
                     hot_aisle_share=args.hot_aisle_share,
                     duplicate_share=args.duplicate_share)


def run_once(run: RunConfig, warehouse=None):
    warehouse = warehouse or build_warehouse(run.warehouse)
    rng = random.Random(run.sim.seed)
    requests = generate_requests(run, warehouse, rng)
    features = request_features(requests, warehouse, run.pick)
    metrics = simulate(run, warehouse, requests)
    return {"config": _config_dict(run), "features": features, "metrics": metrics}


def _config_dict(run):
    return {"warehouse": vars(run.warehouse) | {}, "pick": vars(run.pick) | {},
            "plan": vars(run.plan) | {}, "sim": vars(run.sim) | {},
            "total_requests": run.total_requests,
            "hot_aisle_share": run.hot_aisle_share,
            "duplicate_share": run.duplicate_share}


def selfcheck(out=sys.stdout):
    """벨트 접근 이산화 오차 검증: 기본(2m) vs 조밀(0.5m) 접근 노드 비교."""
    coarse = build_warehouse(WarehouseConfig())
    fine = build_warehouse(WarehouseConfig(access_spacing_m=0.5))
    sample = sorted(coarse.locations)[::7]
    diffs = []
    for node in sample:
        diffs.append(coarse.belt_cost(node) - fine.belt_cost(node))
    bound = WarehouseConfig().access_spacing_m / 2
    print(f"샘플 {len(diffs)}개: 최대 오차 {max(diffs):.3f}m (상한 {bound:.1f}m), "
          f"평균 {mean(diffs):.3f}m, 위반 {sum(1 for d in diffs if d > bound + 1e-6)}건",
          file=out)
    return {"max": max(diffs), "mean": mean(diffs), "bound": bound,
            "violations": sum(1 for d in diffs if d > bound + 1e-6)}


# ------------------------------------------------------------------ 실험
def _cell(run):
    return (run.sim.pickers, run.plan.route_combo, run.plan.assignment,
            run.plan.congestion_aware, run.sim.seed)


def experiment_main(out_dir: str, dev_seeds, eval_seeds, pickers=(1, 10, 20),
                    requests=240, compute_mode="measured"):
    """주 실험: 고정 요청량에서 작업자 수 × 조합 × 배정. seed 그룹 분리."""
    rows = []
    warehouse = build_warehouse(WarehouseConfig())
    runs = []
    for split, seeds in (("dev", dev_seeds), ("eval", eval_seeds)):
        for p in pickers:
            for combo in COMBOS:
                for assignment in ("spatial", "balanced"):
                    for seed in seeds:
                        runs.append(("main", split, make_run_args(
                            pickers=p, combo=combo, assignment=assignment, seed=seed,
                            requests=requests, compute_mode=compute_mode)))
    _execute(runs, rows, warehouse)
    _write(out_dir, "main", rows)
    return rows


def make_run_args(**kw):
    args = argparse.Namespace(pickers=10, combo="nn", assignment="spatial",
                              no_move_swap=False, congestion_aware=False,
                              congestion_mode="v2", congestion_threshold_s=30.0,
                              dropoff_lookahead=False, lookahead_candidates=4,
                              bundling="chunk", variable_cap=False, lns=False,
                              lns_iters=20, lns_time_budget_s=2.0, lns_remove_q=4,
                              requests_per_task=12, seed=1, compute_mode="measured",
                              requests=240, easy_ratio=None, zone_length=None,
                              zone_capacity=None, hot_aisle_share=0.0,
                              duplicate_share=0.0)
    for k, v in kw.items():
        setattr(args, k, v)
    return make_run(args)


def experiment_sensitivity(out_dir, dev_seeds, pickers=10, requests=240):
    """요인별 민감도: 포장 비율·구역 길이·동시 인원 + 주요 상호작용(L×인원)."""
    rows = []
    warehouse = build_warehouse(WarehouseConfig())
    runs = []
    for factor, values, key in (("easy_ratio", (0.3, 0.6, 0.9), "easy_ratio"),
                                ("zone_length", (2.0, 4.0, 8.0), "zone_length"),
                                ("zone_capacity", (2, 3, 4), "zone_capacity")):
        for value in values:
            for combo in ("nn", "nn-2opt-reinsert"):
                for seed in dev_seeds:
                    kw = {"pickers": pickers, "combo": combo, "seed": seed,
                          "requests": requests, key: value}
                    runs.append((f"sens-{factor}", "dev", make_run_args(**kw)))
    for L in (2.0, 4.0):
        for cap in (2, 3):
            for combo in ("nn", "nn-2opt-reinsert"):
                for seed in dev_seeds:
                    runs.append(("sens-Lxcap", "dev", make_run_args(
                        pickers=pickers, combo=combo, seed=seed, requests=requests,
                        zone_length=L, zone_capacity=cap)))
    _execute(runs, rows, warehouse)
    _write(out_dir, "sensitivity", rows)
    return rows


def experiment_per_picker(out_dir, dev_seeds, per_picker=24, compute_mode="measured"):
    """작업자당 요청량 고정 실험: R = 작업자 수 × 24."""
    rows = []
    warehouse = build_warehouse(WarehouseConfig())
    runs = []
    for p in (1, 10, 20):
        for combo in ("nn", "nn-2opt-reinsert", "alt"):
            for seed in dev_seeds:
                runs.append(("per-picker", "dev", make_run_args(
                    pickers=p, combo=combo, seed=seed, requests=p * per_picker,
                    compute_mode=compute_mode)))
    _execute(runs, rows, warehouse)
    _write(out_dir, "per-picker", rows)
    return rows


def experiment_congestion(out_dir, eval_seeds, pickers=(10, 20), requests=240):
    """혼잡 고려 배정 개선 vs 거리 중심(같은 조합·같은 seed 쌍 비교)."""
    rows = []
    warehouse = build_warehouse(WarehouseConfig())
    runs = []
    for p in pickers:
        for congestion in (False, True):
            for seed in eval_seeds:
                runs.append(("congestion", "eval", make_run_args(
                    pickers=p, combo="nn-2opt-reinsert", seed=seed,
                    requests=requests, congestion_aware=congestion,
                    assignment="balanced")))
    _execute(runs, rows, warehouse)
    _write(out_dir, "congestion", rows)
    return rows


def _execute(runs, rows, warehouse):
    order = list(runs)
    random.Random(20261120).shuffle(order)  # 실행 순서 무작위화(재현 가능)
    for i, (suite, split, run) in enumerate(order):
        print(f"[{i + 1}/{len(order)}] {suite} p={run.sim.pickers} "
              f"{run.plan.route_combo} {run.plan.assignment}"
              f"{' +conj' if run.plan.congestion_aware else ''} seed={run.sim.seed}",
              file=sys.stderr)
        result = run_once(run, warehouse)
        result["suite"], result["split"] = suite, split
        rows.append(result)


def _write(out_dir, name, rows):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"{name}.jsonl", "x", encoding="utf-8") as f:
        for r in rows:
            slim = {k: v for k, v in r.items() if k != "metrics"}
            m = r["metrics"]
            slim["metrics"] = {k: v for k, v in m.items()
                               if k not in ("task_records", "events", "pickers")}
            # 작업 단위 분석 가능하도록 원자료에 작업 기록·작업자 요약 저장
            slim["task_count"] = len(m["task_records"])
            slim["task_records"] = [{"tid": t["tid"], "picker": t["picker"],
                                     "n_requests": len(t["requests"]),
                                     "issued_at": t["issued_at"],
                                     "finished_at": t["finished_at"],
                                     "pred_finish": t["pred_finish"],
                                     "start_node": list(t["start_node"]) if t["start_node"] else None,
                                     "nn_cost": t["nn_cost"], "final_cost": t["final_cost"]}
                                    for t in m["task_records"]]
            slim["pickers"] = m["pickers"]
            f.write(json.dumps(slim, ensure_ascii=False) + "\n")
    print(f"wrote {out / name}.jsonl ({len(rows)} runs)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run")
    for arg, kw in (("pickers", {"type": int, "default": 10}),
                    ("combo", {"default": "nn", "choices": COMBOS}),
                    ("assignment", {"default": "spatial", "choices": ["spatial", "balanced"]}),
                    ("no_move_swap", {"action": "store_true"}),
                    ("congestion_aware", {"action": "store_true"}),
                    ("congestion_mode", {"default": "v2"}),
                    ("congestion_threshold_s", {"type": float, "default": 30.0}),
                    ("dropoff_lookahead", {"action": "store_true"}),
                    ("lookahead_candidates", {"type": int, "default": 4}),
                    ("bundling", {"default": "chunk", "choices": ["chunk", "savings"]}),
                    ("variable_cap", {"action": "store_true"}),
                    ("lns", {"action": "store_true"}),
                    ("lns_iters", {"type": int, "default": 20}),
                    ("lns_time_budget_s", {"type": float, "default": 2.0}),
                    ("lns_remove_q", {"type": int, "default": 4}),
                    ("requests_per_task", {"type": int, "default": 12}),
                    ("seed", {"type": int, "default": 1}),
                    ("compute_mode", {"default": "measured", "choices": ["measured", "fixed"]}),
                    ("requests", {"type": int, "default": 240}),
                    ("easy_ratio", {"type": float, "default": None}),
                    ("zone_length", {"type": float, "default": None}),
                    ("zone_capacity", {"type": int, "default": None}),
                    ("hot_aisle_share", {"type": float, "default": 0.0}),
                    ("duplicate_share", {"type": float, "default": 0.0})):
        p_run.add_argument(f"--{arg}", **kw)
    sub.add_parser("selfcheck")
    p_exp = sub.add_parser("experiment")
    p_exp.add_argument("--suite", default="all",
                       choices=["all", "main", "sensitivity", "per-picker", "congestion"])
    p_exp.add_argument("--out", default="results/multi")
    args = parser.parse_args()
    if args.command == "selfcheck":
        selfcheck()
        return
    if args.command == "run":
        result = run_once(make_run(args))
        result["metrics"].pop("events", None)
        print(json.dumps(result, ensure_ascii=False, indent=1, default=str))
        return
    dev = (202, 204, 206, 208, 210, 212)
    ev = (203, 205, 207, 209, 211, 213)
    if args.suite in ("all", "main"):
        experiment_main(args.out, dev, ev)
    if args.suite in ("all", "sensitivity"):
        experiment_sensitivity(args.out, dev)
    if args.suite in ("all", "per-picker"):
        experiment_per_picker(args.out, dev)
    if args.suite in ("all", "congestion"):
        experiment_congestion(args.out, ev)


if __name__ == "__main__":
    main()
