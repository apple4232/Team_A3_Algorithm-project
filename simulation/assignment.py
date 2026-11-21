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


def roundrobin_chunks(requests, plan_cfg, staging):
    """단순 기준 배정: 집결지 거리 -> 좌표 정렬 후 K개 작업에 번갈아 배분.

    근접 묶음 없이 고르게 나누는 약한 기준(비교용). 처리 순서는
    (집결지 통로거리 근사, x, y, id) 정렬, 동률은 정렬 순서, 상한은
    작업별 요청 수/수량을 존중한다.
    """
    import math
    ordered = sorted(requests, key=lambda r: (abs(r["location"][0] - staging[0])
                                              + abs(r["location"][1] - staging[1]),
                                              r["location"][0], r["location"][1], r["id"]))
    n_tasks = max(1, math.ceil(len(ordered) / max(1, plan_cfg.requests_per_task)))
    chunks = [[] for _ in range(n_tasks)]
    qty = [0] * n_tasks
    slot = 0
    for r in ordered:
        placed = False
        for _ in range(n_tasks):
            i = slot % n_tasks
            slot += 1
            cap_qty = plan_cfg.quantity_per_task
            if len(chunks[i]) + 1 <= plan_cfg.requests_per_task and                     (not cap_qty or qty[i] + r["qty"] <= cap_qty):
                chunks[i].append(r)
                qty[i] += r["qty"]
                placed = True
                break
        if not placed:  # 모든 슬롯 포화(수량 상한 혼합) -> 추가 작업
            chunks.append([r])
            qty.append(r["qty"])
    return [c for c in chunks if c]


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


class Interrupted(Exception):
    """협력적 중단(테스트 주입용). 부분 결과를 버리고 마지막 유효 상태를 유지한다."""


def group_profile(g, warehouse, staging, pick_cfg, walk_speed):
    """작업 하나의 추정 프로파일: 시간·거리·구역별 수거 구간(상대시각)."""
    est = task_estimate(g, warehouse, staging, pick_cfg, walk_speed)
    route = est["route"]
    per_leg = est["walk_s"] / max(1, len(route))
    t, spans = 0.0, []
    for node in route:
        t += per_leg
        dur = sum(pick_cfg.easy_seconds if k == "easy" else pick_cfg.packed_seconds
                  for r in g if r["location"] == node for k in r["kinds"])
        spans.append((zone_of(node, pick_cfg), t, t + dur))
        t += dur
    return {"time_s": est["time_s"], "distance_m": est["distance_m"], "spans": spans}


def staggered_starts_from(times, n_pickers):
    """LPT 근사 시작시각(추정시간만 사용, 계획 시점 정보)."""
    order = sorted(range(len(times)), key=lambda i: (-times[i], i))
    free = [0.0] * max(1, n_pickers)
    starts = [0.0] * len(times)
    for i in order:
        j = min(range(len(free)), key=lambda k: (free[k], k))
        starts[i] = free[j]
        free[j] = starts[i] + times[i]
    return starts


def staggered_starts(groups, warehouse, staging, pick_cfg, walk_speed, n_pickers):
    """LPT 근사로 각 작업의 예상 시작시각(하위 호환 래퍼)."""
    times = [task_estimate(g, warehouse, staging, pick_cfg, walk_speed)["time_s"]
             for g in groups]
    return staggered_starts_from(times, n_pickers), times


def _wait_from_profiles(profiles, starts, capacity):
    """분산 시작 스케줄 위 구역 겹침 대기 추정(v2, 프로파일 재사용)."""
    intervals = defaultdict(list)
    for prof, t0 in zip(profiles, starts):
        for zone, s, e in prof["spans"]:
            intervals[zone].append((t0 + s, t0 + e))
    wait = 0.0
    for spans in intervals.values():
        spans.sort()
        for i, (s1, e1) in enumerate(spans):
            overlapping = sum(1 for s2, e2 in spans if s2 < e1 - EPS and s1 < e2 - EPS)
            if overlapping > capacity:
                avg = sum(e - s for s, e in spans) / len(spans)
                wait += (overlapping - capacity) * avg / max(1, overlapping)
    return wait


