"""Repeat randomized full-request measurements on a fixed subset of fresh tasks."""
from dataclasses import asdict
import json
from pathlib import Path
import platform
import random
from statistics import median

from picking.algorithms import IMPROVEMENT_ALGORITHMS
from picking.graph import build_warehouse
from picking.runner import run_request
from .workloads import generate


def main():
    output = Path("results/two-stage-repeat")
    output.mkdir(exist_ok=False)
    rng = random.Random(118)
    tasks = generate(build_warehouse(), [15, 20, 50], range(3000, 3030), paired=True)
    sample = []
    for n in (15, 20, 50):
        sample.extend(rng.sample([t for t in tasks if len(t["required"]) == n], 20))
    graph = build_warehouse()
    rows = []
    with (output / "requests.jsonl").open("w") as file:
        for task in sample:
            for repetition in range(10):
                names = ["nn+2opt", *IMPROVEMENT_ALGORITHMS]
                rng.shuffle(names)
                for name in names:
                    result = run_request(graph, task["start"], task["required"], name, budget_seconds=0.2)
                    assert result.status == "completed" and result.path is not None
                    row = {"task_id": task["id"], "algorithm": name, "repetition": repetition,
                           "distance": result.distance, "total_seconds": result.timings["total"],
                           "budget_exceeded": result.budget_exceeded}
                    rows.append(row)
                    file.write(json.dumps(row) + "\n")
    summary = {"environment": {"python": platform.python_version(), "platform": platform.platform()},
               "tasks": len(sample), "repetitions": 10, "methods": {}}
    for name in ["nn+2opt", *IMPROVEMENT_ALGORITHMS]:
        selected = [r for r in rows if r["algorithm"] == name]
        for task in sample:
            assert len({r["distance"] for r in selected if r["task_id"] == task["id"]}) == 1
        times = sorted(r["total_seconds"] * 1000 for r in selected)
        summary["methods"][name] = {"median_ms": median(times), "p95_ms": times[int(.95*len(times))],
                                    "budget_exceeded": sum(r["budget_exceeded"] for r in selected)}
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
