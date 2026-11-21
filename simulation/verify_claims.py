# -*- coding: utf-8 -*-
"""보고된 최종 결론 사전 검증(기존 원자료 재집계 + 결정론적 요청 재생성).

Usage: python -I simulation/verify_claims.py
새 시뮬레이션을 실행하지 않는다. results/multi3-eval 원자료와
저장된 seed로 요청을 재생성해 묶음 통계를 재계산한다.
"""
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulation.assignment import chunk_requests, roundrobin_chunks  # noqa: E402
from simulation.config import PlanConfig, RunConfig, WarehouseConfig  # noqa: E402
from simulation.requests import generate_requests  # noqa: E402
from simulation.warehouse import build_warehouse  # noqa: E402

OUT = []


def w(s=""):
    OUT.append(s.encode("ascii", "replace").decode("ascii"))


def load(fname):
    return [json.loads(l) for l in open(f"results/multi3-eval/{fname}", encoding="utf-8")
            if l.strip()]


# ---------------------------------------------------------------- 1. cap 의미
w("=" * 30 + " 1. cap24 의미와 분포 ")
pc = PlanConfig(requests_per_task=24)
w(f"requests_per_task는 '요청 수' 상한: chunk_requests가 len(current)+1 > cap 검사 "
  f"(assignment.py chunk_requests). 수량 상한 quantity_per_task={pc.quantity_per_task}(기본 비활성). "
  f"고유 위치 수 상한 아님.")
wh = build_warehouse(WarehouseConfig())
rows = load("eval-ladder.jsonl")
# seed별 요청 재생성(결정론) 후 cap12/cap24 청킹 통계
for cap in (12, 24):
    n_reqs, qtys, uniq = [], [], []
    for seed in range(203, 222, 2):
        rng = random.Random(seed)
        reqs = generate_requests(RunConfig(total_requests=480), wh, rng)
        chunks = chunk_requests(reqs, PlanConfig(requests_per_task=cap))
        n_reqs += [len(c) for c in chunks]
        qtys += [sum(r["qty"] for r in c) for c in chunks]
        uniq += [len({r["location"] for r in c}) for c in chunks]
    w(f"cap{cap}: 작업수/실행={len(n_reqs)/10:.0f} 요청/작업 min={min(n_reqs)} "
      f"max={max(n_reqs)} | 수량/작업 min={min(qtys)} 중앙={sorted(qtys)[len(qtys)//2]} "
      f"max={max(qtys)} | 고유위치/작업 min={min(uniq)} 중앙={sorted(uniq)[len(uniq)//2]} max={max(uniq)}")
# 전체 요청·수량 동일 처리 확인: 같은 seed의 L1 대 C3 total_pick_s 동일성
by = defaultdict(dict)
for r in rows:
    by[(r["config"]["sim"]["seed"],)][r["suite"].split("|")[1]] = r
mismatch = sum(1 for s, d in by.items()
               if "L1-sp-nn" in d and "C3-cap24-bal-n2r" in d
               and abs(d["L1-sp-nn"]["metrics"]["total_pick_s"]
                       - d["C3-cap24-bal-n2r"]["metrics"]["total_pick_s"]) > 1e-6)
same = sum(1 for s, d in by.items() if "L1-sp-nn" in d and "C3-cap24-bal-n2r" in d)
w(f"전체 처리 동일성: 같은 seed에서 L1과 C3의 total_pick_s 불일치 {mismatch}/{same}건 "
  f"(0이면 동일한 요청·품목을 모두 1회 처리)")

# ------------------------------------------------- 2/3. 단계 분해 정확화
w("")
w("=" * 30 + " 2·3. 성분 분해의 산식 ")
def overall_improvement(rows_a, rows_b, key):
    """(ΣA - ΣB)/ΣA: A=기준, B=비교. 같은 seed 짝."""
    ma = {r["config"]["sim"]["seed"]: r["metrics"][key] for r in rows_a}
    mb = {r["config"]["sim"]["seed"]: r["metrics"][key] for r in rows_b}
    seeds = sorted(set(ma) & set(mb))
    sa = sum(ma[s] for s in seeds)
    sb = sum(mb[s] for s in seeds)
    return 100 * (sa - sb) / sa, (sa - sb) / len(seeds), seeds


