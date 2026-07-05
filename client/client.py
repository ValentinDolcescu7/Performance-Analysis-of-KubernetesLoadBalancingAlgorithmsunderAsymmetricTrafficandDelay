#!/usr/bin/env python3
"""Final deterministic traffic_logic client for Kubernetes kube-proxy LB experiments.

Designed for comparing one identical traffic workload across kube-proxy algorithms:
RR / WRR / LC / SED / NQ. The client does not change the cluster; it only
labels the run and generates a reproducible HTTP workload against Podinfo.

Key ideas:
- build the full traffic plan before the run;
- use a fixed random seed;
- open a new TCP connection per request by default;
- use one official traffic scenario named traffic_logic;
- optionally collect Prometheus counter deltas before/after the run.

Heavy requests use POST /store (write payload to disk + SHA1). This is real
server-side work that scales cleanly with payload size when the client runs
from INSIDE the cluster (node or pod), unlike POST /echo with small payloads
whose latency, measured over a laptop link, was dominated by client-side upload.
Light requests use GET / (~10 ms). Run the client from the node or a pod, never
over WiFi, otherwise the upload latency contaminates the measurement.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import random
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus

import aiohttp


# ---------------------------------------------------------------------------
# Default lab settings. Override anything from CLI.
# ---------------------------------------------------------------------------

time_start = time.time()

DEFAULT_BASE_URL = "http://192.168.100.81:30198"
DEFAULT_PROMETHEUS_URL = "http://192.168.100.81:30109"
DEFAULT_NAMESPACE = "lb-podinfo"
DEFAULT_OUTPUT_DIR = "results"


# Podinfo endpoints used by the experiment.
# - fast       : GET /  -> tiny JSON, releases the connection almost instantly.
#                The client can extract the pod hostname directly from the JSON.
# - store_*    : POST /store -> writes the posted body to disk and returns the
#                SHA1 hash. This is real, payload-proportional work on the server
#                (receive body + hash + disk write), so it holds the TCP
#                connection for a controllable duration. The response is JSON
#                ({"hash": "..."}) but does NOT carry the pod hostname; use
#                Prometheus for authoritative per-pod counts in store scenarios.
REQUEST_TEMPLATES: dict[str, dict[str, Any]] = {
    "fast": {"method": "GET", "path": "/"},
    "store_2k": {
        "method": "POST",
        "path": "/store",
        "body": "auto",
        "body_size_bytes": 2 * 1024,
    },    
    "store_4k": {
        "method": "POST",
        "path": "/store",
        "body": "auto",
        "body_size_bytes": 4 * 1024,
    },    
    "store_8k": {
        "method": "POST",
        "path": "/store",
        "body": "auto",
        "body_size_bytes": 8 * 1024,
    },    
    "store_16k": {
        "method": "POST",
        "path": "/store",
        "body": "auto",
        "body_size_bytes": 16 * 1024,
    },    
    "store_32k": {
        "method": "POST",
        "path": "/store",
        "body": "auto",
        "body_size_bytes": 32 * 1024,
    },
}

SCENARIOS: dict[str, dict[str, Any]] = {
    "traffic_logic": {
        "kind": "repeating_pattern",

        # Deterministic stratified heavy/light cyclic workload.
        #   light = GET /            (short-lived connection)
        #   heavy = POST /store      (payload-dependent server-side work)
        # Traffic rate calculation:
        #
        # pattern_length = len(pattern)
        # total_requests = cycles * pattern_length
        # planned_duration_seconds = total_requests * interval_seconds
        # planned_rps = 1 / interval_seconds
        #
        # For a target RPS:
        # interval_seconds = 1 / target_rps
        #
        # Example:
        # target_rps = 173 req/s
        # interval_seconds = 1 / 173 = 0.0057803468
        #
        # For a target duration:
        # cycles = target_duration_seconds / (pattern_length * interval_seconds)
        #
        # Example for ~30 minutes:
        # target_duration_seconds = 30 * 60 = 1800
        # pattern_length = 23
        # interval_seconds = 0.0057803468
        # cycles = 1800 / (23 * 0.0057803468) ≈ 13539
        #
        # Final planned values:
        # total_requests = 13539 * 23 = 311397
        # duration = 311397 * 0.0057803468 ≈ 1800 seconds ≈ 30 minutes
        # planned_rps ≈ 173 req/s
        "cycles": 15000,
        "interval_seconds": 0.005, # 0.00578

        "pattern": [
            "fast", "store_2k", "store_4k",
            "store_8k", "store_32k", "store_16k",
            "store_4k", "store_8k", "fast",
            "store_2k", "store_4k", "store_8k",
            "store_8k", "store_4k", "store_2k",
            "fast", "store_2k", "store_4k",
            "store_8k", "fast", "store_2k",
            "store_8k", "store_32k"
        ],

        "concurrency": 300,
        "timeout_seconds": 180,
    },
}



@dataclass(frozen=True)
class RequestDefinition:
    name: str
    method: str
    path: str
    body: Optional[str] = None
    body_size_bytes: int = 0


@dataclass(frozen=True)
class PlannedRequest:
    request_id: int
    definition: RequestDefinition
    scheduled_offset_s: float


@dataclass
class RequestResult:
    request_id: int
    timestamp: float
    scheduled_offset_s: float
    request_name: str
    method: str
    path: str
    status_code: int
    success: bool
    response_time_ms: float
    bytes_received: int
    pod_name: str = ""
    error: str = ""


@dataclass
class PrometheusSnapshot:
    count_by_pod: dict[str, float] = field(default_factory=dict)
    duration_sum_by_pod: dict[str, float] = field(default_factory=dict)


@dataclass
class MetricsSummary:
    total: int
    successful: int
    failed: int
    error_rate_percent: float
    wall_seconds: float
    throughput_rps: float
    avg_ms: float
    min_ms: float
    max_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    by_request: dict[str, int]
    by_pod_from_response: dict[str, int]
    errors: dict[str, int]


class TrafficPlanBuilder:
    @staticmethod
    def request_definition(name: str) -> RequestDefinition:
        if name not in REQUEST_TEMPLATES:
            raise ValueError(f"Unknown request template {name!r}. Available: {sorted(REQUEST_TEMPLATES)}")
        template = REQUEST_TEMPLATES[name]
        return RequestDefinition(
            name=name,
            method=str(template.get("method", "GET")).upper(),
            path=str(template["path"]),
            body=template.get("body"),
            body_size_bytes=int(template.get("body_size_bytes", 0) or 0),
        )

    @classmethod
    def build_paced_mix(
        cls,
        traffic_mix: dict[str, int],
        total_requests: int,
        duration_seconds: float,
        seed: int,
    ) -> list[PlannedRequest]:
        cls._validate_mix(traffic_mix)
        rng = random.Random(seed)

        names = list(traffic_mix.keys())
        weights = [traffic_mix[name] for name in names]
        counts = cls._exact_counts(total_requests, weights)

        selected_names: list[str] = []
        for name, count in zip(names, counts):
            selected_names.extend([name] * count)
        rng.shuffle(selected_names)

        interval = duration_seconds / float(total_requests)
        return [
            PlannedRequest(
                request_id=index + 1,
                definition=cls.request_definition(name),
                scheduled_offset_s=index * interval,
            )
            for index, name in enumerate(selected_names)
        ]

    @classmethod
    def build_lc_probe(
        cls,
        cycles: int,
        fast_per_heavy: int,
        heavy_template: str,
        fast_template: str,
        fast_interval_seconds: float,
        cycle_gap_seconds: float,
    ) -> list[PlannedRequest]:
        if cycles < 1:
            raise ValueError("cycles must be >= 1")
        if fast_per_heavy < 1:
            raise ValueError("fast_per_heavy must be >= 1")
        if fast_interval_seconds <= 0:
            raise ValueError("fast_interval_seconds must be > 0")
        if cycle_gap_seconds < 0:
            raise ValueError("cycle_gap_seconds must be >= 0")

        heavy = cls.request_definition(heavy_template)
        fast = cls.request_definition(fast_template)
        plan: list[PlannedRequest] = []
        request_id = 1
        cycle_spacing = fast_per_heavy * fast_interval_seconds + cycle_gap_seconds

        for cycle_index in range(cycles):
            cycle_start = cycle_index * cycle_spacing
            plan.append(PlannedRequest(request_id, heavy, cycle_start))
            request_id += 1
            for fast_index in range(fast_per_heavy):
                offset = cycle_start + ((fast_index + 1) * fast_interval_seconds)
                plan.append(PlannedRequest(request_id, fast, offset))
                request_id += 1
        return plan

    @classmethod
    def build_lc_wave(
        cls,
        cycles: int,
        slow_per_wave: int,
        slow_template: str,
        slow_interval_seconds: float,
        burst_start_after_seconds: float,
        burst_requests: int,
        burst_interval_seconds: float,
        burst_mix: dict[str, int],
        wave_interval_seconds: float,
        seed: int,
    ) -> list[PlannedRequest]:
        """Build a deterministic wave-shaped workload for LC experiments.

        One wave does this:
        1. opens several long-lived connections (e.g. large POST /store);
        2. waits briefly so those connections become active in IPVS;
        3. sends a burst of shorter requests while the long connections are open;
        4. starts the next wave before the previous long connections fully expire.

        This makes the ActiveConn signal visible and repeatable.
        """
        if cycles < 1:
            raise ValueError("cycles must be >= 1")
        if slow_per_wave < 1:
            raise ValueError("slow_per_wave must be >= 1")
        if slow_interval_seconds <= 0:
            raise ValueError("slow_interval_seconds must be > 0")
        if burst_start_after_seconds < 0:
            raise ValueError("burst_start_after_seconds must be >= 0")
        if burst_requests < 1:
            raise ValueError("burst_requests must be >= 1")
        if burst_interval_seconds <= 0:
            raise ValueError("burst_interval_seconds must be > 0")
        if wave_interval_seconds <= 0:
            raise ValueError("wave_interval_seconds must be > 0")
        cls._validate_mix(burst_mix)

        slow = cls.request_definition(slow_template)
        rng = random.Random(seed)
        plan: list[PlannedRequest] = []
        request_id = 1

        burst_names = list(burst_mix.keys())
        burst_weights = [burst_mix[name] for name in burst_names]

        for cycle_index in range(cycles):
            wave_start = cycle_index * wave_interval_seconds

            # Phase A: long requests that keep TCP connections active.
            for slow_index in range(slow_per_wave):
                plan.append(
                    PlannedRequest(
                        request_id=request_id,
                        definition=slow,
                        scheduled_offset_s=wave_start + slow_index * slow_interval_seconds,
                    )
                )
                request_id += 1

            # Phase B: deterministic burst while the long requests are still open.
            counts = cls._exact_counts(burst_requests, burst_weights)
            selected: list[str] = []
            for name, count in zip(burst_names, counts):
                selected.extend([name] * count)
            rng.shuffle(selected)

            burst_start = wave_start + burst_start_after_seconds
            for burst_index, name in enumerate(selected):
                plan.append(
                    PlannedRequest(
                        request_id=request_id,
                        definition=cls.request_definition(name),
                        scheduled_offset_s=burst_start + burst_index * burst_interval_seconds,
                    )
                )
                request_id += 1

        return sorted(plan, key=lambda item: (item.scheduled_offset_s, item.request_id))

    @classmethod
    def build_background_burst(
        cls,
        background_template: str,
        background_total_requests: int,
        background_duration_seconds: float,
        burst_start_after_seconds: float,
        burst_total_requests: int,
        burst_duration_seconds: float,
        burst_mix: dict[str, int],
        seed: int,
    ) -> list[PlannedRequest]:
        """Build a two-stream workload: long background holders + measured burst.

        Stream A keeps TCP connections open using a steady rate of heavier requests
        such as store_32k. Stream B starts later and sends the traffic that is
        used for comparing algorithms. The result is deterministic and is still
        a single client/run, but it behaves like two parallel traffic sources.
        """
        if background_total_requests < 1:
            raise ValueError("background_total_requests must be >= 1")
        if background_duration_seconds <= 0:
            raise ValueError("background_duration_seconds must be > 0")
        if burst_start_after_seconds < 0:
            raise ValueError("burst_start_after_seconds must be >= 0")
        if burst_total_requests < 1:
            raise ValueError("burst_total_requests must be >= 1")
        if burst_duration_seconds <= 0:
            raise ValueError("burst_duration_seconds must be > 0")
        cls._validate_mix(burst_mix)

        rng = random.Random(seed)
        plan: list[PlannedRequest] = []
        request_id = 1

        # Stream A: steady long-running background connections.
        background = cls.request_definition(background_template)
        background_interval = background_duration_seconds / float(background_total_requests)
        for index in range(background_total_requests):
            plan.append(
                PlannedRequest(
                    request_id=request_id,
                    definition=background,
                    scheduled_offset_s=index * background_interval,
                )
            )
            request_id += 1

        # Stream B: deterministic burst, mixed by configured percentages.
        burst_names = list(burst_mix.keys())
        burst_weights = [burst_mix[name] for name in burst_names]
        counts = cls._exact_counts(burst_total_requests, burst_weights)
        selected: list[str] = []
        for name, count in zip(burst_names, counts):
            selected.extend([name] * count)
        rng.shuffle(selected)

        burst_interval = burst_duration_seconds / float(burst_total_requests)
        for index, name in enumerate(selected):
            plan.append(
                PlannedRequest(
                    request_id=request_id,
                    definition=cls.request_definition(name),
                    scheduled_offset_s=burst_start_after_seconds + index * burst_interval,
                )
            )
            request_id += 1

        return sorted(plan, key=lambda item: (item.scheduled_offset_s, item.request_id))


    @classmethod
    def build_repeating_pattern(
        cls,
        cycles: int,
        interval_seconds: float,
        pattern: list[str],
    ) -> list[PlannedRequest]:
        """Build a deterministic repeating request pattern.

        This is useful for exposing differences between RR and LC. For a
        3-replica service, a pattern whose length is not a multiple of 3 keeps
        the expensive requests from landing at the same modulo position every
        cycle. Round Robin can therefore keep assigning heavy requests to the
        same backend, while LC should move away from the backend that already
        has active long connections.
        """
        if cycles < 1:
            raise ValueError("cycles must be >= 1")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        if not pattern:
            raise ValueError("pattern cannot be empty")
        for name in pattern:
            cls.request_definition(name)

        plan: list[PlannedRequest] = []
        request_id = 1
        for cycle_index in range(cycles):
            for pattern_index, name in enumerate(pattern):
                offset_index = cycle_index * len(pattern) + pattern_index
                plan.append(
                    PlannedRequest(
                        request_id=request_id,
                        definition=cls.request_definition(name),
                        scheduled_offset_s=offset_index * interval_seconds,
                    )
                )
                request_id += 1
        return plan

    @staticmethod
    def _validate_mix(traffic_mix: dict[str, int]) -> None:
        if not traffic_mix:
            raise ValueError("traffic_mix cannot be empty")
        unknown = [name for name in traffic_mix if name not in REQUEST_TEMPLATES]
        if unknown:
            raise ValueError(f"Unknown templates in traffic_mix: {unknown}. Available: {sorted(REQUEST_TEMPLATES)}")
        non_positive = [name for name, value in traffic_mix.items() if value <= 0]
        if non_positive:
            raise ValueError(f"traffic_mix values must be positive: {non_positive}")
        total = sum(traffic_mix.values())
        if total != 100:
            raise ValueError(f"traffic_mix must sum to 100, got {total}")

    @staticmethod
    def _exact_counts(total: int, weights: list[int]) -> list[int]:
        if total < 1:
            raise ValueError("total_requests must be >= 1")
        weight_sum = sum(weights)
        raw = [(total * weight) / weight_sum for weight in weights]
        counts = [math.floor(value) for value in raw]
        missing = total - sum(counts)
        remainders = sorted(((raw[i] - counts[i], i) for i in range(len(weights))), reverse=True)
        for _, index in remainders[:missing]:
            counts[index] += 1
        return counts


class PodinfoAsyncClient:
    def __init__(self, base_url: str, timeout_seconds: int, connection_close: bool, body_filler_char: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.connection_close = connection_close
        self.headers = {
            "User-Agent": "podinfo-lb-client-v2",
        }
        if connection_close:
            self.headers["Connection"] = "close"
        self.body_filler_char = body_filler_char or "a"
        self.body_cache: dict[int, bytes] = {}

    async def smoke_test(self) -> None:
        connector = aiohttp.TCPConnector(force_close=True, limit=1)
        async with aiohttp.ClientSession(connector=connector) as session:
            result = await self.send(session, PlannedRequest(0, TrafficPlanBuilder.request_definition("fast"), 0.0))
        if not result.success:
            raise RuntimeError(f"Smoke test failed: status={result.status_code}, error={result.error!r}")

    async def send(self, session: aiohttp.ClientSession, planned: PlannedRequest) -> RequestResult:
        definition = planned.definition
        url = self.base_url + definition.path
        headers = dict(self.headers)
        headers["X-LB-Request-Id"] = str(planned.request_id)
        body = self._resolve_body(definition)
        if body is not None:
            headers["Content-Type"] = "application/octet-stream"

        started = time.perf_counter()
        wall_time = time.time()
        try:
            async with session.request(
                definition.method,
                url,
                data=body,
                headers=headers,
                timeout=self.timeout,
            ) as response:
                raw = await response.read()
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                pod_name = self._extract_pod_name(raw, response.content_type)
                return RequestResult(
                    request_id=planned.request_id,
                    timestamp=wall_time,
                    scheduled_offset_s=planned.scheduled_offset_s,
                    request_name=definition.name,
                    method=definition.method,
                    path=definition.path,
                    status_code=response.status,
                    success=200 <= response.status < 400,
                    response_time_ms=elapsed_ms,
                    bytes_received=len(raw),
                    pod_name=pod_name,
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return RequestResult(
                request_id=planned.request_id,
                timestamp=wall_time,
                scheduled_offset_s=planned.scheduled_offset_s,
                request_name=definition.name,
                method=definition.method,
                path=definition.path,
                status_code=0,
                success=False,
                response_time_ms=elapsed_ms,
                bytes_received=0,
                error=type(exc).__name__ + (f": {exc}" if str(exc) else ""),
            )

    def _resolve_body(self, definition: RequestDefinition) -> Optional[bytes]:
        if definition.body is None:
            return None
        if definition.body == "auto":
            size = definition.body_size_bytes
            if size <= 0:
                return b""
            cached = self.body_cache.get(size)
            if cached is None:
                cached = (self.body_filler_char * size).encode("ascii")
                self.body_cache[size] = cached
            return cached
        return definition.body.encode("utf-8")

    @staticmethod
    def _extract_pod_name(raw: bytes, content_type: str) -> str:
        if not raw:
            return ""
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except (ValueError, json.JSONDecodeError):
            return ""
        if not isinstance(payload, dict):
            return ""
        for key in ("hostname", "pod_name", "pod"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return ""


class PrometheusClient:
    def __init__(self, base_url: str, namespace: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.namespace = namespace

    async def snapshot(self) -> PrometheusSnapshot:
        count_query = f'sum by(pod)(http_request_duration_seconds_count{{namespace="{self.namespace}"}})'
        sum_query = f'sum by(pod)(http_request_duration_seconds_sum{{namespace="{self.namespace}"}})'
        async with aiohttp.ClientSession() as session:
            count_by_pod = await self._instant_query(session, count_query)
            duration_sum_by_pod = await self._instant_query(session, sum_query)
        return PrometheusSnapshot(count_by_pod=count_by_pod, duration_sum_by_pod=duration_sum_by_pod)

    async def _instant_query(self, session: aiohttp.ClientSession, query: str) -> dict[str, float]:
        url = f"{self.base_url}/api/v1/query?query={quote_plus(query)}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as response:
            payload = await response.json()
        if payload.get("status") != "success":
            raise RuntimeError(f"Prometheus query failed: {payload}")
        values: dict[str, float] = {}
        for item in payload.get("data", {}).get("result", []):
            pod = item.get("metric", {}).get("pod", "")
            value = item.get("value", [None, "0"])[1]
            if pod:
                values[pod] = float(value)
        return values


def prometheus_delta(before: Optional[PrometheusSnapshot], after: Optional[PrometheusSnapshot]) -> dict[str, Any]:
    if before is None or after is None:
        return {}
    pods = sorted(set(before.count_by_pod) | set(after.count_by_pod) | set(before.duration_sum_by_pod) | set(after.duration_sum_by_pod))
    result: dict[str, Any] = {}
    for pod in pods:
        count_delta = after.count_by_pod.get(pod, 0.0) - before.count_by_pod.get(pod, 0.0)
        sum_delta = after.duration_sum_by_pod.get(pod, 0.0) - before.duration_sum_by_pod.get(pod, 0.0)
        avg_ms = (sum_delta / count_delta * 1000.0) if count_delta > 0 else 0.0
        result[pod] = {
            "requests": round(count_delta, 3),
            "processing_seconds": round(sum_delta, 3),
            "avg_processing_ms": round(avg_ms, 3),
        }
    return result


class LoadRunner:
    def __init__(
        self,
        client: PodinfoAsyncClient,
        plan: list[PlannedRequest],
        concurrency: int,
        progress_interval_seconds: int,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self.client = client
        self.plan = plan
        self.concurrency = concurrency
        self.progress_interval_seconds = progress_interval_seconds

    async def run(self) -> tuple[list[RequestResult], float]:
        connector = aiohttp.TCPConnector(limit=self.concurrency, force_close=self.client.connection_close)
        semaphore = asyncio.Semaphore(self.concurrency)
        results: list[RequestResult] = []

        async with aiohttp.ClientSession(connector=connector) as session:
            run_started_at = datetime.now()
            print(f"Timp start trimitere: {run_started_at.strftime('%H:%M:%S')}")
            started = time.perf_counter()
            next_report = started + self.progress_interval_seconds if self.progress_interval_seconds > 0 else float("inf")

            async def worker(planned: PlannedRequest) -> RequestResult:
                await self._sleep_until(started + planned.scheduled_offset_s)
                async with semaphore:
                    return await self.client.send(session, planned)

            tasks = [asyncio.create_task(worker(planned)) for planned in self.plan]
            for done in asyncio.as_completed(tasks):
                result = await done
                results.append(result)
                now = time.perf_counter()
                if now >= next_report:
                    self._print_progress(started, len(results), len(self.plan), results)
                    next_report = now + self.progress_interval_seconds
            wall_seconds = time.perf_counter() - started
            run_finished_at = datetime.now()
            print(f"Timp final trimitere: {run_finished_at.strftime('%H:%M:%S')}")

        return results, wall_seconds

    @staticmethod
    async def _sleep_until(absolute_time: float) -> None:
        delay = absolute_time - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)

    @staticmethod
    def _print_progress(started: float, completed: int, total: int, results: list[RequestResult]) -> None:
        elapsed = time.perf_counter() - started
        ok = sum(1 for item in results if item.success)
        failed = completed - ok
        rate = completed / elapsed if elapsed > 0 else 0.0
        print(f"progress: {completed}/{total} completed, ok={ok}, failed={failed}, elapsed={elapsed:.1f}s, rate={rate:.2f} req/s")


def compute_summary(results: list[RequestResult], wall_seconds: float) -> MetricsSummary:
    total = len(results)
    successful_results = [item for item in results if item.success]
    failed = total - len(successful_results)
    latencies = sorted(item.response_time_ms for item in successful_results)

    by_request: dict[str, int] = {}
    by_pod: dict[str, int] = {}
    errors: dict[str, int] = {}
    for item in results:
        by_request[item.request_name] = by_request.get(item.request_name, 0) + 1
        if item.pod_name:
            by_pod[item.pod_name] = by_pod.get(item.pod_name, 0) + 1
        if item.error:
            errors[item.error] = errors.get(item.error, 0) + 1

    return MetricsSummary(
        total=total,
        successful=len(successful_results),
        failed=failed,
        error_rate_percent=(failed / total * 100.0) if total else 0.0,
        wall_seconds=wall_seconds,
        throughput_rps=(total / wall_seconds) if wall_seconds > 0 else 0.0,
        avg_ms=(statistics.mean(latencies) if latencies else 0.0),
        min_ms=(latencies[0] if latencies else 0.0),
        max_ms=(latencies[-1] if latencies else 0.0),
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        by_request=dict(sorted(by_request.items())),
        by_pod_from_response=dict(sorted(by_pod.items())),
        errors=dict(sorted(errors.items(), key=lambda item: item[1], reverse=True)),
    )


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = round((pct / 100.0) * (len(sorted_values) - 1))
    return sorted_values[int(index)]


def print_configuration(args: argparse.Namespace, scenario: dict[str, Any], plan: list[PlannedRequest]) -> None:
    print("===== Podinfo LB client v2 configuration =====")
    print(f"algorithm label       = {args.algorithm}")
    print(f"scenario              = {args.scenario}")
    print(f"scenario kind         = {scenario['kind']}")
    print(f"base_url              = {args.base_url}")
    print(f"prometheus_url        = {args.prometheus_url if args.prometheus else '(disabled)'}")
    print(f"namespace             = {args.namespace}")
    print(f"requests              = {len(plan)}")
    print(f"concurrency           = {args.concurrency}")
    print(f"timeout_seconds       = {args.timeout_seconds}")
    print(f"random_seed           = {args.seed}")
    print(f"connection_close      = {not args.keepalive}")
    print(f"output_dir            = {args.output_dir}")

    if scenario["kind"] == "paced_mix":
        print("traffic_mix:")
        for name, pct in scenario["traffic_mix"].items():
            template = REQUEST_TEMPLATES[name]
            body_size = template.get("body_size_bytes", "-")
            print(f"  - {name:10} {template['method']:4} {template['path']:12} {pct:>3}% body={body_size}")
    elif scenario["kind"] == "lc_probe":
        print("lc_probe:")
        print(f"  cycles              = {scenario['cycles']}")
        print(f"  heavy_template      = {scenario['heavy_template']}")
        print(f"  fast_template       = {scenario['fast_template']}")
        print(f"  fast_per_heavy      = {scenario['fast_per_heavy']}")
        print(f"  fast_interval_s     = {scenario['fast_interval_seconds']}")
        print(f"  cycle_gap_s         = {scenario['cycle_gap_seconds']}")
    elif scenario["kind"] == "lc_wave":
        print("lc_wave:")
        print(f"  cycles              = {scenario['cycles']}")
        print(f"  slow_per_wave       = {scenario['slow_per_wave']}")
        print(f"  slow_template       = {scenario['slow_template']}")
        print(f"  slow_interval_s     = {scenario['slow_interval_seconds']}")
        print(f"  burst_start_after_s = {scenario['burst_start_after_seconds']}")
        print(f"  burst_requests      = {scenario['burst_requests']}")
        print(f"  burst_interval_s    = {scenario['burst_interval_seconds']}")
        print(f"  wave_interval_s     = {scenario['wave_interval_seconds']}")
        print("  burst_mix:")
        for name, pct in scenario["burst_mix"].items():
            template = REQUEST_TEMPLATES[name]
            body_size = template.get("body_size_bytes", "-")
            print(f"    - {name:10} {template['method']:4} {template['path']:12} {pct:>3}% body={body_size}")
    elif scenario["kind"] == "repeating_pattern":
        total_requests = int(scenario["cycles"]) * len(scenario["pattern"])
        approx_duration = total_requests * float(scenario["interval_seconds"])
        print("repeating_pattern:")
        print(f"  cycles              = {scenario['cycles']}")
        print(f"  pattern             = {scenario['pattern']}")
        print(f"  interval_s          = {scenario['interval_seconds']}")
        print(f"  requests            = {total_requests}")
        print(f"  approx_duration_s   = {approx_duration:.1f}")
        print("  note                = official traffic_logic: GET fast (light) + POST store (heavy)")
    elif scenario["kind"] == "background_burst":
        bg_rate = scenario["background_total_requests"] / scenario["background_duration_seconds"]
        est_active = 0.0
        print("background_burst:")
        print("  stream A = background connection holders")
        print(f"    template           = {scenario['background_template']}")
        print(f"    requests           = {scenario['background_total_requests']}")
        print(f"    duration_s         = {scenario['background_duration_seconds']}")
        print(f"    rate               = {bg_rate:.2f} req/s")
        if est_active:
            print(f"    estimated active   = ~{est_active:.0f} total connections")
        print("  stream B = measured burst")
        print(f"    start_after_s      = {scenario['burst_start_after_seconds']}")
        print(f"    requests           = {scenario['burst_total_requests']}")
        print(f"    duration_s         = {scenario['burst_duration_seconds']}")
        print(f"    rate               = {scenario['burst_total_requests'] / scenario['burst_duration_seconds']:.2f} req/s")
        print("    burst_mix:")
        for name, pct in scenario["burst_mix"].items():
            template = REQUEST_TEMPLATES[name]
            body_size = template.get("body_size_bytes", "-")
            print(f"      - {name:10} {template['method']:4} {template['path']:12} {pct:>3}% body={body_size}")

    print("first planned requests:")
    for planned in plan[: min(args.preview, len(plan))]:
        definition = planned.definition
        print(f"  #{planned.request_id:<5} t={planned.scheduled_offset_s:>8.3f}s {definition.method:4} {definition.path:12} ({definition.name})")


def print_summary(summary: MetricsSummary, prom_delta: dict[str, Any]) -> None:
    print("\n===== Client-side summary =====")
    print(f"total requests       = {summary.total}")
    print(f"successful           = {summary.successful}")
    print(f"failed               = {summary.failed}")
    print(f"error rate           = {summary.error_rate_percent:.2f}%")
    print(f"wall time            = {summary.wall_seconds:.2f}s")
    print(f"throughput           = {summary.throughput_rps:.2f} req/s")
    print(f"latency avg/min/max  = {summary.avg_ms:.2f}/{summary.min_ms:.2f}/{summary.max_ms:.2f} ms")
    print(f"latency p50/p95/p99  = {summary.p50_ms:.2f}/{summary.p95_ms:.2f}/{summary.p99_ms:.2f} ms")

    print("\nDistribution by request type:")
    for name, count in summary.by_request.items():
        print(f"  {name:14} {count}")

    if summary.by_pod_from_response:
        print("\nDistribution by pod extracted from JSON responses:")
        for pod, count in summary.by_pod_from_response.items():
            print(f"  {pod:45} {count}")
    else:
        print("\nNo pod hostname could be extracted from JSON responses (expected for store traffic).")

    if prom_delta:
        print("\nPrometheus delta by pod, authoritative for thesis figures:")
        print(f"  {'pod':45} {'requests':>10} {'proc_s':>12} {'avg_ms':>12}")
        for pod, values in prom_delta.items():
            print(f"  {pod:45} {values['requests']:>10.0f} {values['processing_seconds']:>12.3f} {values['avg_processing_ms']:>12.3f}")

    if summary.errors:
        print("\nErrors:")
        for error, count in list(summary.errors.items())[:10]:
            print(f"  {count:5} x {error}")


def write_outputs(
    output_dir: Path,
    run_id: str,
    args: argparse.Namespace,
    scenario: dict[str, Any],
    plan: list[PlannedRequest],
    results: list[RequestResult],
    summary: MetricsSummary,
    prom_delta: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{run_id}_requests.csv"
    json_path = output_dir / f"{run_id}_summary.json"
    plan_path = output_dir / f"{run_id}_plan.csv"

    with plan_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["request_id", "scheduled_offset_s", "name", "method", "path", "body_size_bytes"])
        writer.writeheader()
        for planned in plan:
            writer.writerow(
                {
                    "request_id": planned.request_id,
                    "scheduled_offset_s": f"{planned.scheduled_offset_s:.6f}",
                    "name": planned.definition.name,
                    "method": planned.definition.method,
                    "path": planned.definition.path,
                    "body_size_bytes": planned.definition.body_size_bytes,
                }
            )

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(results[0]).keys()) if results else ["request_id"])
        writer.writeheader()
        for result in sorted(results, key=lambda item: item.request_id):
            writer.writerow(asdict(result))

    payload = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "algorithm_label": args.algorithm,
        "scenario_name": args.scenario,
        "scenario": scenario,
        "base_url": args.base_url,
        "prometheus_enabled": args.prometheus,
        "prometheus_url": args.prometheus_url,
        "namespace": args.namespace,
        "connection_close": not args.keepalive,
        "seed": args.seed,
        "concurrency": args.concurrency,
        "timeout_seconds": args.timeout_seconds,
        "summary": asdict(summary),
        "prometheus_delta_by_pod": prom_delta,
        "outputs": {
            "plan_csv": str(plan_path),
            "requests_csv": str(csv_path),
            "summary_json": str(json_path),
        },
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print("\nOutputs written:")
    print(f"  plan    : {plan_path}")
    print(f"  requests: {csv_path}")
    print(f"  summary : {json_path}")


def resolve_scenario(args: argparse.Namespace) -> dict[str, Any]:
    scenario = dict(SCENARIOS[args.scenario])

    if scenario["kind"] == "paced_mix":
        if args.total_requests is not None:
            scenario["total_requests"] = args.total_requests
        if args.duration_seconds is not None:
            scenario["duration_seconds"] = args.duration_seconds
    else:
        if args.cycles is not None:
            scenario["cycles"] = args.cycles
        if args.fast_per_heavy is not None:
            scenario["fast_per_heavy"] = args.fast_per_heavy
        if args.fast_interval_seconds is not None:
            scenario["fast_interval_seconds"] = args.fast_interval_seconds

    if args.concurrency is None:
        args.concurrency = int(scenario["concurrency"])
    if args.timeout_seconds is None:
        args.timeout_seconds = int(scenario["timeout_seconds"])

    return scenario


def build_plan(args: argparse.Namespace, scenario: dict[str, Any]) -> list[PlannedRequest]:
    if scenario["kind"] == "paced_mix":
        return TrafficPlanBuilder.build_paced_mix(
            traffic_mix=scenario["traffic_mix"],
            total_requests=int(scenario["total_requests"]),
            duration_seconds=float(scenario["duration_seconds"]),
            seed=args.seed,
        )
    if scenario["kind"] == "lc_probe":
        return TrafficPlanBuilder.build_lc_probe(
            cycles=int(scenario["cycles"]),
            fast_per_heavy=int(scenario["fast_per_heavy"]),
            heavy_template=str(scenario["heavy_template"]),
            fast_template=str(scenario["fast_template"]),
            fast_interval_seconds=float(scenario["fast_interval_seconds"]),
            cycle_gap_seconds=float(scenario["cycle_gap_seconds"]),
        )
    if scenario["kind"] == "lc_wave":
        return TrafficPlanBuilder.build_lc_wave(
            cycles=int(scenario["cycles"]),
            slow_per_wave=int(scenario["slow_per_wave"]),
            slow_template=str(scenario["slow_template"]),
            slow_interval_seconds=float(scenario["slow_interval_seconds"]),
            burst_start_after_seconds=float(scenario["burst_start_after_seconds"]),
            burst_requests=int(scenario["burst_requests"]),
            burst_interval_seconds=float(scenario["burst_interval_seconds"]),
            burst_mix=dict(scenario["burst_mix"]),
            wave_interval_seconds=float(scenario["wave_interval_seconds"]),
            seed=args.seed,
        )
    if scenario["kind"] == "repeating_pattern":
        return TrafficPlanBuilder.build_repeating_pattern(
            cycles=int(scenario["cycles"]),
            interval_seconds=float(scenario["interval_seconds"]),
            pattern=list(scenario["pattern"]),
        )
    if scenario["kind"] == "background_burst":
        return TrafficPlanBuilder.build_background_burst(
            background_template=str(scenario["background_template"]),
            background_total_requests=int(scenario["background_total_requests"]),
            background_duration_seconds=float(scenario["background_duration_seconds"]),
            burst_start_after_seconds=float(scenario["burst_start_after_seconds"]),
            burst_total_requests=int(scenario["burst_total_requests"]),
            burst_duration_seconds=float(scenario["burst_duration_seconds"]),
            burst_mix=dict(scenario["burst_mix"]),
            seed=args.seed,
        )
    raise ValueError(f"Unsupported scenario kind: {scenario['kind']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic Podinfo load-test client for kube-proxy LB algorithms.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Podinfo NodePort base URL.")
    parser.add_argument("--prometheus-url", default=DEFAULT_PROMETHEUS_URL, help="Prometheus base URL.")
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE, help="Kubernetes namespace for Podinfo metrics.")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="traffic_logic", help="Traffic scenario to run. Default and official scenario: traffic_logic.")
    parser.add_argument("--algorithm", default="unknown", help="Label only: rr, wrr, lc, sh, sed, nq, etc.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for paced_mix scenarios.")
    parser.add_argument("--total-requests", type=int, default=None, help="Override total_requests for paced_mix scenarios.")
    parser.add_argument("--duration-seconds", type=float, default=None, help="Override duration_seconds for paced_mix scenarios.")
    parser.add_argument("--cycles", type=int, default=None, help="Override cycles for repeating_pattern / lc_probe.")
    parser.add_argument("--fast-per-heavy", type=int, default=None, help="Override fast requests per heavy request for lc_probe.")
    parser.add_argument("--fast-interval-seconds", type=float, default=None, help="Override fast request interval for lc_probe.")
    parser.add_argument("--concurrency", type=int, default=None, help="Max simultaneous requests. Defaults to scenario value.")
    parser.add_argument("--timeout-seconds", type=int, default=None, help="Per-request timeout. Defaults to scenario value.")
    parser.add_argument("--keepalive", action="store_true", help="Reuse TCP connections. Default is disabled; new connection per request.")
    parser.add_argument("--no-prometheus", dest="prometheus", action="store_false", help="Disable Prometheus before/after deltas.")
    parser.set_defaults(prometheus=True)
    parser.add_argument("--smoke-test", dest="smoke_test", action="store_true", help="Enable initial GET / health check. Disabled by default for deterministic traffic_logic runs.")
    parser.add_argument("--no-smoke-test", dest="smoke_test", action="store_false", help="Skip initial GET / health check.")
    parser.set_defaults(smoke_test=False)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for CSV/JSON results.")
    parser.add_argument("--preview", type=int, default=25, help="How many planned requests to print before running.")
    parser.add_argument("--progress-interval-seconds", type=int, default=30, help="Progress print interval; 0 disables progress.")
    parser.add_argument("--body-filler-char", default="a", help="ASCII character used for generated POST bodies.")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    scenario = resolve_scenario(args)
    plan = build_plan(args, scenario)
    output_dir = Path(args.output_dir)
    run_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{args.algorithm}_{args.scenario}"

    print_configuration(args, scenario, plan)

    client = PodinfoAsyncClient(
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        connection_close=not args.keepalive,
        body_filler_char=args.body_filler_char,
    )

    if args.smoke_test:
        print("\nRunning smoke test GET / ...")
        await client.smoke_test()
        print("Smoke test OK.")

    prom_client: Optional[PrometheusClient] = None
    before_prom: Optional[PrometheusSnapshot] = None
    after_prom: Optional[PrometheusSnapshot] = None
    if args.prometheus:
        prom_client = PrometheusClient(args.prometheus_url, args.namespace)
        print("Taking Prometheus snapshot before run ...")
        before_prom = await prom_client.snapshot()

    print(f"\nSending {len(plan)} requests with concurrency={args.concurrency} ...")
    runner = LoadRunner(client, plan, args.concurrency, args.progress_interval_seconds)
    results, wall_seconds = await runner.run()

    if prom_client is not None:
        print("Taking Prometheus snapshot after run ...")
        after_prom = await prom_client.snapshot()

    summary = compute_summary(results, wall_seconds)
    prom_delta = prometheus_delta(before_prom, after_prom)
    print_summary(summary, prom_delta)
    write_outputs(output_dir, run_id, args, scenario, plan, results, summary, prom_delta)


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")


if __name__ == "__main__":
    main()
    print("Total time: ", time.time() - time_start)