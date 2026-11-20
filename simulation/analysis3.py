# -*- coding: utf-8 -*-
"""입증 실험(3차) 분석: 사다리별 단계 기여·두 산식·절대값·확장 축.

Usage: python -I simulation/analysis3.py results/multi3-dev
       python -I simulation/analysis3.py results/multi3-eval

짝짓기 키: (suite 접두, 라벨/L0..L6, 작업자 수, 요청량, 창고 이름, seed, split).
기준: L1-sp-nn(주 기준), L0-rr-nn(약한 기준 참고).
주요 지표는 조건별 전체 집계 개선율(요구 산식), 보조로 실행별 평균·CI(산식별 재계산).
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

LADDER_ORDER = ["L0-rr-nn", "L1-sp-nn", "L2-bal-nn", "L3-bal-n2r",
                "L4-bal-n2r-ms", "L5-bal-n2r-ms-auto", "L6-sp-n2r"]


def load(results_dir):
    rows = []
    for path in sorted(Path(results_dir).glob("*.jsonl")):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                rows.append(r)
    return rows


def key_of(r):
    suite, _, label = r["suite"].partition("|")
    return (suite, label, r["config"]["sim"]["pickers"],
            r["config"]["total_requests"], r["config"]["warehouse"]["name"],
            r["config"]["sim"]["seed"], r["split"])


def cond_of(r):
    suite, _, label = r["suite"].partition("|")
    return (suite, label, r["config"]["sim"]["pickers"],
            r["config"]["total_requests"], r["config"]["warehouse"]["name"],
            r["config"]["sim"]["compute_mode"])


def group_ci(pairs, formula, seed=0, repetitions=1000):
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
            sb, sc = sum(b for b, _ in flat), sum(c for _, c in flat)
            samples.append(100 * (sb - sc) / sb if sb else 0.0)
        else:
            samples.append(mean(100 * (b - c) / b for b, c in flat if b))
    samples.sort()
    return [samples[int(.025 * repetitions)], samples[int(.975 * repetitions) - 1]]


def ladder_report(rows, out, baseline="L1-sp-nn", weak="L0-rr-nn"):
    """사다리 라벨별: 두 산식+CI, 절대값, 단계 증분(전 단계 대비 초)."""
    by = {}
    for r in rows:
        if r["suite"].startswith("ladder"):
            by[key_of(r)] = r
    conds = sorted({k[:6] for k in by})  # (suite,label,p,R,wh,mode) sans seed/split... 
    conds = sorted({(k[0], k[1], k[2], k[3], k[4]) for k in by})
    print("\n===== 사다리별 개선율(주=전체 집계식 / 보조=실행별 평균) =====", file=out)
    print(f"{'조건(suite,라벨,p,R,창고,모드)':<58}{'n':>3}{'전체':>9}{'CI(전체)':>20}"
          f"{'실행평':>8}{'CI(실행평)':>20}{'초절감':>8}{'거리절감':>9}", file=out)
    stage = defaultdict(dict)
    for cond in conds:
        suite, label, p, R, wh = cond
        seed_split = {(k[5], k[6]): r for k, r in by.items()
                      if (k[0], k[1], k[2], k[3], k[4]) == cond}
        base = {(s, sp): r for (s, sp), r in seed_split.items()
                if s is not None and True and r["suite"].endswith(baseline)}
        # 같은 (p,R,wh,seed,split)의 baseline 행 찾기
        base_rows = {}
        for k, r in by.items():
            if (k[1] == baseline and k[2] == p and k[3] == R and k[4] == wh
                    and k[0] == suite.split("|")[0] + "|x"):  # placeholder
                pass
        # 단순화: baseline은 같은 suite 접두(ladder)에서 p,R,wh,seed,split 일치로
        base_map = {}
        for k, r in by.items():
            if k[1] == baseline and k[2] == p and k[3] == R and k[4] == wh:
                base_map[(k[5], k[6])] = r
        if label == baseline or not base_map:
            for (seed, split), r in seed_split.items():
                stage[(cond, split)][label] = r["metrics"]
            continue
        pairs, walks = [], []
        mk_b, mk_c = [], []
        for (seed, split), r in seed_split.items():
            b = base_map.get((seed, split))
            if not b:
                continue
            pairs.append((seed, b["metrics"]["makespan_s"], r["metrics"]["makespan_s"]))
            walks.append((b["metrics"]["total_walk_m"], r["metrics"]["total_walk_m"]))
            mk_b.append(b["metrics"]["makespan_s"])
            mk_c.append(r["metrics"]["makespan_s"])
        if not pairs:
            continue
        sb, sc = sum(p[1] for p in pairs), sum(p[2] for p in pairs)
        overall = 100 * (sb - sc) / sb
        per_run = mean(100 * (b - c) / b for _, b, c in pairs)
        ci_all = group_ci(pairs, "overall")
        ci_mean = group_ci(pairs, "per_run")
        n_seed = len({p[0] for p in pairs})
        dw = mean(b for b, _ in walks) - mean(c for _, c in walks)
        print(f"{str(cond):<58}{n_seed:>3}{overall:>+8.2f}%{str(ci_all):>20}"
              f"{per_run:>+7.2f}%{str(ci_mean):>20}"
              f"{(sb - sc) / n_seed:>7.1f}s{dw:>8.1f}m", file=out)
        for (seed, split), r in seed_split.items():
            stage[(cond, split)][label] = r["metrics"]
    # 단계 증분: L1→L2→L3→L4→L5 (같은 seed·split 짝)
    print("\n===== 단계별 증분(직전 사다리 단계 대비, 초/실행·전체 집계식) =====",
          file=out)
    chain = [c for c in LADDER_ORDER if c not in (weak, "L6-sp-n2r")]
    conds2 = sorted({(k[0], k[2], k[3], k[4], k[6]) for k in by})
    for cond in conds2:
        suite, p, R, wh, split = cond
        rows_by_label = {}
        for k, r in by.items():
            if (k[0], k[2], k[3], k[4], k[6]) == cond:
                rows_by_label.setdefault(k[1], {})[k[5]] = r["metrics"]
        parts = []
        for prev, nxt in zip(chain[:-1], chain[1:]):
            if prev not in rows_by_label or nxt not in rows_by_label:
                continue
            seeds = sorted(set(rows_by_label[prev]) & set(rows_by_label[nxt]))
            if not seeds:
                continue
            sb = sum(rows_by_label[prev][s]["makespan_s"] for s in seeds)
            sc = sum(rows_by_label[nxt][s]["makespan_s"] for s in seeds)
            parts.append(f"{prev[-6:]}→{nxt[-6:]} {(sb - sc) / len(seeds):+.1f}s")
        if parts:
            print(f"{cond}: {' | '.join(parts)}", file=out)


def axis_report(rows, out, prefixes):
    """bundle/lookahead/threshold/workload/large 축: 같은 축 내 쌍 비교."""
    for prefix in prefixes:
        subset = [r for r in rows if r["suite"].startswith(prefix + "|")]
        if not subset:
            continue
        print(f"\n===== {prefix} 축 =====", file=out)
        # 그룹: (축변수, p [, 창고]) × seed; 쌍 비교는 축 내 기본값 대비
        groups = defaultdict(dict)
        meta = {}
        for r in subset:
            suite, _, label = r["suite"].partition("|")
            key = (label, r["config"]["sim"]["pickers"],
                   r["config"]["total_requests"],
                   r["config"]["warehouse"]["name"])
            groups[key][r["config"]["sim"]["seed"]] = r
            meta[key] = r
        base_key = None
        # 축별 기준 결정
        labels = {k[0] for k in groups}
        for cand in ("off", "cap12-spatial-nn", "L1-sp-nn", "p0"):
            if any(l.startswith(cand) for l in labels):
                base_key = cand
                break
        if prefix == "bundle":
            base_key = None  # cap12-spatial-nn을 코드로
        for key in sorted(groups):
            if prefix == "bundle":
                label, p, R, wh = key
                if label != "cap12-spatial-nn":
                    continue
                # 같은 (p,R,wh)의 다른 라벨과 비교
                for other in sorted(groups):
                    if other == key or other[1:] != key[1:]:
                        continue
                    pairs = [(s, groups[key][s]["metrics"]["makespan_s"],
                              groups[other][s]["metrics"]["makespan_s"])
                             for s in set(groups[key]) & set(groups[other])]
                    if not pairs:
                        continue
                    sb, sc = sum(p[1] for p in pairs), sum(p[2] for p in pairs)
                    print(f"{other[0]} vs cap12-spatial-nn (p={other[1]}): "
                          f"전체 {100 * (sb - sc) / sb:+.2f}% "
                          f"CI{group_ci(pairs, 'overall')} "
                          f"{(sb - sc) / len({p[0] for p in pairs}):+.1f}s/실행 n={len(pairs)}",
                          file=out)
                continue
            label, p, R, wh = key
            if prefix in ("lookahead", "threshold"):
                is_base = label.endswith("off") or label == "off"
            else:
                is_base = label.endswith("L1-sp-nn")
            if not is_base:
                continue
            for other in sorted(groups):
                if other == key or other[1:] != key[1:]:
                    continue
                pairs = [(s, groups[key][s]["metrics"]["makespan_s"],
                          groups[other][s]["metrics"]["makespan_s"])
                         for s in set(groups[key]) & set(groups[other])]
                if not pairs:
                    continue
                sb, sc = sum(p[1] for p in pairs), sum(p[2] for p in pairs)
                n_seed = len({p[0] for p in pairs})
                extras = ""
                rr = groups[other][pairs[0][0]]["metrics"]
                if prefix == "lookahead":
                    la = rr.get("lookahead") or {}
                    extras = (f" 의사결정 {la.get('decisions')}회(기준외 {la.get('nondefault')}) "
                              f"계산 {la.get('wall_seconds', 0):.3f}s")
                print(f"{other[0]} vs {label} (p={other[1]}, R={other[2]}, {other[3]}): "
                      f"전체 {100 * (sb - sc) / sb:+.2f}% CI{group_ci(pairs, 'overall')} "
                      f"{(sb - sc) / n_seed:+.1f}s/실행 n={n_seed}{extras}", file=out)


def main(results_dir="results/multi3-dev", out=None):
    if out is None:
        out = sys.stdout
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    rows = load(results_dir)
    print(f"loaded {len(rows)} runs from {results_dir}", file=out)
    ladder_report(rows, out)
    axis_report(rows, out, ("lookahead", "threshold", "large", "workload", "bundle"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/multi3-dev")
