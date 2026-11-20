# -*- coding: utf-8 -*-
"""전체 수거 요청 생성(시드 결정론적)과 workload 특성 기록.

요청 = (위치, 수량, 품목별 포장 유형). 포장 유형은 모든 비교 방법에
동일하게 제공되므로 시뮬레이터가 아닌 요청 데이터에 고정한다.
"""
import random
from collections import Counter

from .config import RunConfig


def generate_requests(run: RunConfig, warehouse, rng: random.Random):
    """요청 리스트와 특성 요약을 반환한다.

    - 기본: 전체 수거 위치에서 균등 추출.
    - hot_aisle_share>0: 해당 비율의 요청을 무작위로 뽑은 한 통로에 집중.
    - duplicate_share>0: 해당 비율의 요청은 앞서 뽑은 위치를 재사용(중복 요청).
    - 수량은 1(70%)/2(25%)/3(5%), 품목별 포장은 easy_ratio 확률로 바로 담기.
    """
    locations = list(warehouse.locations)
    if not locations:
        raise ValueError("수거 위치가 없습니다")
    hot_aisle = rng.choice(sorted({x for x, _ in locations}))
    requests = []
    for i in range(run.total_requests):
        if run.duplicate_share > 0 and requests and rng.random() < run.duplicate_share:
            location = requests[rng.randrange(len(requests))]["location"]
        elif run.hot_aisle_share > 0 and rng.random() < run.hot_aisle_share:
            pool = [p for p in locations if p[0] == hot_aisle]
            location = pool[rng.randrange(len(pool))]
        else:
            location = locations[rng.randrange(len(locations))]
        r = rng.random()
        qty = 1 if r < 0.70 else 2 if r < 0.95 else 3
        kinds = ["easy" if rng.random() < run.pick.easy_ratio else "packed" for _ in range(qty)]
        requests.append({"id": i, "location": location, "qty": qty, "kinds": kinds})
    return requests


def request_features(requests, warehouse, pick_cfg):
    """workload 특성(보조 지표용)."""
    locs = [r["location"] for r in requests]
    per_loc = Counter(locs)
    hot = per_loc.most_common(1)[0] if per_loc else None
    aisle_counts = Counter(x for x, _ in locs)
    items = [k for r in requests for k in r["kinds"]]
    return {
        "total_requests": len(requests),
        "total_items": sum(r["qty"] for r in requests),
        "unique_locations": len(per_loc),
        "duplicate_request_count": len(requests) - len(per_loc),
        "easy_item_ratio": (sum(1 for k in items if k == "easy") / len(items)) if items else None,
        "max_single_location_items": max(per_loc.values()) if per_loc else 0,
        "max_aisle_request_share": (max(aisle_counts.values()) / len(requests)) if aisle_counts else 0,
        "hot_aisle": hot[0][0] if hot else None,
    }
