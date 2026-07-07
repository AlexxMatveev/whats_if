from typing import Dict, List, Optional
from pydantic import BaseModel


class SystemConfig(BaseModel):
    num_apps: int = 3
    containers_per_app: int = 2
    num_clients: int = 10000
    rps: int = 100
    db_latency_ms: float = 5.0


class Scenario(BaseModel):
    name: str
    params: Dict[str, float | int | str]


class NormativeEntry(BaseModel):
    app_name: str
    replicas: int = 1
    cpu_cores: float = 1.0
    memory_mib: float = 512
    hpa_cpu_pct: int | None = None
    estimated_rps_capacity: int = 200
    latency_slo_ms: int = 200
    error_slo_pct: float = 1.0


class AnalysisRequest(BaseModel):
    config: SystemConfig
    scenario: Scenario
    normatives: Optional[List[NormativeEntry]] = None


class ComponentMetrics(BaseModel):
    id: str
    label: str
    type: str
    cpu_percent: float
    memory_percent: float
    latency_ms: float
    rps: float
    error_rate: float
    status: str
    load_percent: float
    propagated: bool = False


class EdgeInfo(BaseModel):
    source: str
    target: str
    label: str
    value: float
    status: str


class LimitInfo(BaseModel):
    current: float
    normal: float
    max_capacity: float
    unit: str
    status: str


class ScenarioExplanation(BaseModel):
    title: str
    what_was_tested: str
    verdict: str
    system_limits: Dict[str, LimitInfo]


class AnalysisResult(BaseModel):
    components: List[ComponentMetrics]
    edges: List[EdgeInfo]
    summary: Dict[str, float | str]
    recommendations: List[str]
    config_info: Dict[str, float | int | str]
    scenario_explanation: ScenarioExplanation | None = None
    normatives: List[NormativeEntry] | None = None

    class Config:
        # Allow extra fields (e.g. from locust result with normatives attached)
        extra = "ignore"


class LocustTestRequest(BaseModel):
    target_url: str
    endpoints: List[str]
    config: SystemConfig
    num_users: int = 10
    spawn_rate: float = 2
    duration_sec: int = 30
    method: str = "GET"
    normatives: Optional[List[NormativeEntry]] = None
