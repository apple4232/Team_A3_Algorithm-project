# -*- coding: utf-8 -*-
"""입증 실험(3차): 개발 스크린과 동결 후 독립 평가.

출력 디렉터리(신규, 기존 원자료 불변):
  results/multi3-dev/  개발 스크린(후보·임계 선택용)
  results/multi3-eval/ 동결 후 독립 평가(평가 seed 203~221)

성공 판정 기준(실험 전 고정): 대상 조건(p=10, R=480, 기본 창고)에서
전체 집계 개선 >= 1.0% 且 >= 10s/실행; 악화 허용 CI 하한 > -0.5%·최대 악화 <= 2%;
계산 예산: 실행당 계획 실측 <= 15s·계획 대기 <= 종료 2%.
"""
import sys

from .__main__ import _execute, _write, make_run_args
from .config import PlanConfig, RunConfig, SimConfig, WarehouseConfig, replace

DEV = (202, 204, 206, 208)
DEV6 = (202, 204, 206, 208, 210, 212)
EVAL10 = (203, 205, 207, 209, 211, 213, 215, 217, 219, 221)
STRESS = dict(hot_aisle_share=0.8, duplicate_share=0.3, zone_length=8.0,
              zone_capacity=2)

LADDER = {  # 단계별 기여 분해 축(같은 seed·같은 요청으로 비교)
    "L0-rr-nn": dict(assignment="roundrobin", combo="nn", move_swap=False),
    "L1-sp-nn": dict(assignment="spatial", combo="nn", move_swap=False),
    "L2-bal-nn": dict(assignment="balanced", combo="nn", move_swap=False),
    "L3-bal-n2r": dict(assignment="balanced", combo="nn-2opt-reinsert",
                       move_swap=False),
    "L4-bal-n2r-ms": dict(assignment="balanced", combo="nn-2opt-reinsert",
                          move_swap=True),
    "L5-bal-n2r-ms-auto": dict(assignment="balanced", combo="nn-2opt-reinsert",
                               move_swap=True, congestion_aware=True,
                               congestion_mode="auto"),
    "L6-sp-n2r": dict(assignment="spatial", combo="nn-2opt-reinsert",
                      move_swap=False),
    # 묶음 크기 24 성분 분해 축(동결 제안 관련)
    "C1-cap24-sp-nn": dict(assignment="spatial", combo="nn", move_swap=False,
                           requests_per_task=24),
    "C2-cap24-bal-nn": dict(assignment="balanced", combo="nn", move_swap=False,
                            requests_per_task=24),
    "C3-cap24-bal-n2r": dict(assignment="balanced", combo="nn-2opt-reinsert",
                             move_swap=False, requests_per_task=24),
}


def _run(seed, requests=480, pickers=10, warehouse=None, **plan_kw):
    plan_kw.setdefault("combo", "nn")
    cfg = make_run_args(pickers=pickers, seed=seed,
                        requests=requests, **plan_kw)
    if warehouse is not None:
        cfg = replace(cfg, warehouse=warehouse)
    return cfg


# ------------------------------------------------------------------ 개발
def dev_bundle(out):
    runs = []
    for cap in (6, 12, 24):
        for assignment in ("roundrobin", "spatial", "balanced"):
            for combo in ("nn", "nn-2opt-reinsert"):
                for seed in DEV:
                    runs.append(("bundle", f"cap{cap}-{assignment}-{combo}",
                                 _run(seed, requests_per_task=cap,
                                      assignment=assignment, combo=combo,
                                      move_swap=False)))
    return runs


def dev_ladder(out):
    runs = []
    for p in (1, 10, 20):
        for name, kw in LADDER.items():
            for seed in DEV:
                runs.append(("ladder", name, _run(seed, pickers=p, **kw)))
    return runs


def dev_lookahead(out):
    runs = []
    for p in (10, 20):
        for la in (False, True):
            for seed in DEV:
                runs.append(("lookahead", f"p{p}-{'on' if la else 'off'}",
                             _run(seed, pickers=p,
                                  assignment="balanced", combo="nn-2opt-reinsert",
                                  move_swap=True, dropoff_lookahead=la)))
    return runs


def dev_threshold(out):
    runs = []
    for p in (10, 20):
        variants = [("off", dict(congestion_aware=False)),
                    ("v2", dict(congestion_aware=True, congestion_mode="v2")),
                    ("auto15", dict(congestion_aware=True, congestion_mode="auto",
                                    congestion_threshold_s=15.0)),
                    ("auto60", dict(congestion_aware=True, congestion_mode="auto",
                                    congestion_threshold_s=60.0))]
        for name, kw in variants:
            for seed in DEV6:
                args = make_run_args(pickers=p, combo="nn-2opt-reinsert",
                                     seed=seed, requests=240,
                                     assignment="balanced", **kw, **STRESS)
                runs.append((f"threshold-{name}", f"p{p}", args))
    return runs


