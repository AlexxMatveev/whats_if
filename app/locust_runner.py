"""Run Locust in headless subprocess and parse CSV results."""

import csv
import os
import shutil
import tempfile
import subprocess
import time
import threading
from typing import List, Optional


def generate_locustfile(endpoints: List[str], method: str = "GET") -> str:
    """Generate a temporary locustfile for the given endpoints."""
    lines = [
        "from locust import HttpUser, task, between",
        "import gevent",
        "",
        "class TestUser(HttpUser):",
        "    wait_time = between(0.1, 0.3)",
        "",
        "    @task",
        "    def hit_endpoints(self):",
    ]
    for ep in endpoints:
        if method == "GET":
            lines.append(f'        self.client.get("{ep}", name="{ep}")')
        else:
            lines.append(f'        self.client.post("{ep}", name="{ep}")')
        lines.append("        gevent.sleep(0.05)")
    lines.append("")
    return "\n".join(lines)


def run_locust_test(
    target_url: str,
    endpoints: List[str],
    num_users: int,
    spawn_rate: float,
    duration_sec: int,
    method: str = "GET",
    timeout_sec: int = 120,
) -> dict:
    """Run locust in headless mode, return per-endpoint stats dict."""

    tmpdir = tempfile.mkdtemp(prefix="locust_")
    locustfile_path = os.path.join(tmpdir, "locustfile.py")
    csv_prefix = os.path.join(tmpdir, "locust_output")

    with open(locustfile_path, "w", encoding="utf-8") as f:
        f.write(generate_locustfile(endpoints, method))

    cmd = [
        "locust",
        "--headless",
        "--host", target_url,
        "--locustfile", locustfile_path,
        "--users", str(num_users),
        "--spawn-rate", str(spawn_rate),
        "--run-time", f"{duration_sec}s",
        "--csv", csv_prefix,
        "--csv-full-history",
        "--only-summary",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=tmpdir,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return {"error": "Locust test timed out"}

    # Parse CSV: locust_output_stats.csv
    stats_csv = csv_prefix + "_stats.csv"
    results = {}

    if os.path.exists(stats_csv):
        with open(stats_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("Name", "").strip()
                if not name or name == "Aggregated":
                    continue
                method_val = row.get("Type", "GET")
                num_req = int(float(row.get("Request Count", 0)))
                num_fail = int(float(row.get("Failure Count", 0)))
                avg_ms = float(row.get("Average Response Time", 0))
                min_ms = float(row.get("Min Response Time", 0))
                max_ms = float(row.get("Max Response Time", 0))
                median_ms = float(row.get("Median Response Time", 0))
                p90 = float(row.get("90%", 0))
                p95 = float(row.get("95%", 0))
                p99 = float(row.get("99%", 0))
                rps_val = float(row.get("Requests/s", 0))

                results[name] = {
                    "method": method_val,
                    "name": name,
                    "num_requests": num_req,
                    "num_failures": num_fail,
                    "avg_response_time": avg_ms,
                    "min_response_time": min_ms,
                    "max_response_time": max_ms,
                    "median_response_time": median_ms,
                    "p90": p90,
                    "p95": p95,
                    "p99": p99,
                    "rps": rps_val,
                    "fail_ratio": num_fail / max(1, num_req),
                }

    # Parse failures CSV if exists
    failures_csv = csv_prefix + "_failures.csv"
    failure_details = {}
    if os.path.exists(failures_csv):
        with open(failures_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("Name", "").strip()
                if name:
                    failure_details[name] = {
                        "occurrences": int(row.get("Occurrences", 0)),
                        "error": row.get("Error", ""),
                    }

    shutil.rmtree(tmpdir, ignore_errors=True)

    return {
        "entries": results,
        "failures": failure_details,
    }