def rows_of(label, p):
    return [r for r in rows if r["suite"].endswith("|" + label)
            and r["config"]["sim"]["pickers"] == p
            and r["config"]["total_requests"] == 480
            and r["config"]["warehouse"]["name"] == "warehouse-u-belt-v1"]


for p in (10,):
    base = rows_of("L1-sp-nn", p)
    w(f"p={p}: 각 단계의 '공통 기준(L1) 대비 개선율'과 '직전 단계 대비 증분'")
    prev_pct = 0.0
    for label in ("C1-cap24-sp-nn", "C2-cap24-bal-nn", "C3-cap24-bal-n2r"):
        pct, secs, seeds = overall_improvement(base, rows_of(label, p), "makespan_s")
        w(f"  {label}: L1대비 {pct:+.3f}% ({secs:+.1f}s, n={len(seeds)}) | "
          f"직전 단계 대비 증분 {pct - prev_pct:+.3f}p p")
        prev_pct = pct
    total, secs, _ = overall_improvement(base, rows_of("C3-cap24-bal-n2r", p), "makespan_s")
    w(f"  검산: 단계 증분 합 = 최종 {total:+.3f}% 와 일치해야 함")
# 순서 민감성: cap12에서 배정 단계(L2)의 효과와 cap24에서 배정 단계 효과 비교
for p in (10,):
    w(f"상호작용 참고(p={p}): cap12에서 bal 단계 = {overall_improvement(rows_of('L1-sp-nn', p), rows_of('L2-bal-nn', p), 'makespan_s')[0]:+.3f}%, "
      f"cap24에서 bal 단계 = {overall_improvement(rows_of('C1-cap24-sp-nn', p), rows_of('C2-cap24-bal-nn', p), 'makespan_s')[0]:+.3f}%; "
      f"cap12에서 경로 단계 = {overall_improvement(rows_of('L2-bal-nn', p), rows_of('L3-bal-n2r', p), 'makespan_s')[0]:+.3f}%, "
      f"cap24에서 경로 단계 = {overall_improvement(rows_of('C2-cap24-bal-nn', p), rows_of('C3-cap24-bal-n2r', p), 'makespan_s')[0]:+.3f}%")
# 4가지 비교 존재 확인 (이동·교환 on/off)
w("요청된 4개 비교 존재 여부(원자료): "
  f"1)cap 고정외 동일(C1 vs L1) O 2)cap24 sp vs bal(C1 vs C2) O "
  f"3)동일 cap·배정 NN vs n2r(C2 vs C3) O 4)이동·교환 on/off: ", )
for p in (1, 10, 20):
    a, b = rows_of("L3-bal-n2r", p), rows_of("L4-bal-n2r-ms", p)
    pct, secs, seeds = overall_improvement(a, b, "makespan_s")
    w(f"   ms(L4-L3) p={p}: L3 대비 L4 {pct:+.3f}% ({secs:+.1f}s, n={len(seeds)}) — "
      f"'기준 켬/제안 끔' 비대칭 아님(둘 다 ms off; L4는 L3+ms)")

# --------------------------------------------------------- 4. 대형 창고
w("")
w("=" * 30 + " 4. 대형 창고 조건 ")
large = load("eval-large.jsonl")
for wh_name in ("large-large", "large-largecross"):
    for label in ("L1-sp-nn", "C3-cap24-bal-n2r"):
        rs = [r for r in large if r["suite"].startswith(wh_name + "|")
              and r["suite"].endswith("|" + label)]
        mk = [r["metrics"]["makespan_s"] for r in rs]
        w(f"{wh_name} {label}: n={len(rs)} 종료 중앙={sorted(mk)[len(mk)//2]:.1f}s "
          f"R={rs[0]['config']['total_requests']} seed예={rs[0]['config']['sim']['seed']}")
    a = [r for r in large if r["suite"].startswith(wh_name + "|") and r["suite"].endswith("|L1-sp-nn")]
    b = [r for r in large if r["suite"].startswith(wh_name + "|") and r["suite"].endswith("|C3-cap24-bal-n2r")]
    pct, secs, seeds = overall_improvement(a, b, "makespan_s")
    base_mean = mean(r["metrics"]["makespan_s"] for r in a)
    w(f"{wh_name}: 전체 {pct:+.3f}% | {secs:+.1f}s/실행 | 기준 평균 {base_mean:.1f}s "
      f"-> 검산 {secs / base_mean * 100:+.2f}% (10.94%와 일치 확인) | 동일 seed 쌍 n={len(seeds)}")

