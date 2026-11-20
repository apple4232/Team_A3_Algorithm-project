import unittest
from unittest.mock import patch

from picking.algorithms import IMPROVEMENT_ALGORITHMS, Limits, improve_route, solve
from picking.distances import DeadlineExceeded, Task, prepare_distances
from picking.graph import build_warehouse
from picking.runner import run_request


class TwoStageTests(unittest.TestCase):
    def test_interruption_preserves_valid_route(self):
        graph = build_warehouse()
        task = Task.create(graph, (0, 0), [(4, 2), (8, 14), (12, 34), (24, 26)])
        table = prepare_distances(graph, task)
        base = solve(table, "nn+2opt")
        for stop in (0, 3, 25, 45):
            calls = 0

            def interrupt(deadline):
                nonlocal calls
                calls += 1
                if calls > stop:
                    raise DeadlineExceeded()

            with patch("picking.algorithms.check_deadline", side_effect=interrupt):
                result = improve_route(table, base, IMPROVEMENT_ALGORITHMS[-1], Limits(), None)
            self.assertLessEqual(result.distance, base.distance)
            table.validate_path(result.order, table.reconstruct(result.order), result.distance)

    def test_runner_and_small_exact_solution(self):
        graph = build_warehouse()
        required = [(4, 2), (8, 14), (12, 34), (24, 26), (24, 26), (0, 0)]
        table = prepare_distances(graph, Task.create(graph, (0, 0), required))
        result = run_request(graph, (0, 0), required, IMPROVEMENT_ALGORITHMS[-1])
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.distance, solve(table, "dp").distance)
        table.validate_path(result.order, result.path, result.distance)

    def test_runner_returns_valid_path_when_segment_dp_is_interrupted(self):
        graph = build_warehouse()
        required = [(4, 2), (8, 14), (12, 34), (24, 26)]
        with patch("picking.algorithms._subset_dp", side_effect=DeadlineExceeded()):
            result = run_request(graph, (0, 0), required, IMPROVEMENT_ALGORITHMS[-1])
        self.assertEqual(result.status, "timeout")
        self.assertIsNotNone(result.requested_result.order)
        table = prepare_distances(graph, Task.create(graph, (0, 0), required))
        table.validate_path(result.order, result.path, result.distance)
        self.assertLessEqual(result.distance, solve(table, "nn+2opt").distance)
