# -*- coding: utf-8 -*-
"""다중 작업자 연속 작업 시뮬레이션 설정.

모든 크기·시간 값은 이 파일(또는 CLI 인자)로 분리한다. 기본값 근거는
docs/15-multi-picker-simulation.md 참고.
"""
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class WarehouseConfig:
    """격자 창고와 ㄷ자 컨베이어 형상.

    - 세로 통로는 x_step 간격, 노드 간격은 y_step.
    - 가로 연결 통로는 cross_ys에 지정한 y에서만 존재(선반 통과 금지).
    - belt_walls에 지정된 외벽을 따라 폭 belt_width_m의 벨트가 있고,
      나머지 한 쪽(기본 앞쪽 y=0)은 개방. 벨트 접근 노드는
      access_spacing_m 간격으로 해당 외벽 통로 위에 놓는다(연속 구간의 이산 근사).
    """
    width: int = 36
    height: int = 40
    x_step: int = 4
    y_step: int = 2
    cross_ys: tuple = (0, 20, 40)
    belt_walls: tuple = ("left", "back", "right")
    belt_width_m: float = 1.0
    access_spacing_m: float = 2.0
    staging: tuple = (16, 0)
    name: str = "warehouse-u-belt-v1"

    def refined(self, spacing: float) -> "WarehouseConfig":
        return replace(self, access_spacing_m=spacing)


@dataclass(frozen=True)
class PickConfig:
    """수거·하차·혼잡 규칙(작업 지시에 명시된 값이 기본)."""
    easy_seconds: float = 10.0
    packed_seconds: float = 30.0
    easy_ratio: float = 0.4          # 품목 단위 기본 비율(바로 담기)
    unload_seconds: float = 5.0
    zone_length_m: float = 4.0       # 수거 구역 길이(같은 통로·같은 쪽)
    zone_capacity: int = 3           # 구역당 동시 수거 인원
    walk_speed_m_s: float = 1.0      # 모델 가정: 바구니를 낀 보행 1.0m/s


@dataclass(frozen=True)
class PlanConfig:
    """작업 분할·경로 개선·배정 개선 설정."""
    requests_per_task: int = 12      # 작업당 요청 수 상한(연속 작업 유발)
    quantity_per_task: int | None = None
    route_combo: str = "nn"          # nn|nn-2opt|nn-reinsert|nn-2opt-reinsert|nn-reinsert-2opt|alt|nn-2opt-reinsert-segdp
    assignment: str = "spatial"      # roundrobin(단순)|spatial(거리 중심)|balanced(작업량 균형)
    move_swap: bool = True
    move_swap_rounds: int = 3
    congestion_aware: bool = False   # 거리 중심(False) vs 혼잡 고려(True)
    congestion_mode: str = "v2"      # v1|v2|auto(예상 대기가 임계 이상일 때만 v2)
    congestion_threshold_s: float = 30.0  # auto 판정 임계(개발 데이터로 고정 후 동결)
    dropoff_lookahead: bool = False  # 기본 정책=최근접 하차. True=1단계 선행 평가(확장 후보)
    lookahead_candidates: int = 4    # 선행 평가에서 검토하는 벨트 접근 후보 수
    improvement_eval_budget: int = 20000   # 작업당 평가 횟수 협력적 상한
    segdp_window: int = 6
    segdp_step: int = 3
    # --- 3차 입증: 묶음 구성·배정·LNS ---
    bundling: str = "chunk"            # chunk((x,y) 정렬 청크)|savings(거리 절약 병합)
    max_task_seconds: float | None = None  # 묶음 예상 소요 상한(선택)
    variable_cap: bool = False         # 작업 수 < 작업자 수일 때 최대 묶음 분할
    lns: bool = False                  # 병목 제한 LNS(계획 시점, 미발급 묶음만)
    lns_iters: int = 20
    lns_time_budget_s: float = 2.0
    lns_remove_q: int = 4
    lns_seed: int = 0


@dataclass(frozen=True)
class SimConfig:
    """실행 단위·계산 시간 반영 방식."""
    pickers: int = 10
    seed: int = 1
    compute_mode: str = "measured"   # measured(실측 반영)|fixed(고정 지연, 재현성)
    fixed_initial_plan_s: float = 0.05
    fixed_wave_s: float = 0.01
    record_events: bool = False


@dataclass(frozen=True)
class RunConfig:
    warehouse: WarehouseConfig = field(default_factory=WarehouseConfig)
    pick: PickConfig = field(default_factory=PickConfig)
    plan: PlanConfig = field(default_factory=PlanConfig)
    sim: SimConfig = field(default_factory=SimConfig)
    total_requests: int = 240
    hot_aisle_share: float = 0.0     # 0보다 크면 해당 비율의 요청을 한 통로에 집중
    duplicate_share: float = 0.0     # 기존 요청 위치를 재사용하는 요청 비율