def congestion_wait_estimate_v2(groups, warehouse, staging, pick_cfg, walk_speed,
                                capacity, n_pickers):
    """분산 시작 스케줄 위의 구역 겹침 대기 추정(v2).

    v1은 모든 작업이 t약 0에 동시 시작한다고 가정해 작업 수 > 작업자 수일 때
    대기를 과대 추정했다. v2는 LPT 분산 시작 시각 위에 수거 구간을 놓는다.
    """
    profiles = [group_profile(g, warehouse, staging, pick_cfg, walk_speed)
                for g in groups]
    starts = staggered_starts_from([p["time_s"] for p in profiles], n_pickers)
    return _wait_from_profiles(profiles, starts, capacity)


def _tuple_less(a, b):
    """사전순 개선 판정(첫 성분은 EPS 허용, 이후 성분은 엄격한 사전순)."""
    if a[0] < b[0] - EPS:
        return True
    if abs(a[0] - b[0]) <= EPS:
        return a[1:] < b[1:]
    return False


def improve_assignment(groups, warehouse, staging, run_cfg, round_budget=None,
                       stop_check=None, log=None):
    """발급 전 작업 간 요청 이동·교환으로 계획 시점 목적함수를 개선한다.

    - off: max 추정시간 감소(거리 중심).
    - v1(참조용): 동시 시작 가정 대기 추정을 균등 분배해 시간에 합산.
    - v2: (LPT 추정 종료시간, 분산 시작 대기 추정, 총 거리) 사전순 개선.
    추정 프로파일은 요청 조합별로 캐시해 반복 평가 비용을 줄인다.
    stop_check가 raise하면 그 즉시 현재(마지막 유효) 그룹을 반환한다.
    """
    pick_cfg, plan_cfg = run_cfg.pick, run_cfg.plan
    speed = pick_cfg.walk_speed_m_s
    n_pickers = run_cfg.sim.pickers
    mode = getattr(plan_cfg, "congestion_mode", "v2") if plan_cfg.congestion_aware else "off"
    threshold = getattr(plan_cfg, "congestion_threshold_s", 30.0)
    groups = [list(g) for g in groups]
    if not groups:
        return groups
    profiles = {}

    def prof_of(g):
        key = tuple(sorted(r["id"] for r in g))
        if key not in profiles:
            profiles[key] = group_profile(g, warehouse, staging, pick_cfg, speed)
        return profiles[key]

    def check_stop():
        if stop_check is not None:
            stop_check()

    def objective(gs):
        pr = [prof_of(g) for g in gs]
        times = [p["time_s"] for p in pr]
        if mode == "off":
            return (max(times),)
        if mode == "auto":
            # 계획 시점 예상 대기가 임계 미만이면 혼잡 고려를 적용하지 않는다.
            starts0 = staggered_starts_from(times, n_pickers)
            if _wait_from_profiles(pr, starts0, pick_cfg.zone_capacity) < threshold:
                return (max(times),)
        if mode == "v1":
            extra = congestion_wait_estimate(gs, warehouse, staging, pick_cfg,
                                             speed, pick_cfg.zone_capacity)
            return (max(t + extra / max(1, len(gs)) for t in times),)
        starts = staggered_starts_from(times, n_pickers)
        makespan = max(starts[i] + times[i] for i in range(len(gs)))
        wait = _wait_from_profiles(pr, starts, pick_cfg.zone_capacity)
        dist = sum(p["distance_m"] for p in pr)
        return (makespan, wait, dist)

    rounds = plan_cfg.move_swap_rounds if round_budget is None else round_budget
    try:
        for round_no in range(rounds):
            check_stop()
            current = objective(groups)
            hi = max(range(len(groups)), key=lambda k: (prof_of(groups[k])["time_s"], -k))
            best = None  # (objective, kind, hi, j, r_hi, r_j|None)
            for j in range(len(groups)):
                if j == hi or not groups[hi]:
                    continue
                for r in groups[hi]:
                    check_stop()
                    new_hi = [x for x in groups[hi] if x["id"] != r["id"]]
                    if not new_hi:  # 빈 작업 생성 금지
                        continue
                    new_j = groups[j] + [r]
                    if len(new_j) > plan_cfg.requests_per_task:
                        continue
                    if plan_cfg.quantity_per_task and \
                            sum(x["qty"] for x in new_j) > plan_cfg.quantity_per_task:
                        continue
                    trial = list(groups)
                    trial[hi], trial[j] = new_hi, new_j
                    cand = objective(trial)
                    if _tuple_less(cand, current) and (best is None or _tuple_less(cand, best[0])):
                        best = (cand, "move", hi, j, r, None)
            if best is None:  # 이동 개선 없으면 교환 탐색
                for j in range(len(groups)):
                    if j == hi or not groups[hi] or not groups[j]:
                        continue
                    for r_hi in groups[hi]:
                        for r_j in groups[j]:
                            check_stop()
                            new_hi = [x for x in groups[hi] if x["id"] != r_hi["id"]] + [r_j]
                            new_j = [x for x in groups[j] if x["id"] != r_j["id"]] + [r_hi]
                            if plan_cfg.quantity_per_task and (
                                    sum(x["qty"] for x in new_hi) > plan_cfg.quantity_per_task or
                                    sum(x["qty"] for x in new_j) > plan_cfg.quantity_per_task):
                                continue
                            trial = list(groups)
                            trial[hi], trial[j] = new_hi, new_j
                            cand = objective(trial)
                            if _tuple_less(cand, current) and (best is None or _tuple_less(cand, best[0])):
                                best = (cand, "swap", hi, j, r_hi, r_j)
            if best is None:
                break
            _, kind, hi2, j2, r_hi, r_j = best
            if kind == "move":
                groups[hi2] = [x for x in groups[hi2] if x["id"] != r_hi["id"]]
                groups[j2] = groups[j2] + [r_hi]
            else:
                groups[hi2] = [x for x in groups[hi2] if x["id"] != r_hi["id"]] + [r_j]
                groups[j2] = [x for x in groups[j2] if x["id"] != r_j["id"]] + [r_hi]
            if log is not None and len(log) < 50:
                log.append({"round": round_no, "kind": kind,
                            "objective_before": [round(v, 3) for v in current],
                            "objective_after": [round(v, 3) for v in objective(groups)]})
        return groups
    except Interrupted:
        return groups  # 중단 시 마지막 유효 그룹 반환


