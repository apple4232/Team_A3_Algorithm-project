# Project Verification

Reviewed on November 13, 2026. The implementation baseline is `9c03abd`. The checked `Sichan` revision is `7a9ab03`, which restores the same file tree. The findings below draw on the stored experiment records and the documented Windows verification runs.

## Verified behavior

| Area | Evidence |
|---|---|
| Routing | The shared Dijkstra distance table separates aisle traversal from visit order. Exhaustive Search and DP agreed on all 675 evaluation tasks where both finished. |
| Workloads | Regenerating the same configuration reproduced all 4,050 tasks. Seed grouping keeps related tasks in the same split. |
| Saved results | All 34,425 available evaluation routes passed endpoint, coverage, edge, and distance checks. Candidate routes were reconstructed from stored visit orders. |
| Windows checks | The automated suite passed 37 tests on Windows with Python 3.12.2. The recorded full benchmark used macOS ARM and Python 3.13.5. |

See the [experimental method](08-role-b-experiments.md) and [recorded results](09-role-b-results.md).

## Review findings

### Selection rules and the DP boundary

`train()` tests one feature and one threshold at a time. The count, numeric, and numeric-plus-pattern policies all produced the same split, DP for `n <= 13.5` and NN+2-opt otherwise. This experiment found no additional gain from the extra features within that rule structure.

In the saved full-request evaluation, DP completed 225 of 225 tasks at size 12 with a median of 26.61 ms. All 225 tasks at size 15 timed out under the 200 ms budget. Sizes 20 and 50 hit the configured size guard. Sizes 13 and 14 were absent, so 13.5 describes the fitted split between observed sizes. A boundary experiment would measure sizes 12 through 15 at several budgets and validate the resulting rule on new seed groups. [Training code](../experiments/analysis.py#L84) · [Saved rules](../results/full/rules.json)

### Policy timing and reported effect

`evaluate()` prepares distances and features before calling `run_request()`, which prepares the distances again. The first preparation had a median of about 1.1 ms in the saved run. A new measurement can compare a direct fixed policy, a count policy that only needs the distinct-location count, and a spatial policy that reuses its prepared distances. Measure the full request and preserve timeout, fallback, and path-validation behavior. [Policy evaluator](../experiments/__main__.py#L29) · [Request runner](../picking/runner.py#L30)

On 2,025 evaluation tasks, the count rule reduced mean distance from 168.29 m to 166.86 m. The paired saving was 1.426 m, about 0.85% of the fixed policy's mean, with a 95% bootstrap interval of 1.23–1.63 m across 15 seed groups. It improved 295 tasks and tied 1,730. Median total policy time was 3.47 ms versus 2.41 ms for the fixed policy under the recorded measurement procedure. [Policy comparison](../results/full/eval-policy-comparison.json) · [Policy timing](../results/full/eval-policy-summary.json)

At coefficient 0.5, CA-minus+2-opt returned shorter routes than NN+2-opt on 282 tasks, equal routes on 1,357, and longer routes on 386. Its routes were 0.99 m longer on average. The paired counts show the variation behind the mean. [Candidate records](../results/full/eval-candidate.jsonl)

### Windows peak memory measurement

`experiments/memory.py` imports the Unix `resource` module at startup. On Windows, the import fails before DP runs. PR #1 added a Windows branch using `GetProcessMemoryInfo` and retained the `peak_rss_bytes` output. The patched version passed a standalone measurement and a nine-size batch on Windows. Commit `7a9ab03` restored the original file, so Windows memory sampling still fails at the checked `Sichan` revision. [Current sampler](../experiments/memory.py) · [Windows patch](https://github.com/apple4232/Team_A3_Algorithm-project/pull/1/files) · [Restore commit](https://github.com/apple4232/Team_A3_Algorithm-project/commit/7a9ab03)

### Saved rule fingerprints on Windows

`environment()` hashes native path strings and raw source bytes. The baseline digest matches the saved rule when calculated with POSIX paths and LF line endings. A Windows checkout can produce a different digest for the same source. The Windows memory patch also changes the actual hashed source because `experiments/memory.py` is included. A compatibility fix should preserve detection of real source changes and verify both cases against the evaluation guard. [Fingerprint calculation](../experiments/benchmark.py#L18) · [Evaluation guard](../experiments/__main__.py#L29)

### Demo state and README

`loadDetail()` uses `refreshToken` to discard stale responses. `runLive()` can apply a recalculation response after the selected task changes, showing an earlier route on the current task. Verify any fix by switching tasks while recalculation is pending. The README introduction also describes the UI as planned while its final section documents the available local demo. [Demo state handling](../demo/app.js#L47) · [Recalculation](../demo/app.js#L114) · [README](../README.md)

## Verification scope

The distance and latency figures above come from saved measurements. Verification included record checks, workload regeneration, and focused Windows runs. It did not repeat the full performance benchmark. The results support the count rule in the tested synthetic warehouse and recorded budget. They leave the untested boundary sizes and the added value of combined spatial features open.
