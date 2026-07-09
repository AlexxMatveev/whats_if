"""Router for architecture — supports drawio upload, YAML (ARCHOPS) upload,
topology-aware analysis using actual dependency edges from the diagram."""

import os
import tempfile
import shutil
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Dict, List, Optional, Any

from app.drawio_parser import parse_drawio, ArchNode, ArchEdge
from app.diagram_generator import build_model, System, Container
from app.models import SystemConfig, Scenario, AnalysisResult, ComponentMetrics, EdgeInfo, ComponentCapacities
from app.analyzer import analyze
from app.locust_runner import run_locust_test

router = APIRouter(prefix="/api/architecture", tags=["architecture"])

DRAWIO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "BI_3049.drawio")

_uploaded_data: Optional[Dict[str, Any]] = None
_uploaded_name: Optional[str] = None


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


class ArchPerContainerCapacity(BaseModel):
    rps_per_container_max: Optional[int] = None
    rps_per_container_normal: Optional[int] = None
    container_cpu_normal: Optional[float] = None


class ArchAnalyzeTopologyRequest(BaseModel):
    scenario: str = "baseline"
    params: Dict[str, float | int | str] = {}
    per_container_capacities: Dict[str, ArchPerContainerCapacity] = {}


class ArchAnalyzeResponse(BaseModel):
    analysis: AnalysisResult
    node_statuses: Dict[str, str]


class ArchComponentDetail(BaseModel):
    id: str
    name: str
    type: str
    shape: str
    description: str
    parent_name: str = ""
    capacity: ArchPerContainerCapacity = ArchPerContainerCapacity()


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
    if _uploaded_data is not None:
        return _uploaded_data
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


def _archops_to_archdata(systems: Dict[str, System], standalone: List[Container]) -> Dict[str, Any]:
    """Convert ARCHOPS model (from build_model) to the nodes/edges dict format."""
    nodes: List[ArchNode] = []
    edges: List[ArchEdge] = []
    edge_id_counter = 0

    for s in systems.values():
        sys_id = s.id
        nodes.append(ArchNode(
            id=sys_id, name=s.name, type="systemBoundary",
            description=s.desc, fill="none", shape="",
        ))
        for c in s.containers:
            kind = c.kind or "service"
            shape_map = {"db": "cylinder3", "ui": "mxgraph.c4.webBrowserContainer2"}
            shape = shape_map.get(kind, "")
            nodes.append(ArchNode(
                id=c.id, name=c.name, type="container",
                description=c.desc or f"[{kind}] {c.name}",
                parent_id=sys_id, fill="#23A2D9", shape=shape,
            ))
            for dep in c.dependencies:
                edge_id_counter += 1
                source = c.id
                target = dep.interfaceId or dep.id
                edges.append(ArchEdge(
                    id=f"edge_{edge_id_counter}",
                    source=source, target=target,
                    description=dep.desc, technology=dep.tech, dataflow=dep.dataflow,
                ))

    for c in standalone:
        kind = c.kind or "service"
        shape_map = {"db": "cylinder3", "ui": "mxgraph.c4.webBrowserContainer2"}
        shape = shape_map.get(kind, "")
        nodes.append(ArchNode(
            id=c.id, name=c.name, type="container",
            description=c.desc or f"[{kind}] {c.name}",
            parent_id="", fill="#23A2D9", shape=shape,
        ))
        for dep in c.dependencies:
            edge_id_counter += 1
            source = c.id
            target = dep.interfaceId or dep.id
            edges.append(ArchEdge(
                id=f"edge_{edge_id_counter}",
                source=source, target=target,
                description=dep.desc, technology=dep.tech, dataflow=dep.dataflow,
            ))

    return {"nodes": nodes, "edges": edges}


