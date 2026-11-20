# -*- coding: utf-8 -*-
"""다중 작업자 연속 작업 이벤트 시뮬레이터.

물리 시간(시뮬레이션 초)과 컴퓨터 실행시간을 구분한다. 계획 계산은 순차 자원
하나에서 비선점으로 수행되고, 발급용 경로 계산(ROUTE)이 사전 계산(PREROUTE)과
배정 개선(IMPROVE)보다 우선한다. 계산은 PLAN_START에서 수행해 PLAN_DONE(시작+지속)
시점에 반영하므로 측정 지속시간이 시뮬레이션 시간에 정확히 한 번만 반영된다.

동시 시각 처리: (시각, 우선순위, 순번) 힙 — 완료(0) → 도착/입장(1) → 계획(2).
구역 대기는 도착 순서, 동시 도착은 작업자 ID. 미래 실제 혼잡은 계획에 사용하지
않고 추정만 사용하며, 예측-실제 오차는 작업별로 기록한다.
"""
import heapq
import sys
import time
from collections import defaultdict

from .assignment import Interrupted as AssignInterrupted
from .assignment import task_estimate
from .planner import PlanState, Planner, TaskPlan
from .routes import Interrupted as RouteInterrupted
from .routes import RouteContext
from .warehouse import zone_of

PRIO_DONE, PRIO_ARRIVE, PRIO_PLAN = 0, 1, 2
OPEN_STATUSES = ("pending", "prerouted", "reserved")


