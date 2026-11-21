"""Summarize preserved expansion records without running the simulator.

Usage: python -m simulation.archive_summary results/expansion-archive-summary.json
The output is a read-only reaggregation of historical experiment files, not a
new experiment, independent evaluation, or correctness certificate.
"""
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
import sys

from .analysis3 import group_ci


def summarize(root):
    inventory, rounds = [], {}
    for name in ("multi", "multi2", "multi3-dev", "multi3-eval",
                 "multi4-dev", "multi4-eval"):
        rows = []
        for path in sorted((root / name).glob("*.jsonl")):
            data = path.read_bytes()
            records = [json.loads(line) for line in data.decode("utf-8").splitlines()
                       if line.strip()]
            inventory.append({"path": path.as_posix(), "records": len(records),
                              "sha256_lf_normalized": hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()})
            rows.extend(records)
        rounds[name] = rows
    stress = root / "multi/congestion-stress.json"
    data = stress.read_bytes()
    inventory.append({"path": stress.as_posix(),
                      "records": len(json.loads(data)),
                      "sha256_lf_normalized": hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()})

    cells = defaultdict(dict)
    for row in rounds["multi4-eval"]:
        condition, label = row["suite"].split("|", 1)
        cfg = row["config"]
        key = (condition, row["split"], cfg["sim"]["pickers"],
               cfg["total_requests"], cfg["warehouse"]["name"],
               cfg["sim"]["compute_mode"])
        seed = cfg["sim"]["seed"]
        if seed in cells[key].get(label, {}):
            raise ValueError(f"Duplicate seed/method: {key}, {label}, {seed}")
        cells[key].setdefault(label, {})[seed] = row

    comparisons = []
    for key, methods in sorted(cells.items()):
        base = methods.get("S1-C3", {})
        for label in ("S3b-chunk-comp", "S4b-var-LNS"):
            candidate = methods.get(label)
            if not candidate:
                continue
            if set(base) != set(candidate):
                raise ValueError(f"Unpaired seeds: {key}, {label}")
            pairs = [(s, base[s]["metrics"]["makespan_s"],
                      candidate[s]["metrics"]["makespan_s"])
                     for s in sorted(base)]
            sb, sc = sum(b for _, b, _ in pairs), sum(c for _, _, c in pairs)
            differences = [b - c for _, b, c in pairs]
            comparisons.append({
                "condition": list(key), "baseline": "S1-C3", "candidate": label,
                "seeds": sorted(base), "n": len(pairs),
                "aggregate_improvement_percent": 100 * (sb - sc) / sb,
                "aggregate_ci95_seed_bootstrap": group_ci(pairs, "overall"),
                "mean_per_run_percent": mean(100 * (b - c) / b for _, b, c in pairs),
                "mean_seconds_saved": mean(differences),
                "improved": sum(x > 1e-9 for x in differences),
                "tied": sum(abs(x) <= 1e-9 for x in differences),
                "worse": sum(x < -1e-9 for x in differences),
                "max_candidate_plan_wall_seconds": max(
                    candidate[s]["metrics"]["plan"]["wall_seconds"] for s in base),
            })
    seeds3 = {r["config"]["sim"]["seed"] for r in rounds["multi3-eval"]}
    seeds4 = {r["config"]["sim"]["seed"] for r in rounds["multi4-eval"]}
    return {
        "purpose": "Archive inventory and saved-data reaggregation; no simulation rerun",
        "round_record_counts_jsonl": {name: len(rows) for name, rows in rounds.items()},
        "first_round_additional_stress_array_records": len(json.loads(data)),
        "total_records_including_stress_array": sum(x["records"] for x in inventory),
        "files": inventory,
        "reused_evaluation_seed_ids_round3_round4": sorted(seeds3 & seeds4),
        "round4_vs_cap24_comparisons": comparisons,
        "limitations": [
            "Round1 predates planner-serialization fix; historical only",
            "Reused seed IDs require disclosure; fresh independent evaluation absent",
            "Repeated machine timing is absent",
            "Inactive variable splitting cannot establish its effectiveness",
            "LNS propagation into issued work is not established by unchanged makespan",
        ],
    }


def main():
    destination = Path(sys.argv[1] if len(sys.argv) > 1
                       else "results/expansion-archive-summary.json")
    result = summarize(Path("results"))
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(f"Saved {destination}: {result['total_records_including_stress_array']} records")


if __name__ == "__main__":
    main()
