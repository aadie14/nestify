"""Learning statistics API for agentic deployment patterns."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter

from app.database import list_deployment_patterns

router = APIRouter()


def _parse_created_at(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _extract_pattern(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    pattern = payload.get("pattern")
    return pattern if isinstance(pattern, dict) else {}


def _is_success_outcome(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"live", "success", "completed"}


@router.get("/stats")
async def get_learning_stats(limit: int = 5000) -> dict[str, Any]:
    """Return aggregate learning metrics from recorded deployment patterns."""

    rows = list_deployment_patterns(limit=max(1, min(limit, 20000)))

    now = datetime.utcnow()
    last_30_days = now - timedelta(days=30)

    outcome_counter: Counter[str] = Counter()
    platform_counter: Counter[str] = Counter()
    fix_counter: Counter[str] = Counter()
    failure_signal_counter: Counter[str] = Counter()
    by_day_counter: Counter[str] = Counter()
    proactive_actions_total = 0
    recent_count = 0
    patterns_with_attempt_data = 0
    first_attempt_successes = 0
    recovered_successes = 0

    for row in rows:
        outcome = str(row.get("outcome") or "unknown").lower()
        outcome_counter[outcome] += 1

        pattern = _extract_pattern(row.get("pattern_payload"))
        if pattern:
            platform = str(pattern.get("platform_choice") or "unknown").lower()
            platform_counter[platform] += 1

            fixes_applied = pattern.get("fixes_applied") or []
            proactive_actions_total += len(fixes_applied)
            for fix in fixes_applied:
                normalized_fix = str(fix).strip().lower()
                if normalized_fix:
                    fix_counter[normalized_fix] += 1

            attempts = pattern.get("deployment_attempts") or []
            if isinstance(attempts, list) and attempts:
                patterns_with_attempt_data += 1
                if _is_success_outcome(outcome):
                    if len(attempts) == 1:
                        first_attempt_successes += 1
                    elif len(attempts) > 1:
                        had_failure = any(
                            str(item.get("status") or "").lower() == "failed"
                            for item in attempts
                            if isinstance(item, dict)
                        )
                        if had_failure:
                            recovered_successes += 1

                for item in attempts:
                    if not isinstance(item, dict):
                        continue
                    error_text = str(item.get("error") or "").lower()
                    if "timeout" in error_text:
                        failure_signal_counter["timeout"] += 1
                    if "memory" in error_text or "resource" in error_text:
                        failure_signal_counter["resource_limits"] += 1
                    if "build" in error_text:
                        failure_signal_counter["build_failure"] += 1
                    if "env" in error_text or "environment" in error_text:
                        failure_signal_counter["env_misconfig"] += 1
                    if "port" in error_text:
                        failure_signal_counter["port_misconfig"] += 1

        created = _parse_created_at(row.get("created_at"))
        if created and created >= last_30_days:
            recent_count += 1
        if created and created >= (now - timedelta(days=14)):
            by_day_counter[created.strftime("%Y-%m-%d")] += 1

    total = len(rows)
    success = outcome_counter.get("live", 0) + outcome_counter.get("success", 0)
    success_rate = round((success / total), 4) if total else 0.0
    first_attempt_success_rate = (
        round(first_attempt_successes / patterns_with_attempt_data, 4)
        if patterns_with_attempt_data
        else 0.0
    )
    self_heal_recovery_rate = (
        round(recovered_successes / patterns_with_attempt_data, 4)
        if patterns_with_attempt_data
        else 0.0
    )

    top_platforms = [
        {"platform": name, "count": count}
        for name, count in platform_counter.most_common(5)
    ]
    top_fix_patterns = [
        {"action": name, "count": count}
        for name, count in fix_counter.most_common(8)
    ]
    top_failure_signals = [
        {"signal": name, "count": count}
        for name, count in failure_signal_counter.most_common(6)
    ]

    trend_last_14_days = [
        {"date": key, "patterns": by_day_counter[key]}
        for key in sorted(by_day_counter.keys())
    ]

    return {
        "total_patterns": total,
        "patterns_last_30_days": recent_count,
        "outcomes": dict(outcome_counter),
        "success_rate": success_rate,
        "first_attempt_success_rate": first_attempt_success_rate,
        "self_heal_recovery_rate": self_heal_recovery_rate,
        "patterns_with_attempt_data": patterns_with_attempt_data,
        "top_platforms": top_platforms,
        "top_fix_patterns": top_fix_patterns,
        "top_failure_signals": top_failure_signals,
        "trend_last_14_days": trend_last_14_days,
        "proactive_actions_recorded": proactive_actions_total,
        "note": "Learning stats are derived from anonymized deployment pattern records.",
    }