def simulate(run_cfg, warehouse, requests, planner_cls=Planner, stop_check=None):
    """전체 실험 1회 실행: 지표·작업 기록·(선택)이벤트 로그 반환.

    stop_check는 계획 단계(초기화·경로·배정 개선·검증 직전)의 협력적 검사점에서
    호출된다. raise하면 해당 후보만 폐기하고 마지막 유효 계획으로 진행하며,
    중단은 plan.aborts에 기록된다.
    """
    t_heap, seq = [], [0]

    def push(at, prio, kind, payload):
        seq[0] += 1
        heapq.heappush(t_heap, (at, prio, seq[0], kind, payload))

    pick_cfg = run_cfg.pick
    speed = pick_cfg.walk_speed_m_s
    cap = pick_cfg.zone_capacity
    n_pickers = run_cfg.sim.pickers
    planner = planner_cls(run_cfg, warehouse)
    state = PlanState()
    request_ids = [r["id"] for r in requests]
    for r in requests:
        if r["location"] not in warehouse.adjacency:
            raise ValueError(f"요청 위치가 지도 노드가 아닙니다: {r['location']}")
    zones = defaultdict(_Zone)
    edge_log = []
    task_records = []
    task_meta = {}
    events_out = [] if run_cfg.sim.record_events else None
    pickers = {i: {"id": i, "node": warehouse.staging, "state": "wait_plan",
                   "task": None, "route_pos": None, "walk_m": 0.0, "pick_s": 0.0,
                   "zone_wait_s": 0.0, "plan_wait_s": 0.0, "tasks": 0,
                   "free_since": 0.0} for i in range(n_pickers)}
    pending_ops, op_seq = [], [0]
    planner_free_at = [0.0]
    plan_stats = {"ops": 0, "preroute_reuse": 0, "improve_rounds": 0,
                  "moves_applied": 0, "improve_discarded": 0, "aborts": []}
    adoption_log = []
    stop_fired = [False]

    def checked_stop():
        """중단 주입 지점: 최초 발생만 기록하고 원래 예외를 전파한다."""
        if stop_check is None:
            return
        try:
            stop_check()
        except BaseException as exc:
            if not stop_fired[0]:
                stop_fired[0] = True
                plan_stats["aborts"].append({"exception": type(exc).__name__})
            raise
    improve_rounds_left = run_cfg.plan.move_swap_rounds if run_cfg.plan.move_swap else 0
    improve_inflight = [False]

    def enqueue_op(prio, op):
        op_seq[0] += 1
        pending_ops.append((prio, op_seq[0], op))

    def schedule_planner(now):
        if not pending_ops or planner_free_at[0] > now:
            return
        prio, s, op = min(pending_ops)
        pending_ops.remove((prio, s, op))
        if op["kind"] == "IMPROVE":
            improve_inflight[0] = True  # 꺼낸 순간부터 실행 전 사이에도 중복 적립 방지
        start = max(now, planner_free_at[0])
        op["requested_at"] = now
        push(start, PRIO_PLAN, "PLAN_START", op)

    def find_task(tid):
        """tid로 작업 찾기. 배정 개선으로 재그룹화되어 사라졌으면 None(폐기)."""
        return next((t for t in state.tasks if t.tid == tid), None)

    def candidates():
        return [t for t in state.tasks if t.status in ("pending", "prerouted")]

    def pick_seconds_at(task, node):
        total = 0.0
        for r in task.requests:
            if r["location"] == node:
                for kind in r["kinds"]:
                    total += pick_cfg.easy_seconds if kind == "easy" else pick_cfg.packed_seconds
        return total

    def pick_seconds_of(task):
        return sum(pick_cfg.easy_seconds if k == "easy" else pick_cfg.packed_seconds
                   for r in task.requests for k in r["kinds"])

    def _walk_to(p, target, now, next_kind):
        src = p["node"]
        if src == target:
            push(now, PRIO_ARRIVE, next_kind, p["id"])
            return
        path = warehouse.path(src, target)
        dist = warehouse.d(src, target)
        t = now
        for a, b in zip(path[:-1], path[1:]):
            seg = warehouse.d(a, b) / speed
            edge_log.append((tuple(sorted((a, b))), t, t + seg, 1 if b > a else -1))
            t += seg
        p["walk_m"] += dist
        push(now + dist / speed, PRIO_ARRIVE, next_kind, p["id"])

    def _start_pick(p, now):
        task = p["task"]
        node = task.route[p["route_pos"]]
        zones[zone_of(node, pick_cfg)].active += 1
        p["state"] = "picking"
        push(now + pick_seconds_at(task, node), PRIO_DONE, "PICK_DONE", (p["id"], node))

    def try_admit(now):
        for zone in zones.values():
            while zone.queue and zone.active < cap:
                arrival, pid = min(zone.queue)
                zone.queue.remove((arrival, pid))
                zone.total_wait += now - arrival
                zone.blocked += 1
                pickers[pid]["zone_wait_s"] += now - arrival
                _start_pick(pickers[pid], now)

    def issue_task(task, picker_id, now, route, route_cost, nn_cost=None):
        task.status, task.route = "issued", route
        p = pickers[picker_id]
        p["state"], p["task"], p["route_pos"] = "walking", task, 0
        p["tasks"] += 1
        p["free_since"] = None
        task.pred_finish = now + route_cost / speed + pick_seconds_of(task) + pick_cfg.unload_seconds
        task_meta[task.tid] = {"nn_cost": nn_cost, "cost": route_cost,
                               "issued_at": now, "start_node": p["node"]}
        if route:
            _walk_to(p, route[0], now, "pick_arrive")
        else:
            _walk_to(p, warehouse.belt_node(p["node"]), now, "belt_arrive")

    def preroute_next(just_issued, now):
        open_tasks = candidates()
        nxt = next((t for t in open_tasks if t.status == "pending"), None)
        if nxt is None or not just_issued.route:
            return
        start = warehouse.belt_node(just_issued.route[-1])
        enqueue_op(2, {"kind": "PREROUTE", "tid": nxt.tid, "start": start})
        schedule_planner(now)

    def next_task_for_picker(p, now):
        open_tasks = candidates()
        if not open_tasks:
            p["state"], p["free_since"] = "done", now
            return
        task = open_tasks[0]
        if task.status == "prerouted" and task.preroute_start == p["node"]:
            plan_stats["preroute_reuse"] += 1
            cost = RouteContext(warehouse, p["node"], task.locations).cost(task.route)
            issue_task(task, p["id"], now, task.route, cost)
            preroute_next(task, now)
            return
        task.status, task.reserved_picker = "reserved", p["id"]
        enqueue_op(0, {"kind": "ROUTE", "tid": task.tid, "picker": p["id"]})
        p["state"], p["free_since"] = "wait_plan", now
        schedule_planner(now)

    def run_op(op, now):
        """PLAN_START: 계산 수행 후 PLAN_DONE을 (now+지속)에 예약한다.

        op가 시작된 순간 계산 자원을 (완료 예정 시각까지) 사용 중으로 표시해,
        실행 중인 op와 다음 op가 겹치지 않게 한다(순차 자원 보장).
        """
        if op["kind"] == "IMPROVE":
            improve_inflight[0] = True
        if op["kind"] == "ROUTE":
            task, p = find_task(op["tid"]), pickers[op["picker"]]
            if task is None or task.status != "reserved":
                return  # 재그룹화 등으로 무효화된 op: 폐기(유효 계획 유지)
            order, nn_cost, cost, duration = planner.route_for(task, p["node"],
                                                               stop_check=checked_stop)
            planner_free_at[0] = now + duration
            push(now + duration, PRIO_PLAN, "PLAN_DONE",
                 {"kind": "ROUTE", "task": task, "picker": p["id"], "route": order,
                  "nn_cost": nn_cost, "cost": cost})
        elif op["kind"] == "PREROUTE":
            task = find_task(op["tid"])
            if task is None or task.status != "pending":
                return
            order, _nn, _cost, duration = planner.route_for(task, op["start"],
                                                            stop_check=checked_stop)
            planner_free_at[0] = now + duration
            push(now + duration, PRIO_PLAN, "PLAN_DONE",
                 {"kind": "PREROUTE", "task": task, "route": order, "start": op["start"]})
        elif op["kind"] == "IMPROVE":
            t_w = time.perf_counter()
            groups = [[r for r in t.requests] for t in candidates() if t.status == "pending"]
            try:
                new_groups = planner.improve_groups(groups, stop_check=checked_stop,
                                                    log=adoption_log)
            except AssignInterrupted:
                plan_stats["ops"] += 1
                planner_free_at[0] = now
                push(now, PRIO_PLAN, "PLAN_DONE", {"kind": "IMPROVE_ABORTED"})
                return
            wall = time.perf_counter() - t_w
            duration = planner.fixed_improve_duration() if planner.mode == "fixed" else wall
            planner.wall_total += wall
            planner_free_at[0] = now + duration
            push(now + duration, PRIO_PLAN, "PLAN_DONE",
                 {"kind": "IMPROVE", "groups": new_groups,
                  "changed": [tuple(r["id"] for r in g) for g in new_groups] !=
                             [tuple(r["id"] for r in g) for g in groups]})
        plan_stats["ops"] += 1

    # ---- 초기 계획(계산은 t=0에 수행, 지속시간 d0 후 반영) ----
    wall0 = time.perf_counter()
    tasks, d0 = planner.initial_plan(requests, stop_check=checked_stop,
                                     log=adoption_log)
    state.tasks = tasks
    ok, why = state.validate(request_ids, run_cfg.plan)
    if not ok:
        raise RuntimeError(f"초기 계획 불변식 위반: {why}")
    push(d0, PRIO_PLAN, "PLAN_DONE", {"kind": "INITIAL"})

    guard = 0
    while t_heap:
        guard += 1
        if guard > 2_000_000:
            raise RuntimeError("이벤트 한도 초과(무한 루프 의심)")
        now, _prio, _, kind, payload = heapq.heappop(t_heap)
        if events_out is not None:
            events_out.append({"t": round(now, 6), "kind": kind,
                               "payload": _brief(payload)})
        if kind == "PLAN_START":
            run_op(payload, now)
        elif kind == "PLAN_DONE":
            planner_free_at[0] = now
            if payload["kind"] == "INITIAL":
                for i, task in enumerate(state.tasks[:n_pickers]):
                    task.status, task.reserved_picker = "reserved", i
                    enqueue_op(0, {"kind": "ROUTE", "tid": task.tid, "picker": i})
                if improve_rounds_left > 0 and len(candidates()) > 1:
                    enqueue_op(2, {"kind": "IMPROVE"})
            elif payload["kind"] == "ROUTE":
                task, pid = payload["task"], payload["picker"]
                p = pickers[pid]
                if p["free_since"] is not None:
                    p["plan_wait_s"] += now - p["free_since"]
                issue_task(task, pid, now, payload["route"], payload["cost"],
                           nn_cost=payload["nn_cost"])
                preroute_next(task, now)
            elif payload["kind"] == "PREROUTE":
                task = payload["task"]
                if task.status == "pending":  # 아직 발급 전이면 사전 경로 저장
                    task.status, task.route = "prerouted", payload["route"]
                    task.preroute_start = payload["start"]
            elif payload["kind"] == "IMPROVE_ABORTED":
                improve_inflight[0] = False  # 중단: 후보 폐기, 마지막 유효 계획 유지
            elif payload["kind"] == "IMPROVE":
                improve_inflight[0] = False
                plan_stats["improve_rounds"] += 1
                improve_rounds_left -= 1
                # 계산 중 발급 예약·사전 계산으로 대상 집합이 바뀌면 폐기(마지막 유효 계획 유지)
                captured = sorted(r["id"] for g in payload["groups"] for r in g)
                current = sorted(r["id"] for t in state.tasks if t.status == "pending"
                                 for r in t.requests)
                if captured != current:
                    plan_stats["improve_discarded"] = plan_stats.get("improve_discarded", 0) + 1
                else:
                    try:
                        checked_stop()  # 최종 검증 직전 중단 지점
                        preserved = [t for t in state.tasks if t.status != "pending"]
                        new_tasks = []
                        for i, group in enumerate(payload["groups"]):
                            t = TaskPlan(tid=10_000 + plan_stats["improve_rounds"] * 1000 + i,
                                         requests=list(group))
                            t.est_time = task_estimate(group, warehouse, warehouse.staging,
                                                       pick_cfg, speed)["time_s"]
                            new_tasks.append(t)
                        candidate = preserved + new_tasks
                        candidate.sort(key=lambda t: (-t.est_time, t.tid))
                        ok, why = PlanState(tasks=list(candidate)).validate(
                            request_ids, run_cfg.plan)
                        if not ok:
                            raise RuntimeError(f"배정 개선 후 불변식 위반: {why}")
                        state.tasks = candidate  # 검증 통과 후에만 반영
                        if payload["changed"]:
                            plan_stats["moves_applied"] += 1
                    except (AssignInterrupted, RouteInterrupted):
                        plan_stats["improve_discarded"] += 1  # 검증 단계 중단: 미반영
            improve_pending = (improve_inflight[0]
                               or any(op[2]["kind"] == "IMPROVE" for op in pending_ops))
            if (improve_rounds_left > 0 and not improve_pending
                    and len([t for t in candidates() if t.status == "pending"]) > 1):
                enqueue_op(2, {"kind": "IMPROVE"})
            schedule_planner(now)
        elif kind == "pick_arrive":
            p = pickers[payload]
            task = p["task"]
            node = task.route[p["route_pos"]]
            p["node"] = node
            zone = zones[zone_of(node, pick_cfg)]
            if zone.active < cap:
                _start_pick(p, now)
            else:
                zone.queue.append((now, p["id"]))
                zone.max_queue = max(zone.max_queue, len(zone.queue))
                p["state"] = "zone_wait"
        elif kind == "PICK_DONE":
            pid, node = payload
            p = pickers[pid]
            task = p["task"]
            zones[zone_of(node, pick_cfg)].active -= 1
            p["pick_s"] += pick_seconds_at(task, node)
            p["route_pos"] += 1
            try_admit(now)
            p["state"] = "walking"
            if p["route_pos"] < len(task.route):
                _walk_to(p, task.route[p["route_pos"]], now, "pick_arrive")
            else:
                _walk_to(p, warehouse.belt_node(node), now, "belt_arrive")
        elif kind == "belt_arrive":
            p = pickers[payload]
            task = p["task"]
            p["node"] = warehouse.belt_node(task.route[-1]) if task.route else p["node"]
            p["state"] = "unloading"
            push(now + pick_cfg.unload_seconds, PRIO_DONE, "UNLOAD_DONE", p["id"])
        elif kind == "UNLOAD_DONE":
            p = pickers[payload]
            task = p["task"]
            task.status = "done"
            meta = task_meta.get(task.tid, {})
            task_records.append({
                "tid": task.tid, "picker": p["id"], "requests": sorted(r["id"] for r in task.requests),
                "issued_at": meta.get("issued_at"), "finished_at": now,
                "pred_finish": task.pred_finish, "nn_cost": meta.get("nn_cost"),
                "final_cost": meta.get("cost"), "start_node": meta.get("start_node"),
            })
            p["task"] = None
            next_task_for_picker(p, now)
    # ---- 지표 집계 ----
    makespan = max((r["finished_at"] for r in task_records), default=0.0)
    for p in pickers.values():
        busy = p["walk_m"] / speed + p["pick_s"]
        p["busy_s"] = busy
        p["idle_s"] = max(0.0, makespan - busy - p["zone_wait_s"] - p["plan_wait_s"])
    pred_errors = [abs(r["pred_finish"] - r["finished_at"])
                   for r in task_records if r["pred_finish"] is not None]
    busy_values = [p["busy_s"] for p in pickers.values()]
    last_task = max(task_records, key=lambda r: r["finished_at"]) if task_records else None
    last_picker = pickers[last_task["picker"]] if last_task else None
    return {
        "last_finisher": (None if last_task is None else {
            "picker": last_task["picker"], "finished_at": last_task["finished_at"],
            "zone_wait_s": last_picker["zone_wait_s"],
            "plan_wait_s": last_picker["plan_wait_s"],
            "walk_m": last_picker["walk_m"], "tasks": last_picker["tasks"],
        }),
        "makespan_s": round(makespan, 6),
        "tasks_done": len(task_records),
        "total_walk_m": round(sum(p["walk_m"] for p in pickers.values()), 6),
        "total_pick_s": round(sum(p["pick_s"] for p in pickers.values()), 6),
        "total_zone_wait_s": round(sum(z.total_wait for z in zones.values()), 6),
        "zone_max_queue": max((z.max_queue for z in zones.values()), default=0),
        "zone_blocked_admissions": sum(z.blocked for z in zones.values()),
        "busy_spread_s": round(max(busy_values) - min(busy_values), 6) if busy_values else 0.0,
        "plan_wait_total_s": round(sum(p["plan_wait_s"] for p in pickers.values()), 6),
        "idle_total_s": round(sum(p["idle_s"] for p in pickers.values()), 6),
        "plan": {"ops": plan_stats["ops"], "wall_seconds": round(planner.wall_total, 6),
                 "sim_delay_seconds": round(planner.sim_delay_total, 6),
                 "preroute_reuse": plan_stats["preroute_reuse"],
                 "improve_rounds": plan_stats["improve_rounds"],
                 "moves_applied": plan_stats["moves_applied"],
                 "improve_discarded": plan_stats["improve_discarded"],
                 "aborts": plan_stats["aborts"],
                 "adoption_log": adoption_log},
        "prediction_mae_s": round(sum(pred_errors) / len(pred_errors), 6) if pred_errors else None,
        "prediction_tasks": len(pred_errors),
        "edge_overlap_pairs": _count_overlaps(edge_log),
        "route_cost_nn_total": round(sum(r["nn_cost"] or 0 for r in task_records), 6),
        "route_cost_final_total": round(sum(r["final_cost"] or 0 for r in task_records), 6),
        "wall_run_seconds": round(time.perf_counter() - wall0, 6),
        "pickers": {i: {k: (round(v, 6) if isinstance(v, float) else v)
                        for k, v in p.items() if k != "task"}
                    for i, p in pickers.items()},
        "task_records": task_records,
        "events": events_out,
    }


class _Zone:
    def __init__(self):
        self.active = 0
        self.queue = []
        self.total_wait = 0.0
        self.max_queue = 0
        self.blocked = 0


def _brief(payload):
    if isinstance(payload, dict):
        return {k: v for k, v in payload.items()
                if k not in ("task", "groups", "route")}
    return payload


def _count_overlaps(edge_log):
    by_edge = defaultdict(list)
    for edge, t0, t1, direction in edge_log:
        by_edge[edge].append((t0, t1, direction))
    same = opposite = 0
    for spans in by_edge.values():
        spans.sort()
        for i in range(len(spans)):
            for j in range(i + 1, len(spans)):
                if spans[j][0] < spans[i][1] - 1e-9:
                    if spans[i][2] == spans[j][2]:
                        same += 1
                    else:
                        opposite += 1
                else:
                    break
    return {"same_direction": same, "opposite_direction": opposite}
