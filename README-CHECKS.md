# Проверки (Assertions) — на базе Apache JMeter

Вкладка **«🔍 Проверки»** реализует систему assertions, аналогичную [Apache JMeter](https://jmeter.apache.org/).

---

## Как работают проверки в JMeter (оригинал)

В JMeter **Assertions** — это элементы, которые валидируют ответы от сервера после выполнения Sampler'а:

1. **Sampler** (HTTP Request, JDBC Request, ...) отправляет запрос и получает ответ
2. **Assertion** (дочерний элемент Sampler'а) проверяет ответ по заданному правилу
3. Если условие не выполнено → Sampler помечается как **failed**
4. Переменная `JMeterThread.last_sample_ok` = `false`
5. **Listeners** (Assertion Results, View Results Tree) показывают pass/fail

### Типы Assertions в JMeter (секция 18.5 Component Reference)

| Тип | Что проверяет | Параметры |
|-----|---------------|-----------|
| **Response Assertion** | Тело ответа, код, заголовки | Contains / Matches / Equals / Substring + паттерн |
| **Duration Assertion** | Время ответа | Максимум в ms |
| **Size Assertion** | Размер ответа в байтах | = / > / < / != |
| **JSON Assertion** | JSON-структуру | JsonPath + ожидаемое значение |
| **XML Assertion** | Well-formed XML | — |
| **XPath Assertion** | XPath-выражение | XPath + expected |
| **HTML Assertion** | HTML-синтаксис (JTidy) | — |
| **BeanShell / JSR223 Assertion** | Кастомный скрипт | Groovy, BeanShell |
| **Compare Assertion** | Сравнение двух результатов | Content / Elapsed Time |

### Scoping (область применения)

- Assertion на уровне **Sampler** → применяется только к этому Sampler'у
- Assertion на уровне **Thread Group** → применяется ко всем Sampler'ам внутри
- Поддерживаются: Main sample, Sub-samples, Main+Sub-samples, JMeter Variable

---

## Как реализовано в «Whats If»

В проекте используется **аналогичная модель**:

```
POST /api/analyze  (Sampler)
  ↓
ComponentMetrics[]  (результаты: CPU, память, latency, error rate, status)
  ↓
Assertion Rules × N  (применяются к КАЖДОМУ компоненту)
  ↓
Pass / Fail  →  визуализация на графе + таблица
```

### Сопоставление с JMeter

| Правило | JMeter Assertion | Логика JMeter | Логика проекта |
|---------|-----------------|---------------|----------------|
| **Статус** | Response Assertion | `Response Code == 200` | `component.status == "healthy"` |
| **Длительность** | Duration Assertion | `elapsed_time < max_ms` | `latency_ms < 200` |
| **CPU** | Size Assertion | `response_size < limit` | `cpu_percent < 80` |
| **Память** | Size Assertion | `response_size > limit → FAIL` | `memory_percent < 80` |
| **Ошибки** | JSON Assertion | JsonPath `$.error_rate == expected` | `error_rate < 5` |
| **Нагрузка** | Response Assertion | `Text contains pattern → FAIL` | `load_percent < 80` |

### Scoping (как в JMeter)

- Правила применяются к **каждому компоненту** (аналог Thread Group-level assertions)
- Компоненты = Clients, Load Balancer, Gateway, все Apps, все Containers, Databases, External CRM
- Всего: **N компонентов × M активных правил = total assertions**

### Проход Fail

Если хотя бы одна проверка у компонента не прошла:
- Компонент на графе получает **красную обводку** (вместо стандартной)
- На ноде отображается бейдж **`X/Y`** (провалено/всего)
- В таблице выводятся только FAIL-строки
- В модалке по клику — детали по каждой проверке

### Цепочка выполнения (в терминах JMeter)

```
Test Plan
  └── Thread Group
       ├── Sampler: POST /api/analyze
       │    ├── Response Assertion: status == healthy
       │    ├── Duration Assertion: latency < 200ms
       │    ├── Size Assertion: cpu < 80%
       │    ├── Size Assertion: memory < 80%
       │    ├── JSON Assertion: errors < 5%
       │    └── Response Assertion: load < 80%
       └── Listener: Assertion Graph + Results Table
```

---

## Визуализация

- **Force-directed граф** (D3.js) — как во вкладке «Анализ»
- **Обводка нод**: зелёная (все проверки пройдены) / красная (есть FAIL)
- **Бейдж**: число проваленных / общее число проверок
- **Таблица**: только проваленные проверки (как Assertion Results в JMeter)
- **Модалка**: детали по всем проверкам компонента (как View Results Tree)

---

## Управление

- Каждое правило можно **отключить** кликом (аналог — удалить assertion из Test Plan)
- Кнопка **«▶ Запустить проверки»** — перезапустить все активные правила
- При переключении правил проверки перезапускаются автоматически
- При новом анализе (Sampler) результаты сбрасываются

---

## Формулы расчёта метрик (industry standard)

Метрики компонентов (CPU, latency, error rate, load) рассчитываются не произвольно, а на основе **трёх общепринятых моделей** из теории массового обслуживания и observability.

### 1. Little's Law — связь конкуренции, пропускной способности и задержки

Фундаментальный закон теории очередей, используется повсеместно в capacity planning и performance testing (JMeter, k6, LoadRunner).

```
L = λ × W
```
- `L` — среднее число concurrent запросов в системе
- `λ` — arrival rate (RPS)
- `W` — среднее время обработки (latency)

**Как применяется в анализаторе:**
- При росте RPS (`λ`) при фиксированном `L` (количество контейнеров) — latency растёт линейно
- Если контейнер падает, `L` на оставшиеся контейнеры растёт → latency увеличивается
- `W = L / λ` — используется для расчёта времени ответа при перераспределении нагрузки

**Формула в коде** (`analyzer.py:248`):
```python
app_latency = (
    10
    + (container_load_pct / 100) * 40
    + (db_impact - 1) * 8
    + (gw_cascade / 25) * 10
)
```
- Базовая задержка: 10ms (service time при нулевой нагрузке)
- `(load / 100) * 40`: время в очереди (waiting time) по Little's Law — растёт с utilisation
- `db_impact * 8`: задержка из-за медленной БД (λ не меняется, но W растёт, значит L растёт)
- `gw_cascade / 25 * 10`: каскадный эффект от перегруженного Gateway

### 2. M/M/c Queueing Model — utilisation и время ожидания

Стандартная модель multi-server очереди, применяется для расчёта CPU нагрузки и времени ответа.

**Utilisation (загрузка):**
```
ρ = λ / (c × μ)
```
- `ρ` — utilisation (0..1), преобразуется в load_percent
- `λ` — arrival rate (RPS)
- `c` — количество серверов (контейнеров)
- `μ` — service rate (сколько запросов в секунду обрабатывает один сервер)

**Формула в коде** (`analyzer.py:235`):
```python
container_load_pct = (rps_per_container / RPS_PER_CONTAINER_MAX) * 100
```
- `rps_per_container` = λ / c (RPS, распределённый на контейнер)
- `RPS_PER_CONTAINER_MAX` = μ (максимальная пропускная способность контейнера)
- `ρ = λ / (c × μ) = rps_per_container / RPS_PER_CONTAINER_MAX`
- Если ρ > 1 (load > 100%) → компонент в status = "critical"

**CPU как функция utilisation** (`analyzer.py:239`):
```python
app_cpu = CONTAINER_CPU_NORMAL + container_load_pct * 0.5 + db_cascade * 0.6
```
- `CONTAINER_CPU_NORMAL = 25%`: базовый CPU при нулевой нагрузке
- `container_load_pct * 0.5`: CPU растёт пропорционально utilisation (Amdahl's Law: последовательная часть + параллельная)
- `db_cascade * 0.6`: дополнительная работа из-за retry/timeout при медленной БД

### 3. RED Method — Rate, Errors, Duration

Стандарт observability от Tom Wilkie (Google SRE / CNCF), используется в Prometheus, Grafana, Jaeger.

| Метрика | Описание | В проекте |
|---------|----------|-----------|
| **Rate** | Количество запросов в секунду | `rps` — пропускная способность компонента |
| **Errors** | Количество/процент ошибок | `error_rate` — доля failed запросов |
| **Duration** | Время обработки запроса | `latency_ms` — задержка в миллисекундах |

**Error Rate расчёт** (`analyzer.py:252`):
```python
app_error = (
    (container_load_pct / 100) * 3       # ошибки от перегрузки (queue timeout)
    + max(0, db_impact - 1) * 2          # ошибки от таймаутов БД
    + (1 if gw_status == "critical" else 0) * 5  # ошибки от отказа Gateway
)
```
- Каждый источник ошибок складывается аддитивно (как в Jaeger: error rate = sum of span errors / total spans)
- При cascading failure ошибки умножаются: если Gateway critical → все App получают +5% ошибок

### 4. Cascading Failure Propagation — по графу зависимостей

Реализует BFS-распространение отказов по цепочкам зависимостей:
- **Backward**: если компонент critical, его непосредственные предшественники получают warning/critical (аналог Jaeger Service Graph: dependency check)
- **Forward**: от всех degraded-компонентов распространяется warning на downstream (аналог Jaeger: если upstream service slow → downstream получает увеличенную latency)

---

### Итоговая модель

```
Вход: config + scenario params
  │
  ├─ Little's Law: λ (RPS) → W (latency) для каждого компонента
  ├─ M/M/c: ρ (utilization) → CPU, load_percent, status
  ├─ RED: Rate × Errors × Duration → метрики компонента
  ├─ Cascading: BFS по графу → degraded propagation
  │
  └─ Результат: ComponentMetrics[] → assertions → pass/fail
```
