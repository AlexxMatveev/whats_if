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
    return analyze(req.config, req.scenario)
