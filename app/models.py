from typing import Dict, List
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


class AnalysisRequest(BaseModel):
    config: SystemConfig
    scenario: Scenario


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
    scenario_explanation: ScenarioExplanation
