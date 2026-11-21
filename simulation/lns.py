# -*- coding: utf-8 -*-
"""병목 작업 대상 제한적 LNS(초기 구현: 병목 제거 + 최선 삽입).

- 대상: 예상 종료가 가장 늦은 미발급 묶음(병목). 제거 요청은 묶음 중심에서
  가장 먼 요청 q개(병목 연산자) 또는 고정 seed 무작위 q개(무작위 연산자).
- 복구: 제거 요청을 (제거된 묶음 포함) 각 미발급 묶음에 삽입해 추정 종료시간
  증가가 가장 작은 곳에 배치(단순 최선 삽입; regret-2는 별도 후보).
- 채택 기준: 추정 전체 종료시간(completion_schedule 기반) 감소. 거리 감소만으로
  종료시간 악화를 허용하지 않는다.
- 예산: 반복 횟수 제한과 wall-clock 제한을 구분해 적용. 중단(예산 초과·stop_check)
  시 마지막 완전한 유효 계획(묶음 리스트)을 반환한다.
- 상태: 복사본에서 완성·검증(전체 요청 정확히 1회, 상한 준수) 후 한 번에 반영.
"""
import random
import time
from collections import defaultdict

from .assignment import completion_schedule, expected_makespan

EPS = 1e-9


def _validate(bundles, request_ids, plan_cfg):
    seen = []
    for b in bundles:
        if len(b) > plan_cfg.requests_per_task:
            return False
        if plan_cfg.quantity_per_task and \
                sum(r["qty"] for r in b) > plan_cfg.quantity_per_task:
            return False
        seen += [r["id"] for r in b]
    return sorted(seen) == sorted(request_ids)


def lns_improve(bundles, warehouse, staging, run_cfg, stop_check=None, log=None):
    """제한적 LNS. 묶음 리스트를 개선해 반환(불변식 위반 시 원본 반환)."""
    plan_cfg, pick_cfg = run_cfg.plan, run_cfg.pick
    speed = pick_cfg.walk_speed_m_s
    n_pickers = run_cfg.sim.pickers
    request_ids = [r["id"] for b in bundles for r in b]
    max_iters = getattr(plan_cfg, "lns_iters", 20)
    time_budget = getattr(plan_cfg, "lns_time_budget_s", 2.0)
    q = max(1, getattr(plan_cfg, "lns_remove_q", 4))
    rng = random.Random(getattr(plan_cfg, "lns_seed", 0))
    current = [list(b) for b in bundles]
    best_obj = expected_makespan(current, warehouse, staging, pick_cfg, speed, n_pickers)
    t0 = time.perf_counter()
    iters = aborts = 0
    try:
        for it in range(max_iters):
            if stop_check is not None:
                stop_check()
            if time.perf_counter() - t0 > time_budget:
                aborts += 1
                break
            iters += 1
            trial = [list(b) for b in current]
            _, assign, finish = completion_schedule(trial, warehouse, staging,
                                                    pick_cfg, speed, n_pickers)
            if not finish:
                break
            # 병목 묶음(동률은 대표 요청 id)
            bi = max(range(len(trial)), key=lambda i: (finish[i],
                                                       -min(r["id"] for r in trial[i])))
            use_random = (it % 2 == 1)  # 교대: 병목 중심 / 고정 seed 무작위
            group = sorted(trial[bi], key=lambda r: r["id"])
            if use_random or len(group) <= q:
                removed = rng.sample(group, min(q, len(group)))
            else:
                cx = sum(r["location"][0] for r in group) / len(group)
                cy = sum(r["location"][1] for r in group) / len(group)
                removed = sorted(group, key=lambda r: (-abs(r["location"][0] - cx)
                                                       - abs(r["location"][1] - cy),
                                                       r["id"]))[:q]
            trial[bi] = [r for r in trial[bi] if r["id"] not in {x["id"] for x in removed}]
            if not trial[bi]:
                trial.pop(bi)
            # 최선 삽입 복구(제거 요청 id 오름차순 — 결정론)
            for r in sorted(removed, key=lambda x: x["id"]):
                best_k, best_obj_r = None, None
                for k in range(len(trial)):
                    if len(trial[k]) + 1 > plan_cfg.requests_per_task:
                        continue
                    if plan_cfg.quantity_per_task and \
                            sum(x["qty"] for x in trial[k]) + r["qty"] > plan_cfg.quantity_per_task:
                        continue
                    cand = trial[k] + [r]
                    obj = expected_makespan(trial[:k] + [cand] + trial[k + 1:],
                                            warehouse, staging, pick_cfg, speed,
                                            n_pickers)
                    if best_obj_r is None or obj < best_obj_r - EPS:
                        best_obj_r, best_k = obj, k
                if best_k is None:  # 삽입 불가(용량) → 새 묶음
                    trial.append([r])
                else:
                    trial[best_k] = trial[best_k] + [r]
            if not _validate(trial, request_ids, plan_cfg):
                aborts += 1
                continue
            obj = expected_makespan(trial, warehouse, staging, pick_cfg, speed,
                                    n_pickers)
            if obj < best_obj - EPS:
                current, best_obj = trial, obj
                if log is not None and len(log) < 50:
                    log.append({"iter": it, "op": "rand" if use_random else "bottleneck",
                                "objective": round(obj, 3)})
    except Exception:
        aborts += 1
    return current, {"iters": iters, "aborts": aborts,
                     "wall_s": round(time.perf_counter() - t0, 4),
                     "objective": round(best_obj, 3)}
