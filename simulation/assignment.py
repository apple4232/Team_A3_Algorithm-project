# -*- coding: utf-8 -*-
"""작업 분할·배정: 거리 중심 청크, 작업량 균형, 발급 전 요청 이동·교환.

추정 시간 = 이동(NN 경로 거리/보행속도) + 수거(품목별 10/30초 합) + 하차 5초.
계획 시점에는 실제 혼잡을 모르므로 추정만 사용하고, 혼잡 고려 모드에서는
구역별 예상 구간 겹침으로 대기 추정을 더한다(실제 결과를 읽지 않는다).
"""
from collections import defaultdict

from .routes import RouteContext, nn_order
from .warehouse import zone_of

EPS = 1e-9


def sort_key(requests):
    """공간 응집을 위한 정렬 키: 통로 → 위치."""
    return sorted(requests, key=lambda r: (r["location"][0], r["location"][1], r["id"]))


def chunk_requests(requests, plan_cfg):
    """정렬된 요청을 상한(요청 수/수량)을 넘지 않는 연속 청크로 나눈다."""
    ordered = sort_key(requests)
    chunks, current, qty = [], [], 0
    for r in ordered:
        cap_req = plan_cfg.requests_per_task
        cap_qty = plan_cfg.quantity_per_task
        if current and (len(current) + 1 > cap_req or (cap_qty and qty + r["qty"] > cap_qty)):
            chunks.append(current)
            current, qty = [], 0
        current.append(r)
        qty += r["qty"]
    if current:
        chunks.append(current)
    return chunks


def pick_seconds(group, pick_cfg):
    total = 0.0
    for r in group:
        for kind in r["kinds"]:
            total += pick_cfg.easy_seconds if kind == "easy" else pick_cfg.packed_seconds
    return total


def task_estimate(group, warehouse, start, pick_cfg, walk_speed):
    """작업 하나의 독립 추정(시작 위치 가정). 혼잡 미포함."""
    locations = {r["location"] for r in group}
    ctx = RouteContext(warehouse, start, locations)
    order = nn_order(ctx)
    distance = ctx.cost(order)
    walk = distance / walk_speed
    pick = pick_seconds(group, pick_cfg)
    return {"time_s": walk + pick + pick_cfg.unload_seconds,
            "distance_m": distance, "pick_s": pick, "walk_s": walk,
            "route": order}


def rebalance_chunks(chunks, warehouse, staging, pick_cfg, walk_speed, plan_cfg,
                     max_rounds=50):
    """청크 경계의 요청을 옮겨 추정 완료시간 편차(최대-최소)를 줄인다(상한 준수)."""
    chunks = [list(c) for c in chunks]
    def est(c):
        return task_estimate(c, warehouse, staging, pick_cfg, walk_speed)["time_s"]
    for _ in range(max_rounds):
        ests = [est(c) for c in chunks]
        lo, hi = ests.index(min(ests)), ests.index(max(ests))
        if ests[hi] - ests[lo] <= EPS or len(chunks[hi]) <= 1:
            break
        donor, receiver = chunks[hi], chunks[lo]
        moved = False
        for r in sorted(donor, key=lambda r: (abs(r["location"][0] - staging[0]),
                                              r["location"][1], r["id"])):
            candidate_d = [x for x in donor if x is not r]
            candidate_r = receiver + [r]
            if not candidate_d or len(candidate_r) > plan_cfg.requests_per_task:
                continue
            if plan_cfg.quantity_per_task and \
                    sum(x["qty"] for x in candidate_r) > plan_cfg.quantity_per_task:
                continue
            new_hi = max(est(candidate_d), est(candidate_r))
            others = [est(c) for i, c in enumerate(chunks) if i not in (hi, lo)]
            new_spread = max([new_hi] + others) - min([est(candidate_d), est(candidate_r)] + others)
            if new_spread < (ests[hi] - ests[lo]) - EPS:
                chunks[hi], chunks[lo] = candidate_d, candidate_r
                moved = True
                break
        if not moved:
            break
    return chunks


def congestion_wait_estimate(groups, warehouse, staging, pick_cfg, walk_speed, capacity):
    """구역별 예상 수거 구간 겹침으로 대기 초 추정(계획 시점 휴리스틱).

    각 작업의 예상 타임라인(순차 가정)에서 구역 방문 구간을 뽑고, 같은 구역에서
    동시 수거 인원을 초과하는 겹침에 대해 초과 인원×평균 수거시간/인원수를 더한다.
    """
    intervals = defaultdict(list)
    for group in groups:
        est = task_estimate(group, warehouse, staging, pick_cfg, walk_speed)
        t = est["walk_s"]  # staging 출발 가정(순차 시작 근사)
        start_node = staging
        for node in est["route"]:
            t += warehouse.d(start_node, node) / walk_speed
            pick = sum(pick_cfg.easy_seconds if k == "easy" else pick_cfg.packed_seconds
                       for r in group if r["location"] == node for k in r["kinds"])
            intervals[zone_of(node, pick_cfg)].append((t, t + pick))
            t += pick
            start_node = node
    wait = 0.0
    for zone, spans in intervals.items():
        spans.sort()
        for i, (s1, e1) in enumerate(spans):
            overlapping = sum(1 for s2, e2 in spans if s2 < e1 - EPS and s1 < e2 - EPS)
            if overlapping > capacity:
                avg = sum(e - s for s, e in spans) / len(spans)
                wait += (overlapping - capacity) * avg / max(1, overlapping)
    return wait


