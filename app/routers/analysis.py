from fastapi import APIRouter
from fastapi.staticfiles import StaticFiles

from app.models import AnalysisRequest
from app.analyzer import analyze
from app.scenarios import SCENARIOS

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/scenarios")
def get_scenarios():
    return {
        "scenarios": {
            k: {
                "name": v["name"],
                "description": v["description"],
                "params": v["params"],
            }
            for k, v in SCENARIOS.items()
        }
    }


@router.post("/analyze")
def run_analysis(req: AnalysisRequest):
    result = analyze(req.config, req.scenario)
    if req.normatives:
        result.normatives = req.normatives
        # Add SLO-based recommendations
        for comp in result.components:
            for n in req.normatives:
                if n.app_name.lower().replace("-","").replace("_","") == comp.label.lower().replace(" ","").replace("-","").replace("_",""):
                    if n.latency_slo_ms and comp.latency_ms > n.latency_slo_ms:
                        result.recommendations.append(
                            f"⚠ {n.app_name}: latency {comp.latency_ms:.0f}ms > SLO {n.latency_slo_ms}ms"
                        )
                    if n.error_slo_pct and comp.error_rate > n.error_slo_pct:
                        result.recommendations.append(
                            f"⚠ {n.app_name}: error rate {comp.error_rate:.1f}% > SLO {n.error_slo_pct:.0f}%"
                        )
    return result
