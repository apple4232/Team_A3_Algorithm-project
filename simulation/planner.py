# -*- coding: utf-8 -*-
"""계획 상태와 계획기: 유효 계획 불변식, 순차 계산 자원, 중단 안전.

- 계획 = 전체 요청을 정확히 한 번씩 포함하는 작업들의 나열(불변식).
- 개선(경로·배정)은 복사본에서 평가하고 검증 뒤 한 번에 반영하며, 예산 초과·
  중단 시 마지막 유효 계획을 유지한다(routes.improve의 BudgetExceeded 처리와
  동일 원칙).
- 계산 시간: measured 모드는 실제 실행시간을 측정해 시뮬레이션 시간에 반영하고,
  fixed 모드는 고정 지연을 사용한다(재현성 테스트). 이중 계산은 하지 않는다.
"""
import time
from dataclasses import dataclass, field

from .assignment import (chunk_requests, completion_schedule, ensure_task_count,
                         improve_assignment, rebalance_chunks, roundrobin_chunks,
                         savings_bundles, task_estimate)
from .routes import RouteContext, improve as improve_route

VALID_STATUSES = ("pending", "prerouted", "reserved", "issued", "done")


@dataclass
class TaskPlan:
    tid: int
    requests: list
    status: str = "pending"           # pending → prerouted → issued → done
    route: list | None = None         # 방문 순서(발급 시 확정)
    reserved_picker: int | None = None
    assigned_picker: int | None = None   # completion 배정이 지정한 담당 작업자
    preroute_start: tuple | None = None
    est_time: float = 0.0
    pred_finish: float | None = None

    @property
    def locations(self):
        return tuple(sorted({r["location"] for r in self.requests}))


@dataclass
class PlanState:
    tasks: list = field(default_factory=list)

    def pending(self):
        return [t for t in self.tasks if t.status == "pending"]

    def validate(self, request_ids, plan_cfg):
        """불변식: 전체 요청 정확히 1회 배정, 작업 상한 준수, 상태 전이 정상."""
        seen = []
        for t in self.tasks:
            if t.status not in VALID_STATUSES:
                return False, f"잘못된 상태: {t.status}"
            if len(t.requests) > plan_cfg.requests_per_task:
                return False, "작업당 요청 수 상한 위반"
            if plan_cfg.quantity_per_task and \
                    sum(r["qty"] for r in t.requests) > plan_cfg.quantity_per_task:
                return False, "작업당 수량 상한 위반"
            seen += [r["id"] for r in t.requests]
        if sorted(seen) != sorted(request_ids):
            return False, "요청이 정확히 한 번씩 배정되지 않음"
        return True, "ok"


