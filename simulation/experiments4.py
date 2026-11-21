# -*- coding: utf-8 -*-
"""4차 입증 실험: savings 묶음·completion 배정·가변 묶음·제한적 LNS.

목표: 현재 cap24 조합(C3) 대비 추가 종료시간 감소가 있는지.
출력: results/multi4-dev/, results/multi4-eval/ (기존 원자료 불변).
계산 예산: 기존 15초 기준 유지. fixed 모드가 논리 비교 기준.
"""
import sys

from .__main__ import _execute, _write, make_run_args
from .config import WarehouseConfig, replace

DEV = (202, 204, 206, 208)
EVAL10 = (203, 205, 207, 209, 211, 213, 215, 217, 219, 221)
LARGE = WarehouseConfig(width=76, height=80, cross_ys=(0, 40, 80),
                        staging=(36, 0), name="warehouse-large-v1")

# 단계(모두 n2r 경로, move_swap off, 혼잡 off, 선행하차 off)
STAGES = {
    "S1-C3": dict(assignment="balanced", requests_per_task=24),
    "S2-savings-bal": dict(assignment="balanced", bundling="savings",
                           requests_per_task=24),
    "S3-savings-comp": dict(assignment="completion", bundling="savings",
                            requests_per_task=24),
    "S3b-chunk-comp": dict(assignment="completion", requests_per_task=24),
    "S4b-var-LNS": dict(assignment="completion", requests_per_task=24,
                        variable_cap=True, lns=True, lns_time_budget_s=2.0),
}


def _cfg(seed, pickers=10, requests=480, warehouse=None, mode="fixed", **plan_kw):
    plan_kw.setdefault("combo", "nn-2opt-reinsert")
    plan_kw.setdefault("move_swap", False)
    cfg = make_run_args(pickers=pickers, seed=seed, requests=requests,
                        compute_mode=mode, **plan_kw)
    return replace(cfg, warehouse=warehouse) if warehouse else cfg


def dev_stages(out):
    return [(f"stages|{name}", "dev", _cfg(seed, **kw))
            for name, kw in STAGES.items() for seed in DEV]


EVAL_CONDITIONS = [  # (조건명, pickers, requests, warehouse, plan_kw 추가)
    ("p10-R480", 10, 480, None, {}),
    ("p20-R480", 20, 480, None, {}),
    ("p20-R960", 20, 960, None, {}),
    ("large-p10-R960", 10, 960, LARGE, {}),
    ("hot-p10-R480", 10, 480, None, dict(hot_aisle_share=0.6, duplicate_share=0.2)),
    ("packed70-dup-p10", 10, 480, None, dict(easy_ratio=0.3, duplicate_share=0.3)),
]
EVAL_METHODS = {
    "L1-cap12": dict(assignment="spatial", requests_per_task=12, combo="nn"),
    "S1-C3": STAGES["S1-C3"],
    "S3b-chunk-comp": STAGES["S3b-chunk-comp"],
    "S4b-var-LNS": STAGES["S4b-var-LNS"],
}


def eval_all(out):
    runs = []
    for cond, p, R, wh, extra in EVAL_CONDITIONS:
        for name, kw in EVAL_METHODS.items():
            for seed in EVAL10:
                runs.append((f"{cond}|{name}", "eval",
                             _cfg(seed, pickers=p, requests=R, warehouse=wh, **{**kw, **extra})))
    return runs


def eval_measured(out):
    runs = []
    for cond, p, R, wh, extra in EVAL_CONDITIONS:
        for name in ("S1-C3", "S3b-chunk-comp"):
            for seed in EVAL10:
                runs.append((f"{cond}-measured|{name}", "eval",
                             _cfg(seed, pickers=p, requests=R, warehouse=wh,
                                  mode="measured", **{**EVAL_METHODS[name], **extra})))
    return runs


def main(out_root="results", suites=("dev-stages",)):
    from .__main__ import run_once
    from .warehouse import build_warehouse
    import random as _r
    builders = {"dev-stages": dev_stages, "eval-all": eval_all,
                "eval-measured": eval_measured}
    cache = {}
    default_wh = build_warehouse(WarehouseConfig())

    def wh_for(cfg):
        name = cfg.warehouse.name
        if name == WarehouseConfig().name:
            return default_wh
        if name not in cache:
            cache[name] = build_warehouse(cfg.warehouse)
        return cache[name]

    for suite in suites:
        prepared = builders[suite](out_root)
        rows = []
        order = list(prepared)
        _r.Random(20261122).shuffle(order)
        for i, (label, split, run) in enumerate(order):
            print(f"[{i+1}/{len(order)}] {label} seed={run.sim.seed}",
                  file=sys.stderr)
            result = run_once(run, wh_for(run))
            result["suite"], result["split"] = label, split
            rows.append(result)
        out_dir = f"{out_root}/multi4-{'dev' if 'dev' in suite else 'eval'}"
        _write(out_dir, suite, rows)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0] if args else "results", tuple(args[1:]) or ("dev-stages",))
