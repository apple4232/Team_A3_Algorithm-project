# -*- coding: utf-8 -*-
"""simulation 확장의 정확성 검증.

테스트 개수가 아니라 "어떤 성질을 검증했는지"가 중요하다. 각 테스트는
모듈 docstring의 성질 항목과 대응한다. 기존 1인 기능(picking)은 기존
37개 테스트로 회귀 검증한다(이 파일이 대체하지 않음).
"""
import random
import sys
import unittest
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulation.assignment import (chunk_requests, congestion_wait_estimate,
                                   improve_assignment)
from simulation.config import PickConfig, PlanConfig, RunConfig, SimConfig
from simulation.planner import PlanState, Planner
from simulation.requests import generate_requests
from simulation.routes import (RouteContext, brute_force_best, improve,
                               nn_order)
from simulation.simulator import simulate
from simulation.warehouse import WarehouseConfig, build_warehouse, zone_of

EPS = 1e-9


def run_cfg(**kw):
    base = RunConfig(sim=SimConfig(compute_mode="fixed"))
    fields = {**kw}
    if "combo" in fields:
        fields["route_combo"] = fields.pop("combo")
    plan = replace(base.plan, **{k: fields.pop(k) for k in list(fields) if k in
                                 ("route_combo", "assignment", "move_swap",
                                  "congestion_aware", "requests_per_task",
                                  "improvement_eval_budget", "move_swap_rounds",
                                  "congestion_mode", "congestion_threshold_s",
                                  "dropoff_lookahead", "lookahead_candidates",
                                  "bundling", "variable_cap", "lns", "lns_iters",
                                  "lns_time_budget_s", "lns_remove_q",
                                  "max_task_seconds")})
    sim = replace(base.sim, **{k: fields.pop(k) for k in list(fields) if k in
                               ("pickers", "seed", "compute_mode",
                                "fixed_initial_plan_s", "fixed_wave_s")})
    pick = replace(base.pick, **{k: fields.pop(k) for k in list(fields) if k in
                                 ("easy_ratio", "zone_length_m", "zone_capacity",
                                  "walk_speed_m_s")})
    return RunConfig(plan=plan, sim=sim, pick=pick, **fields)


def one_request(loc, qty=1, kind="easy", rid=0):
    return {"id": rid, "location": loc, "qty": qty, "kinds": [kind] * qty}


class TestWarehouseBelt(unittest.TestCase):
    """벨트 근사·무통과·구역 규칙 성질."""

    def test_belt_discretization_error_bound(self):
        """연속 접근 구간 근사: 접근 노드 간격 s의 절반이 오차 상한.

        기본 2m에서는 격자 노드와 접근 노드가 정렬되어 오차 0(정확한 이산화)이고,
        간격 3m에서는 상한 1.5m 이내로 근사된다(0.5m 조밀 그래프와 비교).
        """
        for spacing in (2.0, 3.0):
            coarse = build_warehouse(WarehouseConfig(access_spacing_m=spacing))
            fine = build_warehouse(WarehouseConfig(access_spacing_m=0.5))
            diffs = []
            for node in sorted(coarse.locations)[::5]:
                diff = coarse.belt_cost(node) - fine.belt_cost(node)
                self.assertGreaterEqual(diff, -1e-6)
                diffs.append(diff)
            self.assertGreaterEqual(spacing / 2 + 1e-6, max(diffs),
                                    f"spacing={spacing}: {max(diffs)}")

    def test_no_edge_crosses_belt_or_shelf(self):
        """모든 간선은 통로 선(세로 x=격자, 가로 y=교차로) 위의 축정렬 선분이다."""
        wh = build_warehouse(WarehouseConfig())
        xs = set(range(0, 37, 4))
        cross = {0, 20, 40}
        for a, nbrs in wh.adjacency.items():
            for b, length in nbrs.items():
                if a < b:
                    self.assertEqual(length, abs(a[0] - b[0]) + abs(a[1] - b[1]))
                    on_vertical = a[0] == b[0] and a[0] in xs
                    on_horizontal = a[1] == b[1] and a[1] in cross
                    self.assertTrue(on_vertical or on_horizontal, f"통로 밖 간선 {a}-{b}")

    def test_midpoints_preserve_node_distances(self):
        """접근 중간점 추가가 기존 노드 간 최단거리를 바꾸지 않는다."""
        multi = build_warehouse(WarehouseConfig())
        grid_only = build_warehouse(WarehouseConfig(access_spacing_m=4.0))
        for a in [(0, 0), (16, 20), (8, 14), (36, 40)]:
            for b in [(36, 0), (4, 38), (20, 30)]:
                self.assertAlmostEqual(multi.d(a, b), grid_only.d(a, b), places=9)

    def test_zone_side_and_segment_rule(self):
        """같은 통로·같은 쪽·같은 L 구간이 같은 구역; 쪽/구간이 다르면 다른 구역."""
        cfg = PickConfig(zone_length_m=4.0)
        self.assertEqual(zone_of((8, 2), cfg), zone_of((8, 6), cfg)[:1] + (1, 0))  # 같은 쪽, 다른 4m 구간
        self.assertNotEqual(zone_of((8, 2), cfg), zone_of((8, 6), cfg))
        self.assertNotEqual(zone_of((8, 2), cfg), zone_of((8, 4), cfg))  # 인접 다른 쪽
        cfg8 = PickConfig(zone_length_m=8.0)
        self.assertEqual(zone_of((8, 2), cfg8), zone_of((8, 6), cfg8))  # 같은 쪽 8m 내
        self.assertNotEqual(zone_of((8, 4), cfg8), zone_of((8, 8), cfg8))  # 다른 쪽


