"""Runtime Metrics Analyzer — Post-deployment monitoring and feedback loop.

Ingests application logs, detects anomalies (error rate spikes, latency
degradation), and triggers re-analysis when thresholds are exceeded.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ─── Configuration ────────────────────────────────────────────────────────

ERROR_RATE_THRESHOLD = 0.10     # 10% error rate triggers alert
LATENCY_SPIKE_FACTOR = 2.0     # 2x above baseline triggers alert
HEALTH_CHECK_TIMEOUT = 10      # seconds
WINDOW_SIZE = 100               # sliding window for metric calculation


# ─── Data Models ──────────────────────────────────────────────────────────

@dataclass(slots=True)
class MetricPoint:
    """A single metric observation."""
    timestamp: float
    status_code: int
    latency_ms: float
    error: bool = False


@dataclass(slots=True)
class AnomalyReport:
    """Detected anomaly in runtime metrics."""
    anomaly_type: str       # "error_rate_spike" | "latency_degradation" | "health_check_failed"
    severity: str           # "warning" | "critical"
    current_value: float
    threshold: float
    message: str
    timestamp: float = field(default_factory=time.time)
    should_reanalyze: bool = False


@dataclass(slots=True)
class RuntimeStatus:
    """Aggregated runtime health status."""
    is_healthy: bool
    deployment_url: str
    total_checks: int
    error_rate: float
    avg_latency_ms: float
    anomalies: list[AnomalyReport] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_healthy": self.is_healthy,
            "deployment_url": self.deployment_url,
            "total_checks": self.total_checks,
            "error_rate": round(self.error_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "anomalies": [
                {
                    "type": a.anomaly_type,
                    "severity": a.severity,
                    "current_value": round(a.current_value, 4),
                    "threshold": a.threshold,
                    "message": a.message,
                    "should_reanalyze": a.should_reanalyze,
                }
                for a in self.anomalies
            ],
        }


# ─── Metrics Analyzer ────────────────────────────────────────────────────

class MetricsAnalyzer:
    """Post-deployment runtime monitoring with anomaly detection.

    Performs health checks against the deployed URL, collects latency
    and error metrics, and detects anomalies using sliding-window analysis.
    """

    def __init__(self, deployment_url: str) -> None:
        self.deployment_url = deployment_url.rstrip("/")
        self._metrics: deque[MetricPoint] = deque(maxlen=WINDOW_SIZE)
        self._baseline_latency: float | None = None

    async def health_check(self) -> MetricPoint:
        """Perform a single health check against the deployed application."""
        start = time.monotonic()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self.deployment_url,
                    timeout=HEALTH_CHECK_TIMEOUT,
                    follow_redirects=True,
                )
                latency = (time.monotonic() - start) * 1000

                point = MetricPoint(
                    timestamp=time.time(),
                    status_code=resp.status_code,
                    latency_ms=latency,
                    error=resp.status_code >= 500,
                )

        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            point = MetricPoint(
                timestamp=time.time(),
                status_code=0,
                latency_ms=latency,
                error=True,
            )
            logger.warning("Health check failed for %s: %s", self.deployment_url, exc)

        self._metrics.append(point)
        return point

    def analyze(self) -> RuntimeStatus:
        """Analyze collected metrics and detect anomalies."""
        if not self._metrics:
            return RuntimeStatus(
                is_healthy=True,
                deployment_url=self.deployment_url,
                total_checks=0,
                error_rate=0.0,
                avg_latency_ms=0.0,
            )

        total = len(self._metrics)
        errors = sum(1 for m in self._metrics if m.error)
        error_rate = errors / total
        avg_latency = sum(m.latency_ms for m in self._metrics) / total

        # Set baseline from first batch of healthy checks
        if self._baseline_latency is None and total >= 5:
            healthy = [m for m in self._metrics if not m.error]
            if healthy:
                self._baseline_latency = sum(m.latency_ms for m in healthy) / len(healthy)

        # Detect anomalies
        anomalies: list[AnomalyReport] = []

        if error_rate > ERROR_RATE_THRESHOLD:
            anomalies.append(AnomalyReport(
                anomaly_type="error_rate_spike",
                severity="critical" if error_rate > 0.30 else "warning",
                current_value=error_rate,
                threshold=ERROR_RATE_THRESHOLD,
                message=f"Error rate {error_rate:.1%} exceeds threshold {ERROR_RATE_THRESHOLD:.1%}",
                should_reanalyze=error_rate > 0.30,
            ))

        if self._baseline_latency and avg_latency > self._baseline_latency * LATENCY_SPIKE_FACTOR:
            anomalies.append(AnomalyReport(
                anomaly_type="latency_degradation",
                severity="warning",
                current_value=avg_latency,
                threshold=self._baseline_latency * LATENCY_SPIKE_FACTOR,
                message=f"Avg latency {avg_latency:.0f}ms is {avg_latency/self._baseline_latency:.1f}x baseline",
            ))

        # Last check failed
        if self._metrics[-1].error:
            anomalies.append(AnomalyReport(
                anomaly_type="health_check_failed",
                severity="critical",
                current_value=self._metrics[-1].status_code,
                threshold=200,
                message=f"Last health check returned status {self._metrics[-1].status_code}",
                should_reanalyze=True,
            ))

        is_healthy = len([a for a in anomalies if a.severity == "critical"]) == 0

        return RuntimeStatus(
            is_healthy=is_healthy,
            deployment_url=self.deployment_url,
            total_checks=total,
            error_rate=error_rate,
            avg_latency_ms=avg_latency,
            anomalies=anomalies,
        )
