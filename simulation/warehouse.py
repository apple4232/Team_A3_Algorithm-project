# -*- coding: utf-8 -*-
"""ㄷ자 컨베이어 창고 그래프와 수거 구역.

- 그래프 표현: 기존 picking 패키지와 동일하게 노드=통로 지점, 간선=통로 구간.
  벨트는 외벽 바깥쪽 폭 1m에 있으므로 어떤 간선도 벨트나 선반을 가로지르지 않는다.
- 연속 벨트 접근 구간의 근사: 벨트 옆 통로(외벽 열/행)를 따라 access_spacing_m
  이하 간격의 접근 노드를 두고 하차 비용 = min(통로 최단거리). 이산화 오차 상한은
  절반 간격(기본 1.0m)이며 test_simulation.py에서 조밀 그래프와 비교 검증한다.
- 통로는 양방향 2인 통행 가능(모델 가정). 점유·교행은 지표로만 기록.
"""
from types import SimpleNamespace

from picking.distances import dijkstra

from .config import WarehouseConfig


def _split_points(a, b, spacing):
    """간선 (a,b) 위를 spacing 이하 간격으로 나누는 내부 점들(정렬)."""
    (x1, y1), (x2, y2) = a, b
    length = abs(x2 - x1) + abs(y2 - y1)
    if length <= spacing + 1e-9:
        return []
    pieces = int(-(-length // spacing))
    return [(round(x1 + (x2 - x1) * k / pieces, 6), round(y1 + (y2 - y1) * k / pieces, 6))
            for k in range(1, pieces)]


class Warehouse:
    """통로 그래프 + 벨트 접근 노드 + 최단거리 캐시."""

    def __init__(self, cfg: WarehouseConfig):
        self.config = cfg
        xs = list(range(0, cfg.width + 1, cfg.x_step))
        ys = list(range(0, cfg.height + 1, cfg.y_step))
        if cfg.staging[0] not in xs or cfg.staging[1] not in ys:
            raise ValueError("집결지는 그래프 노드여야 합니다")
        grid = {(x, y) for x in xs for y in ys}
        # 1) 간선 목록: 세로 통로 + 가로 연결 통로
        base_edges = []
        for x in xs:
            for y in ys[:-1]:
                base_edges.append(((x, y), (x, y + cfg.y_step)))
        for y in cfg.cross_ys:
            for x in xs[:-1]:
                base_edges.append(((x, y), (x + cfg.x_step, y)))
        # 2) 벨트 접근 구간(외벽 통로 선분)과 접근 노드
        belt_edges = []
        if "left" in cfg.belt_walls:
            belt_edges += [((0, y), (0, y + cfg.y_step)) for y in ys[:-1]]
        if "right" in cfg.belt_walls:
            w = xs[-1]
            belt_edges += [((w, y), (w, y + cfg.y_step)) for y in ys[:-1]]
        if "back" in cfg.belt_walls:
            h = ys[-1]
            belt_edges += [((x, h), (x + cfg.x_step, h)) for x in xs[:-1]]
        if "front" in cfg.belt_walls:
            belt_edges += [((x, 0), (x + cfg.x_step, 0)) for x in xs[:-1]]
        belt_set = set(belt_edges) | {(b, a) for a, b in belt_edges}
        self.access_nodes = set()
        extra = set()
        for a, b in belt_edges:
            self.access_nodes.add(a)
            self.access_nodes.add(b)
            for m in _split_points(a, b, cfg.access_spacing_m):
                self.access_nodes.add(m)
                extra.add(m)
        # 3) 인접 구성: 벨트 통로 간선은 중간 접근 노드로 분할
        adjacency = {n: {} for n in grid | extra}
        for a, b in base_edges:
            if (a, b) in belt_set:
                on_edge = sorted(_split_points(a, b, cfg.access_spacing_m))
                pts = [a] + on_edge + [b]
            else:
                pts = [a, b]
            for p, q in zip(pts[:-1], pts[1:]):
                seg = abs(q[0] - p[0]) + abs(q[1] - p[1])
                adjacency[p][q] = float(seg)
                adjacency[q][p] = float(seg)
        self.adjacency = adjacency
        self.access_nodes = tuple(sorted(self.access_nodes))
        self.staging = cfg.staging
        # 수거 위치: 가로 통로가 아닌 원래 격자 노드(중간점 제외)
        self.locations = tuple(sorted(n for n in grid if n[1] not in cfg.cross_ys))
        self._dist = {}
        self._prev = {}

    # ---- 거리/경로 ----
    def distances_from(self, source):
        if source not in self._dist:
            if source not in self.adjacency:
                raise KeyError(f"노드가 지도에 없습니다: {source}")
            dist, prev = dijkstra(SimpleNamespace(adjacency=self.adjacency), source)
            self._dist[source] = dist
            self._prev[source] = prev
        return self._dist[source]

    def path(self, source, target):
        """source→target 통로 경로(노드열)."""
        if source not in self.adjacency or target not in self.adjacency:
            raise KeyError("경로 끝점이 지도 노드가 아닙니다")
        if source == target:
            return (source,)
        dist = self.distances_from(source)
        if target not in dist:
            raise KeyError(f"도달 불가: {source}→{target}")
        prev = self._prev[source]
        out = [target]
        while out[-1] != source:
            out.append(prev[out[-1]])
        return tuple(reversed(out))

    def d(self, a, b):
        return self.distances_from(a)[b]

    def belt_cost(self, node):
        dist = self.distances_from(node)
        return min(dist[a] for a in self.access_nodes)

    def belt_node(self, node):
        dist = self.distances_from(node)
        return min(self.access_nodes, key=lambda a: (dist[a], a))


def build_warehouse(cfg: WarehouseConfig | None = None) -> Warehouse:
    """설정으로 창고를 구성한다(기본 = 기존 10통로 36×40m + ㄷ자 벨트)."""
    return Warehouse(cfg or WarehouseConfig())


def zone_of(node, pick_cfg) -> tuple:
    """수거 구역: (통로 x, 같은 쪽, 길이 L 구간).

    합성 모델에는 좌/우 선반 구분이 없어 (y//y_step)%2로 쪽을 번갈아 배정한다
    (모델 가정, docs/15 참고). 같은 통로 같은 쪽의 L미터 구역이 자원 단위.
    """
    x, y = node
    return (x, (y // 2) % 2, int(y // pick_cfg.zone_length_m))