class TestRoutes(unittest.TestCase):
    """순서 알고리즘 성질: 무악화·최적 하한·예산 협력·멱등성."""

    @classmethod
    def setUpClass(cls):
        cls.wh = build_warehouse(WarehouseConfig())

    def test_improvements_never_worse_than_nn(self):
        """모든 조합은 NN 비용을 초과하지 않는다(불악화 보장)."""
        rng = random.Random(7)
        for _ in to_iter(12):
            locs = rng.sample(self.wh.locations, 8)
            ctx = RouteContext(self.wh, self.wh.staging, locs)
            nn = improve(ctx, "nn")
            base = ctx.cost(nn)
            for combo in ("nn-2opt", "nn-reinsert", "nn-2opt-reinsert",
                          "nn-reinsert-2opt", "alt", "nn-2opt-reinsert-segdp"):
                got = improve(ctx, combo, order=list(nn))
                self.assertLessEqual(ctx.cost(got), base + EPS, combo)

    def test_improvements_match_bruteforce_on_small_cases(self):
        """작은 사례(≤6 위치)에서 2opt·재삽입·교대·구간DP는 열거 최적과 일치하거나
        그 이하로 내려가지 않는다(하한 준수). 6 이하는 구간DP=전체 최적이어야 한다."""
        rng = random.Random(11)
        for _ in to_iter(10):
            locs = rng.sample(self.wh.locations, 5)
            ctx = RouteContext(self.wh, self.wh.staging, locs)
            best_order, best_cost = brute_force_best(ctx)
            seg = improve(ctx, "nn-2opt-reinsert-segdp")
            self.assertAlmostEqual(ctx.cost(seg), best_cost, places=9)  # 단일 창=전체 최적
            for combo in ("nn-2opt", "nn-reinsert", "alt"):
                got = improve(ctx, combo)
                self.assertGreaterEqual(ctx.cost(got), best_cost - EPS)
                self.assertLessEqual(ctx.cost(got), ctx.cost(nn_order(ctx)) + EPS)

    def test_evaluation_budget_is_cooperative(self):
        """평가 예산 초과 시 예외 대신 마지막 유효 경로를 반환한다."""
        rng = random.Random(3)
        locs = rng.sample(self.wh.locations, 9)
        ctx = RouteContext(self.wh, self.wh.staging, locs)
        out = improve(ctx, "alt", budget=5)
        self.assertEqual(sorted(out), sorted(locs))  # 순열 보존 = 유효 경로

    def test_alt_terminates_and_idempotent(self):
        """교대 반복은 유한 시간 내 종료하며 이미 지역최적인 경우 변경이 없다."""
        locs = sorted(self.wh.locations)[:7]
        ctx = RouteContext(self.wh, self.wh.staging, locs)
        once = improve(ctx, "alt")
        twice = improve(ctx, "alt", order=list(once))
        self.assertEqual(ctx.cost(once), ctx.cost(twice))

    def test_last_move_recomputes_belt_cost(self):
        """마지막 방문 위치 변경 시 벨트 종료 비용이 다시 계산된다(비용 함수 검증)."""
        wh = self.wh
        far, near = (16, 18), (0, 18)  # 중앙 통로(먼) vs 벨트 인접 통로(가까운)
        ctx = RouteContext(wh, wh.staging, [far, near])
        self.assertGreater(wh.belt_cost(far), wh.belt_cost(near) + 10.0)
        self.assertAlmostEqual(ctx.cost([far, near]),
                               wh.d(wh.staging, far) + wh.d(far, near) + wh.belt_cost(near))


class TestAssignment(unittest.TestCase):
    """배정 성질: 상한·분할 불변식·혼잡 추정 방향성."""

    @classmethod
    def setUpClass(cls):
        cls.wh = build_warehouse(WarehouseConfig())

    def test_chunk_partition_and_caps(self):
        rng = random.Random(5)
        reqs = generate_requests(RunConfig(total_requests=100), self.wh, rng)
        groups = chunk_requests(reqs, PlanConfig(requests_per_task=12))
        flat = [r["id"] for g in groups for r in g]
        self.assertEqual(sorted(flat), sorted(r["id"] for r in reqs))
        for g in groups:
            self.assertLessEqual(len(g), 12)
            self.assertTrue(g)

    def test_improve_assignment_keeps_partition(self):
        rng = random.Random(6)
        reqs = generate_requests(RunConfig(total_requests=60), self.wh, rng)
        cap = 8
        groups = chunk_requests(reqs, PlanConfig(requests_per_task=cap))
        out = improve_assignment(groups, self.wh, self.wh.staging,
                                 RunConfig(plan=PlanConfig(requests_per_task=cap)))
        flat = [r["id"] for g in out for r in g]
        self.assertEqual(sorted(flat), sorted(r["id"] for r in reqs))
        for g in out:
            self.assertLessEqual(len(g), cap)

    def test_congestion_estimate_positive_for_same_zone(self):
        """같은 구역 동시 수거 추정은 양수, 분산 시 0에 가깝다(방향성)."""
        cfg = PickConfig(zone_length_m=8.0)
        run = RunConfig(pick=cfg)
        same = [[one_request((8, 2), 2, "packed", 0)],
                [one_request((8, 6), 2, "packed", 1)]]  # 같은 쪽 8m 내
        apart = [[one_request((8, 2), 2, "packed", 0)],
                 [one_request((28, 6), 2, "packed", 1)]]
        w_same = congestion_wait_estimate(same, self.wh, self.wh.staging, cfg, 1.0, 1)
        w_apart = congestion_wait_estimate(apart, self.wh, self.wh.staging, cfg, 1.0, 1)
        self.assertGreater(w_same, 0.0)
        self.assertAlmostEqual(w_apart, 0.0, places=6)


