"""Тесты анализатора сценариев."""

from app.models import SystemConfig, Scenario
from app.analyzer import analyze


def test_baseline():
    config = SystemConfig(num_apps=3, containers_per_app=2, num_clients=10000, rps=100, db_latency_ms=5)
    scenario = Scenario(name="baseline", params={"rps_multiplier": 1, "client_multiplier": 1, "fail_count": 0, "containers_add": 0, "db_latency_multiplier": 1})
    result = analyze(config, scenario)
    assert result.summary["total_components"] > 0
    assert result.summary["healthy"] > 0


def test_load_spike():
    config = SystemConfig(rps=200)
    scenario = Scenario(name="load_spike", params={"rps_multiplier": 10})
    result = analyze(config, scenario)
    assert result.summary["critical"] > 0


def test_container_failure():
    config = SystemConfig(num_apps=1, containers_per_app=3, rps=300)
    scenario = Scenario(name="container_failure", params={"fail_count": 1})
    result = analyze(config, scenario)
    assert result.summary["critical"] >= 1


def test_client_growth():
    config = SystemConfig(num_clients=200_000)
    scenario = Scenario(name="client_growth", params={"client_multiplier": 3})
    result = analyze(config, scenario)
    assert result.summary["avg_latency_ms"] > 0


def test_latency_spike():
    config = SystemConfig(db_latency_ms=5)
    scenario = Scenario(name="latency_spike", params={"db_latency_multiplier": 50})
    result = analyze(config, scenario)
    assert result.summary["avg_latency_ms"] > 100