# ==================================================================
# 거리 절약 기반 묶음 · 예상 종료시간 배정 · 가변 묶음 (3차 입증용)
# ==================================================================

def _bundle_estimate(requests, warehouse, start, pick_cfg, speed):
    """NN 근사 경로 기반 묶음 추정(시작점 start, 벨트 종료 비용 포함)."""
    return task_estimate(requests, warehouse, start, pick_cfg, speed)


def savings_bundles(requests, plan_cfg, warehouse, staging, pick_cfg, speed,
                    neighbor_k=8, stop_check=None):
    """거리 절약 기반 묶음 구성.

    - 초기 묶음: 동일 위치 요청을 미리 병합(방문 병합·수거시간 합산 반영).
    - 병합 절약 = est(A) + est(B) - est(A∪B). est는 NN 근사 경로에
      컨베이어 종료 비용(최근접 접근)을 포함하며 시작점은 집결지(배정 전
      가상 기준 위치 — 배정 후에도 절약이 유지되는지 실험에서 확인).
    - 후보는 중심(평균 좌표) 유클리드 근사 거리 k-nearest로 제한(가지치기 규칙).
    - 상한: 요청 수 cap(수량 상한 설정 시 함께 존중), 선택적 max_task_seconds.
    - 절약 내림차순, 동률은 (절약, 병합 후 요청 수, 대표 요청 id) 사전순 — 결정론.
    """
    import heapq
    from time import perf_counter
    cap = plan_cfg.requests_per_task
    cap_qty = plan_cfg.quantity_per_task
    max_task_s = getattr(plan_cfg, "max_task_seconds", None)

    by_loc = {}
    for r in requests:
        by_loc.setdefault(r["location"], []).append(r)
    bundles = {i: list(v) for i, v in enumerate(sorted(by_loc.values(),
                                                       key=lambda g: (g[0]["location"], g[0]["id"])))}
    alive = set(bundles)

    def est(bid):
        return _bundle_estimate(bundles[bid], warehouse, staging, pick_cfg, speed)["time_s"]

    def merge_ok(a, b):
        merged = bundles[a] + bundles[b]
        if len(merged) > cap:
            return False
        if cap_qty and sum(r["qty"] for r in merged) > cap_qty:
            return False
        if max_task_s is not None:
            if _bundle_estimate(merged, warehouse, staging, pick_cfg, speed)["time_s"] > max_task_s:
                return False
        return True

    def neighbors(a):
        cx = sum(r["location"][0] for r in bundles[a]) / len(bundles[a])
        cy = sum(r["location"][1] for r in bundles[a]) / len(bundles[a])
        cand = sorted(alive, key=lambda b: ((sum(r["location"][0] for r in bundles[b]) / len(bundles[b]) - cx) ** 2
                                            + (sum(r["location"][1] for r in bundles[b]) / len(bundles[b]) - cy) ** 2,
                                           min(r["id"] for r in bundles[b])))
        return [b for b in cand if b != a][:neighbor_k]

    heap = []
    rev = 0

    def push(a, b):
        nonlocal rev
        if not merge_ok(a, b):
            return
        saving = est(a) + est(b) - _bundle_estimate(bundles[a] + bundles[b], warehouse,
                                                    staging, pick_cfg, speed)["time_s"]
        if saving > 1e-9:
            heapq.heappush(heap, (-saving, len(bundles[a]) + len(bundles[b]),
                                  min(r["id"] for r in bundles[a]),
                                  min(r["id"] for r in bundles[b]), rev, a, b))
        rev += 1

    for a in list(alive):
        for b in neighbors(a):
            if a < b:
                push(a, b)
    while heap:
        if stop_check is not None:
            stop_check()
        neg, _, _, _, _, a, b = heapq.heappop(heap)
        if a not in alive or b not in alive or not merge_ok(a, b):
            continue
        saving = est(a) + est(b) - _bundle_estimate(bundles[a] + bundles[b], warehouse,
                                                    staging, pick_cfg, speed)["time_s"]
        if saving < (-neg) - 1e-9:  # 지연 갱신: 다시 투입
            heapq.heappush(heap, (-saving, len(bundles[a]) + len(bundles[b]),
                                  min(r["id"] for r in bundles[a]),
                                  min(r["id"] for r in bundles[b]), rev, a, b))
            rev += 1
            continue
        keep, drop = (a, b) if min(r["id"] for r in bundles[a]) <= min(r["id"] for r in bundles[b]) else (b, a)
        bundles[keep] = bundles[keep] + bundles[drop]
        alive.discard(drop)
        for nb in neighbors(keep):
            push(keep, nb)
    return [bundles[i] for i in sorted(alive, key=lambda i: min(r["id"] for r in bundles[i]))]