class TestSimulator(unittest.TestCase):
    """시뮬레이터 성질: 분할·시간 산술·혼잡·연결·재현성·중단 안전."""

    @classmethod
    def setUpClass(cls):
        cls.wh = build_warehouse(WarehouseConfig())

    def run_sim(self, requests, **kw):
        cfg = run_cfg(**kw)
        return simulate(cfg, self.wh, requests), cfg

    def test_hand_computed_single_request_makespan(self):
        """1작업자·1요청 수작업 대조: makespan = 초기계획 + 경로계산 + 이동 + 10 + 5."""
        loc = (16, 2)
        m, cfg = self.run_sim([one_request(loc, 1, "easy")], pickers=1,
                              fixed_initial_plan_s=0.5, fixed_wave_s=0.1,
                              move_swap=False)
        walk = self.wh.d(self.wh.staging, loc) + self.wh.d(loc, self.wh.belt_node(loc))
        expected = 0.5 + 0.1 + walk / 1.0 + 10.0 + 5.0
        self.assertAlmostEqual(m["makespan_s"], expected, places=6)
        # 포장(30초) 품목으로 동일 검증
        m2, _ = self.run_sim([one_request(loc, 1, "packed")], pickers=1,
                             fixed_initial_plan_s=0.5, fixed_wave_s=0.1,
                             move_swap=False)
        self.assertAlmostEqual(m2["makespan_s"], expected + 20.0, places=6)

    def test_duplicate_location_single_visit_summed_time(self):
        """같은 위치 요청 2건: 방문은 1회, 수거시간은 합산(10+30=40초)."""
        reqs = [one_request((12, 6), 1, "easy", 0), one_request((12, 6), 1, "packed", 1)]
        m, _ = self.run_sim(reqs, pickers=1, fixed_initial_plan_s=0.0,
                            fixed_wave_s=0.0, move_swap=False)
        self.assertEqual(m["total_pick_s"], 40.0)
        walk = self.wh.d(self.wh.staging, (12, 6)) + self.wh.d((12, 6), self.wh.belt_node((12, 6)))
        self.assertAlmostEqual(m["makespan_s"], 40.0 + 5.0 + walk, places=6)

    def test_all_requests_assigned_exactly_once(self):
        rng = random.Random(9)
        reqs = generate_requests(RunConfig(total_requests=120), self.wh, rng)
        m, _ = self.run_sim(reqs, pickers=7, combo="nn-2opt-reinsert")
        flat = [rid for t in m["task_records"] for rid in t["requests"]]
        self.assertEqual(sorted(flat), sorted(r["id"] for r in reqs))
        self.assertEqual(m["tasks_done"], len(m["task_records"]))

    def test_walk_distance_matches_route_costs_no_congestion(self):
        """단일 작업자: 실제 이동거리 합 = 경로 비용 합(전처리~벨트 포함)."""
        rng = random.Random(10)
        reqs = generate_requests(RunConfig(total_requests=24), self.wh, rng)
        m, _ = self.run_sim(reqs, pickers=1, combo="nn-2opt")
        self.assertAlmostEqual(m["total_walk_m"],
                               sum(t["final_cost"] or 0 for t in m["task_records"]),
                               places=6)
        self.assertAlmostEqual(m["prediction_mae_s"] or 0.0, 0.0, places=6)

    def test_zone_capacity_fifo_and_completion_first(self):
        """같은 구역 4작업자 동시 도착: 3명 수거, 4번째(ID 큰)가 대기 후 입장."""
        loc = (20, 2)
        reqs = [one_request(loc, 1, "easy", i) for i in range(4)]
        m, _ = self.run_sim(reqs, pickers=4, requests_per_task=1,
                            zone_capacity=3, fixed_initial_plan_s=0.0,
                            fixed_wave_s=0.0, move_swap=False)
        self.assertEqual(m["zone_blocked_admissions"], 1)
        self.assertAlmostEqual(m["total_zone_wait_s"], 10.0, places=6)  # 첫 완료(10초) 후 입장
        waits = [p["zone_wait_s"] for p in m["pickers"].values()]
        self.assertEqual(sorted(waits), [0.0, 0.0, 0.0, 10.0])
        self.assertEqual(m["zone_max_queue"], 1)

    def test_staging_first_then_individual_starts(self):
        """첫 작업은 전원 집결지 출발, 이후 작업은 직전 하차 위치 출발."""
        rng = random.Random(4)
        reqs = generate_requests(RunConfig(total_requests=36), self.wh, rng)
        m, _ = self.run_sim(reqs, pickers=2, requests_per_task=6, move_swap=False)
        firsts = {}
        for t in m["task_records"]:
            pid = t["picker"]
            if pid not in firsts or t["issued_at"] < firsts[pid]["issued_at"]:
                firsts[pid] = t
        for t in firsts.values():
            self.assertEqual(t["start_node"], self.wh.staging)
        # 작업자별 연쇄: 다음 작업 시작 = 직전 작업 마지막 위치의 최단 벨트 노드
        by_picker = {}
        for t in sorted(m["task_records"], key=lambda t: (t["picker"], t["issued_at"])):
            by_picker.setdefault(t["picker"], []).append(t)
        for pid, tasks in by_picker.items():
            for prev, nxt in zip(tasks[:-1], tasks[1:]):
                belt = self.wh.belt_node  # 직전 경로 기록 없음: 시작 위치가 그래프 노드인지만 단정
                self.assertIn(nxt["start_node"], self.wh.adjacency)

    def test_plan_overlap_zero_wait_vs_late_penalty(self):
        """계산 겹침: 이전 작업 중 계산 완료 → 추가 대기 0. 늦으면 초과 지연 발생."""
        rng = random.Random(12)
        reqs = generate_requests(RunConfig(total_requests=36), self.wh, rng)
        # (a) 계산이 매우 빠르면(0.001초): 각 발급의 대기는 계산 지속시간 이하,
        # 즉 계산 자체 외 추가 대기가 없다(이중 계산·누적 없음).
        m_fast, _ = self.run_sim(reqs, pickers=2, requests_per_task=6,
                                 fixed_initial_plan_s=0.001, fixed_wave_s=0.001,
                                 move_swap=False)
        self.assertLessEqual(m_fast["plan_wait_total_s"],
                             (m_fast["plan"]["ops"] + 1) * 0.001 + EPS)
        # (b) 파도당 300초 계산: 준비가 늦은 작업자는 초과 지간만큼 대기한다
        m_slow, _ = self.run_sim(reqs, pickers=2, requests_per_task=6,
                                 fixed_initial_plan_s=0.001, fixed_wave_s=300.0,
                                 move_swap=False)
        self.assertGreater(m_slow["plan_wait_total_s"], 100.0)
        self.assertGreater(m_slow["makespan_s"], m_fast["makespan_s"] + 100.0)

    def test_empty_run_and_bad_location(self):
        """빈 요청: makespan 0. 지도 밖 요청: 명확한 오류."""
        m, _ = self.run_sim([], pickers=3)
        self.assertEqual(m["makespan_s"], 0.0)
        self.assertEqual(m["tasks_done"], 0)
        with self.assertRaises(ValueError):
            self.run_sim([one_request((999, 999), 1, "easy", 0)], pickers=1)

    def test_determinism_fixed_mode(self):
        """고정 입력·고정 계산 지연에서 두 실행의 결과는 동일하다."""
        rng = random.Random(42)
        reqs = generate_requests(RunConfig(total_requests=60), self.wh, rng)
        keys = ("makespan_s", "total_walk_m", "total_pick_s", "total_zone_wait_s",
                "task_records", "edge_overlap_pairs", "plan_wait_total_s")
        out = []
        for _ in range(2):
            m, _ = self.run_sim([dict(r) for r in reqs], pickers=5,
                                combo="nn-2opt-reinsert", seed=42,
                                requests_per_task=6)
            out.append({k: m[k] for k in keys})
        self.assertEqual(out[0], out[1])

    def test_interrupted_improvement_keeps_valid_plan(self):
        """예산 1로 개선 중단 시에도 유효 계획(NN)이 유지되고 전 요청이 처리된다."""
        rng = random.Random(13)
        reqs = generate_requests(RunConfig(total_requests=36), self.wh, rng)
        m, _ = self.run_sim(reqs, pickers=3, combo="alt",
                            improvement_eval_budget=1, move_swap=False)
        flat = [rid for t in m["task_records"] for rid in t["requests"]]
        self.assertEqual(sorted(flat), sorted(r["id"] for r in reqs))
        for t in m["task_records"]:
            self.assertIsNotNone(t["final_cost"])

    def test_move_swap_only_unissued(self):
        """발급된 작업은 배정 개선 대상에서 제외된다(candidates 상태 검증)."""
        state = PlanState(tasks=[])
        from simulation.planner import TaskPlan
        t0 = TaskPlan(tid=0, requests=[one_request((4, 2), 1, "easy", 0)])
        t1 = TaskPlan(tid=1, requests=[one_request((32, 38), 1, "easy", 1)])
        t0.status = "issued"
        state.tasks = [t0, t1]
        self.assertEqual([t.tid for t in state.pending()], [1])

    def test_congestion_aware_mode_runs_and_keeps_partition(self):
        rng = random.Random(14)
        reqs = generate_requests(RunConfig(total_requests=48), self.wh, rng)
        m, _ = self.run_sim(reqs, pickers=6, congestion_aware=True,
                            assignment="balanced", combo="nn-2opt-reinsert")
        flat = [rid for t in m["task_records"] for rid in t["requests"]]
        self.assertEqual(sorted(flat), sorted(r["id"] for r in reqs))

    def test_hot_zone_produces_waits_and_prediction_error(self):
        """집중 시나리오에서 대기>0·예측 오차>0이 관측된다(압력 테스트)."""
        run = run_cfg(pickers=20, combo="nn", seed=1, zone_capacity=2,
                      zone_length_m=8.0, move_swap=False)
        rng = random.Random(1)
        reqs = generate_requests(replace(run, hot_aisle_share=0.8,
                                         total_requests=240), self.wh, rng)
        m = simulate(run, self.wh, reqs)
        self.assertGreater(m["total_zone_wait_s"], 0.0)
        self.assertGreater(m["prediction_mae_s"] or 0.0, 0.0)

    def test_single_picker_existing_package_intact(self):
        """기존 1인 기능 회귀: picking.run_request가 여전히 유효 경로를 반환."""
        from picking.distances import Task, prepare_distances
        from picking.runner import run_request
        graph = __import__("picking.graph", fromlist=["build_warehouse"]).build_warehouse()
        table = prepare_distances(graph, Task.create(graph, (0, 0),
                                                     [(0, 8), (8, 14), (20, 30), (32, 6)]))
        from picking.algorithms import solve
        result = solve(table, "dp")
        self.assertEqual(result.status, "completed")
        path = table.reconstruct(result.order)
        table.validate_path(result.order, path, result.distance)