def _analyze_topology(
    nodes: List[ArchNode],
    arch_edges: List[ArchEdge],
    scenario: Scenario,
    per_container_capacities: Dict[str, ArchPerContainerCapacity] = None,
) -> Dict[str, str]:
    """Run analysis using the architecture's actual component graph.
    Returns {component_id: status} mapping."""
    per_container_capacities = per_container_capacities or {}

    containers = [n for n in nodes if n.type == "container"]
    databases = [n for n in nodes if n.type == "container" and n.shape == "cylinder3"]
    externals = [n for n in nodes if n.type == "external"]
    non_db_containers = [n for n in containers if n.shape != "cylinder3"]

    if not containers:
        return {}

    num_apps = len(non_db_containers) or 1
    num_dbs = len(databases) or 1
    num_externals = len(externals) or 1

    sp = scenario.params
    rps_mult = float(sp.get("rps_multiplier", 1))
    client_mult = float(sp.get("client_multiplier", 1))
    fail_count = int(sp.get("fail_count", 0))
    db_lat_mult = float(sp.get("db_latency_multiplier", 1))

    base_rps = 100 * num_apps
    base_clients = 10000 * num_externals
    base_db_latency = 5

    effective_rps = base_rps * rps_mult
    effective_clients = base_clients * client_mult
    effective_db_latency = base_db_latency * db_lat_mult

    # Build id -> node lookup
    node_by_id = {n.id: n for n in nodes}

    # Build edge-based dependency graph (forward/backward)
    arch_edge_pairs = []
    for e in arch_edges:
        src = e.source if e.source in node_by_id else _resolve_port(e.source, nodes)
        tgt = e.target if e.target in node_by_id else _resolve_port(e.target, nodes)
        if src and tgt and src in node_by_id and tgt in node_by_id and src != tgt:
            arch_edge_pairs.append((src, tgt))

    # Compute per-component metrics
    comp_metrics: Dict[str, ComponentMetrics] = {}

    # Clients
    clients_load = min(100, effective_clients / max(1, 500_000) * 100)
    comp_metrics["__clients__"] = ComponentMetrics(
        id="__clients__", label=f"Clients ({effective_clients:,.0f})", type="clients",
        cpu_percent=0, memory_percent=0, latency_ms=0, rps=0, error_rate=0,
        status="critical" if clients_load >= 80 else "warning" if clients_load >= 50 else "healthy",
        load_percent=round(clients_load, 1),
    )

    # Containers (services + databases)
    for i, n in enumerate(containers):
        cid = n.id
        caps = per_container_capacities.get(cid, ArchPerContainerCapacity())
        cont_max_rps = caps.rps_per_container_max or 80
        cont_norm_rps = caps.rps_per_container_normal or 25
        cpu_base = caps.container_cpu_normal or 25

        is_db = n.shape == "cylinder3"
        rps_share = effective_rps / max(1, len(containers))
        db_lat = effective_db_latency if is_db else max(1, effective_db_latency * 0.3)

        load_pct = min(100, rps_share / max(1, cont_max_rps) * 100)
        cpu_pct = min(100, (rps_share / max(1, cont_norm_rps)) * cpu_base)
        mem_pct = min(100, cpu_pct * 0.8)
        latency = db_lat * (1 + load_pct / 100)
        err_rate = max(0.1, load_pct * 0.05)

        status = "critical" if load_pct >= 80 else "warning" if load_pct >= 50 else "healthy"

        comp_metrics[cid] = ComponentMetrics(
            id=cid, label=f"{n.name}\n{rps_share:,.0f} RPS",
            type="database" if is_db else "container",
            cpu_percent=round(cpu_pct, 1),
            memory_percent=round(mem_pct, 1),
            latency_ms=round(latency, 1),
            rps=round(rps_share, 1),
            error_rate=round(err_rate, 1),
            status=status,
            load_percent=round(load_pct, 1),
        )

    # External systems
    for n in externals:
        comp_metrics[n.id] = ComponentMetrics(
            id=n.id, label=n.name, type="external",
            cpu_percent=0, memory_percent=0, latency_ms=0, rps=0, error_rate=0,
            status="healthy", load_percent=0,
        )

    # Apply container failure scenario
    for n in non_db_containers[:fail_count]:
        if n.id in comp_metrics:
            comp_metrics[n.id].status = "critical"
            comp_metrics[n.id].load_percent = 100

    # Build edge list for propagation
    prop_edges = []
    for src, tgt in arch_edge_pairs:
        if src in comp_metrics and tgt in comp_metrics:
            prop_edges.append(EdgeInfo(
                source=src, target=tgt,
                label="", value=1, status="healthy",
            ))

    # Propagate along actual dependency edges (BFS)
    fwd: Dict[str, List[str]] = {}
    bwd: Dict[str, List[str]] = {}
    for src, tgt in arch_edge_pairs:
        fwd.setdefault(src, []).append(tgt)
        bwd.setdefault(tgt, []).append(src)
    for cid in comp_metrics:
        fwd.setdefault(cid, [])
        bwd.setdefault(cid, [])

    # Backward: predecessors of critical get warning/critical
    crit_ids = [cid for cid, cm in comp_metrics.items() if cm.status == "critical"]
    warn_ids = [cid for cid, cm in comp_metrics.items() if cm.status == "warning"]

    for nid in crit_ids:
        for nb in bwd.get(nid, []):
            if nb in comp_metrics and comp_metrics[nb].status == "healthy":
                comp_metrics[nb].status = "critical"
                comp_metrics[nb].propagated = True
    for nid in warn_ids:
        for nb in bwd.get(nid, []):
            if nb in comp_metrics and comp_metrics[nb].status == "healthy":
                comp_metrics[nb].status = "warning"
                comp_metrics[nb].propagated = True

    # Forward: degraded components propagate warning downstream
    degraded = [cid for cid, cm in comp_metrics.items() if cm.status in ("critical", "warning")]
    visited = set(degraded)
    queue = list(degraded)
    while queue:
        cid = queue.pop(0)
        for nb in fwd.get(cid, []):
            if nb in comp_metrics and comp_metrics[nb].status == "healthy":
                comp_metrics[nb].status = "warning"
                comp_metrics[nb].propagated = True
            if nb not in visited:
                visited.add(nb)
                queue.append(nb)

    # Update edge statuses
    for e in prop_edges:
        if e.source in comp_metrics:
            e.status = comp_metrics[e.source].status

    # Build summary
    statuses = [cm.status for cm in comp_metrics.values()]
    healthy_count = statuses.count("healthy")
    warning_count = statuses.count("warning")
    critical_count = statuses.count("critical")

    all_latencies = [cm.latency_ms for cm in comp_metrics.values() if cm.latency_ms > 0]
    avg_latency = round(sum(all_latencies) / max(1, len(all_latencies)), 1) if all_latencies else 0
    max_cpu = max((cm.cpu_percent for cm in comp_metrics.values()), default=0)
    total_rps = sum(cm.rps for cm in comp_metrics.values())

    summary: Dict[str, float | str] = {
        "healthy": float(healthy_count),
        "warning": float(warning_count),
        "critical": float(critical_count),
        "avg_latency_ms": avg_latency,
        "max_cpu_percent": round(max_cpu, 1),
        "total_rps": round(total_rps, 1),
        "avg_error_rate": round(
            sum(cm.error_rate for cm in comp_metrics.values()) / max(1, len(comp_metrics)), 2
        ),
        "total_components": float(len(comp_metrics)),
        "description": f"Топология: {len(containers)} контейнеров, "
                       f"{len(databases)} БД, {len(externals)} внешних. "
                       f"Статус: {healthy_count}/{warning_count}/{critical_count}",
    }

    # Build node_statuses
    parent_children: Dict[str, List[str]] = {}
    for n in nodes:
        if n.parent_id:
            parent_children.setdefault(n.parent_id, []).append(n.id)

    node_statuses = {}
    for n in nodes:
        if n.id in comp_metrics:
            node_statuses[n.id] = comp_metrics[n.id].status
        elif n.type == "systemBoundary":
            child_statuses = [
                comp_metrics.get(cid, ComponentMetrics(id="", label="", type="", cpu_percent=0, memory_percent=0, latency_ms=0, rps=0, error_rate=0, status="healthy", load_percent=0)).status
                for cid in parent_children.get(n.id, [])
            ]
            if any(s == "critical" for s in child_statuses):
                node_statuses[n.id] = "critical"
            elif any(s == "warning" for s in child_statuses):
                node_statuses[n.id] = "warning"
            else:
                node_statuses[n.id] = "healthy"

    return node_statuses


