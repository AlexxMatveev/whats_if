# Whats If

Сервис для анализа сценариев **«что если» (what-if)** для распределённых систем.  
Позволяет моделировать нагрузки, отказы компонентов и DDoS-атаки, визуализируя влияние на всю архитектуру.

---

## Возможности

- **6 встроенных сценариев**: скачок RPS, рост клиентов, отказ контейнера, сбой БД, масштабирование, DDoS
- **Анализ архитектуры** из drawio-диаграмм (C4 model) через BI_3049.drawio
- **Генерация drawio-диаграмм** из ARCHOPS YAML-манифестов
- **REST API** для интеграции в сторонние системы
- **Веб-интерфейс** (FastAPI + статика)

---

## Быстрый старт

### Локально

```bash
pip install -r requirements.txt
python run.py
# → http://localhost:8000
```

### Docker

```bash
docker-compose up --build
# → http://localhost:8000
```

---

## Структура проекта

```
Whats if/
├── app/                          # Серверная часть (FastAPI)
│   ├── main.py                   # Точка входа, настройка CORS и маршрутов
│   ├── models.py                 # Pydantic-модели (SystemConfig, AnalysisResult и др.)
│   ├── analyzer.py               # Бизнес-логика анализа сценариев
│   ├── diagram_generator.py      # Генерация drawio-диаграмм из ARCHOPS YAML
│   ├── drawio_parser.py          # Парсер drawio-файлов C4 model
│   ├── scenarios.py              # Словарь сценариев по умолчанию
│   └── routers/
│       ├── analysis.py           # POST/GET для анализа и списка сценариев
│       ├── architecture.py       # Работа с архитектурой из drawio
│       └── diagram.py            # Генерация drawio из YAML + product view
├── examples/                     # Примеры ARCHOPS YAML-манифестов
│   ├── main.py                   # CLI-утилита для конвертации YAML → drawio
│   └── *.yaml                    # Манифесты систем и контейнеров
├── static/                       # Веб-интерфейс
│   ├── index.html
│   ├── css/style.css
│   └── js/app.js
├── tests/
│   ├── __init__.py
│   └── test_analyzer.py          # Тесты анализатора
├── BI_3049.drawio                 # Архитектурная диаграмма (C4 model)
├── run.py                        # Скрипт запуска
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## API Endpoints

| Метод | Путь                              | Описание                                          |
|-------|-----------------------------------|---------------------------------------------------|
| GET   | `/api/scenarios`                  | Список доступных сценариев и их параметров         |
| POST  | `/api/analyze`                    | Запустить анализ сценария                          |
| GET   | `/api/architecture/view`          | Получить данные архитектуры из BI_3049.drawio      |
| POST  | `/api/architecture/analyze`       | Анализ сценария на архитектуре из drawio           |
| GET   | `/api/diagram`                    | Скачать .drawio файл из YAML-манифестов            |
| GET   | `/api/diagram/data`               | JSON с layout для product view                     |
| GET   | `/api/diagram/view`               | HTML/SVG product view                              |
| GET   | `/`                               | Перенаправление на веб-интерфейс                   |

---

## Интеграция в ваш проект

### 1. Python-клиент

```python
import requests

BASE_URL = "http://localhost:8000"

# Получить список сценариев
scenarios = requests.get(f"{BASE_URL}/api/scenarios").json()

# Запустить анализ
payload = {
    "config": {
        "num_apps": 4,
        "containers_per_app": 2,
        "num_clients": 10000,
        "rps": 100,
        "db_latency_ms": 5,
    },
    "scenario": {
        "name": "load_spike",
        "params": {
            "rps_multiplier": 3,
            "client_multiplier": 1,
            "fail_count": 0,
            "containers_add": 0,
            "db_latency_multiplier": 1,
        },
    },
}
result = requests.post(f"{BASE_URL}/api/analyze", json=payload).json()

print(result["summary"])
print(result["recommendations"])
```

### 2. Модульное использование (Python)

```python
from app.models import SystemConfig, Scenario
from app.analyzer import analyze

config = SystemConfig(num_apps=3, rps=100)
scenario = Scenario(name="load_spike", params={"rps_multiplier": 3})
result = analyze(config, scenario)

for comp in result.components:
    print(f"{comp.label}: {comp.status} (CPU {comp.cpu_percent}%)")
```

### 3. cURL

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "config": {"num_apps": 3, "containers_per_app": 2, "num_clients": 10000, "rps": 100, "db_latency_ms": 5},
    "scenario": {"name": "ddos", "params": {"rps_multiplier": 20, "client_multiplier": 20}}
  }'
```

---

## Модели данных

### SystemConfig

| Поле               | Тип    | По умолч. | Описание                        |
|--------------------|--------|-----------|---------------------------------|
| num_apps           | int    | 3         | Количество приложений            |
| containers_per_app | int    | 2         | Контейнеров на приложение        |
| num_clients        | int    | 10000     | Активных клиентов                |
| rps                | int    | 100       | Запросов в секунду               |
| db_latency_ms      | float  | 5.0       | Базовая задержка БД (ms)         |

### Scenario

| Поле   | Тип    | Описание                        |
|--------|--------|---------------------------------|
| name   | str    | `load_spike`, `client_growth`, `container_failure`, `latency_spike`, `scale_out`, `ddos` |
| params | dict   | Параметры модификаторов нагрузки |

### AnalysisResult

| Поле                 | Тип     | Описание                                  |
|----------------------|---------|-------------------------------------------|
| components           | list    | Метрики каждого компонента системы          |
| edges                | list    | Связи между компонентами                    |
| summary              | dict    | Сводка: healthy/warning/critical/avg_latency |
| recommendations      | list    | Рекомендации по улучшению                   |
| config_info          | dict    | Использованная конфигурация                  |
| scenario_explanation | object  | Вердикт, описание, лимиты                   |

---

## Сценарии

| Сценарий            | Ключ               | Что моделирует                    |
|---------------------|--------------------|-----------------------------------|
| Скачок нагрузки     | `load_spike`       | RPS ×3, ×10, ×20                 |
| Рост клиентов       | `client_growth`    | Клиенты ×3, ×5, ×10              |
| Отказ контейнера    | `container_failure`| Падение 1–N контейнеров           |
| Сбой БД             | `latency_spike`    | Задержка БД ×5, ×10, ×50         |
| Масштабирование     | `scale_out`        | Добавление контейнеров             |
| DDoS-атака          | `ddos`             | RPS ×20, клиенты ×20              |

---

## Тестирование

```bash
python -m pytest tests/
```

---

## ARCHOPS → drawio

Сервис умеет читать ARCHOPS YAML-манифесты и генерировать drawio-диаграммы в нотации C4.

```bash
python examples/main.py --input examples/ --output diagram.drawio
```

Или через API: `GET /api/diagram`

---

## License

MIT
