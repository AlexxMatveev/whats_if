from typing import Dict, List

from app.models import (
    ComponentMetrics, EdgeInfo, SystemConfig, Scenario,
    AnalysisResult, LimitInfo, ScenarioExplanation,
)

APP_NAMES = [
    "Auth API", "User API", "Order API", "Payment API",
    "Notification API", "Catalog API", "Cart API",
    "Search API", "Analytics API", "Admin API",
]
DB_NAMES = ["PostgreSQL (Main)", "Redis (Cache)", "MongoDB (Docs)"]
GATEWAY_NAME = "API Gateway"
LB_NAME = "Load Balancer"

# ── Capacity limits ──
MAX_CLIENTS = 500_000
LB_MAX_RPS = 5_000
GW_MAX_RPS = 3_000
RPS_PER_CONTAINER_MAX = 80
RPS_PER_CONTAINER_NORMAL = 25
DB_LATENCY_NORMAL = 5
DB_LATENCY_DANGER = 50
CONTAINER_CPU_NORMAL = 25

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


def _limit_status(current: float, normal: float, max_cap: float) -> str:
    if current > max_cap:
        return "critical"
    if current > normal:
        return "warning"
    return "healthy"


def analyze(config: SystemConfig, scenario: Scenario) -> AnalysisResult:
    sname = scenario.name
    sp = scenario.params

    rps_mult = float(sp.get("rps_multiplier", 1))
    client_mult = float(sp.get("client_multiplier", 1))
    fail_count = int(sp.get("fail_count", 0))
    containers_add = int(sp.get("containers_add", 0))
    db_lat_mult = float(sp.get("db_latency_multiplier", 1))

    base_rps = config.rps
    base_clients = config.num_clients
    base_db_latency = config.db_latency_ms

    effective_rps = base_rps * rps_mult
    effective_clients = base_clients * client_mult
    effective_db_latency = base_db_latency * db_lat_mult
    effective_conts = config.containers_per_app + containers_add

    active_apps = min(config.num_apps, len(APP_NAMES))
    active_dbs = min(3, len(DB_NAMES))

    components: List[ComponentMetrics] = []
    edges: List[EdgeInfo] = []
    recommendations: List[str] = []

    # ── helpers ──
    def add_edge(src: str, tgt: str, label: str, value: float, status: str):
        edges.append(EdgeInfo(source=src, target=tgt, label=label, value=round(value, 1), status=status))

    # ═══════════════════════════════════════════════════════════
    #  1. CLIENTS
    # ═══════════════════════════════════════════════════════════
    client_load_pct = effective_clients / MAX_CLIENTS * 100
    client_status = _status(client_load_pct)

    client_overage = max(1.0, effective_clients / MAX_CLIENTS)
    lb_conn_load = min(80, (effective_clients / 50_000) * 5)  # +5% per 50K clients

    components.append(ComponentMetrics(
        id="clients", label=f"Клиенты\n{effective_clients:,}", type="clients",
        cpu_percent=0, memory_percent=0, latency_ms=0, rps=0, error_rate=0,
        status=client_status,
        load_percent=_cap_load(client_load_pct),
    ))
    add_edge("clients", "lb", f"{effective_clients:,}", effective_clients / 1000, client_status)

    # ═══════════════════════════════════════════════════════════
    #  2. LOAD BALANCER
    # ═══════════════════════════════════════════════════════════
    lb_rps_load = (effective_rps / LB_MAX_RPS) * 100
    lb_load = lb_rps_load + lb_conn_load
    lb_status = _status(lb_load)
    lb_saturation = lb_load > 100
    if lb_saturation:
        lb_status = "critical"

    components.append(ComponentMetrics(
        id="lb", label=LB_NAME, type="lb",
        cpu_percent=_cap_load(10 + lb_load * 0.6),
        memory_percent=_cap_load(15 + lb_load * 0.3),
        latency_ms=round(1 + (lb_load / 100) * 3, 1),
        rps=effective_rps,
        error_rate=round(min(15, (lb_load / 100) * 4), 2),
        status=lb_status,
        load_percent=_cap_load(lb_load),
    ))

    # ── Cascade: if LB is saturated, Gateway takes extra ──
    lb_cascade = 0
    if lb_status == "critical":
        lb_cascade = 15  # extra % load on Gateway

    add_edge("lb", "gateway", f"{effective_rps} RPS", effective_rps, lb_status)

    # ═══════════════════════════════════════════════════════════
    #  3. GATEWAY
    # ═══════════════════════════════════════════════════════════
    gw_base_load = (effective_rps / GW_MAX_RPS) * 100
    gw_load = gw_base_load + lb_cascade
    gw_status = _status(gw_load)
    if gw_load > 100:
        gw_status = "critical"

    components.append(ComponentMetrics(
        id="gateway", label=GATEWAY_NAME, type="gateway",
        cpu_percent=_cap_load(15 + gw_load * 0.7),
        memory_percent=_cap_load(20 + gw_load * 0.4),
        latency_ms=round(2 + (gw_load / 100) * 5, 1),
        rps=effective_rps,
        error_rate=round(min(15, (gw_load / 100) * 6), 2),
        status=gw_status,
        load_percent=_cap_load(gw_load),
    ))

    # ── Cascade: if Gateway is critical, apps take extra load ──
    gw_cascade = 0
    if gw_status == "critical":
        gw_cascade = 25

    # ═══════════════════════════════════════════════════════════
    #  4. APPS & CONTAINERS
    # ═══════════════════════════════════════════════════════════
    rps_per_app = effective_rps / max(1, active_apps)

    # DB impact factor
    db_impact = effective_db_latency / max(1, DB_LATENCY_NORMAL)
    db_cascade = 0
    if db_impact > 5:
        db_cascade = 30
    elif db_impact > 2:
        db_cascade = 15

    for i in range(active_apps):
        app_name = APP_NAMES[i]
        app_id = f"app_{i}"

        conts = effective_conts
        failed_in_this_app = 0
        if sname == "container_failure" and i == 0:
            failed_in_this_app = min(fail_count, conts - 1)

        healthy_conts = max(1, conts - failed_in_this_app)
        rps_per_container = rps_per_app / healthy_conts

        # Container oversaturation
        container_load_pct = (rps_per_container / RPS_PER_CONTAINER_MAX) * 100
        redistribution_factor = conts / healthy_conts  # 1.0 if all healthy, >1 if some failed

        # App CPU = f(container load, DB cascade, Gateway cascade)
        app_cpu = (
            CONTAINER_CPU_NORMAL
            + container_load_pct * 0.5
            + db_cascade * 0.6
            + gw_cascade * 0.5
        )
        app_mem = 30 + container_load_pct * 0.3 + db_cascade * 0.2
        app_latency = (
            10
            + (container_load_pct / 100) * 40
            + (db_impact - 1) * 8
            + (gw_cascade / 25) * 10
        )
        app_error = (
            (container_load_pct / 100) * 3
            + max(0, db_impact - 1) * 2
            + (1 if gw_status == "critical" else 0) * 5
        )
        app_load = app_cpu * 1.1

        # App status from key metrics
        app_load_capped = _cap_load(app_load)
        app_status_from_cpu = _status(app_cpu)
        app_status_from_latency = "critical" if app_latency > 300 else "warning" if app_latency > 150 else "healthy"
        app_status = app_status_from_cpu if app_status_from_cpu != "healthy" else app_status_from_latency

        # If too many containers died, app is critical
        if failed_in_this_app > 0 and healthy_conts <= 1:
            app_status = "critical"
            app_error = min(30, app_error + 10)
            app_latency = app_latency * 2

        components.append(ComponentMetrics(
            id=app_id, label=app_name, type="app",
            cpu_percent=_cap_load(app_cpu),
            memory_percent=_cap_load(app_mem),
            latency_ms=round(min(500, app_latency), 1),
            rps=round(rps_per_app, 1),
            error_rate=round(min(30, app_error), 2),
            status=app_status,
            load_percent=app_load_capped,
        ))

        edge_st = "critical" if app_status == "critical" else "warning" if app_status == "warning" else "healthy"
        add_edge("gateway", app_id, f"{rps_per_app:.0f} RPS", rps_per_app, edge_st)

        # ── Containers ──
        for c in range(conts):
            cid = f"container_{i}_{c}"
            is_failed = failed_in_this_app > 0 and c < failed_in_this_app

            if is_failed:
                components.append(ComponentMetrics(
                    id=cid, label=f"{app_name.split()[0]}-{c+1}", type="container",
                    cpu_percent=0, memory_percent=0, latency_ms=0, rps=0, error_rate=100,
                    status="critical", load_percent=0,
                ))
                add_edge(app_id, cid, f"{app_name.split()[0]}-{c+1}", 1, "critical")
                continue

            # Healthy container — load depends on redistribution + cascade
            cont_cpu = CONTAINER_CPU_NORMAL + container_load_pct * 0.6 + db_cascade * 0.3
            cont_mem = 25 + (rps_per_container / 20) * 5
            cont_lat = app_latency * (0.8 + (c % 3) * 0.1)
            cont_err = max(0.1, app_error * (0.5 + (c % 3) * 0.1))

            cont_status = _status(cont_cpu)
            # If parent app is critical, container gets warning too
            if app_status == "critical" and cont_status == "healthy":
                cont_status = "warning"

            components.append(ComponentMetrics(
                id=cid, label=f"{app_name.split()[0]}-{c+1}", type="container",
                cpu_percent=_cap_load(cont_cpu),
                memory_percent=_cap_load(cont_mem),
                latency_ms=round(min(500, cont_lat), 1),
                rps=round(rps_per_container, 1),
                error_rate=round(min(20, cont_err), 2),
                status=cont_status,
                load_percent=_cap_load(cont_cpu * 1.2),
            ))
            add_edge(app_id, cid, f"{app_name.split()[0]}-{c+1}", 1, cont_status)

    # ═══════════════════════════════════════════════════════════
    #  5. DATABASES
    # ═══════════════════════════════════════════════════════════
    db_base_cpu_per_ms = 3
    db_base_mem_per_ms = 4

    for i in range(active_dbs):
        db_id = f"db_{i}"
        db_name = DB_NAMES[i]

        db_weight = [1.0, 0.6, 0.7][i]
        db_lat = effective_db_latency * db_weight

        db_cpu_val = 20 + db_lat * db_base_cpu_per_ms + (effective_rps / 500) * 3
        db_mem = 30 + db_lat * db_base_mem_per_ms + (effective_rps / 300) * 2
        db_load = db_cpu_val

        db_status = _status(db_cpu_val)
        if db_lat > DB_LATENCY_DANGER:
            db_status = "critical"

        if i == 0:
            primary_db_cpu = db_cpu_val
            primary_db_status = db_status

        components.append(ComponentMetrics(
            id=db_id, label=db_name, type="database",
            cpu_percent=_cap_load(db_cpu_val),
            memory_percent=_cap_load(db_mem),
            latency_ms=round(db_lat, 1),
            rps=round(effective_rps * (0.5 - i * 0.1), 1),
            error_rate=round(min(10, (db_lat / DB_LATENCY_DANGER) * 3), 2),
            status=db_status,
            load_percent=_cap_load(db_load),
        ))

        for j in range(active_apps):
            add_edge(f"app_{j}", db_id, db_name[:6], db_lat, db_status)

    # ═══════════════════════════════════════════════════════════
    #  6. CASCADING: chain-wide propagation
    # ═══════════════════════════════════════════════════════════
    # If DB is critical → all apps that touch it get worse
    any_db_critical = any(c.status == "critical" for c in components if c.type == "database")
    if any_db_critical:
        for comp in components:
            if comp.type == "app" and comp.status == "healthy":
                comp.status = "warning"
                comp.latency_ms = round(min(500, comp.latency_ms * 1.8), 1)
                comp.error_rate = round(min(comp.error_rate + 3, 20), 2)

    # If app is critical → its containers scale up error / latency (already handled above)

    # If Gateway is critical AND any app is critical → SYSTEM EDGE IS DOWN
    gw_down = gw_status == "critical"
    any_app_critical = any(c.status == "critical" for c in components if c.type == "app")
    if gw_down and any_app_critical:
        for comp in components:
            if comp.type in ("app", "container") and comp.status == "warning":
                comp.status = "critical"

    # ═══════════════════════════════════════════════════════════
    #  7. SUMMARY
    # ═══════════════════════════════════════════════════════════
    healthy_c = sum(1 for c in components if c.status == "healthy")
    warning_c = sum(1 for c in components if c.status == "warning")
    critical_c = sum(1 for c in components if c.status == "critical")
    total_c = len(components)

    non_clients = [c for c in components if c.type != "clients"]
    avg_lat = round(sum(c.latency_ms for c in non_clients) / max(1, len(non_clients)), 1)
    max_cpu = round(max(c.cpu_percent for c in components), 1)
    tot_rps = round(sum(c.rps for c in non_clients), 1)
    avg_err = round(sum(c.error_rate for c in non_clients) / max(1, len(non_clients)), 2)

    gen_rps_per_container = effective_rps / max(1, active_apps) / max(1, effective_conts)

    # ── Verdict ──
    critical_pct = critical_c / max(1, total_c) * 100
    if critical_pct >= 50:
        verdict = "❌ СИСТЕМА НЕДОСТУПНА — более половины компонентов в критическом состоянии"
    elif critical_c >= 3:
        verdict = "❌ КРИТИЧЕСКИЙ СБОЙ — критических компонентов больше 3, требуется вмешательство"
    elif critical_c >= 1:
        verdict = "⚠️ ЧАСТИЧНЫЙ ОТКАЗ — система деградирует, потеряны ключевые узлы"
    elif warning_c >= 3:
        verdict = "⚡ ПРЕДЕЛЬНАЯ НАГРУЗКА — система на грани, рекомендуется масштабирование"
    elif warning_c >= 1:
        verdict = "⚡ СИСТЕМА ПОД НАГРУЗКОЙ — есть предупреждения, но функциональность сохранена"
    else:
        verdict = "✅ СИСТЕМА СТАБИЛЬНА — все компоненты работают в штатном режиме"

    # ── What was tested ──
    what_tested = {
        "load_spike": (
            f"Симуляция роста RPS в {rps_mult:.0f} раза: "
            f"{base_rps} → {effective_rps:.0f} запросов/сек. "
            f"Лимит Gateway: {GW_MAX_RPS} RPS, лимит LB: {LB_MAX_RPS} RPS. "
            f"Норма на контейнер: ~{RPS_PER_CONTAINER_NORMAL} RPS, "
            f"максимум: {RPS_PER_CONTAINER_MAX} RPS. "
            f"Если нагрузка превышает лимиты — каскадный отказ."
        ),
        "client_growth": (
            f"Симуляция роста клиентов в {client_mult:.0f} раза: "
            f"{base_clients:,} → {effective_clients:,}. "
            f"Максимальная ёмкость системы: {MAX_CLIENTS:,} клиентов. "
            f"При превышении растёт нагрузка на LB (connection overhead) "
            f"и далее на Gateway."
        ),
        "container_failure": (
            f"Отказ {fail_count} контейнера в {APP_NAMES[0]}. "
            f"Было: {effective_conts} контейнеров, здоровых: {healthy_conts}. "
            f"Нагрузка перераспределяется на оставшиеся контейнеры "
            f"(коэффициент: x{redistribution_factor:.1f}). "
            f"Если контейнеры не выдерживают — приложение деградирует."
        ),
        "latency_spike": (
            f"Сбой базы данных: задержка выросла в {db_lat_mult:.0f} раза — "
            f"{base_db_latency}ms → {effective_db_latency}ms. "
            f"Норма: {DB_LATENCY_NORMAL}ms, критический порог: {DB_LATENCY_DANGER}ms. "
            f"Замедление БД распространяется на все приложения по цепочке."
        ),
        "scale_out": (
            f"Добавление {containers_add} контейнера(ов) на каждое приложение: "
            f"было {config.containers_per_app}, стало {effective_conts}. "
            f"Цель: снизить RPS на контейнер и повысить отказоустойчивость."
        ),
        "ddos": (
            f"DDoS-атака: RPS ×{rps_mult:.0f} ({base_rps} → {effective_rps:.0f}), "
            f"клиенты ×{client_mult:.0f} ({base_clients:,} → {effective_clients:,}). "
            f"Лимиты: Gateway {GW_MAX_RPS} RPS, LB {LB_MAX_RPS} RPS, "
            f"клиентов {MAX_CLIENTS:,}. При превышении — каскадный коллапс."
        ),
    }

    # ── Scenario limits ──
    scenario_limits: Dict[str, tuple] = {
        "load_spike": {
            "RPS (входящий)": (effective_rps, base_rps, GW_MAX_RPS, "RPS"),
            "RPS на контейнер": (round(gen_rps_per_container, 1), RPS_PER_CONTAINER_NORMAL, RPS_PER_CONTAINER_MAX, "RPS"),
            "Загрузка Gateway": (round(gw_load, 1), 20, 100, "%"),
        },
        "client_growth": {
            "Клиенты": (effective_clients, base_clients, MAX_CLIENTS, "шт."),
            "Нагрузка LB": (round(lb_load, 1), 20, 100, "%"),
            "Соединений (overhead)": (round((client_overage - 1) * 100, 1), 0, 200, "%"),
        },
        "container_failure": {
            "Здоровых контейнеров": (healthy_conts, effective_conts, effective_conts, "шт."),
            "RPS на контейнер": (round(rps_per_container, 1), RPS_PER_CONTAINER_NORMAL, RPS_PER_CONTAINER_MAX, "RPS"),
            "Коэфф. перераспределения": (round(redistribution_factor, 2), 1.0, 3.0, "x"),
        },
        "latency_spike": {
            "Задержка БД": (round(effective_db_latency, 1), DB_LATENCY_NORMAL, DB_LATENCY_DANGER, "ms"),
            "Ср. задержка API": (round(avg_lat, 1), 20, 300, "ms"),
            "DB impact": (round(db_impact, 1), 1.0, 10.0, "x"),
        },
        "scale_out": {
            "Контейнеров на приложение": (effective_conts, config.containers_per_app, 10, "шт."),
            "RPS на контейнер": (round(gen_rps_per_container, 1), RPS_PER_CONTAINER_NORMAL, RPS_PER_CONTAINER_MAX, "RPS"),
            "Макс. CPU": (round(max_cpu, 1), 30, 100, "%"),
        },
        "ddos": {
            "RPS (атака)": (effective_rps, base_rps, GW_MAX_RPS, "RPS"),
            "Клиенты (атака)": (effective_clients, base_clients, MAX_CLIENTS, "шт."),
            "Критических компонентов": (critical_c, 0, total_c, "шт."),
        },
    }

    limits_data = scenario_limits.get(sname, {})
    system_limits = {}
    for name, (cur, norm, max_cap, unit) in limits_data.items():
        st = _limit_status(float(cur), float(norm), float(max_cap))
        system_limits[name] = LimitInfo(
            current=round(float(cur), 1),
            normal=round(float(norm), 1),
            max_capacity=round(float(max_cap), 1),
            unit=unit,
            status=st,
        )

    # ── Recommendations ──
    scenario_recs = {
        "load_spike": [
            "Увеличьте количество контейнеров для каждого приложения",
            "Добавьте реплики API Gateway для распределения нагрузки",
            "Включите авто-масштабирование (HPA) по CPU",
            f"Лимит Gateway: {GW_MAX_RPS} RPS, текущий: {effective_rps:.0f}",
            f"Норма RPS на контейнер: {RPS_PER_CONTAINER_NORMAL}, макс: {RPS_PER_CONTAINER_MAX}",
        ],
        "client_growth": [
            "Масштабируйте Load Balancer — добавьте второй экземпляр",
            "Увеличьте pool соединений к БД",
            "Внедрите кэширование (Redis) для горячих данных",
            f"Макс. клиентов: {MAX_CLIENTS:,}, текущий: {effective_clients:,}",
            f"Загрузка LB: {lb_load:.0f}%",
        ],
        "container_failure": [
            f"Восстановите упавший контейнер в {APP_NAMES[0]}",
            "Настройте liveness/readiness probes для автоматического перезапуска",
            "Увеличьте количество контейнеров для отказоустойчивости (min 3)",
            f"RPS на контейнер после перераспределения: {rps_per_container:.1f} (норма: {RPS_PER_CONTAINER_NORMAL})",
        ],
        "latency_spike": [
            "Проверьте запросы к БД — возможен медленный запрос (slow query)",
            "Добавьте индексы в PostgreSQL",
            "Увеличьте размер кэша Redis",
            "Рассмотрите репликацию БД для распределения read-нагрузки",
            f"Задержка БД: {effective_db_latency}ms (норма: {DB_LATENCY_NORMAL}ms, критично: {DB_LATENCY_DANGER}ms)",
        ],
        "scale_out": [
            "Система чувствует себя лучше после масштабирования",
            "Можно дополнительно настроить авто-масштабирование",
            "Убедитесь, что БД выдерживает увеличенное количество подключений",
            f"RPS на контейнер снижен до {gen_rps_per_container:.1f}",
        ],
        "ddos": [
            "СИСТЕМА ПОД DDoS-АТАКОЙ — необходима срочная защита",
            "Активируйте WAF / Rate Limiting на уровне Gateway",
            "Подключите Cloudflare или другое DDoS-защитное решение",
            "Заблокируйте подозрительные IP на Load Balancer",
            f"Текущий RPS: {effective_rps:.0f} при лимите Gateway {GW_MAX_RPS}",
            f"Клиентов: {effective_clients:,} при лимите {MAX_CLIENTS:,}",
        ],
    }

    recs = list(scenario_recs.get(sname, []))

    critical_comps = [c for c in components if c.status == "critical"]
    warning_comps = [c for c in components if c.status == "warning"]

    if critical_comps:
        types_in_critical = set(c.type for c in critical_comps)
        if "container" in types_in_critical and sname != "container_failure":
            recs.append("⚠️ Контейнеры перегружены — требуется масштабирование")
        if "database" in types_in_critical:
            recs.append("⚠️ База данных перегружена — проверьте соединения и индексы")
        if "gateway" in types_in_critical:
            recs.append("⚠️ Gateway перегружен — добавьте реплики")
        if "app" in types_in_critical:
            recs.append("⚠️ Приложения критичны — не хватает ресурсов")
        if "lb" in types_in_critical:
            recs.append("⚠️ Load Balancer перегружен — добавьте второй экземпляр")
    elif warning_comps and sname not in ("scale_out",):
        recs.append("⚡ Система на пределе — рекомендуется масштабирование")
    elif sname == "scale_out":
        recs.append("✅ После масштабирования система стабильна")
    else:
        recs.append("✅ Система в норме. Наблюдайте за метриками.")

    # ─── Summary description ──
    descriptions = {
        "load_spike": (
            f"RPS ×{rps_mult:.0f}: {base_rps} → {effective_rps:.0f}. "
            f"Gateway: {gw_status}, БД: {primary_db_status}, "
            f"критических: {critical_c}/{total_c}. "
            f"{'⚠️ Система не справляется' if critical_c else '✅ Система держит удар'}"
        ),
        "client_growth": (
            f"Клиенты ×{client_mult:.0f}: {base_clients:,} → {effective_clients:,}. "
            f"LB загружен на {lb_load:.0f}%. "
            f"{'⚠️ Требуется масштабирование' if lb_status != 'healthy' else '✅ LB справляется'}"
        ),
        "container_failure": (
            f"Отказ {fail_count} контейнера в {APP_NAMES[0]}. "
            f"Перераспределение x{redistribution_factor:.1f}. "
            f"{'⚠️ Риск каскадного отказа' if critical_c > 0 else '✅ Система сохранила работоспособность'}"
        ),
        "latency_spike": (
            f"Задержка БД: {base_db_latency}ms → {effective_db_latency}ms. "
            f"Ср. задержка API: {avg_lat}ms. "
            f"{'⚠️ Критическое замедление' if avg_lat > 200 else '⚠️ Замедление заметно'}"
        ),
        "scale_out": (
            f"Добавлено {containers_add} контейнера(ов) на приложение. "
            f"RPS на контейнер: {gen_rps_per_container:.1f}. "
            f"Макс. CPU: {max_cpu}%. "
            f"{'✅ Нагрузка снижена' if max_cpu < 40 else '⚡ Требуется ещё ресурсов'}"
        ),
        "ddos": (
            f"DDoS! RPS ×{rps_mult:.0f}, Клиенты ×{client_mult:.0f}. "
            f"Критических: {critical_c}/{total_c}. "
            f"{'❌ СИСТЕМА НЕДОСТУПНА' if critical_pct >= 50 else '⚠️ ДЕГРАДАЦИЯ'}"
        ),
    }

    summary: Dict[str, float | str] = {
        "healthy": healthy_c,
        "warning": warning_c,
        "critical": critical_c,
        "avg_latency_ms": avg_lat,
        "max_cpu_percent": max_cpu,
        "total_rps": tot_rps,
        "avg_error_rate": avg_err,
        "total_components": total_c,
        "description": descriptions.get(sname, "Анализ завершён."),
    }

    config_info = {
        "num_apps": config.num_apps,
        "containers_per_app": config.containers_per_app,
        "num_clients": config.num_clients,
        "rps": config.rps,
        "db_latency_ms": config.db_latency_ms,
        "effective_rps": round(effective_rps, 0),
        "effective_clients": effective_clients,
        "effective_db_latency": round(effective_db_latency, 1),
        "effective_conts_per_app": effective_conts,
        "scenario": sname,
    }

    scenario_titles = {
        "load_spike": "Скачок нагрузки (RPS ↑)",
        "client_growth": "Рост клиентов (Users ↑)",
        "container_failure": "Отказ контейнера",
        "latency_spike": "Сбой БД (Latency ↑)",
        "scale_out": "Масштабирование (+ контейнеры)",
        "ddos": "DDoS-атака",
    }

    return AnalysisResult(
        components=components,
        edges=edges,
        summary=summary,
        recommendations=recs,
        config_info=config_info,
        scenario_explanation=ScenarioExplanation(
            title=scenario_titles.get(sname, "Тест"),
            what_was_tested=what_tested.get(sname, "Тестирование системы"),
            verdict=verdict,
            system_limits=system_limits,
        ),
    )