class Planner:
    """순차 계산 자원 하나를 사용하는 계획기(ops의 실제 수행은 simulator가 호출)."""

    def __init__(self, run_cfg, warehouse):
        self.run = run_cfg
        self.warehouse = warehouse
        self.mode = run_cfg.sim.compute_mode
        self.wall_total = 0.0
        self.phases = {}
        self.lns_log = []
        self.sim_delay_total = 0.0
        self.ops_count = 0

    def _timed(self, fn):
        """계산을 수행하고 (결과, 반영할 계산 지속시간)을 반환한다."""
        if self.mode == "fixed":
            result = fn()
            duration = None  # 호출자가 fixed 값을 사용
            return result, duration
        t0 = time.perf_counter()
        result = fn()
        wall = time.perf_counter() - t0
        self.wall_total += wall
        return result, wall

    def initial_plan(self, requests, stop_check=None, log=None):
        """전체 요청 → (작업들, 소요). 단계별 계산시간을 self.phases에 기록.

        파이프라인: 묶음(chunk|savings) → 배정(spatial|balanced|roundrobin|completion)
        → (선택) 가변 묶음 분할 → (선택) 이동·교환(off 권장) → (선택) LNS.
        completion 배정은 묶음별 담당 작업자를 지정하고 이동·교환을 건너뛴다
        (발급 예약 변경 범위를 LNS와 구분하기 위함).
        """
        from time import perf_counter
        plan_cfg = self.run.plan
        pick_cfg = self.run.pick
        staging = self.warehouse.staging
        speed = pick_cfg.walk_speed_m_s
        self.phases = {}

        def timed_phase(name, fn):
            t0 = perf_counter()
            out = fn()
            self.phases[name] = round(perf_counter() - t0, 4)
            return out

        lns_log = []

        def compute():
            def do_bundle():
                if getattr(plan_cfg, "bundling", "chunk") == "savings":
                    return savings_bundles(requests, plan_cfg, self.warehouse, staging,
                                           pick_cfg, speed, stop_check=stop_check)
                if plan_cfg.assignment == "roundrobin":
                    return roundrobin_chunks(requests, plan_cfg, staging)
                return chunk_requests(requests, plan_cfg)

            groups = timed_phase("bundling", do_bundle)
            if plan_cfg.assignment == "balanced":
                groups = timed_phase("balance",
                                     lambda: rebalance_chunks(groups, self.warehouse,
                                                              staging, pick_cfg, speed,
                                                              plan_cfg))
            if getattr(plan_cfg, "variable_cap", False):
                groups = timed_phase("variable_cap",
                                     lambda: ensure_task_count(groups, plan_cfg,
                                                               self.warehouse, staging,
                                                               pick_cfg, speed,
                                                               self.run.sim.pickers))
            assign = None
            if plan_cfg.assignment == "completion":
                ordered, assign, _ = timed_phase("completion",
                                                 lambda: completion_schedule(
                                                     groups, self.warehouse, staging,
                                                     pick_cfg, speed,
                                                     self.run.sim.pickers))
                groups = ordered
            elif plan_cfg.move_swap:
                groups = timed_phase("move_swap",
                                     lambda: improve_assignment(groups, self.warehouse,
                                                                staging, self.run,
                                                                stop_check=stop_check,
                                                                log=log))
            if getattr(plan_cfg, "lns", False):
                def do_lns():
                    from .lns import lns_improve
                    out, stats = lns_improve(groups, self.warehouse, staging,
                                             self.run, stop_check=stop_check,
                                             log=lns_log)
                    self.phases["lns_stats"] = stats
                    return out
                groups = timed_phase("lns", do_lns)
            return groups, assign

        (groups, assign), wall = self._timed(compute)
        if self.mode == "fixed":
            duration = self.run.sim.fixed_initial_plan_s
        else:
            duration = wall
        self.sim_delay_total += duration
        self.ops_count += 1
        tasks = []
        for i, group in enumerate(groups):
            est = task_estimate(group, self.warehouse, staging, pick_cfg, speed)
            t = TaskPlan(tid=i, requests=list(group), est_time=est["time_s"])
            t.assigned_picker = assign[i] if assign else None
            tasks.append(t)
        # 긴 작업 먼저 발급(결정론적 정렬)
        tasks.sort(key=lambda t: (-t.est_time, t.tid))
        for i, t in enumerate(tasks):
            t.tid = i
        self.lns_log = lns_log
        return tasks, duration

    def route_for(self, task, start_node, stop_check=None):
        """발급용 경로 계산: 조합 적용 + NN 기준 비용. (route, nn_cost, cost, duration)"""
        plan_cfg = self.run.plan
        locations = task.locations

        def compute():
            ctx = RouteContext(self.warehouse, start_node, locations)
            order = improve_route(ctx, plan_cfg.route_combo,
                                  budget=plan_cfg.improvement_eval_budget,
                                  segdp_window=plan_cfg.segdp_window,
                                  segdp_step=plan_cfg.segdp_step,
                                  stop_check=stop_check)
            nn = improve_route(ctx, "nn")  # 기록용 NN 기준(같은 측정 구간에 포함)
            return ctx, order, ctx.cost(nn), ctx.cost(order)

        (ctx, order, nn_cost, cost), wall = self._timed(compute)
        duration = self.run.sim.fixed_wave_s if self.mode == "fixed" else wall
        self.sim_delay_total += duration
        self.ops_count += 1
        return order, nn_cost, cost, duration

    def improve_groups(self, groups, stop_check=None, log=None):
        """발급 전 이동·교환(혼잡 고려 옵션). 지속시간은 호출자가 계산."""
        return improve_assignment(groups, self.warehouse, self.warehouse.staging,
                                  self.run, stop_check=stop_check, log=log)

    def fixed_improve_duration(self):
        return self.run.sim.fixed_wave_s
