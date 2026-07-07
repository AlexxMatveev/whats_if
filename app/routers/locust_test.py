from fastapi import APIRouter, HTTPException

from app.models import LocustTestRequest, ComponentMetrics, EdgeInfo, AnalysisResult, LimitInfo, ScenarioExplanation
from app.locust_runner import run_locust_test

router = APIRouter(prefix="/api", tags=["locust"])

APP_NAMES = [
    "Auth API", "User API", "Order API", "Payment API",
    "Notification API", "Catalog API", "Cart API",
    "Search API", "Analytics API", "Admin API",
]
DB_NAMES = ["PostgreSQL (Main)", "Redis (Cache)", "MongoDB (Docs)"]
GATEWAY_NAME = "API Gateway"
LB_NAME = "Load Balancer"

MAX_CLIENTS = 500_000
LB_MAX_RPS = 5_000
GW_MAX_RPS = 3_000
RPS_PER_CONTAINER_NORMAL = 25
RPS_PER_CONTAINER_MAX = 80
CONTAINER_CPU_NORMAL = 25
DB_LATENCY_NORMAL = 5

WARN_PCT = 50
CRIT_PCT = 80


def _cap_load(load: float) -> float:
    return round(min(100, max(0, load)), 1)


def _status(load: float) -> str:
    if load >= CRIT_PCT:
        return "critical"
    if load >= WARN_PCT:
        return "warning"
    return "healthy"


def _severity_from_error(fail_ratio: float) -> str:
    if fail_ratio > 0.1:
        return "critical"
    if fail_ratio > 0.02:
        return "warning"
    return "healthy"


def _severity_from_latency(lat_ms: float) -> str:
    if lat_ms > 500:
        return "critical"
    if lat_ms > 200:
        return "warning"
    return "healthy"