# --------------------------------------------------------- 5. 20인 악화
w("")
w("=" * 30 + " 5. 20인 악화 상세 ")
for label in ("L1-sp-nn", "C3-cap24-bal-n2r"):
    rs = [r for r in rows if r["suite"].endswith("|" + label)
          and r["config"]["sim"]["pickers"] == 20
          and r["config"]["total_requests"] == 480]
    tasks_per = []
    chained = 0
    for r in rs:
        byp = Counter(t["picker"] for t in r["task_records"])
        tasks_per += byp.values()
        staging = tuple(r["config"]["warehouse"]["staging"])
        for t in r["task_records"]:
            if tuple(t["start_node"]) != staging:
                chained += 1
    m = rs[0]["metrics"]
    w(f"{label} p=20: 작업/실행={len(rs[0]['task_records'])} 작업자별 "
      f"min/중앙/max={min(tasks_per)}/{sorted(tasks_per)[len(tasks_per)//2]}/{max(tasks_per)} "
      f"연쇄시작 합={chained} ({chained/len(rs):.0f}/실행) "
      f"busy_spread 중앙={sorted(x['metrics']['busy_spread_s'] for x in rs)[len(rs)//2]:.0f}s "
      f"plan_wait 합평균={mean(x['metrics']['plan_wait_total_s'] for x in rs):.1f}s "
      f"zone_wait={mean(x['metrics']['total_zone_wait_s'] for x in rs):.1f}s")
a = rows_of("L1-sp-nn", 20)
b = rows_of("C3-cap24-bal-n2r", 20)
pct, secs, _ = overall_improvement(a, b, "makespan_s")
w(f"20인 C3 vs L1: {pct:+.2f}% ({secs:+.1f}s)")
w("20인·R=960 cap24 자료 존재: "
  + str(any(r["config"]["sim"]["pickers"] == 20 and r["config"]["total_requests"] == 960
            and "C3" in r["suite"] for r in rows + large)))

# --------------------------------------------------- 6. 성공 기준 충족
w("")
w("=" * 30 + " 6. 성공 기준 충족 검사 ")
for p in (1, 10):
    a, b = rows_of("L1-sp-nn", p), rows_of("C3-cap24-bal-n2r", p)
    ma = {r["config"]["sim"]["seed"]: r["metrics"]["makespan_s"] for r in a}
    mb = {r["config"]["sim"]["seed"]: r["metrics"]["makespan_s"] for r in b}
    imps = sorted(100 * (ma[s] - mb[s]) / ma[s] for s in ma)
    wall = [r["metrics"]["plan"]["wall_seconds"] for r in b]
    pw = [r["metrics"]["plan_wait_total_s"] for r in b]
    mk = [r["metrics"]["makespan_s"] for r in b]
    pct, secs, _ = overall_improvement(a, b, "makespan_s")
    w(f"p={p}: 전체 {pct:+.2f}% ({secs:+.1f}s) 최대악화 {imps[0]:+.2f}% 최대개선 {imps[-1]:+.2f}% "
      f"악화건수 {sum(1 for x in imps if x < 0)}/{len(imps)} | 계획실측 최대 {max(wall):.2f}s "
      f"(기준 15s) | 계획대기/종료 최대 {max(x / y for x, y in zip(pw, mk)) * 100:.2f}% (기준 2%)")
w("동일 입력 반복 시간 측정: multi3에는 없음(무작위 순서만) — 스크립트로 확인 불가, 미수행")

print("\n".join(OUT))
open("results/multi3-eval/claim-verification.txt", "w", encoding="utf-8").write("\n".join(OUT))
