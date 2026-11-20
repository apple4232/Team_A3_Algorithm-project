# -*- coding: utf-8 -*-
"""병목 분석: 종료시간을 구성 요소로 분해한다(작업자 시간 합계 ≠ 종료시간).

Usage: python -I simulation/bottleneck.py [results_dir] [suites...]

출력(조건별 평균):
- 용량 대비 부하: Σ작업자 작업시간 / (인원×종료시간) = 병렬 활용도
- 구성(작업자 합계 기준): 이동/수거/구역대기/계획대기/하차/유휴 비율
- 마지막 완료자: 작업 수·이동·수거·대기·계획대기·유휴, 종료시간 대비 구성
- 종료시간 구조: max(작업자 (작업+대기+계획대기)) + 초기계획지연 ≈ 종료시간 검증
"""
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean


def load(results_dir, suites):
    rows = []
    for name in suites:
        path = Path(results_dir) / f"{name}.jsonl"
        if not path.exists():
            continue
        for line in open(path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                r.setdefault("suite", name)
                rows.append(r)
    return rows


def main(results_dir="results/multi2", suites=("continuous20", "fixed20"),
         out=None):
    if out is None:
        out = sys.stdout
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    rows = [r for r in load(results_dir, suites)
            if r["config"]["plan"]["route_combo"] == "nn"
            and r["config"]["plan"]["assignment"] == "spatial"
            and not r["config"]["plan"]["congestion_aware"]]
    print(f"NN 기준 실행 {len(rows)}건", file=out)
    acc = defaultdict(list)
    for r in rows:
        m = r["metrics"]
        speed = r["config"]["pick"]["walk_speed_m_s"]
        unload = r["config"]["pick"]["unload_seconds"]
        mk = m["makespan_s"]
        n_pickers = r["config"]["sim"]["pickers"]
        walk = sum(p["walk_m"] for p in r["pickers"].values()) / speed
        pick = sum(p["pick_s"] for p in r["pickers"].values())
        zwait = sum(p["zone_wait_s"] for p in r["pickers"].values())
        pwait = sum(p["plan_wait_s"] for p in r["pickers"].values())
        n_tasks = m["tasks_done"]
        unload_total = unload * n_tasks
        idle = sum(p["idle_s"] for p in r["pickers"].values())
        lf = m.get("last_finisher") or {}
        lfp = r["pickers"][str(lf["picker"])] if lf and str(lf["picker"]) in r["pickers"] else (r["pickers"].get(lf["picker"]) if lf else None)
        per_picker_max = max((p["busy_s"] + p["zone_wait_s"] + p["plan_wait_s"])
                             for p in r["pickers"].values())
        initial_delay = m["plan"]["sim_delay_seconds"] - m["plan_wait_total_s"]
        initial_delay = max(0.0, initial_delay)
        cond = (r["split"], n_pickers, r["config"]["total_requests"],
                r["config"]["sim"]["compute_mode"])
        acc[cond].append({
            "mk": mk, "walk": walk, "pick": pick, "zwait": zwait,
            "pwait": pwait, "unload": unload_total, "idle": idle,
            "util": (walk + pick + zwait + pwait + unload_total) / (n_pickers * mk),
            "lf_tasks": (lfp or {}).get("tasks"),
            "lf_walk": (lfp or {}).get("walk_m", 0) / speed,
            "lf_pick": (lfp or {}).get("pick_s", 0),
            "lf_zwait": (lfp or {}).get("zone_wait_s", 0),
            "lf_pwait": (lfp or {}).get("plan_wait_s", 0),
            "lf_idle": (lfp or {}).get("idle_s", 0),
            "decomp_gap": mk - (per_picker_max + initial_delay),
        })
    print(f"{'조건(split,p,R,mode)':<34}{'종료':>8}{'활용도':>7}{'이동':>7}{'수거':>8}"
          f"{'구역대기':>8}{'계획대기':>8}{'하차':>7}{'유휴':>8}  마지막완료자(작업수/이동/수거/대기/계획대기/유휴)  분해오차",
          file=out)
    for cond in sorted(acc):
        runs = acc[cond]
        n = len(runs)
        avg = lambda k: mean(x[k] for x in runs)  # noqa: E731
        print(f"{str(cond):<34}{avg('mk'):>8.1f}{avg('util'):>7.1%}"
              f"{avg('walk'):>7.1f}{avg('pick'):>8.1f}{avg('zwait'):>8.1f}"
              f"{avg('pwait'):>8.1f}{avg('unload'):>7.1f}{avg('idle'):>8.1f}"
              f"  {avg('lf_tasks') or 0:.0f}개/{avg('lf_walk'):.0f}s/{avg('lf_pick'):.0f}s/"
              f"{avg('lf_zwait'):.0f}s/{avg('lf_pwait'):.0f}s/{avg('lf_idle'):.0f}s"
              f"  {avg('decomp_gap'):+.1f}s", file=out)
    print("\n해석 기준: 이동/수거/대기/하차/유휴는 작업자 시간 합계(병렬 수행 포함)이며, "
          "종료시간과 직접 더하지 않는다. 활용도=합계/(인원×종료시간).", file=out)
    print("분해오차 = 종료시간 − (최대 작업자 부하 + 초기 계획 지연 추정): 0에 가까우면 "
          "종료시간이 최대 부하 작업자에 의해 결정됨을 시사(인과 단정 아님).", file=out)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    main(args[0] if args else "results/multi2",
         tuple(args[1:]) or ("continuous20", "fixed20"))
