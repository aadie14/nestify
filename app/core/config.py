"""Runtime configuration for the Nestify V2 DevSecOps platform."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    """Central configuration loaded from environment variables."""

    # ── Server ────────────────────────────────────────────────────────
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    log_level: str = os.getenv("NESTIFY_LOG_LEVEL", "INFO").upper()

    # ── Agent Behavior ────────────────────────────────────────────────
    allow_fix_agent_llm: bool = os.getenv("NESTIFY_ENABLE_LLM_FIXES", "true").lower() == "true"
    security_score_threshold: int = int(os.getenv("NESTIFY_SECURITY_THRESHOLD", "70"))
    enforce_security_threshold: bool = os.getenv("NESTIFY_ENFORCE_SECURITY_THRESHOLD", "false").lower() == "true"

    # ── LLM Provider Keys ────────────────────────────────────────────
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")

    # ── Agentic Intelligence Layer ───────────────────────────────────
    agentic_mode_enabled: bool = os.getenv("AGENTIC_MODE_ENABLED", "true").lower() == "true"
    agentic_learning_enabled: bool = os.getenv("AGENTIC_LEARNING_ENABLED", "true").lower() == "true"
    agentic_opt_in_param: str = os.getenv("AGENTIC_OPT_IN_PARAM", "agentic")

    # ── Docker Isolation Limits ──────────────────────────────────────
    docker_max_memory: str = os.getenv("DOCKER_MAX_MEMORY", "1g")
    docker_max_cpu: float = float(os.getenv("DOCKER_MAX_CPU", "1.0"))
    docker_timeout_seconds: int = int(os.getenv("DOCKER_TIMEOUT", "300"))

    # ── Cost Optimization Defaults ───────────────────────────────────
    load_test_duration_seconds: int = int(os.getenv("LOAD_TEST_DURATION", "60"))
    load_test_target_rps: int = int(os.getenv("LOAD_TEST_RPS", "100"))
    load_test_enabled: bool = os.getenv("LOAD_TEST_ENABLED", "true").lower() == "true"

    # ── Monitoring Controls ───────────────────────────────────────────
    monitor_duration_hours: int = int(os.getenv("MONITOR_DURATION_HOURS", "24"))
    optimization_threshold: float = float(os.getenv("OPTIMIZATION_THRESHOLD", "0.6"))

    # ── Deployment Provider Keys ──────────────────────────────────────
    vercel_token: str = os.getenv("VERCEL_TOKEN", "")
    netlify_api_token: str = os.getenv("NETLIFY_API_TOKEN", "")
    render_api_key: str = os.getenv("RENDER_API_KEY", "")
    railway_api_key: str = os.getenv("RAILWAY_API_KEY", "")

    # ── Neo4j (Graph Database) ────────────────────────────────────────
    neo4j_uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user: str = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "nestify")

    # ── Qdrant (Vector Database) ──────────────────────────────────────
    qdrant_host: str = os.getenv("QDRANT_HOST", "localhost")
    qdrant_port: int = int(os.getenv("QDRANT_PORT", "6333"))

    # ── PostgreSQL (Production Metadata) ──────────────────────────────
    postgres_dsn: str = os.getenv("POSTGRES_DSN", "")

    # ── GitHub Integration ────────────────────────────────────────────
    github_webhook_secret: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    github_app_id: str = os.getenv("GITHUB_APP_ID", "")
    github_private_key: str = os.getenv("GITHUB_PRIVATE_KEY", "")

    # ── GCP / Cloud Run ───────────────────────────────────────────────
    gcp_enabled: bool = os.getenv("GCP_ENABLED", "false").lower() == "true"
    gcp_project_id: str = os.getenv("GCP_PROJECT_ID", "")
    gcp_region: str = os.getenv("GCP_REGION", "us-central1")
    # Base64-encoded service account JSON key (never log this value)
    gcp_service_account_json_base64: str = os.getenv("GCP_SERVICE_ACCOUNT_JSON_BASE64", "")
    # Cloud Run cost guardrails (demo-safe defaults)
    gcp_cloud_run_max_instances: int = int(os.getenv("GCP_CLOUD_RUN_MAX_INSTANCES", "1"))
    gcp_cloud_run_min_instances: int = int(os.getenv("GCP_CLOUD_RUN_MIN_INSTANCES", "0"))
    gcp_cloud_run_memory: str = os.getenv("GCP_CLOUD_RUN_MEMORY", "512Mi")
    gcp_cloud_run_cpu: str = os.getenv("GCP_CLOUD_RUN_CPU", "1")
    gcp_cloud_run_concurrency: int = int(os.getenv("GCP_CLOUD_RUN_CONCURRENCY", "80"))
    gcp_cloud_run_timeout: int = int(os.getenv("GCP_CLOUD_RUN_TIMEOUT", "60"))


def configure_logging(level: str) -> None:
    """Set up structured logging for the application."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


settings = Settings()