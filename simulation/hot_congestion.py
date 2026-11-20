# -*- coding: utf-8 -*-
"""집중(혼잡 유발) 시나리오에서 혼잡 고려 배정 개선 비교 보조 실험.

균등 작업에서는 구역 대기 자체가 0에 가까워 혼잡 고려의 효과를 측정할 수
없다(주 실험 결과 참조). 이 스크립트는 한 통로 집중+중복 요청+구역 확대
시나리오에서 congestion_aware on/off를 같은 seed 쌍으로 비교한다.

Usage: python -m simulation.hot_congestion [out_dir]
"""
import json
import random
import sys
from pathlib import Path

from .__main__ import _execute, _write, make_run_args


def main(out_dir="results/multi"):
    runs = []
    for p in (10, 20):
        for congestion in (False, True):
            for seed in (203, 205, 207, 209, 211, 213):
                runs.append(("congestion-hot", "eval", make_run_args(
                    pickers=p, combo="nn-2opt-reinsert", seed=seed, requests=240,
                    assignment="balanced", congestion_aware=congestion,
                    hot_aisle_share=0.6, duplicate_share=0.2,
                    zone_length=8.0, zone_capacity=3)))
    rows = []
    from .warehouse import build_warehouse
    _execute(runs, rows, build_warehouse())
    _write(out_dir, "congestion-hot", rows)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/multi")