# ------------------------------------------------------------------ 평가(동결 후)
LARGE_SAME = WarehouseConfig(width=76, height=80, cross_ys=(0, 40, 80),
                             staging=(36, 0), name="warehouse-large-v1")
LARGE_CROSS = WarehouseConfig(width=76, height=80, cross_ys=(0, 20, 40, 60, 80),
                              staging=(36, 0), name="warehouse-largecross-v1")


def eval_ladder(out):
    runs = []
    for p in (1, 10, 20):
        for name, kw in LADDER.items():
            for seed in EVAL10:
                runs.append(("ladder", name,
                             _run(seed, pickers=p, **kw)))
    return runs


def eval_large(out):
    runs = []
    for wh_name, wh in (("large", LARGE_SAME), ("largecross", LARGE_CROSS)):
        for name in ("L1-sp-nn", "L3-bal-n2r", "C3-cap24-bal-n2r"):
            kw = LADDER[name]
            for seed in EVAL10:
                runs.append((f"large-{wh_name}", name,
                             _run(seed, pickers=10, requests=960,
                                  warehouse=wh, **kw)))
    return runs


def eval_workload(out):
    runs = []
    variants = [("hot", dict(hot_aisle_share=0.6, duplicate_share=0.2)),
                ("slow", dict(walk_speed_override=0.7)),
                ("packed70", dict(easy_ratio_override=0.3))]
    for tag, kw in variants:
        for name in ("L1-sp-nn", "C3-cap24-bal-n2r"):
            plan_kw = LADDER[name]
            for seed in EVAL10:
                extra = {}
                if "walk_speed_override" in kw:
                    args = make_run_args(pickers=10, seed=seed, requests=480,
                                         **plan_kw)
                    args = replace(args, pick=replace(args.pick,
                                                      walk_speed_m_s=kw["walk_speed_override"]))
                elif "easy_ratio_override" in kw:
                    args = make_run_args(pickers=10, seed=seed, requests=480,
                                         **plan_kw)
                    args = replace(args, pick=replace(args.pick,
                                                      easy_ratio=kw["easy_ratio_override"]))
                else:
                    args = make_run_args(pickers=10, seed=seed, requests=480,
                                         **plan_kw, **kw)
                runs.append((f"workload-{tag}", name, args))
    return runs


def eval_lookahead(out):
    runs = []
    for p in (10, 20):
        for la in (False, True):
            for seed in EVAL10:
                runs.append(("lookahead", f"p{p}-{'on' if la else 'off'}",
                             _run(seed, pickers=p,
                                  assignment="balanced", combo="nn-2opt-reinsert",
                                  move_swap=True, dropoff_lookahead=la)))
    return runs


BUILDERS = {
    "dev-bundle": dev_bundle, "dev-ladder": dev_ladder,
    "dev-lookahead": dev_lookahead, "dev-threshold": dev_threshold,
    "eval-ladder": eval_ladder, "eval-large": eval_large,
    "eval-workload": eval_workload, "eval-lookahead": eval_lookahead,
}


def main(out_root="results", suites=("dev-all",)):
    from .warehouse import build_warehouse
    groups = {"dev-all": ["dev-bundle", "dev-ladder", "dev-lookahead",
                          "dev-threshold"],
              "eval-all": ["eval-ladder", "eval-large", "eval-workload",
                           "eval-lookahead"]}
    names = groups.get(suites[0], list(suites))
    warehouse = build_warehouse(WarehouseConfig())
    large_cache = {}

    def wh_for(cfg):
        name = cfg.warehouse.name
        if name == WarehouseConfig().name:
            return warehouse
        if name not in large_cache:
            from .warehouse import build_warehouse as bw
            large_cache[name] = bw(cfg.warehouse)
        return large_cache[name]

    for name in names:
        builder = BUILDERS[name]
        prepared = []
        for suite, label, run in builder(out_root):
            prepared.append((f"{suite}|{label}",
                             "dev" if name.startswith("dev-") else "eval", run))
        rows = []
        _execute_wh(prepared, rows, wh_for)
        out_dir = f"{out_root}/multi3-{'dev' if name.startswith('dev-') else 'eval'}"
        _write(out_dir, name, rows)


def _execute_wh(prepared, rows, wh_for):
    """실행 순서 무작위화 + 창고 설정별 캐시 재사용 실행."""
    import random as _r
    from .__main__ import run_once
    order = list(prepared)
    _r.Random(20261121).shuffle(order)
    for i, (suite, split, run) in enumerate(order):
        print(f"[{i+1}/{len(order)}] {suite} p={run.sim.pickers} "
              f"{run.plan.route_combo} {run.plan.assignment} seed={run.sim.seed}",
              file=sys.stderr)
        result = run_once(run, wh_for(run))
        result["suite"], result["split"] = suite, split
        rows.append(result)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0] if args else "results", tuple(args[1:]) or ("dev-all",))
