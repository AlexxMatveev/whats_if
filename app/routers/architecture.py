"""Router for architecture (product view) from BI_3049.drawio."""

import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional, Any

from app.drawio_parser import parse_drawio, ArchNode, ArchEdge
from app.models import SystemConfig, Scenario, AnalysisResult
from app.analyzer import analyze

router = APIRouter(prefix="/api/architecture", tags=["architecture"])

DRAWIO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "BI_3049.drawio")


class ArchComponentOut(BaseModel):
    id: str
    name: str
    type: str
    description: str
    children: List[str] = []
    fill: str = ""
    shape: str = ""


class ArchEdgeOut(BaseModel):
    source: str
    target: str
    description: str = ""
    technology: str = ""
    dataflow: str = ""


class ArchViewData(BaseModel):
    components: List[ArchComponentOut]
    edges: List[ArchEdgeOut]


class ArchAnalyzeRequest(BaseModel):
    scenario: str = "baseline"
    params: Dict[str, float | int | str] = {}
    component_id: str = ""


class ArchAnalyzeResponse(BaseModel):
    analysis: AnalysisResult
    node_statuses: Dict[str, str]  # arch component id → status


def _resolve_port(port_id: str, nodes: List[ArchNode]) -> Optional[str]:
    for n in nodes:
        if n.id == port_id:
            return port_id
    parts = port_id.split(".")
    for i in range(len(parts) - 1, 0, -1):
        candidate = ".".join(parts[:i])
        for n in nodes:
            if n.id == candidate:
                return candidate
    return None


def _load_arch_data():
    if not os.path.exists(DRAWIO_PATH):
        raise HTTPException(status_code=404, detail="BI_3049.drawio not found")
    return parse_drawio(DRAWIO_PATH)


def _build_resolved_view(data):
    nodes: List[ArchNode] = data["nodes"]
    edges: List[ArchEdge] = data["edges"]
    node_by_id = {n.id: n for n in nodes}
    parent_children: Dict[str, List[str]] = {}
    for n in nodes:
        if n.parent_id:
            parent_children.setdefault(n.parent_id, []).append(n.id)

    resolved_edges = []
    for e in edges:
        src = e.source if e.source in node_by_id else _resolve_port(e.source, nodes)
        tgt = e.target if e.target in node_by_id else _resolve_port(e.target, nodes)
        if src and tgt and src in node_by_id and tgt in node_by_id and src != tgt:
            resolved_edges.append(ArchEdgeOut(
                source=src, target=tgt, description=e.description,
                technology=e.technology, dataflow=e.dataflow,
            ))

    seen = set()
    unique_edges = []
    for e in resolved_edges:
        key = (e.source, e.target)
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    comps_out = []
    for n in nodes:
        comps_out.append(ArchComponentOut(
            id=n.id, name=n.name, type=n.type, description=n.description,
            children=parent_children.get(n.id, []), fill=n.fill, shape=n.shape,
        ))

    return ArchViewData(components=comps_out, edges=unique_edges)


@router.get("/view", response_model=ArchViewData)
async def get_architecture_view():
    data = _load_arch_data()
    return _build_resolved_view(data)


@router.post("/analyze", response_model=ArchAnalyzeResponse)
async def analyze_architecture(req: ArchAnalyzeRequest):
    data = _load_arch_data()
    nodes: List[ArchNode] = data["nodes"]

    # Count topology elements
    containers = [n for n in nodes if n.type == "container"]
    databases = [n for n in nodes if n.type == "container" and n.shape == "cylinder3"]
    externals = [n for n in nodes if n.type == "external"]

    num_containers = len(containers)
    num_dbs = len(databases) if databases else 1
    num_externals = len(externals)

    # Find the selected component
    selected = None
    for n in nodes:
        if n.id == req.component_id:
            selected = n
            break

    # Build config from architecture topology
    config = SystemConfig(
        num_apps=num_containers,
        containers_per_app=1,
        num_clients=10000 * max(1, num_externals),
        rps=100 * max(1, num_containers),
        db_latency_ms=5,
    )

    # Adjust config based on selected component type
    if selected:
        if selected.type == "container":
            if selected.shape == "cylinder3":
                config.db_latency_ms = 20
            else:
                config.rps = 100 * max(1, num_containers)
        elif selected.type == "external":
            config.num_clients = 50000 * max(1, num_externals)

    # Build scenario
    scenario = Scenario(name=req.scenario, params=req.params or {})

    # Run analysis
    result = analyze(config, scenario)

    # Build node status mapping — map analysis result component types to arch nodes
    node_statuses: Dict[str, str] = {}
    for comp in result.components:
        # Map analysis component types to architecture nodes by name similarity
        if comp.type == "app":
            # Assign to container nodes round-robin
            for i, n in enumerate(containers):
                if comp.id == f"app_{i % num_containers}":
                    node_statuses[n.id] = comp.status
        elif comp.type == "container":
            for i, n in enumerate(containers):
                if n.shape != "cylinder3" and comp.id == f"container_{i % num_containers}_0":
                    node_statuses[n.id] = comp.status
        elif comp.type == "database":
            for i, n in enumerate(databases):
                if comp.id == f"db_{i % num_dbs}":
                    node_statuses[n.id] = comp.status
        elif comp.type == "gateway":
            pass  # No direct mapping in architecture
        elif comp.type == "lb":
            pass
        elif comp.type == "clients":
            for n in externals:
                node_statuses[n.id] = comp.status

    # Also assign status to unassigned container nodes
    default_status = "healthy"
    if result.summary["critical"] > 0:
        default_status = "warning"
    for n in nodes:
        nid = n.id
        if nid not in node_statuses:
            if n.type == "systemBoundary":
                # Check if any child is critical
                children_statuses = [
                    node_statuses.get(cid, default_status)
                    for cid in n.id
                ]
                if any(s == "critical" for s in children_statuses):
                    node_statuses[nid] = "critical"
                elif any(s == "warning" for s in children_statuses):
                    node_statuses[nid] = "warning"
                else:
                    node_statuses[nid] = "healthy"
            elif n.type == "external":
                node_statuses[nid] = default_status
            elif n.type == "role":
                node_statuses[nid] = "healthy"
            elif n.type == "container":
                node_statuses[nid] = default_status

    return ArchAnalyzeResponse(analysis=result, node_statuses=node_statuses)