def improve_assignment(groups, warehouse, staging, run_cfg, round_budget=None):
    """발급 전 작업 간 요청 이동·교환으로 추정 완료시간(최대)을 줄인다.

    - 이동: 최대 추정 작업의 각 요청을 다른 작업으로 옮겼을 때의 max 개선 평가.
    - 교환: 이동으로 개선이 없을 때, 최대 작업의 각 요청과 상대 작업의 각 요청을
      1:1로 맞교환(개수 불변, 수량 상한만 재확인).
    - 혼잡 고려 모드에서는 대기 추정을 균등 분배해 작업별 추정에 더해 비교한다.
    추정 캐시로 변경된 두 작업만 재계산한다.
    """
    pick_cfg, plan_cfg = run_cfg.pick, run_cfg.plan
    speed = pick_cfg.walk_speed_m_s
    groups = [list(g) for g in groups]
    if not groups:
        return groups
    cache = {}

    def est(g):
        key = tuple(sorted(r["id"] for r in g))
        if key not in cache:
            cache[key] = task_estimate(g, warehouse, staging, pick_cfg, speed)["time_s"]
        return cache[key]

    def objective_after(hi, j, new_hi, new_j):
        """hi, j 두 작업만 바뀐 상태의 max 추정시간."""
        values = [est(g) for k, g in enumerate(groups) if k not in (hi, j)]
        values += [est(new_hi), est(new_j)]
        if plan_cfg.congestion_aware:
            trial = [g for k, g in enumerate(groups)]
            trial[hi], trial[j] = new_hi, new_j
            extra = congestion_wait_estimate(trial, warehouse, staging, pick_cfg, speed,
                                             pick_cfg.zone_capacity)
            values = [v + extra / max(1, len(groups)) for v in values]
        return max(values)

    rounds = plan_cfg.move_swap_rounds if round_budget is None else round_budget
    for _ in range(rounds):
        current_max = max(est(g) for g in groups)
        hi = max(range(len(groups)), key=lambda k: (est(groups[k]), -k))
        best = None  # (gain, kind, hi, j, r_hi, r_j|None)
        for j in range(len(groups)):
            if j == hi or not groups[hi]:
                continue
            for r in groups[hi]:
                new_hi = [x for x in groups[hi] if x["id"] != r["id"]]
                if not new_hi:  # 빈 작업 생성 금지
                    continue
                new_j = groups[j] + [r]
                if len(new_j) > plan_cfg.requests_per_task:
                    continue
                if plan_cfg.quantity_per_task and \
                        sum(x["qty"] for x in new_j) > plan_cfg.quantity_per_task:
                    continue
                gain = current_max - objective_after(hi, j, new_hi, new_j)
                if gain > EPS and (best is None or gain > best[0]):
                    best = (gain, "move", hi, j, r, None)
        if best is None:  # 이동으로 개선 없으면 교환 탐색
            for j in range(len(groups)):
                if j == hi or not groups[hi] or not groups[j]:
                    continue
                for r_hi in groups[hi]:
                    for r_j in groups[j]:
                        new_hi = [x for x in groups[hi] if x["id"] != r_hi["id"]] + [r_j]
                        new_j = [x for x in groups[j] if x["id"] != r_j["id"]] + [r_hi]
                        if plan_cfg.quantity_per_task and (
                                sum(x["qty"] for x in new_hi) > plan_cfg.quantity_per_task or
                                sum(x["qty"] for x in new_j) > plan_cfg.quantity_per_task):
                            continue
                        gain = current_max - objective_after(hi, j, new_hi, new_j)
                        if gain > EPS and (best is None or gain > best[0]):
                            best = (gain, "swap", hi, j, r_hi, r_j)
        if best is None:
            break
        _, kind, hi, j, r_hi, r_j = best
        if kind == "move":
            groups[hi] = [x for x in groups[hi] if x["id"] != r_hi["id"]]
            groups[j] = groups[j] + [r_hi]
        else:
            groups[hi] = [x for x in groups[hi] if x["id"] != r_hi["id"]] + [r_j]
            groups[j] = [x for x in groups[j] if x["id"] != r_j["id"]] + [r_hi]
    return groups
