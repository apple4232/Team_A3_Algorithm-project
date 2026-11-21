# Expansion Experiment Archive

This archive accompanies [the complete study record](../docs/20-expansion-study-record.md). It is exploratory evidence, not a production-performance certificate. The extension exploration ended without merging PR #7.

## Record inventory

- `multi/`: 762 JSONL records plus 24 records in `congestion-stress.json`, total 786. Generated before the planning-resource serialization fix; historical only.
- `multi2/`: 474 post-fix records across five suites.
- `multi3-dev/`: 220 development records for batching and component screening.
- `multi3-eval/`: 420 evaluation-set comparisons for the ladder, larger layouts and workload variations.
- `multi4-dev/`: 20 savings/completion/LNS development records.
- `multi4-eval/`: 360 records, including 240 fixed and 120 measured comparisons.

Total: **2,280 experiment records**, not 2,280 independent workloads. Successive rounds reuse evaluation seed IDs; randomized execution order is not same-input repeated timing validation.

## Current read-only summary

[expansion-archive-summary.json](expansion-archive-summary.json) records file counts, LF-normalized SHA-256 digests and paired completion-versus-cap24 comparisons. Produce a separate copy from the repository root with:

```powershell
python -m simulation.archive_summary results/expansion-archive-summary-rerun.json
```

This command parses saved data and calculates statistics; it does not run optimization or generate new workloads. Fixed and measured timing modes remain separate.

## Handling historical reports

Retain the originally committed analysis files as historical artifacts. Current interpretation is in documents 16 and 20. The imported `multi3-eval/claim-verification.txt` has damaged non-ASCII labels; use its source and the readable current summaries with caution. `simulation/verify_claims.py` overwrites that fixed path if executed, so do not run it blindly over preserved evidence.

Observed gains do not waive computation-budget failures. A large-layout measured case reaches about 79.4 seconds of planning time against a 15-second target. Basket capacity is excluded, inactive splitting was not evaluated, and LNS propagation remains unresolved. No real-facility productivity claim is made.

Do not overwrite old datasets when resuming experiments. New policies, physical assumptions or fresh evaluation groups require a distinct directory and documented code/configuration provenance.