@router.post("/locust/run")
def run_locust(req: LocustTestRequest):
    cfg = req.config

    raw = run_locust_test(
        target_url=req.target_url.rstrip("/"),
        endpoints=req.endpoints,
        num_users=req.num_users,
        spawn_rate=req.spawn_rate,
        duration_sec=req.duration_sec,
        method=req.method,
    )

    if "error" in raw:
        raise HTTPException(status_code=500, detail=raw["error"])

    entries = raw.get("entries", {})
    if not entries:
        raise HTTPException(status_code=500, detail="Locust returned no results")

    # Aggregate real metrics
    ep_list = list(entries.values())
    avg_lat = sum(e["avg_response_time"] for e in ep_list) / len(ep_list)
    max_lat = max(e["avg_response_time"] for e in ep_list)
    total_rps = sum(e["rps"] for e in ep_list)
    total_requests = sum(e["num_requests"] for e in ep_list)
    total_failures = sum(e["num_failures"] for e in ep_list)
    overall_fail_ratio = total_failures / max(1, total_requests)
    overall_fail_pct = overall_fail_ratio * 100

    # Expected load from config
    expected_rps = cfg.rps
    expected_clients = cfg.num_clients

    # Derived utilisation
    rps_ratio = total_rps / max(1, expected_rps)  # how much of expected load was achieved
    lb_load_pct = min(100, (total_rps / LB_MAX_RPS) * 100)
    gw_load_pct = min(100, (total_rps / GW_MAX_RPS) * 100)
    client_load_pct = min(100, (expected_clients / MAX_CLIENTS) * 100)

    active_apps = min(cfg.num_apps, len(APP_NAMES))
    active_dbs = min(3, max(1, cfg.num_apps // 2))
    conts_per_app = cfg.containers_per_app

    components = []
    edges = []

    def add_edge(src: str, tgt: str, label: str, value: float, status: str):
        edges.append(EdgeInfo(source=src, target=tgt, label=label, value=round(value, 1), status=status))

    # ── 1. Clients ──
    client_status = _status(client_load_pct)
    components.append(ComponentMetrics(
        id="clients", label=f"Клиенты\n{expected_clients:,}", type="clients",
        cpu_percent=0, memory_percent=0, latency_ms=0, rps=0, error_rate=0,
        status=client_status, load_percent=_cap_load(client_load_pct),
    ))
    add_edge("clients", "lb", f"{expected_clients:,}", expected_clients / 1000, client_status)

    # ── 2. Load Balancer ──
    lb_status = _status(lb_load_pct)
    components.append(ComponentMetrics(
        id="lb", label=LB_NAME, type="lb",
        cpu_percent=_cap_load(10 + lb_load_pct * 0.6),
        memory_percent=_cap_load(15 + lb_load_pct * 0.3),
        latency_ms=round(1 + (lb_load_pct / 100) * 3, 1),
        rps=round(total_rps, 1),
        error_rate=round((lb_load_pct / 100) * 4, 2),
        status=lb_status, load_percent=_cap_load(lb_load_pct),
    ))
    add_edge("lb", "gateway", f"{total_rps:.0f} / {expected_rps} RPS", total_rps, lb_status)

    # ── 3. Gateway ──
    gw_status = _status(gw_load_pct)
    components.append(ComponentMetrics(
        id="gateway", label=GATEWAY_NAME, type="gateway",
        cpu_percent=_cap_load(15 + gw_load_pct * 0.7),
        memory_percent=_cap_load(20 + gw_load_pct * 0.4),
        latency_ms=round(2 + (gw_load_pct / 100) * 5, 1),
        rps=round(total_rps, 1),
        error_rate=round(overall_fail_pct, 2),
        status=gw_status, load_percent=_cap_load(gw_load_pct),
    ))

    # ── 4. Apps ──
    rps_per_app = total_rps / max(1, active_apps)
    lat_per_app = avg_lat
    fail_pct_per_app = overall_fail_pct

    for i in range(active_apps):
        app_id = f"app_{i}"
        app_name = APP_NAMES[i]

        # App CPU from real RPS + errors
        cpu = _cap_load(CONTAINER_CPU_NORMAL + (rps_per_app / RPS_PER_CONTAINER_NORMAL) * 15 + fail_pct_per_app * 1.5 + (lat_per_app / 100) * 3)
        mem = _cap_load(30 + (rps_per_app / RPS_PER_CONTAINER_NORMAL) * 10 + fail_pct_per_app)
        load = _cap_load(cpu * 1.1)

        app_status = _severity_from_error(overall_fail_ratio)
        if app_status == "healthy":
            app_status = _severity_from_latency(lat_per_app)

        components.append(ComponentMetrics(
            id=app_id, label=app_name, type="app",
            cpu_percent=cpu, memory_percent=mem,
            latency_ms=round(lat_per_app, 1),
            rps=round(rps_per_app, 1),
            error_rate=round(fail_pct_per_app, 2),
            status=app_status, load_percent=load,
        ))
        add_edge("gateway", app_id, f"{rps_per_app:.0f} RPS", rps_per_app, app_status)

        # Containers per app
        rps_per_container = rps_per_app / max(1, conts_per_app)
        for c in range(conts_per_app):
            cid = f"container_{i}_{c}"
            cont_cpu = _cap_load(CONTAINER_CPU_NORMAL + (rps_per_container / RPS_PER_CONTAINER_NORMAL) * 20 + fail_pct_per_app)
            cont_mem = _cap_load(25 + (rps_per_container / 20) * 5)
            cont_lat = round(lat_per_app * (0.8 + c * 0.1), 1)
            cont_err = round(max(0.1, fail_pct_per_app * 0.6), 2)
            cont_status = app_status if app_status != "healthy" else (
                "warning" if cont_cpu > WARN_PCT else "healthy"
            )
            components.append(ComponentMetrics(
                id=cid, label=f"{app_name.split()[0]}-{c+1}", type="container",
                cpu_percent=cont_cpu, memory_percent=cont_mem,
                latency_ms=cont_lat, rps=round(rps_per_container, 1),
                error_rate=cont_err, status=cont_status,
                load_percent=_cap_load(cont_cpu * 1.2),
            ))
            add_edge(app_id, cid, f"{app_name.split()[0]}-{c+1}", 1, cont_status)

    # ── 5. Databases ──
    db_impact = avg_lat / 50
    db_cascade = 30 if db_impact > 5 else (15 if db_impact > 2 else 0)

    for i in range(active_dbs):
        db_id = f"db_{i}"
        db_name = DB_NAMES[i]
        db_weight = [1.0, 0.6, 0.7][i]
        db_lat = avg_lat * db_weight
        db_cpu_val = _cap_load(20 + db_lat * 0.3 + (total_rps / 500) * 3)
        db_mem = _cap_load(30 + db_lat * 0.4 + (total_rps / 300) * 2)
        db_err = round((db_lat / 200) * 5, 2)
        db_status = _severity_from_latency(db_lat)

        components.append(ComponentMetrics(
            id=db_id, label=db_name, type="database",
            cpu_percent=db_cpu_val, memory_percent=db_mem,
            latency_ms=round(db_lat, 1),
            rps=round(total_rps * (0.5 - i * 0.1), 1),
            error_rate=db_err, status=db_status,
            load_percent=_cap_load(db_cpu_val),
        ))
        for j in range(active_apps):
            add_edge(f"app_{j}", db_id, db_name[:6], db_lat, db_status)

    # ── 6. External CRM ──
    ext_status = "healthy"
    for c in components:
        if c.id == "container_0_0":
            ext_status = c.status
            break
    ext_lat = 20 + avg_lat * 0.6
    ext_err = round(overall_fail_ratio * 50 + (5 if ext_status == "critical" else 1 if ext_status == "warning" else 0.1), 2)
    components.append(ComponentMetrics(
        id="ext_crm", label="Внешний CRM\n(via Auth-1)", type="external",
        cpu_percent=0, memory_percent=0,
        latency_ms=round(min(500, ext_lat), 1),
        rps=round(total_rps * 0.3, 1),
        error_rate=ext_err, status=ext_status,
        load_percent=_cap_load(avg_lat * 0.5),
    ))
    add_edge("container_0_0", "ext_crm", "API call", total_rps * 0.3, ext_status)

    # ── Summary ──
    healthy_c = sum(1 for c in components if c.status == "healthy")
    warning_c = sum(1 for c in components if c.status == "warning")
    critical_c = sum(1 for c in components if c.status == "critical")
    total_c = len(components)
    non_clients = [c for c in components if c.type != "clients"]
    avg_lat_all = round(sum(c.latency_ms for c in non_clients) / max(1, len(non_clients)), 1)
    max_cpu_all = round(max(c.cpu_percent for c in components), 1)
    tot_rps_all = round(sum(c.rps for c in non_clients), 1)

    # ── Verdict & Commentary ──
    load_achieved_pct = (total_rps / max(1, expected_rps)) * 100
    lines = []
    lines.append(f"Цель: {expected_rps} RPS, Факт: {total_rps:.0f} RPS ({load_achieved_pct:.0f}% от цели)")

    if overall_fail_ratio > 0.1:
        lines.append(f"КРИТИЧЕСКИ — ошибок {overall_fail_pct:.1f}% (порог: 10%)")
    elif overall_fail_ratio > 0.02:
        lines.append(f"ПРЕДУПРЕЖДЕНИЕ — ошибок {overall_fail_pct:.1f}% (порог: 2%)")
    else:
        lines.append(f"Ошибки в норме: {overall_fail_pct:.1f}%")

    if avg_lat > 300:
        lines.append(f"Задержка высокая: {avg_lat:.0f}ms (порог: 300ms)")
    elif avg_lat > 100:
        lines.append(f"Задержка умеренная: {avg_lat:.0f}ms")
    else:
        lines.append(f"Задержка низкая: {avg_lat:.0f}ms")

    if total_failures > 0:
        lines.append(f"Отказов: {total_failures} из {total_requests} запросов")
    else:
        lines.append("Без отказов")

    healthy_str = f"healthy={healthy_c}" if healthy_c > 0 else ""
    warn_str = f" warning={warning_c}" if warning_c > 0 else ""
    crit_str = f" CRITICAL={critical_c}" if critical_c > 0 else ""
    lines.append(f"Компоненты:{healthy_str}{warn_str}{crit_str}")
    verdict = "\n".join(lines)

    # ── What was tested ──
    what_tested = (
        f"Реальный нагрузочный тест (Locust)\n"
        f"Целевой URL: {req.target_url}\n"
        f"Endpoint'ы: {', '.join(req.endpoints)}\n"
        f"Пользователей: {req.num_users}, Запуск: {req.spawn_rate}/s, Длит: {req.duration_sec}s\n"
        f"Конфигурация: {cfg.num_apps} приложений, {cfg.containers_per_app} контейнеров, {cfg.num_clients:,} клиентов, {cfg.rps} RPS целевых\n"
        f"Запросов: {total_requests}, Отказов: {total_failures} ({overall_fail_pct:.1f}%)\n"
        f"Ср. задержка: {avg_lat:.0f}ms, Макс: {max_lat:.0f}ms, RPS: {total_rps:.0f}"
    )

    # ── Recommendations ──
    recs = []
    if overall_fail_ratio > 0.05:
        recs.append(f"⚠️ Высокий уровень ошибок ({overall_fail_pct:.1f}%) — проверьте стабильность endpoint'ов")
    if avg_lat > 300:
        recs.append(f"⚠️ Высокая задержка ({avg_lat:.0f}ms) — требуется масштабирование или оптимизация")
    if max_lat > 1000:
        recs.append("⚠️ Некоторые ответы >1s — проверьте медленные endpoint'ы")
    if load_achieved_pct < 50:
        recs.append(f"ℹ️ Достигнуто только {load_achieved_pct:.0f}% от целевого RPS ({total_rps:.0f} из {expected_rps}) — возможно, target не выдерживает или users мало")
    if total_rps > LB_MAX_RPS * 0.7:
        recs.append("⚠️ Приближение к лимиту LB — рассмотрите масштабирование")
    if not recs:
        recs.append("✅ Система стабильна — все показатели в норме")

    system_limits = {
        "Avg Latency": LimitInfo(
            current=round(avg_lat, 1), normal=100, max_capacity=500,
            unit="ms", status=_severity_from_latency(avg_lat),
        ),
        "Error Rate": LimitInfo(
            current=round(overall_fail_pct, 2), normal=2, max_capacity=10,
            unit="%", status=_severity_from_error(overall_fail_ratio),
        ),
        "Target RPS": LimitInfo(
            current=round(total_rps, 1), normal=expected_rps, max_capacity=GW_MAX_RPS,
            unit="RPS", status=_status(100 - load_achieved_pct),
        ),
    }

    # ── Apply normatives if provided ──
    norms_used = []
    if req.normatives:
        norms_used = req.normatives
        for comp in components:
            for n in req.normatives:
                if n.app_name.lower().replace("-","").replace("_","") == comp.label.lower().replace(" ","").replace("-","").replace("_",""):
                    if n.latency_slo_ms and comp.latency_ms > n.latency_slo_ms:
                        recs.append(f"⚠ {n.app_name}: latency {comp.latency_ms:.0f}ms > SLO {n.latency_slo_ms}ms")
                    if n.error_slo_pct and comp.error_rate > n.error_slo_pct:
                        recs.append(f"⚠ {n.app_name}: error rate {comp.error_rate:.1f}% > SLO {n.error_slo_pct:.0f}%")

    return AnalysisResult(
        components=components,
        edges=edges,
        normatives=norms_used or None,
        summary={
            "healthy": healthy_c,
            "warning": warning_c,
            "critical": critical_c,
            "avg_latency_ms": avg_lat_all,
            "max_cpu_percent": max_cpu_all,
            "total_rps": tot_rps_all,
            "avg_error_rate": round(overall_fail_pct, 2),
            "total_components": total_c,
            "description": f"Locust: {req.num_users} юзеров, {req.duration_sec}с → {total_rps:.0f}/{expected_rps} RPS, ошибок {overall_fail_pct:.1f}%, latency {avg_lat:.0f}ms",
        },
        recommendations=recs,
        config_info={
            "mode": "locust",
            "target_url": req.target_url,
            "users": req.num_users,
            "duration": req.duration_sec,
            "expected_rps": expected_rps,
            "actual_rps": round(total_rps, 1),
            "total_requests": total_requests,
            "total_failures": total_failures,
        },
        scenario_explanation=ScenarioExplanation(
            title="⚡ Реальный тест (Locust)",
            what_was_tested=what_tested,
            verdict=verdict,
            system_limits=system_limits,
        ),
    )