_EST_CACHE = {}


def cached_est(requests, warehouse, start, pick_cfg, speed):
    key = (start, tuple(sorted(r["id"] for r in requests)))
    hit = _EST_CACHE.get(key)
    if hit is None:
        hit = task_estimate(requests, warehouse, start, pick_cfg, speed)
        if len(_EST_CACHE) > 200000:
            _EST_CACHE.clear()
        _EST_CACHE[key] = hit
    return hit


def completion_schedule(bundles, warehouse, staging, pick_cfg, speed, n_pickers):
    """예상 종료시간 기반 배정(계획 시점 정보만 사용).

    묶음을 추정 소요 내림차순(동률은 대표 요청 id)으로 검사하고, 각 묶음을
    finish_j = avail[j] + d(pos[j], 첫 방문)/speed + 수거 + 벨트 이동/하차
    를 최소화하는 작업자에 배정한다. pos[j] 갱신: 첫 작업은 집결지, 이후는
    해당 묶음 NN 경로의 마지막 위치에서 최근접 벨트 접근 노드(예측).
    10초/30초 수거시간과 수량은 task_estimate의 수거 합계에 반영된다.
    반환: (순서있는 묶음 리스트, 각 묶음의 배정 작업자, 추정 종료시각 목록).
    """
    ests = [_bundle_estimate(b, warehouse, staging, pick_cfg, speed) for b in bundles]
    order = sorted(range(len(bundles)),
                   key=lambda i: (-ests[i]["time_s"], min(r["id"] for r in bundles[i])))
    avail = [0.0] * max(1, n_pickers)
    pos = [staging] * max(1, n_pickers)
    assign, finish = [None] * len(bundles), [0.0] * len(bundles)
    for i in order:
        best_j, best_f = None, None
        for j in range(max(1, n_pickers)):
            est = cached_est(bundles[i], warehouse, pos[j], pick_cfg, speed)
            f = avail[j] + est["time_s"]
            if best_f is None or f < best_f - 1e-9 or (abs(f - best_f) <= 1e-9 and j < best_j):
                best_j, best_f = j, f
        assign[i] = best_j
        finish[i] = best_f
        avail[best_j] = best_f
        route = cached_est(bundles[i], warehouse, pos[best_j], pick_cfg, speed)["route"]
        pos[best_j] = warehouse.belt_node(route[-1]) if route else pos[best_j]
    return [bundles[i] for i in order], [assign[i] for i in order], [finish[i] for i in order]


