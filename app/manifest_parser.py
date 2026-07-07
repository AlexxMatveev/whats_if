"""Parse Kubernetes YAML manifests and extract configuration + SLOs."""

from typing import List, Dict, Optional
import yaml


class ManifestApp:
    def __init__(self):
        self.name: str = ""
        self.replicas: int = 1
        self.cpu_request: str = ""
        self.cpu_limit: str = ""
        self.mem_request: str = ""
        self.mem_limit: str = ""
        self.hpa_cpu_target: Optional[int] = None
        self.service_ports: List[int] = []
        self.ingress_paths: List[str] = []


class ManifestResult:
    def __init__(self):
        self.apps: List[ManifestApp] = []
        self.ingress_hosts: List[str] = []


def _parse_cpu(val: str) -> float:
    """Convert K8s CPU string to cores (e.g. '500m' -> 0.5, '2' -> 2.0)."""
    if not val:
        return 0
    val = str(val)
    if val.endswith("m"):
        return float(val[:-1]) / 1000
    try:
        return float(val)
    except ValueError:
        return 0


def _parse_mem(val: str) -> float:
    """Convert K8s memory string to MiB (e.g. '512Mi' -> 512, '1Gi' -> 1024)."""
    if not val:
        return 0
    val = str(val)
    if val.endswith("Ki"):
        return float(val[:-2]) / 1024
    if val.endswith("Mi"):
        return float(val[:-2])
    if val.endswith("Gi"):
        return float(val[:-2]) * 1024
    try:
        return float(val)
    except ValueError:
        return 0


def _get_container_resources(container: dict) -> tuple:
    req = container.get("resources", {}).get("requests", {})
    lim = container.get("resources", {}).get("limits", {})
    return (
        str(req.get("cpu", "")),
        str(lim.get("cpu", "")),
        str(req.get("memory", "")),
        str(lim.get("memory", "")),
    )


def parse_manifests(yaml_texts: List[str]) -> ManifestResult:
    result = ManifestResult()
    app_map: Dict[str, ManifestApp] = {}

    for text in yaml_texts:
        docs = yaml.safe_load_all(text)
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            kind = doc.get("kind", "")
            meta = doc.get("metadata", {})
            name = meta.get("name", "")
            if not name:
                continue

            if kind == "Deployment":
                app = app_map.get(name)
                if not app:
                    app = ManifestApp()
                    app.name = name
                    app_map[name] = app

                spec = doc.get("spec", {})
                app.replicas = spec.get("replicas", 1)

                tmpl = spec.get("template", {})
                pod_spec = tmpl.get("spec", {})
                containers = pod_spec.get("containers", [])
                for c in containers:
                    cups_req, cups_lim, mem_req, mem_lim = _get_container_resources(c)
                    if cups_req:
                        app.cpu_request = cups_req
                    if cups_lim:
                        app.cpu_limit = cups_lim
                    if mem_req:
                        app.mem_request = mem_req
                    if mem_lim:
                        app.mem_limit = mem_lim

            elif kind == "HorizontalPodAutoscaler":
                # Could match by scaleTargetRef.name
                scale_target = doc.get("spec", {}).get("scaleTargetRef", {})
                target_name = scale_target.get("name", name)
                app = app_map.get(target_name)
                if not app:
                    app = ManifestApp()
                    app.name = target_name
                    app_map[target_name] = app

                metrics_list = doc.get("spec", {}).get("metrics", [])
                for m in metrics_list:
                    if m.get("type") == "Resource":
                        res = m.get("resource", {})
                        if res.get("name") == "cpu":
                            target = res.get("target", {})
                            if target.get("type") == "Utilization":
                                app.hpa_cpu_target = target.get("averageUtilization")

            elif kind == "Service":
                app = app_map.get(name)
                if not app:
                    app = ManifestApp()
                    app.name = name
                    app_map[name] = app
                spec = doc.get("spec", {})
                ports = spec.get("ports", [])
                for p in ports:
                    port = p.get("port", 0)
                    if port:
                        app.service_ports.append(port)

            elif kind == "Ingress":
                spec = doc.get("spec", {})
                rules = spec.get("rules", [])
                for rule in rules:
                    host = rule.get("host", "")
                    if host and host not in result.ingress_hosts:
                        result.ingress_hosts.append(host)
                    http = rule.get("http", {})
                    paths = http.get("paths", [])
                    for p in paths:
                        path = p.get("path", "")
                        if path:
                            # Try to associate with a backend service
                            backend = p.get("backend", {})
                            service_name = backend.get("service", {}).get("name", "")
                            if service_name:
                                svc_app = app_map.get(service_name)
                                if svc_app and path not in svc_app.ingress_paths:
                                    svc_app.ingress_paths.append(path)

    # Convert app_map to list, sort by name
    result.apps = sorted(app_map.values(), key=lambda a: a.name)

    # Auto-detect service ports from app names if not set
    for app in result.apps:
        if not app.service_ports:
            app.service_ports = [80]

    return result


def manifest_to_normatives(result: ManifestResult) -> List[dict]:
    """Convert parsed manifests to a SLO/normatives list for testing."""
    normatives = []
    for app in result.apps:
        entry = {
            "app_name": app.name,
            "replicas": app.replicas,
            "cpu_cores": _parse_cpu(app.cpu_limit) or _parse_cpu(app.cpu_request) or 1.0,
            "memory_mib": _parse_mem(app.mem_limit) or _parse_mem(app.mem_request) or 512,
            "hpa_cpu_pct": app.hpa_cpu_target,
        }
        # Estimate RPS capacity based on CPU cores (rough heuristic: 100 RPS per core)
        cpu_cores = entry["cpu_cores"]
        entry["estimated_rps_capacity"] = max(10, int(cpu_cores * 200))
        # SLO: latency target
        entry["latency_slo_ms"] = 200
        # SLO: error rate target
        entry["error_slo_pct"] = 1

        normatives.append(entry)

    return normatives