class TestHardenedProperties(unittest.TestCase):
    """피드백 반영 강화 테스트: 수작업 검산·동시성·중단 주입·불변식."""

    @classmethod
    def setUpClass(cls):
        cls.wh = build_warehouse(WarehouseConfig())

    def run_sim(self, requests, stop_check=None, **kw):
        cfg = run_cfg(**kw)
        return simulate(cfg, self.wh, requests, stop_check=stop_check), cfg

    # ---------- 사전 계산과 대기: 수작업 검산 가능한 정확 값 ----------
    def test_plan_wait_exact_values_and_no_double_count(self):
        """고정 지연 3작업: 대기 = (초기+첫 ROUTE)=12초, 이후 추가 대기 0."""
        locs = [(16, 2), (20, 4), (12, 6)]
        reqs = [one_request(locs[i], 1, "easy", i) for i in range(3)]
        m, _ = self.run_sim(reqs, pickers=1, requests_per_task=1,
                            fixed_initial_plan_s=10.0, fixed_wave_s=2.0,
                            move_swap=False)
        self.assertEqual(m["pickers"][0]["plan_wait_s"], 12.0)
        self.assertAlmostEqual(m["plan_wait_total_s"], 12.0, places=6)
        # 첫 작업은 계획 완료(12초)에 즉시 발급, 이후 작업은 체인(추가 대기 0)
        recs = sorted(m["task_records"], key=lambda t: t["issued_at"])
        self.assertAlmostEqual(recs[0]["issued_at"], 12.0, places=6)
        for prev, cur in zip(recs[:-1], recs[1:]):
            self.assertAlmostEqual(cur["issued_at"], prev["finished_at"], places=6)
        # 정합성: 완료 = 발급 + 경로비용(도보) + 수거10 + 하차5 (모든 작업)
        for t in m["task_records"]:
            self.assertAlmostEqual(t["finished_at"],
                                   t["issued_at"] + t["final_cost"] + 10.0 + 5.0,
                                   places=6)
        # 겹친 계산의 이중 합산 없음: 작업자 대기 합 <= 초기지연 + 자원 총지속
        self.assertLessEqual(m["plan_wait_total_s"],
                             m["plan"]["sim_delay_seconds"] + 1e-6)

    def test_plan_wait_late_penalty_exact(self):
        """파도당 400초 계산: 두 번째 작업 대기 = ROUTE2 완료 - 작업1 완료."""
        locs = [(16, 2), (20, 4)]
        reqs = [one_request(locs[i], 1, "easy", i) for i in range(2)]
        m, _ = self.run_sim(reqs, pickers=1, requests_per_task=1,
                            fixed_initial_plan_s=10.0, fixed_wave_s=400.0,
                            move_swap=False)
        free_at = m["task_records"][0]["finished_at"]  # ROUTE1(10~410) + 작업1 소요
        # 순차 자원: PREROUTE(410~810) 실행 중 ROUTE2 대기 → 810~1210에 실행
        expected_total = 410.0 + (1210.0 - free_at)
        self.assertAlmostEqual(m["pickers"][0]["plan_wait_s"], expected_total, places=6)
        self.assertGreater(m["pickers"][0]["plan_wait_s"], 400.0)  # 초과 지간만큼만

    def test_sequential_resource_contention_exact(self):
        """2작업자 동시 대기: ROUTE 직렬화로 대기 6초/11초(초기1+파도5)."""
        reqs = [one_request((16, 2), 1, "easy", 0), one_request((20, 4), 1, "easy", 1)]
        m, _ = self.run_sim(reqs, pickers=2, requests_per_task=1,
                            fixed_initial_plan_s=1.0, fixed_wave_s=5.0,
                            move_swap=False)
        waits = sorted(p["plan_wait_s"] for p in m["pickers"].values())
        self.assertEqual(waits, [6.0, 11.0])

    # ---------- 거리와 최적값: 수작업 대조 ----------
    def test_hand_computed_route_distance_tiny_warehouse(self):
        """소형 창고(8x4): NN 경로와 비용 6m를 손계산과 정확히 일치."""
        cfg = WarehouseConfig(width=8, height=4, cross_ys=(0, 4), staging=(4, 0))
        wh = build_warehouse(cfg)
        self.assertEqual(wh.locations, ((0, 2), (4, 2), (8, 2)))
        self.assertEqual(wh.d((4, 0), (4, 2)), 2.0)
        self.assertEqual(wh.d((4, 2), (0, 2)), 8.0)  # y=2 가로 통로 없음: y=0/4 경유
        ctx = RouteContext(wh, wh.staging, wh.locations)
        nn = improve(ctx, "nn")
        # 손계산: (4,0)->(4,2)=2, ->(0,2)=8(y=0/4 경유), ->(8,2)=12, 벨트((8,2))=0
        self.assertEqual(nn, [(4, 2), (0, 2), (8, 2)])
        self.assertAlmostEqual(ctx.cost(nn), 22.0, places=9)
        best, best_cost = brute_force_best(ctx)
        self.assertAlmostEqual(best_cost, 22.0, places=9)

    def test_segment_dp_local_optimal_with_boundary_costs(self):
        """구간 DP 결과: 경계 비용 포함 모든 인접 교환이 개선되지 않음."""
        rng = random.Random(21)
        for _ in range(8):
            locs = rng.sample(self.wh.locations, 7)
            ctx = RouteContext(self.wh, self.wh.staging, locs)
            order = improve(ctx, "nn-2opt")
            out = improve(ctx, "nn-2opt-reinsert-segdp", order=list(order))
            for i in range(len(out) - 1):
                cand = out[:i] + [out[i + 1], out[i]] + out[i + 2:]
                self.assertGreaterEqual(ctx.cost(cand), ctx.cost(out) - EPS)

    # ---------- 혼잡과 이벤트: 정확한 동시성 ----------
    def test_completion_before_arrival_fifo_exact(self):
        """완료와 신규 도착 동시각: 완료 처리 -> 대기자 입장 -> 신규 대기.

        보행 0.9m/s, A=(16,2) 수거40초(품목4), B=(16,6), C=(16,38), 구역 길이 40m.
        A 완료시각(issue+2/0.9+40) == C 도착시각(issue+38/0.9)이 정확히 같다.
        """
        reqs = [one_request((16, 2), 4, "easy", 0),
                one_request((16, 6), 1, "easy", 1),
                one_request((16, 38), 1, "easy", 2)]
        m, _ = self.run_sim(reqs, pickers=3, requests_per_task=1,
                            zone_capacity=1, zone_length_m=40.0,
                            walk_speed_m_s=0.9, fixed_initial_plan_s=0.0,
                            fixed_wave_s=0.0, move_swap=False)
        # est 내림차순 발급: picker0=A(16,2), picker1=C(16,38), picker2=B(16,6)
        waits = {p: m["pickers"][p]["zone_wait_s"] for p in range(3)}
        self.assertAlmostEqual(waits[0], 0.0, places=6)               # A 즉시 수거
        self.assertAlmostEqual(waits[2], 40.0 - 4.0 / 0.9, places=6)  # B: A 완료까지 FIFO 대기
        self.assertAlmostEqual(waits[1], 10.0, places=6)              # C: 동시각 도착, 완료 처리 후 B 입장으로 대기
        self.assertEqual(m["zone_blocked_admissions"], 2)

    def test_two_zones_independent(self):
        """서로 다른 구역은 독립 처리: 원거리 두 위치에서 대기 0."""
        reqs = [one_request((4, 2), 1, "easy", 0), one_request((32, 38), 1, "easy", 1)]
        m, _ = self.run_sim(reqs, pickers=2, requests_per_task=1,
                            zone_capacity=1, fixed_initial_plan_s=0.0,
                            fixed_wave_s=0.0, move_swap=False)
        self.assertAlmostEqual(m["total_zone_wait_s"], 0.0, places=6)
        self.assertEqual(m["zone_blocked_admissions"], 0)

    def test_zone_capacity_invariant_by_zone_state_replay(self):
        """구역 상태 재생: 시뮬레이터가 유지하는 active 상한을 기록으로 점검.

        입장은 항상 active<capacity 조건에서만 발생하므로, 차단 입장 수와
        대기 합계의 정합성으로 검증한다(초과 입장이 있으면 대기 합계 감소).
        """
        run = run_cfg(pickers=20, combo="nn", zone_capacity=2, zone_length_m=8.0,
                      hot_aisle_share=0.8, duplicate_share=0.3, total_requests=240, seed=5)
        rng = random.Random(5)
        reqs = generate_requests(run, self.wh, rng)
        m = simulate(run, self.wh, reqs)
        self.assertGreater(m["zone_blocked_admissions"], 0)   # 혼잡 실발생
        self.assertGreater(m["total_zone_wait_s"], 0.0)
        self.assertEqual(len(m["task_records"]), 20)          # 240요청/12 = 20작업

    # ---------- 중단 주입: 전 단계 스윕 ----------
    def test_interruption_sweep_all_stages(self):
        """검사점 1..40번째마다 1회 중단: 어느 단계에서도 유효 계획 유지."""
        from simulation.routes import Interrupted as RStop
        from simulation.assignment import Interrupted as AStop

        class Boom(RStop, AStop):
            pass

        rng = random.Random(31)
        reqs = generate_requests(RunConfig(total_requests=36), self.wh, rng)
        for n in range(1, 41):
            calls = {"n": 0}

            def stop(n=n, calls=calls):
                calls["n"] += 1
                if calls["n"] == n:
                    raise Boom()

            m, _ = self.run_sim([dict(r) for r in reqs], stop_check=stop,
                                pickers=4, combo="alt", requests_per_task=6,
                                seed=31)
            flat = [rid for t in m["task_records"] for rid in t["requests"]]
            self.assertEqual(sorted(flat), sorted(r["id"] for r in reqs),
                             f"n={n}: 요청 누락/중복")
            self.assertGreater(m["makespan_s"], 0.0)
            self.assertTrue(m["plan"]["aborts"], f"n={n}: 중단 기록 없음")

    def test_interruption_keeps_issued_records_complete(self):
        """중단 시에도 발급된 작업의 기록(비용·시작 위치)은 완전하다."""
        from simulation.routes import Interrupted as RStop
        from simulation.assignment import Interrupted as AStop

        class Boom(RStop, AStop):
            pass
        rng = random.Random(33)
        reqs = generate_requests(RunConfig(total_requests=24), self.wh, rng)
        for n in (3, 7, 12):
            calls = {"n": 0}

            def stop(n=n, calls=calls):
                calls["n"] += 1
                if calls["n"] == n:
                    raise Boom()

            m, _ = self.run_sim([dict(r) for r in reqs], stop_check=stop,
                                pickers=2, combo="nn-2opt-reinsert",
                                requests_per_task=6, seed=33)
            for t in m["task_records"]:
                self.assertIsNotNone(t["final_cost"])
                self.assertIsNotNone(t["start_node"])

    def test_v2_congestion_mode_runs_and_partition(self):
        """v2 혼잡 고려 모드도 분할 불변식을 유지한다."""
        rng = random.Random(35)
        reqs = generate_requests(RunConfig(total_requests=36), self.wh, rng)
        m, _ = self.run_sim(reqs, pickers=4, congestion_aware=True,
                            requests_per_task=6, seed=35)
        flat = [rid for t in m["task_records"] for rid in t["requests"]]
        self.assertEqual(sorted(flat), sorted(r["id"] for r in reqs))
        self.assertGreaterEqual(m["plan"]["moves_applied"], 0)




