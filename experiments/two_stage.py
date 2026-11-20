"""Run the frozen two-stage comparison on fresh seed groups."""
import argparse
from collections import defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import random
from statistics import mean, median

from picking.algorithms import IMPROVEMENT_ALGORITHMS
from picking.graph import build_warehouse
from picking.runner import run_request
from .workloads import generate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    graph = build_warehouse()
    tasks = generate(graph, [15, 20, 50], range(3000, 3030), paired=True)
    rng = random.Random(73)
    methods = ("nn+2opt", *IMPROVEMENT_ALGORITHMS)
    rows = []
    for task in tasks:
        names = list(methods)
        rng.shuffle(names)
        for name in names:
            result = run_request(graph, task["start"], task["required"], name, budget_seconds=0.2)
            assert result.distance is None or result.order is not None and result.path is not None
            rows.append({"task": task, "algorithm": name, "result": asdict(result)})
    with (args.output / "requests.jsonl").open("w") as file:
        for row in rows:
            file.write(json.dumps(row) + "\n")
    summary = {}
    for name in methods:
        selected = [r["result"] for r in rows if r["algorithm"] == name]
        valid = [r for r in selected if r["distance"] is not None]
        summary[name] = {
            "attempts": len(selected), "completed": sum(r["status"] == "completed" for r in selected),
            "budget_exceeded": sum(r["budget_exceeded"] for r in selected),
            "mean_distance_m": mean(r["distance"] for r in valid) if valid else None,
            "median_total_ms": median(r["timings"]["total"] * 1000 for r in selected),
            "p95_total_ms": sorted(r["timings"]["total"] * 1000 for r in selected)[int(0.95 * len(selected))],
        }
    paired = defaultdict(dict)
    for row in rows:
        paired[row["task"]["id"]][row["algorithm"]] = row
    first, second = IMPROVEMENT_ALGORITHMS[1:]
    groups = defaultdict(list)
    for pair in paired.values():
        a, b = pair[first], pair[second]
        if all(r["result"]["status"] == "completed" for r in (a, b)):
            groups[a["task"]["group"]].append(a["result"]["distance"] - b["result"]["distance"])
    values = [mean(v) for v in groups.values()]
    if values:
        boot = sorted(mean(rng.choices(values, k=len(values))) for _ in range(10000))
        summary["two_stage_vs_two_reinsertions"] = {
            "paired_completed_tasks": sum(map(len, groups.values())),
            "seed_groups": len(groups), "mean_saving_m": mean(values),
            "ci95_seed_bootstrap_m": [boot[250], boot[9749]],
        }
    source_files = sorted(Path("picking").glob("*.py")) + sorted(Path("experiments").glob("*.py"))
    summary["environment"] = {
        "python": platform.python_version(), "platform": platform.platform(),
        "source_sha256": hashlib.sha256(b"".join(p.read_bytes() for p in source_files)).hexdigest(),
        "seeds": [3000, 3029], "window": 6, "stride": 3, "passes": 1,
        "budget_seconds": 0.2, "timing": "full run_request including reconstruction and validation",
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