def expected_makespan(bundles, warehouse, staging, pick_cfg, speed, n_pickers):
    """completion_schedule 기준 추정 전체 종료시간(LNS 채택 목적함수)."""
    _, _, finish = completion_schedule(bundles, warehouse, staging, pick_cfg,
                                       speed, n_pickers)
    return max(finish) if finish else 0.0


def ensure_task_count(bundles, plan_cfg, warehouse, staging, pick_cfg, speed,
                      n_pickers, min_tasks=None):
    """가변 묶음 제한: 작업 수가 작업자 수 미만이면 가장 긴 묶음을 분할.

    분할은 요청 id 정렬 후 절반 나누기(결정론). 상한 초과 분할은 허용되지
    않으므로 cap 이하 묶음에서만 발생. 남는 작업자가 있으면 부하가 커지는
    조건을 방지하기 위한 최소한의 규칙이다.
    """
    min_tasks = min_tasks if min_tasks is not None else n_pickers
    bundles = [list(b) for b in bundles]
    cap = plan_cfg.requests_per_task
    while len(bundles) < min_tasks:
        idx = max(range(len(bundles)),
                  key=lambda i: (_bundle_estimate(bundles[i], warehouse, staging,
                                                  pick_cfg, speed)["time_s"], -i))
        if len(bundles[idx]) < 2:
            break
        group = sorted(bundles[idx], key=lambda r: r["id"])
        half = len(group) // 2
        bundles[idx] = group[:half] if len(group[:half]) <= cap else group[:cap]
        bundles.append(group[len(bundles[idx]):])
    return bundles
