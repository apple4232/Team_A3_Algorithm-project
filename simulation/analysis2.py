# -*- coding: utf-8 -*-
"""보완 실험(results/multi2) 분석: 두 개선율 산식, 절대값, 배정 기록, 혼잡 추적.

Usage: python -I simulation/analysis2.py [results_dir]

주요 개선율(전체 산식) = (Σ기준 종료시간 − Σ제안 종료시간) / Σ기준 × 100
보조(실행별 평균)     = mean((기준−제안)/기준 × 100)
두 값은 다를 수 있고 신뢰구간도 산식별로 매 재표본마다 해당 식을 다시 계산한다.
조건(작업자 수·요청량·모드·방식)이 다른 실행은 절대 합산하지 않는다.
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

EPS = 1e-9


def group_bootstrap(pairs, formula, seed=0, repetitions=1000):
    """seed 그룹 재추출 후 매번 해당 산식을 재계산해 95% 구간을 만든다.

    pairs: [(seed, base_value, cand_value), ...]
    formula: "overall" | "per_run"
    """
    groups = defaultdict(list)
    for s, b, c in pairs:
        groups[s].append((b, c))
    keys = sorted(groups)
    if len(keys) < 2:
        return None
    rng = random.Random(seed)
    samples = []
    for _ in range(repetitions):
        picked = [groups[keys[rng.randrange(len(keys))]] for _ in keys]
        flat = [(b, c) for g in picked for b, c in g]
        if formula == "overall":
            sb = sum(b for b, _ in flat)
            sc = sum(c for _, c in flat)
            samples.append(100 * (sb - sc) / sb if sb else 0.0)
        else:
            samples.append(mean(100 * (b - c) / b for b, c in flat if b))
    samples.sort()
    return [samples[int(.025 * repetitions)], samples[int(.975 * repetitions) - 1]]


def load(results_dir):
    rows = []
    for path in sorted(Path(results_dir).glob("*.jsonl")):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                r.setdefault("suite", path.stem)
                rows.append(r)
    return rows


def _get(r, axis):
    if axis == "pickers":
        return r["config"]["sim"]["pickers"]
    if axis == "combo":
        return r["config"]["plan"]["route_combo"]
    if axis == "mode":
        return r["config"]["sim"]["compute_mode"]
    if axis == "assignment":
        return r["config"]["plan"]["assignment"]
    if axis == "method":
        return r.get("suite", "").rsplit("-", 1)[-1]
    if axis == "requests":
        return r["config"]["total_requests"]
    raise KeyError(axis)


def condition(r, axes):
    return tuple(_get(r, a) for a in axes)


def fmt_ci(ci):
    return f"[{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "n/a"


# ---------------------------------------------------------------- 주 비교
def compare_combos(rows, out, suites, baseline_combo="nn", label=""):
    """동일 조건·동일 seed 쌍으로 두 산식 + 절대값 보고."""
    subset = [r for r in rows if r["suite"] in suites]
    by = defaultdict(dict)
    meta = {}
    for r in subset:
        cond = condition(r, ("pickers", "requests", "mode", "assignment"))
        key = (cond, r["config"]["sim"]["seed"], r["split"])
        by[key][_get(r, "combo")] = r
        meta[key] = r
    acc = defaultdict(list)  # cell -> [(seed, base_ms, cand_ms, base_r, cand_r)]
    for (cond, seed, split), cells in by.items():
        base = cells.get(baseline_combo)
        if base is None:
            continue
        for combo, r in cells.items():
            if combo == baseline_combo:
                continue
            acc[(split,) + cond + (combo,)].append(
                (seed, base["metrics"]["makespan_s"], r["metrics"]["makespan_s"],
                 base, r))
    print(f"\n===== 조합 비교 {label} (기준={baseline_combo}) =====", file=out)
    print(f"{'조건(split,p,R,mode,조합)':<58}{'전체산식':>12}{'CI(전체)':>20}"
          f"{'실행평균':>10}{'CI(평균)':>20}{'초절감':>9}{'거리절감':>9}", file=out)
    for cell in sorted(acc):
        pairs = acc[cell]
        seeds = sorted({p[0] for p in pairs})
        sb = sum(p[1] for p in pairs)
        sc = sum(p[2] for p in pairs)
        overall = 100 * (sb - sc) / sb
        per_run = mean(100 * (p[1] - p[2]) / p[1] for p in pairs)
        ci_all = group_bootstrap([(p[0], p[1], p[2]) for p in pairs], "overall")
        ci_mean = group_bootstrap([(p[0], p[1], p[2]) for p in pairs], "per_run")
        dist_base = mean(p[3]["metrics"]["total_walk_m"] for p in pairs)
        dist_cand = mean(p[4]["metrics"]["total_walk_m"] for p in pairs)
        saved_s = (sb - sc) / len(seeds)
        print(f"{str(cell):<58}{overall:>+11.2f}%{fmt_ci(ci_all):>20}"
              f"{per_run:>+9.2f}%{fmt_ci(ci_mean):>20}{saved_s:>8.1f}s"
              f"{dist_base - dist_cand:>8.1f}m", file=out)
    return acc


def absolute_details(rows, out, suites):
    """절대값·계산비용·개선/동일/악화·최대 악화 사례."""
    subset = [r for r in rows if r["suite"] in suites]
    by = defaultdict(dict)
    for r in subset:
        key = (r["split"], _get(r, "pickers"), _get(r, "requests"),
               _get(r, "mode"), r["config"]["sim"]["seed"])
        by[key][_get(r, "combo")] = r
    stats = defaultdict(lambda: {"imp": 0, "same": 0, "worse": 0, "worst": (0.0, None),
                                 "mk_b": [], "mk_c": [], "wait_b": [], "wait_c": [],
                                 "walk_b": [], "walk_c": [], "last_wait": [],
                                 "plan_wall": [], "plan_delay": [], "plan_wait": []})
    for (split, p, reqs, mode, seed), cells in by.items():
        base = cells.get("nn")
        if base is None:
            continue
        for combo, r in cells.items():
            if combo == "nn":
                continue
            mb, mc = base["metrics"]["makespan_s"], r["metrics"]["makespan_s"]
            imp = 100 * (mb - mc) / mb
            d = stats[(split, p, reqs, mode, combo)]
            d["imp" if imp > EPS else "same" if imp >= -EPS else "worse"] += 1
            if imp < d["worst"][0]:
                d["worst"] = (imp, seed)
            d["mk_b"].append(mb)
            d["mk_c"].append(mc)
            d["wait_b"].append(base["metrics"]["total_zone_wait_s"])
            d["wait_c"].append(r["metrics"]["total_zone_wait_s"])
            d["walk_b"].append(base["metrics"]["total_walk_m"])
            d["walk_c"].append(r["metrics"]["total_walk_m"])
            lf = r["metrics"].get("last_finisher") or {}
            d["last_wait"].append(lf.get("zone_wait_s"))
            d["plan_wall"].append(r["metrics"]["plan"]["wall_seconds"])
            d["plan_delay"].append(r["metrics"]["plan"]["sim_delay_seconds"])
            d["plan_wait"].append(r["metrics"]["plan_wait_total_s"])
    print("\n===== 절대값·계산비용 (기준=NN, 제안=조합) =====", file=out)
    for cell in sorted(stats):
        d = stats[cell]
        n = len(d["mk_b"])
        print(f"{cell}: n={n} 기준종료={mean(d['mk_b']):.1f}s 제안종료={mean(d['mk_c']):.1f}s "
              f"절감={mean(d['mk_b']) - mean(d['mk_c']):.1f}s/실행 "
              f"거리 {mean(d['walk_b']):.0f}→{mean(d['walk_c']):.0f}m "
              f"대기 {mean(d['wait_b']):.1f}→{mean(d['wait_c']):.1f}s "
              f"개선/동일/악화={d['imp']}/{d['same']}/{d['worse']} "
              f"최대악화={d['worst'][0]:.2f}%(seed {d['worst'][1]})", file=out)
        print(f"    계산: 실측 {mean(d['plan_wall']):.2f}s, 반영지연 {mean(d['plan_delay']):.2f}s, "
              f"작업자 계획대기 {mean(d['plan_wait']):.2f}s, 마지막완료자 대기 "
              f"{mean([x for x in d['last_wait'] if x is not None]) if any(x is not None for x in d['last_wait']) else 0:.1f}s",
              file=out)


# ------------------------------------------------------- §2 배정 기록 분석
def assignment_records(rows, out, suites):
    """작업 묶음 수·작업자별 작업 수 분포·연쇄 시작·유휴·불균형."""
    subset = [r for r in rows if r["suite"] in suites and _get(r, "combo") == "nn"]
    print("\n===== 배정 기록 (NN 기준 실행) =====", file=out)
    for cell in sorted({(r["split"], _get(r, "pickers"), _get(r, "requests"),
                         _get(r, "mode")) for r in subset}):
        group = [r for r in subset if (r["split"], _get(r, "pickers"),
                                       _get(r, "requests"), _get(r, "mode")) == cell]
        tasks_per_run, per_picker_all, chained, idle_runs, spreads = [], [], 0, 0, []
        for r in group:
            recs = r.get("task_records", [])
            tasks_per_run.append(len(recs))
            by_picker = defaultdict(list)
            for t in recs:
                by_picker[t["picker"]].append(t)
            counts = [len(v) for v in by_picker.values()]
            per_picker_all.extend(counts)
            n_pickers = r["config"]["sim"]["pickers"]
            idle_runs += n_pickers - len(by_picker)
            for pid, ts in by_picker.items():
                ts.sort(key=lambda t: t["issued_at"])
                for t in ts[1:]:  # 후속 작업: 직전 하차 위치 출발(집결지 아님)
                    if tuple(t["start_node"]) != tuple(r["config"]["warehouse"]["staging"]):
                        chained += 1
            spreads.append(r["metrics"]["busy_spread_s"])
        print(f"{cell}: 작업수/실행={median(tasks_per_run):.0f} "
              f"작업자별작업 분포 min={min(per_picker_all) if per_picker_all else 0}/"
              f"중앙={median(per_picker_all) if per_picker_all else 0}/"
              f"max={max(per_picker_all) if per_picker_all else 0} "
              f"연쇄시작 합계={chained} / 실행평균={chained / len(group):.1f} "
              f"유휴작업자={idle_runs} 작업시간편차중앙={median(spreads):.0f}s",
              file=out)


# ------------------------------------------------------- §5 혼잡 추적
def congestion_tracking(rows, out):
    """같은 seed의 base/v1/v2 쌍: 종료시간·대기·거리·마지막 완료자·예측 오차."""
    cong = [r for r in rows if r["suite"].startswith("congestion-")]
    if not cong:
        return
    by = defaultdict(dict)
    for r in cong:
        method = r["suite"].rsplit("-", 1)[-1]          # dev-<method>/eval-<method>
        key = (r["split"], _get(r, "pickers"), r["config"]["sim"]["seed"])
        by[key][method] = r
    print("\n===== 혼잡 고려 추적 (극한 시나리오, 쌍 비교) =====", file=out)
    stats = defaultdict(lambda: {"mk": [], "wait": [], "walk": [], "pred": [],
                                 "last_wait": [], "imp": [], "dwait": [], "dwalk": [],
                                 "adopts": [], "wait_shift": []})
    for (split, p, seed), cells in sorted(by.items()):
        base = cells.get("base")
        if base is None:
            continue
        for method in ("v1", "v2"):
            r = cells.get(method)
            if r is None:
                continue
            mb, mc = base["metrics"]["makespan_s"], r["metrics"]["makespan_s"]
            wb, wc = base["metrics"]["total_zone_wait_s"], r["metrics"]["total_zone_wait_s"]
            kb, kc = base["metrics"]["total_walk_m"], r["metrics"]["total_walk_m"]
            d = stats[(split, p, method)]
            d["mk"].append((mb, mc))
            d["wait"].append((wb, wc))
            d["walk"].append((kb, kc))
            d["pred"].append((base["metrics"].get("prediction_mae_s"),
                              r["metrics"].get("prediction_mae_s")))
            lf = r["metrics"].get("last_finisher") or {}
            lb = base["metrics"].get("last_finisher") or {}
            d["last_wait"].append((lb.get("zone_wait_s"), lf.get("zone_wait_s")))
            d["imp"].append(100 * (mb - mc) / mb)
            d["dwait"].append(wb - wc)
            d["dwalk"].append(kc - kb)
            d["adopts"].append(len(r["metrics"]["plan"].get("adoption_log", [])))
            # 가설 C: 한 작업자의 대기 감소가 다른 작업자 대기 증가와 맞바뀌었는가
            pw = {int(k): v["zone_wait_s"] for k, v in base["pickers"].items()}
            qw = {int(k): v["zone_wait_s"] for k, v in r["pickers"].items()}
            gains = [pw[k] - qw.get(k, 0.0) for k in pw]
            d["wait_shift"].append((sum(x for x in gains if x > 0),
                                    -sum(x for x in gains if x < 0)))
    for cell in sorted(stats):
        d = stats[cell]
        n = len(d["imp"])
        print(f"{cell}: n={n} 종료 개선(실행평균)={mean(d['imp']):+.2f}% "
              f"[최악 {min(d['imp']):+.2f}%, 최선 {max(d['imp']):+.2f}%] "
              f"대기 {mean(a for a, _ in d['wait']):.0f}→{mean(b for _, b in d['wait']):.0f}s "
              f"(Δ={mean(d['dwait']):+.0f}s) 거리 {mean(a for a, _ in d['walk']):.0f}→"
              f"{mean(b for _, b in d['walk']):.0f}m (Δ={mean(d['dwalk']):+.0f}m)", file=out)
        pred_b = [a for a, _ in d["pred"] if a is not None]
        pred_c = [b for _, b in d["pred"] if b is not None]
        if pred_b and pred_c:
            print(f"    예측MAE {mean(pred_b):.1f}→{mean(pred_c):.1f}s "
                  f"채택이력평균={mean(d['adopts']):.1f}건 "
                  f"마지막완료자 대기 {mean(a for a, _ in d['last_wait'] if a is not None) if any(a is not None for a, _ in d['last_wait']) else 0:.0f}"
              f"→{mean(b for _, b in d['last_wait'] if b is not None) if any(b is not None for _, b in d['last_wait']) else 0:.0f}s "
                  f"대기 이전(감소/증가) {mean(a for a, _ in d['wait_shift']):.0f}/"
                  f"{mean(b for _, b in d['wait_shift']):.0f}s", file=out)
        # 가설 A: 대기 감소 < 거리 증가(시간 환산) 비율
        both = [(dw, dk) for dw, dk in zip(d["dwait"], d["dwalk"])]
        if both:
            reduced = sum(dw for dw, _ in both if dw > 0)
            grew = sum(dk for _, dk in both if dk > 0)
            print(f"    [참고 집계] 대기감소 합 {reduced:.0f}s vs 거리증가 합 {grew:.0f}m"
                  " (서로 다른 양의 변화 집계이며, 종료시간 악화의 인과 증거가 아님)",
                  file=out)


# ------------------------------------------------------- §5 예측-실제(채택)
def adoption_vs_actual(rows, out):
    """v2 채택 시 예측 목적함수 개선과 실제 결과의 방향 일치율(불일치=목적함수 문제)."""
    cong = [r for r in rows if r["suite"].endswith("-v2")]
    agree = disagree = total_adopts = 0
    for r in cong:
        log = r["metrics"]["plan"].get("adoption_log", [])
        total_adopts += len(log)
        # 실제 방향은 실행 쌍 비교가 아닌, 채택 라운드별 재실행이 필요하므로
        # 여기서는 기록된 목적함수가 실제로 개선 방향인지(양수 감소)만 확인
        for entry in log:
            before, after = entry["objective_before"], entry["objective_after"]
            if after[0] < before[0]:
                agree += 1
            else:
                disagree += 1
    if total_adopts:
        print(f"\n[목적함수 기록] v2 채택 {total_adopts}건: 추정 종료시간 감소 방향 "
              f"{agree}건 / 비감소(대기·거리 개선 우선) {disagree}건", file=out)


# ------------------------------------------------------- 기존 결과 재계산
def recompute_old(rows, out):
    """1차 결과(results/multi)를 두 산식으로 재계산 — 순차자원 버그 시기 데이터."""
    subset = [r for r in rows if r["suite"] in ("main", "per-picker")
              and "task_records" not in r]
    if not subset:
        return
    by = defaultdict(dict)
    for r in subset:
        key = (r["suite"], r["split"], _get(r, "pickers"), r["config"]["plan"]["assignment"],
               r["config"]["sim"]["seed"])
        by[key][r["config"]["plan"]["route_combo"]] = r
    acc = defaultdict(list)
    for key, cells in by.items():
        base = cells.get("nn")
        if not base:
            continue
        for combo, r in cells.items():
            if combo != "nn":
                acc[key[:4] + (combo,)].append(
                    (key[4], base["metrics"]["makespan_s"], r["metrics"]["makespan_s"]))
    print("\n===== 1차 결과 재계산(전체 산식 / 실행별 평균, 버그 시기 데이터) =====",
          file=out)
    for cell in sorted(acc):
        pairs = acc[cell]
        sb, sc = sum(p[1] for p in pairs), sum(p[2] for p in pairs)
        overall = 100 * (sb - sc) / sb
        per_run = mean(100 * (b - c) / b for _, b, c in pairs)
        ci_all = group_bootstrap(pairs, "overall")
        print(f"{cell}: 전체={overall:+.2f}% {fmt_ci(ci_all)} | 실행별평균={per_run:+.2f}% "
              f"n={len(pairs)}", file=out)


def main(results_dir="results/multi2", out=None):
    if out is None:
        out = sys.stdout
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    rows = load(results_dir)
    print(f"loaded {len(rows)} runs from {results_dir}", file=out)
    suites = sorted({r["suite"].split("-dev-")[0].split("-eval-")[0] for r in rows})
    print(f"suites: {suites}", file=out)
    route_suites = {s for s in suites if s in
                    ("fixed-total", "per-picker", "continuous20", "fixed20")}
    if route_suites:
        compare_combos(rows, out, route_suites, baseline_combo="nn")
        absolute_details(rows, out, route_suites)
        assignment_records(rows, out, route_suites)
    if "main" in suites or "per-picker" in suites:
        recompute_old(rows, out)
    congestion_tracking(rows, out)
    adoption_vs_actual(rows, out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/multi2")