class ArchUploadResponse(BaseModel):
    success: bool
    name: str
    components: int
    edges: int
    view: ArchViewData


@router.post("/upload", response_model=ArchUploadResponse)
async def upload_architecture(file: UploadFile = File(...)):
    global _uploaded_data, _uploaded_name
    content = await file.read()
    name = file.filename or "unknown"

    if name.endswith(".drawio"):
        with tempfile.NamedTemporaryFile(suffix=".drawio", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            data = parse_drawio(tmp_path)
        finally:
            os.unlink(tmp_path)

    elif name.endswith((".yaml", ".yml")):
        tmpdir = tempfile.mkdtemp()
        try:
            filepath = os.path.join(tmpdir, name)
            with open(filepath, "wb") as f:
                f.write(content)
            systems, standalone, _, _ = build_model(tmpdir)
            data = _archops_to_archdata(systems, standalone)
        finally:
            shutil.rmtree(tmpdir)

    else:
        raise HTTPException(status_code=400, detail="Only .drawio, .yaml, .yml files are supported")

    _uploaded_data = data
    _uploaded_name = name

    view = _build_resolved_view(data)
    return ArchUploadResponse(
        success=True, name=name,
        components=len(view.components), edges=len(view.edges),
        view=view,
    )


@router.post("/reset")
async def reset_architecture():
    global _uploaded_data, _uploaded_name
    _uploaded_data = None
    _uploaded_name = None
    return {"success": True, "name": "BI_3049.drawio"}


@router.get("/view", response_model=ArchViewData)
async def get_architecture_view():
    data = _load_arch_data()
    return _build_resolved_view(data)


@router.post("/analyze", response_model=ArchAnalyzeResponse)
async def analyze_architecture(req: ArchAnalyzeRequest):
    """Legacy analyze — uses the old component-count mapping without topology."""
    data = _load_arch_data()
    nodes: List[ArchNode] = data["nodes"]

    containers = [n for n in nodes if n.type == "container"]
    databases = [n for n in nodes if n.type == "container" and n.shape == "cylinder3"]
    externals = [n for n in nodes if n.type == "external"]

    num_containers = len(containers)
    num_dbs = len(databases) if databases else 1
    num_externals = len(externals)

    selected = None
    for n in nodes:
        if n.id == req.component_id:
            selected = n
            break

    config = SystemConfig(
        num_apps=num_containers,
        containers_per_app=1,
        num_clients=10000 * max(1, num_externals),
        rps=100 * max(1, num_containers),
        db_latency_ms=5,
    )

    if selected:
        if selected.type == "container":
            if selected.shape == "cylinder3":
                config.db_latency_ms = 20
            else:
                config.rps = 100 * max(1, num_containers)
        elif selected.type == "external":
            config.num_clients = 50000 * max(1, num_externals)

    scenario = Scenario(name=req.scenario, params=req.params or {})

    # Build a custom edge list from the architecture diagram
    arch_edges: List[ArchEdge] = data["edges"]
    node_by_id = {n.id: n for n in nodes}
    custom_edges: List[EdgeInfo] = []
    container_list = [n for n in nodes if n.type == "container"]
    container_ids = {n.id for n in container_list}

    # Add the standard entry edges (clients -> first containers)
    for i, n in enumerate(container_list):
        if n.shape != "cylinder3":
            custom_edges.append(EdgeInfo(
                source="__clients__", target=n.id,
                label="traffic", value=config.rps / max(1, len(container_list)),
                status="healthy",
            ))

    # Add architecture diagram edges
    for e in arch_edges:
        src = e.source if e.source in node_by_id else _resolve_port(e.source, nodes)
        tgt = e.target if e.target in node_by_id else _resolve_port(e.target, nodes)
        if src and tgt and src in node_by_id and tgt in node_by_id and src != tgt:
            # Only include edges between containers/externals (skip boundaries/roles)
            if src in container_ids or src in {n.id for n in externals}:
                custom_edges.append(EdgeInfo(
                    source=src, target=tgt,
                    label=e.description or e.technology or "",
                    value=1.0, status="healthy",
                ))

    result = analyze(config, scenario)

    # Mark architecture-derived edges on the result
    result.edges = custom_edges

    node_statuses: Dict[str, str] = {}
    # Map analysis components to arch nodes
    for comp in result.components:
        if comp.type == "app":
            for i, n in enumerate(container_list):
                if n.shape != "cylinder3" and comp.id == f"app_{i % max(1, len([c for c in container_list if c.shape != 'cylinder3']))}":
                    node_statuses[n.id] = comp.status
        elif comp.type == "container":
            for i, n in enumerate(container_list):
                if n.shape != "cylinder3" and comp.id == f"container_{i % max(1, len([c for c in container_list if c.shape != 'cylinder3']))}_0":
                    node_statuses[n.id] = comp.status
        elif comp.type == "database":
            for i, n in enumerate(databases):
                if comp.id == f"db_{i % max(1, num_dbs)}":
                    node_statuses[n.id] = comp.status
        elif comp.type == "clients":
            for n in externals:
                node_statuses[n.id] = comp.status

    default_status = "healthy"
    if result.summary["critical"] > 0:
        default_status = "warning"
    for n in nodes:
        nid = n.id
        if nid not in node_statuses:
            if n.type == "systemBoundary":
                children_statuses = [
                    node_statuses.get(cid, default_status)
                    for cid in (node_by_id[n.id].children if n.id in node_by_id else [])
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


@router.post("/analyze-topology", response_model=ArchAnalyzeResponse)
async def analyze_architecture_topology(req: ArchAnalyzeTopologyRequest):
    """Topology-aware analysis using the actual dependency edges from the diagram.
    Each container is mapped to its own analysis component; propagation follows arch edges."""
    data = _load_arch_data()
    nodes: List[ArchNode] = data["nodes"]
    arch_edges: List[ArchEdge] = data["edges"]

    scenario = Scenario(name=req.scenario, params=req.params or {})
    node_statuses = _analyze_topology(nodes, arch_edges, scenario, req.per_container_capacities)

    containers = [n for n in nodes if n.type == "container"]
    databases = [n for n in nodes if n.type == "container" and n.shape == "cylinder3"]
    externals = [n for n in nodes if n.type == "external"]

    num_containers = len(containers)
    num_dbs = len(databases) or 1
    num_externals = len(externals) or 1

    sp = req.params
    rps_mult = float(sp.get("rps_multiplier", 1))
    client_mult = float(sp.get("client_multiplier", 1))

    base_rps = 100 * max(1, num_containers)
    base_clients = 10000 * max(1, num_externals)

    effective_rps = base_rps * rps_mult
    effective_clients = base_clients * client_mult

    # Build a minimal AnalysisResult from the topology
    comp_list = []
    for n in nodes:
        if n.id in node_statuses:
            comp_list.append(node_statuses[n.id])
        else:
            comp_list.append("healthy")

    healthy_count = sum(1 for s in comp_list if s == "healthy")
    warning_count = sum(1 for s in comp_list if s == "warning")
    critical_count = sum(1 for s in comp_list if s == "critical")

    summary: Dict[str, float | str] = {
        "healthy": float(healthy_count),
        "warning": float(warning_count),
        "critical": float(critical_count),
        "avg_latency_ms": 0.0,
        "max_cpu_percent": 0.0,
        "total_rps": float(effective_rps),
        "avg_error_rate": 0.0,
        "total_components": float(len(node_statuses)),
        "description": f"Топологический анализ: {num_containers} контейнеров, "
                       f"{num_dbs} БД, {num_externals} внешних. "
                       f"Статус: {healthy_count}/{warning_count}/{critical_count}",
    }

    result = AnalysisResult(
        components=[],
        edges=[],
        summary=summary,
        recommendations=[],
        config_info={
            "num_apps": num_containers,
            "num_clients": effective_clients,
            "rps": effective_rps,
            "scenario": req.scenario,
            "architecture_containers": num_containers,
            "architecture_databases": num_dbs,
            "architecture_externals": num_externals,
        },
    )

    return ArchAnalyzeResponse(analysis=result, node_statuses=node_statuses)


@router.get("/component/{component_id}")
async def get_component_detail(component_id: str):
    """Get detailed info and editable parameters for a specific component."""
    data = _load_arch_data()
    nodes: List[ArchNode] = data["nodes"]
    node_by_id = {n.id: n for n in nodes}

    node = node_by_id.get(component_id)
    if not node:
        raise HTTPException(status_code=404, detail="Component not found")

    parent_name = ""
    if node.parent_id and node.parent_id in node_by_id:
        parent_name = node_by_id[node.parent_id].name

    return ArchComponentDetail(
        id=node.id, name=node.name, type=node.type,
        shape=node.shape, description=node.description,
        parent_name=parent_name,
    )


@router.get("/uploaded")
async def get_uploaded_info():
    return {"uploaded": _uploaded_data is not None, "name": _uploaded_name or "BI_3049.drawio"}


class ArchLocustRunRequest(BaseModel):
    target_url: str = "http://localhost:8000"
    num_users: int = 10
    spawn_rate: float = 2
    duration_sec: int = 30
    component_endpoints: Dict[str, str] = {}  # component_id → endpoint path


class ArchLocustRunResponse(BaseModel):
    success: bool
    component_results: Dict[str, dict]  # component_id → {avg_latency, error_rate, rps, status}
    node_statuses: Dict[str, str]


@router.post("/locust-run", response_model=ArchLocustRunResponse)
async def run_architecture_locust(req: ArchLocustRunRequest):
    """Run real load test (Locust) against architecture components by their URLs."""
    data = _load_arch_data()
    nodes: List[ArchNode] = data["nodes"]
    node_by_id = {n.id: n for n in nodes}

    if not req.component_endpoints:
        raise HTTPException(status_code=400, detail="No component endpoints provided")

    component_results: Dict[str, dict] = {}
    node_statuses: Dict[str, str] = {}

    target = req.target_url.rstrip("/")

    for cid, endpoint in req.component_endpoints.items():
        if not endpoint:
            continue
        ep_path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        full_url = f"{target}{ep_path}"

        raw = run_locust_test(
            target_url=full_url,
            endpoints=["/"],
            num_users=req.num_users,
            spawn_rate=req.spawn_rate,
            duration_sec=req.duration_sec,
            timeout_sec=req.duration_sec + 30,
        )

        if "error" in raw:
            component_results[cid] = {"error": raw["error"], "status": "critical"}
            node_statuses[cid] = "critical"
            continue

        entries = raw.get("entries", {})
        ep_data = next(iter(entries.values()), None)

        if not ep_data:
            component_results[cid] = {"error": "no data", "status": "warning"}
            node_statuses[cid] = "warning"
            continue

        avg_lat = ep_data.get("avg_response_time", 0)
        fail_ratio = ep_data.get("fail_ratio", 0)
        rps_val = ep_data.get("rps", 0)
        error_rate = fail_ratio * 100

        if fail_ratio > 0.1:
            status = "critical"
        elif fail_ratio > 0.02 or avg_lat > 500:
            status = "warning"
        else:
            status = "healthy"

        component_results[cid] = {
            "avg_latency_ms": round(avg_lat, 1),
            "error_rate": round(error_rate, 2),
            "rps": round(rps_val, 1),
            "status": status,
        }
        node_statuses[cid] = status

    # Assign statuses to parent boundaries
    parent_children: Dict[str, List[str]] = {}
    for n in nodes:
        if n.parent_id:
            parent_children.setdefault(n.parent_id, []).append(n.id)
    for n in nodes:
        if n.id not in node_statuses and n.type == "systemBoundary":
            child_statuses = [node_statuses.get(cid, "healthy") for cid in parent_children.get(n.id, [])]
            if any(s == "critical" for s in child_statuses):
                node_statuses[n.id] = "critical"
            elif any(s == "warning" for s in child_statuses):
                node_statuses[n.id] = "warning"
            else:
                node_statuses[n.id] = "healthy"

    return ArchLocustRunResponse(
        success=True,
        component_results=component_results,
        node_statuses=node_statuses,
    )


_arch_urls: Dict[str, str] = {}  # component_id → URL


class ArchUrlSaveRequest(BaseModel):
    component_urls: Dict[str, str]


@router.post("/save-urls")
async def save_component_urls(req: ArchUrlSaveRequest):
    global _arch_urls
    _arch_urls.update(req.component_urls)
    return {"success": True, "saved": len(req.component_urls)}


@router.get("/urls")
async def get_component_urls():
    return {"urls": _arch_urls}