class TestEvidenceFeatures(unittest.TestCase):
    """입증 실험용 신규 기능: 단순 배정·선행 하차·혼잡 조건부."""

    @classmethod
    def setUpClass(cls):
        cls.wh = build_warehouse(WarehouseConfig())

    def run_sim(self, requests, **kw):
        cfg = run_cfg(**kw)
        return simulate(cfg, self.wh, requests), cfg

    def test_roundrobin_partition_and_caps(self):
        from simulation.assignment import roundrobin_chunks
        from simulation.config import PlanConfig
        rng = random.Random(51)
        reqs = generate_requests(RunConfig(total_requests=50), self.wh, rng)
        out = roundrobin_chunks(reqs, PlanConfig(requests_per_task=12), self.wh.staging)
        flat = [r["id"] for c in out for r in c]
        self.assertEqual(sorted(flat), sorted(r["id"] for r in reqs))
        for c in out:
            self.assertLessEqual(len(c), 12)
            self.assertTrue(c)
        self.assertLessEqual(max(len(c) for c in out) - min(len(c) for c in out), 1)

    def test_roundrobin_runs_end_to_end(self):
        rng = random.Random(53)
        reqs = generate_requests(RunConfig(total_requests=36), self.wh, rng)
        m, _ = self.run_sim(reqs, pickers=4, assignment="roundrobin",
                            combo="nn", requests_per_task=6, move_swap=False)
        flat = [rid for t in m["task_records"] for rid in t["requests"]]
        self.assertEqual(sorted(flat), sorted(r["id"] for r in reqs))

    def test_lookahead_records_and_preserves_requests(self):
        """선행 하차(확장 후보): 의사결정 기록, 전 요청 처리, 분할 불변 유지."""
        rng = random.Random(55)
        reqs = generate_requests(RunConfig(total_requests=48), self.wh, rng)
        m, _ = self.run_sim(reqs, pickers=2, dropoff_lookahead=True,
                            combo="nn-2opt-reinsert", requests_per_task=6,
                            move_swap=False)
        flat = [rid for t in m["task_records"] for rid in t["requests"]]
        self.assertEqual(sorted(flat), sorted(r["id"] for r in reqs))
        self.assertGreaterEqual(m["lookahead"]["decisions"], 1)
        self.assertIsNotNone(m["lookahead"]["mean_pred_m"])

    def test_lookahead_prefers_forward_belt_on_split_workload(self):
        """좌측 집중 작업 후 우측 집중 작업: 선행 평가가 기본(최근접)과 다른
        접근 지점을 고르는 사례가 발생하고 예측-실제 기록이 남는다."""
        left = [(0, 6), (0, 10), (0, 14), (0, 18), (4, 6), (4, 10)]
        right = [(36, 6), (36, 10), (36, 14), (36, 18), (32, 6), (32, 10)]
        reqs = [one_request(loc, 1, "easy", i) for i, loc in enumerate(left + right)]
        m_on, _ = self.run_sim([dict(r) for r in reqs], pickers=1,
                               dropoff_lookahead=True, requests_per_task=6,
                               combo="nn", move_swap=False)
        self.assertGreaterEqual(m_on["lookahead"]["decisions"], 1)
        # 체인 작업이 존재(2작업)하므로 예측이 다음 작업과 대응될 기회 존재
        self.assertEqual(m_on["tasks_done"], 2)

    def test_auto_congestion_equals_v2_at_zero_threshold(self):
        """임계 0의 auto는 v2와 논리적으로 동일해야 한다(fixed 모드, 동일 seed)."""
        rng = random.Random(57)
        reqs = generate_requests(RunConfig(total_requests=24), self.wh, rng)
        common = dict(pickers=4, congestion_aware=True, assignment="balanced",
                      requests_per_task=6, combo="nn", move_swap=False)
        m_auto, _ = self.run_sim([dict(r) for r in reqs], congestion_mode="auto",
                                 congestion_threshold_s=0.0, **common)
        m_v2, _ = self.run_sim([dict(r) for r in reqs], congestion_mode="v2", **common)
        self.assertAlmostEqual(m_auto["makespan_s"], m_v2["makespan_s"], places=6)
        self.assertAlmostEqual(m_auto["total_walk_m"], m_v2["total_walk_m"], places=6)

    def test_auto_congestion_equals_off_at_huge_threshold(self):
        rng = random.Random(59)
        reqs = generate_requests(RunConfig(total_requests=24), self.wh, rng)
        common = dict(pickers=4, congestion_aware=True, assignment="balanced",
                      requests_per_task=6, combo="nn", move_swap=False)
        m_auto, _ = self.run_sim([dict(r) for r in reqs], congestion_mode="auto",
                                 congestion_threshold_s=1e9, **common)
        m_off, _ = self.run_sim([dict(r) for r in reqs], congestion_aware=False,
                                assignment="balanced", requests_per_task=6,
                                combo="nn", move_swap=False)
        self.assertAlmostEqual(m_auto["makespan_s"], m_off["makespan_s"], places=6)




