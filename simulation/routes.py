# -*- coding: utf-8 -*-
"""작업 경로(방문 순서) 최적화 — 거리 전처리와 분리된 순수 순서 알고리즘.

모든 알고리즘은 RouteContext 위에서 동작한다:
- 시작점은 작업자의 이전 하차 위치(첫 작업은 집결지)로 고정.
- 종료 비용 end_cost(v) = v에서 벨트까지 통로 최단거리(min over 접근 노드).
  마지막 방문 위치가 바뀌면 종료 비용을 다시 계산한다(요구 사양).
- 재삽입: 순회 시작 시 방문 순서대로 검사, 모든 삽입 자리 중 최선 채택.
- 2-opt: 고정 후보 순서에서 첫 개선 채택 후 재탐색.
- 교대 반복: 개선 없거나 평가 예산 소진 시 종료.
- 구간 DP: 창(기본 6)·간격(기본 3) 한 번 순회, 마지막 창 포함, 창 내 완전 최적.
평가 예산은 협력적 상한(횟수 계산)이며 초과 시 BudgetExceeded.
"""
from itertools import permutations

EPS = 1e-9


class BudgetExceeded(Exception):
    pass


class RouteContext:
    """{시작점} ∪ 위치 들의 거리와 벨트 종료 비용 캐시."""

    def __init__(self, warehouse, start, locations):
        self.warehouse = warehouse
        self.start = start
        self.locations = tuple(sorted(set(locations)))
        self._end = {}

    def d(self, a, b):
        return self.warehouse.d(a, b)

    def end_cost(self, v):
        if v not in self._end:
            self._end[v] = self.warehouse.belt_cost(v)
        return self._end[v]

    def cost(self, order):
        if not order:
            return self.end_cost(self.start)
        total = self.d(self.start, order[0])
        for a, b in zip(order[:-1], order[1:]):
            total += self.d(a, b)
        return total + self.end_cost(order[-1])


class _Meter:
    def __init__(self, budget):
        self.left = budget

    def spend(self, n=1):
        self.left -= n
        if self.left < 0:
            raise BudgetExceeded


def nn_order(ctx: RouteContext):
    unvisited = set(ctx.locations)
    current, order = ctx.start, []
    while unvisited:
        following = min(unvisited, key=lambda p: (ctx.d(current, p), p))
        order.append(following)
        unvisited.remove(following)
        current = following
    return order


def two_opt(ctx: RouteContext, order, meter: _Meter):
    """첫 개선 채택 후 처음부터 재탐색. 고정 순서 (i<j) 열거."""
    order = list(order)
    while True:
        improved = False
        for i in range(len(order) - 1):
            for j in range(i + 1, len(order)):
                meter.spend()
                candidate = order[:i] + list(reversed(order[i:j + 1])) + order[j + 1:]
                if ctx.cost(candidate) < ctx.cost(order) - EPS:
                    order = candidate
                    improved = True
                    break
            if improved:
                break
        if not improved:
            return order


def reinsert(ctx: RouteContext, order, meter: _Meter):
    """순회 시작 시점의 방문 순서대로 각 위치를 검사해 최선 삽입 자리로 이동."""
    order = list(order)
    snapshot = list(order)
    for element in snapshot:
        meter.spend()
        if element not in order:
            continue
        i = order.index(element)
        rest = order[:i] + order[i + 1:]
        best_order, best_cost = order, ctx.cost(order)
        for j in range(len(rest) + 1):
            meter.spend()
            candidate = rest[:j] + [element] + rest[j:]
            c = ctx.cost(candidate)
            if c < best_cost - EPS:
                best_order, best_cost = candidate, c
        order = best_order
    return order


def segment_dp(ctx: RouteContext, order, meter: _Meter, window=6, step=3):
    """연속 window개 위치를 양 경계 고정 후 창 내 완전 탐색(DP)으로 재배열.

    경계 진입/이탈 비용(왼쪽 경계→첫 위치, 마지막 위치→오른쪽 경계 또는 벨트)을
    목적함수에 포함한다. 채택은 전체 경로 비용이 실제로 줄 때만.
    """
    order = list(order)
    n = len(order)
    if n == 0:
        return order
    starts = list(range(0, max(1, n - window + 1), step))
    if n > window and starts[-1] != n - window:
        starts.append(n - window)
    for s in starts:
        meter.spend()
        e = min(s + window, n)
        seg = order[s:e]
        left = ctx.start if s == 0 else order[s - 1]
        right = ("END",) if e == n else order[e]
        best_seg, best_total = _window_exact(ctx, seg, left, right, meter)
        candidate = order[:s] + best_seg + order[e:]
        if ctx.cost(candidate) < ctx.cost(order) - EPS:
            order = candidate
    return order


def _window_exact(ctx, seg, left, right, meter):
    """left → perm(seg) → right 의 최적 순열(작은 창이므로 열거, 동률은 사전순)."""
    best, best_total = None, None
    for p in permutations(seg):
        meter.spend()
        total = ctx.d(left, p[0]) + sum(ctx.d(a, b) for a, b in zip(p[:-1], p[1:]))
        total += ctx.end_cost(p[-1]) if right == ("END",) else ctx.d(p[-1], right)
        if best_total is None or total < best_total - EPS or \
           (abs(total - best_total) <= EPS and p < best):
            best, best_total = p, total
    return list(best) if best else [], best_total


def improve(ctx: RouteContext, combo: str, order=None, budget=20000,
            segdp_window=6, segdp_step=3):
    """조합 이름에 따라 경로를 개선한다. 중단 시 마지막 유효 경로 반환."""
    meter = _Meter(budget)
    order = list(order if order is not None else nn_order(ctx))
    try:
        if combo == "nn":
            pass
        elif combo == "nn-2opt":
            order = two_opt(ctx, order, meter)
        elif combo == "nn-reinsert":
            order = reinsert(ctx, order, meter)
        elif combo == "nn-2opt-reinsert":
            order = reinsert(ctx, two_opt(ctx, order, meter), meter)
        elif combo == "nn-reinsert-2opt":
            order = two_opt(ctx, reinsert(ctx, order, meter), meter)
        elif combo == "alt":
            while True:
                before = ctx.cost(order)
                order = two_opt(ctx, order, meter)
                order = reinsert(ctx, order, meter)
                if ctx.cost(order) >= before - EPS:
                    break
        elif combo == "nn-2opt-reinsert-segdp":
            order = reinsert(ctx, two_opt(ctx, order, meter), meter)
            order = segment_dp(ctx, order, meter, segdp_window, segdp_step)
        else:
            raise ValueError(f"알 수 없는 조합: {combo}")
    except BudgetExceeded:
        pass  # 협력적 예산: 마지막 유효 경로 반환
    return order


def brute_force_best(ctx: RouteContext):
    """테스트용 전열거 최적(위치 수 ≤ 7 권장)."""
    if not ctx.locations:
        return [], ctx.cost([])
    best, best_total = None, None
    for p in permutations(ctx.locations):
        c = ctx.cost(list(p))
        if best_total is None or c < best_total - EPS:
            best, best_total = list(p), c
    return best, best_total
