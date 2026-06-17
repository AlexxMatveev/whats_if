SCENARIOS = {
    "load_spike": {
        "name": "Скачок нагрузки (RPS ×3)",
        "description": "Увеличение запросов в секунду. Gateway и контейнеры принимают удар.",
        "params": {"rps_multiplier": 3, "label": "RPS ×3 от базового"},
    },
    "client_growth": {
        "name": "Рост клиентов (Users ×3)",
        "description": "Увеличение активных пользователей. Load Balancer и Gateway под давлением.",
        "params": {"client_multiplier": 3, "label": "Клиенты ×3 от базового"},
    },
    "container_failure": {
        "name": "Отказ контейнера",
        "description": "Один контейнер падает — нагрузка перераспределяется на остальные.",
        "params": {"fail_count": 1, "label": "1 контейнер недоступен"},
    },
    "latency_spike": {
        "name": "Сбой БД (Latency ×10)",
        "description": "База данных начинает тормозить — latency уходит вверх по цепочке.",
        "params": {"db_latency_multiplier": 10, "label": "Задержка БД ×10"},
    },
    "scale_out": {
        "name": "Масштабирование (+ контейнеры)",
        "description": "Добавление контейнеров снижает нагрузку на каждый экземпляр.",
        "params": {"containers_add": 2, "label": "+2 контейнера на приложение"},
    },
    "ddos": {
        "name": "DDoS-атака",
        "description": "Лавина трафика. Все компоненты системы под угрозой.",
        "params": {
            "rps_multiplier": 20,
            "client_multiplier": 20,
            "label": "RPS ×20, Клиенты ×20",
        },
    },
}