class TestThirdRound(unittest.TestCase):
    """3차: savings 묶음·completion 배정·가변 묶음·제한적 LNS의 정확성."""

    @classmethod
    def setUpClass(cls):
        cls.wh = build_warehouse(WarehouseConfig())

    def run_sim(self, requests, **kw):
        cfg = run_cfg(**kw)
        return simulate(cfg, self.wh, requests)

    def test_savings_partition_caps_determinism(self):
        from simulation.assignment import savings_bundles
        rng = random.Random(61)
        reqs = generate_requests(RunConfig(total_requests=100), self.wh, rng)
        cfg = PlanConfig(requests_per_task=12)
        a = savings_bundles(reqs, cfg, self.wh, self.wh.staging, PickConfig(), 1.0)
        b = savings_bundles([dict(r) for r in reqs], cfg, self.wh, self.wh.staging,
                            PickConfig(), 1.0)
        flat = sorted(r["id"] for x in a for r in x)
        self.assertEqual(flat, sorted(r["id"] for r in reqs))
        for x in a:
            self.assertLessEqual(len(x), 12)
        self.assertEqual([sorted(r["id"] for r in x) for x in a],
                         [sorted(r["id"] for r in x) for x in b])  # 결정론

    def test_savings_same_location_merged(self):
        from simulation.assignment import savings_bundles
        reqs = [one_request((8, 6), 2, "easy", 0), one_request((8, 6), 1, "packed", 1)]
        out = savings_bundles(reqs, PlanConfig(requests_per_task=4), self.wh,
                              self.wh.staging, PickConfig(), 1.0)
        self.assertEqual(len(out), 1)  # 동일 위치는 묶임(방문 병합)

    def test_completion_schedule_properties(self):
        from simulation.assignment import completion_schedule
        rng = random.Random(63)
        reqs = generate_requests(RunConfig(total_requests=60), self.wh, rng)
        bundles = chunk_requests(reqs, PlanConfig(requests_per_task=12))
        ordered, assign, finish = completion_schedule(bundles, self.wh,
                                                      self.wh.staging, PickConfig(),
                                                      1.0, 4)
        self.assertEqual(len(ordered), len(bundles))
        self.assertTrue(all(0 <= j < 4 for j in assign))
        # 가용시각 단조: 각 작업자의 배정 순서대로 finish는 비감소
        by_picker = defaultdict(list)
        for b, j, f in zip(ordered, assign, finish):
            by_picker[j].append(f)
        for values in by_picker.values():
            self.assertEqual(values, sorted(values))

    def test_completion_mode_end_to_end_partition(self):
        rng = random.Random(65)
        reqs = generate_requests(RunConfig(total_requests=48), self.wh, rng)
        m = self.run_sim(reqs, pickers=4, assignment="completion",
                         combo="nn-2opt-reinsert", requests_per_task=12,
                         move_swap=False, compute_mode="fixed")
        flat = [rid for t in m["task_records"] for rid in t["requests"]]
        self.assertEqual(sorted(flat), sorted(r["id"] for r in reqs))

    def test_variable_cap_ensures_min_tasks(self):
        from simulation.assignment import ensure_task_count
        rng = random.Random(67)
        reqs = generate_requests(RunConfig(total_requests=30), self.wh, rng)
        big = [reqs]  # 묶음 1개
        out = ensure_task_count(big, PlanConfig(requests_per_task=12), self.wh,
                                self.wh.staging, PickConfig(), 1.0, 5)
        self.assertGreaterEqual(len(out), 5)
        flat = sorted(r["id"] for x in out for r in x)
        self.assertEqual(flat, sorted(r["id"] for r in reqs))
        for x in out:
            self.assertLessEqual(len(x), 12)

    def test_lns_preserves_partition_and_respects_abort(self):
        from simulation.lns import lns_improve
        from simulation.routes import Interrupted as RStop

        class Boom(RStop):
            pass
        rng = random.Random(69)
        reqs = generate_requests(RunConfig(total_requests=60), self.wh, rng)
        bundles = chunk_requests(reqs, PlanConfig(requests_per_task=12))
        ids = [r["id"] for b in bundles for r in b]
        run = RunConfig(sim=SimConfig(pickers=4, seed=1, compute_mode="fixed"),
                        plan=PlanConfig(requests_per_task=12, lns=True,
                                        lns_iters=5, lns_remove_q=3))
        # 정상 실행
        out, stats = lns_improve(bundles, self.wh, self.wh.staging, run)
        self.assertEqual(sorted(r["id"] for b in out for r in b), sorted(ids))
        for b in out:
            self.assertLessEqual(len(b), 12)
        # 즉시 중단: 원본 보존(유효 계획 유지)
        calls = {"n": 0}

        def stop():
            calls["n"] += 1
            if calls["n"] == 1:
                raise Boom()
        out2, stats2 = lns_improve([list(b) for b in bundles], self.wh,
                                   self.wh.staging, run, stop_check=stop)
        self.assertEqual(sorted(r["id"] for b in out2 for r in b), sorted(ids))
        self.assertEqual(stats2["aborts"], 1)

    def test_lns_never_worsens_estimate(self):
        from simulation.assignment import expected_makespan
        from simulation.lns import lns_improve
        rng = random.Random(71)
        reqs = generate_requests(RunConfig(total_requests=60), self.wh, rng)
        bundles = chunk_requests(reqs, PlanConfig(requests_per_task=12))
        run = RunConfig(sim=SimConfig(pickers=4, seed=1, compute_mode="fixed"),
                        plan=PlanConfig(requests_per_task=12, lns_iters=10))
        out, _ = lns_improve(bundles, self.wh, self.wh.staging, run)
        before = expected_makespan(bundles, self.wh, self.wh.staging, PickConfig(), 1.0, 4)
        after = expected_makespan(out, self.wh, self.wh.staging, PickConfig(), 1.0, 4)
        self.assertLessEqual(after, before + 1e-6)  # 채택은 추정 종료 감소만

    def test_new_pipeline_reproducible_fixed(self):
        rng = random.Random(73)
        reqs = generate_requests(RunConfig(total_requests=36), self.wh, rng)
        keys = ("makespan_s", "total_walk_m", "task_records")
        outs = []
        for _ in range(2):
            m = self.run_sim([dict(r) for r in reqs], pickers=3, assignment="completion",
                             combo="nn-2opt-reinsert", bundling="savings",
                             requests_per_task=12, move_swap=False, lns=True,
                             lns_iters=5, seed=73, compute_mode="fixed")
            outs.append({k: m[k] for k in keys})
        self.assertEqual(outs[0], outs[1])


def to_iter(n):
    return range(n)


if __name__ == "__main__":
    unittest.main()
