# -*- coding: utf-8 -*-
"""피드백 반영 보완 실험 (results/multi2, 기존 결과와 분리).

suites:
  fixed-total   전체 요청량 고정(R=480) 작업자 수 비교: p in {5,10,20}
  per-picker    작업자당 요청량 고정(48개=작업4개): p in {5,10,20} -> R in {240,480,960}
  continuous20  20인 연속 작업: R in {240,480,960} (작업/인원 = 1,2,4)
  fixed20       continuous20의 고정 계산 지연 버전(경로 개선 효과와 계산 지연 분리)
  congestion    혼잡 극한 시나리오에서 base vs v1 vs v2 (dev로 방식 비교, eval로 최종)

seed 설계: 개발 4~6개(202~212 짝수), 평가 10개(203~221 홀수) — 기존 6개보다 확대.
실행 순서는 고정 rng로 무작위화한다. 모든 실행에 작업 단위 기록을 남긴다.
"""
import sys

from .__main__ import _execute, _write, make_run_args
from .config import PlanConfig, RunConfig, SimConfig, replace

DEV = (202, 204, 206, 208)
DEV6 = (202, 204, 206, 208, 210, 212)
EVAL10 = (203, 205, 207, 209, 211, 213, 215, 217, 219, 221)
STRESS = dict(hot_aisle_share=0.8, duplicate_share=0.3, zone_length=8.0,
              zone_capacity=2)


def suite_fixed_total(out):
    runs = []
    for p in (5, 10, 20):
        for combo in ("nn", "nn-2opt-reinsert", "alt"):
            for seed in DEV + EVAL10:
                runs.append(("fixed-total", "dev" if seed in DEV else "eval",
                             make_run_args(pickers=p, combo=combo, seed=seed,
                                           requests=480)))
    return runs


def suite_per_picker(out):
    runs = []
    for p in (5, 10, 20):
        for combo in ("nn", "nn-2opt-reinsert"):
            for seed in DEV + EVAL10:
                runs.append(("per-picker", "dev" if seed in DEV else "eval",
                             make_run_args(pickers=p, combo=combo, seed=seed,
                                           requests=p * 48)))
    return runs


def suite_continuous20(out):
    runs = []
    for reqs in (240, 480, 960):
        for combo in ("nn", "nn-2opt-reinsert"):
            for seed in DEV + EVAL10:
                runs.append(("continuous20", "dev" if seed in DEV else "eval",
                             make_run_args(pickers=20, combo=combo, seed=seed,
                                           requests=reqs)))
    return runs


def suite_fixed20(out):
    runs = []
    for reqs in (240, 480, 960):
        for combo in ("nn", "nn-2opt-reinsert"):
            for seed in DEV + EVAL10:
                runs.append(("fixed20", "dev" if seed in DEV else "eval",
                             make_run_args(pickers=20, combo=combo, seed=seed,
                                           requests=reqs, compute_mode="fixed")))
    return runs


def suite_congestion(out):
    runs = []
    for p in (10, 20):
        for method in ("base", "v1", "v2"):
            for seed in DEV6:
                runs.append((f"congestion-dev-{method}", "dev",
                             make_run_args(pickers=p, combo="nn-2opt-reinsert",
                                           seed=seed, requests=240,
                                           assignment="balanced",
                                           congestion_aware=method != "base",
                                           **STRESS)))
    for p in (10, 20):
        for method in ("base", "v1", "v2"):
            for seed in EVAL10:
                runs.append((f"congestion-eval-{method}", "eval",
                             make_run_args(pickers=p, combo="nn-2opt-reinsert",
                                           seed=seed, requests=240,
                                           assignment="balanced",
                                           congestion_aware=method != "base",
                                           **STRESS)))
    return runs


def _mode_of(run, method):
    """congestion-aware 방식(v1/v2)을 PlanConfig.congestion_mode에 반영."""
    if method == "base":
        return run
    return replace(run, plan=replace(run.plan, congestion_mode=method))


def main(out_dir="results/multi2", suites=("all",)):
    from .warehouse import build_warehouse
    builders = {"fixed-total": suite_fixed_total, "per-picker": suite_per_picker,
                "continuous20": suite_continuous20, "fixed20": suite_fixed20,
                "congestion": suite_congestion}
    selected = builders if "all" in suites else {k: builders[k] for k in suites}
    warehouse = build_warehouse()
    for name, builder in selected.items():
        prepared = []
        for suite, split, run in builder(out_dir):
            method = suite.rsplit("-", 2)[-1] if suite.startswith("congestion") else None
            prepared.append((suite, split, _mode_of(run, method) if method else run))
        rows = []
        _execute(prepared, rows, warehouse)
        _write(out_dir, name, rows)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0] if args else "results/multi2",
         tuple(args[1:]) or ("all",))
