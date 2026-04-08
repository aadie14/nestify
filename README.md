# Nestify V2 - Autonomous DevSecOps Intelligence Platform

Nestify V2 is an autonomous DevSecOps platform that scans source code, builds graph-aware dependency intelligence, computes multi-factor risk scores, applies simulation-gated fixes, and deploys applications through a controlled remediation workflow.

Nestify V2 now runs as an always-on agentic platform. The 7 specialized agents are the primary execution engine for scanning, risk reasoning, remediation, deployment strategy, self-healing, monitoring, and learning.

## Latest Product Updates (April 2026)

- Decision-driven orchestration is now the primary execution model: actions are selected from current state, not a fixed linear phase chain.
- Analyze and Deploy paths are explicitly separated.
  - Analyze path is read-only and does not auto-deploy.
  - Autonomous Fix and Deploy path performs remediation with simulation-gated retries.
- Meta-agent loop now classifies failures (`missing_env`, `build_error`, `dependency_issue`, `infra_issue`, `unknown`) and adapts strategy per class.
- Retry policy is bounded and anti-repeat:
  - provider attempt caps,
  - duplicate-fix suppression,
  - strategy switching when repeated failures are detected.
- Deployment flow now favors high-signal operator feedback:
  - compressed decision-action-outcome feed,
  - duplicate/retry collapse,
  - reasoning-noise suppression in primary UI.
- Deployment fallback behavior is explicit:
  - cloud deploy attempts remain primary,
  - local preview fallback is clearly labeled when used.
- ZIP-only backend deploy automation can publish to a temporary private GitHub repository when `github_url` is not provided.
- Temporary GitHub publishing supports non-main default branches and existing-file SHA updates.
- Railway workspace-aware automation is supported via `RAILWAY_WORKSPACE_ID` when required by account policy.
- Manual remediation loop remains available: users can resubmit updated ZIP or GitHub URL and restart the full decision cycle.

## Current Workflow

1. Upload source (ZIP or GitHub URL).
2. Run analysis path:
  - stack and architecture profiling,
  - security/risk enrichment,
  - deployment intent and cost reasoning,
  - status/report generation for operator review.
3. Choose execution path:
  - Autonomous Fix and Deploy, or
  - Manual remediation and resubmission.
4. Autonomous path executes:
  - deploy attempt,
  - failure classification,
  - targeted remediation,
  - simulation validation gate,
  - bounded redeploy,
  - provider switch when strategy/provider cap requires.
5. If cloud deployment remains blocked, fallback messaging is explicit and local preview mode is reported as fallback.
6. Outcomes, fixes, provider attempts, and decision trace are persisted for explainability and learning.

## Architecture Snapshot

- Frontend (React + Vite + TypeScript + Framer Motion): Upload, Analysis, and Deployment views with compressed real-time execution feed.
- Realtime transport: WebSocket progress stream with polling fallback for status/report snapshots.
- Backend (FastAPI): project-centric endpoints for upload, status, reports, audit/PDF export, and autonomous deployment actions.
- Orchestration core: centralized decision engine in `app/core/execution_engine.py` with cycle-aware state memory and action policy.
- Agent layer: specialized roles for code intelligence, security, remediation, simulation validation, deployment execution, and learning curation.
- State contracts: failure classes, provider attempts, fixes applied, simulation validation status, and decision log are captured for traceability.
- Storage: SQLite by default for project state, findings, remediation events, and deployment outcomes.
- Delivery strategy: cloud-first deployment with bounded retries and explicit local fallback reporting.

For a full implementation-level breakdown, see `README_ARCHITECTURE.md`.

## 🤖 Agentic Intelligence Layer (New in V2)

Traditional deployment systems treat each deployment as an isolated event. Nestify treats deployments as learning opportunities: each outcome becomes reusable intelligence for future runs. The result is a system that gets smarter, cheaper, and more reliable over time.

### What You Get

- 💰 **30-40% cost reduction** - Automatic right-sizing can reduce typical over-allocation, often saving about $5-20/month per continuously running app.
- 🔧 **70%+ self-healing coverage** - Common deployment failures can be recovered automatically before escalation.
- 🧬 **Learning that compounds** - Historical deployment patterns improve future recommendations and proactive fixes.
- 🔍 **Transparent decisions** - Platform choices, remediation priorities, and optimization recommendations are returned with explicit reasoning.
- 🛡️ **Backward compatible by design** - Existing contracts remain stable, with additive `agentic_insights` only.

### Backward Compatibility Guarantee

- Existing endpoints are unchanged.
- Agentic features are additive, not replacing existing fields.
- If agentic processing fails, baseline pipeline behavior continues.
- Agentic orchestration is enabled by default and powers every deployment workflow.

### The Learning Loop: What Makes This Different

Traditional hosts such as Vercel, Railway, and Netlify are excellent deployment targets, but they do not natively operate as a cross-deployment intelligence loop for your full pipeline decisions.

- **After 10 deployments**: The system starts identifying strong framework/runtime patterns (for example, FastAPI vs Next.js deployment shape).
- **After 100 deployments**: Proactive recommendations become practical and specific, such as "87% of similar FastAPI apps needed `DATABASE_URL`; apply preemptively."
- **After 1,000 deployments**: Pattern confidence becomes high enough to materially improve first-attempt success and platform-fit accuracy.

Your deployments make the system smarter for everyone.

### Seven Specialized Agents

## 🚧 Current Implementation Status

We believe in transparency. Here is what is working now versus what is still being built:

### ✅ Working Now (Production Ready)

- Code Intelligence Analysis: graph-based framework detection, dependency analysis, and resource prediction.
- Security Enrichment: LLM-based exploit narratives and business-impact context.
- Platform Selection Logic: rule-driven provider matching with rationale.
- Multi-Provider Deployment: Vercel, Railway, and Netlify flows.
- Learning Metrics Endpoint: `/api/v1/learning/stats` with deployment and pattern trends.

### 🚧 In Development (Next 2 Weeks)

- Docker-Based Cost Optimization: heuristic estimation is active, with Docker-backed benchmark path now being integrated.
- Cross-Deployment Learning: vector-backed similarity works, tuning and confidence scoring are still improving.
- Self-Healing Deployment: bounded retry loop exists, deeper failure-specific remediations are in progress.
- Production Monitoring: health sampling works, richer metrics and recommendations are expanding.

### 📋 Planned Features

- Real-time post-deployment optimization suggestions.
- Multi-agent collaboration orchestration.
- Advanced failure pattern recognition.
- Cost forecasting at scale.

Why this matters: we prefer an honest status over demo-only claims. A feature is marked complete only when it is shipped and demonstrable.

## 📊 Metrics We Track

- Deployment success rate over time.
- Cost optimization savings (when benchmark coverage is available).
- Pattern database growth.
- Average deployment time.

[View current metrics at `/api/v1/learning/stats`]

#### Agent 1: Code Intelligence Analyst 🧠

Role: Deeply understands application architecture from code graph analysis.

- Analyzes graph structure to estimate resource requirements.
- Identifies service dependencies (databases, caches, external APIs).
- Scores deployment complexity from coupling and dependency depth.

Example output:
> "Detected: FastAPI API with PostgreSQL and Redis dependencies. Predicted resources: 512MB RAM, 0.5 vCPU. Deployment complexity: moderate due to startup dependency order."

Integration: Uses existing GraphBuilder output and intelligence modules.

#### Agent 2: Security Intelligence Expert 🔒

Role: Enriches security findings with exploitation scenarios and business context.

- Adds real-world exploit narratives to deterministic findings.
- Uses graph reachability to prioritize practical risk.
- Reorders remediation by business impact, not severity label alone.

Example output:
> "CRITICAL: JWT secret hardcoded in config. Exploitation: token forgery and auth bypass. Business impact: account takeover risk. Recommended action: immediate env extraction and rotation."

Differentiation: ⭐ Context-aware security reasoning beyond scanner output.

#### Agent 3: Cost Optimization Specialist 💰

Role: Finds minimum viable resources through benchmark-driven evaluation.

- Evaluates multiple resource tiers (256MB, 512MB, 1GB).
- Checks latency/success behavior against target thresholds.
- Recommends lowest-cost configuration that still meets SLA goals.

Example output:
> "Recommendation: 512MB RAM, 0.5 vCPU. Estimated monthly cost: $3.20 vs $6.40 default. Projected savings: 50%."

Differentiation: ⭐ Automated cost-aware right-sizing in deployment planning.

#### Agent 4: Platform Selection Strategist 🎯

Role: Chooses optimal deployment platform with explicit tradeoff reasoning.

- Matches app requirements to provider capabilities.
- Compares Vercel, Netlify, and Railway alternatives.
- Returns platform rationale with fallback options.

Example output:
> "Selected Railway: backend runtime fit, database-friendly flow, and better projected cost profile than generic backend alternatives for this workload."

Differentiation: ⭐ Platform-agnostic intelligent routing.

#### Agent 5: Self-Healing Deployment Engineer 🔧

Role: Executes deployments with autonomous recovery when failures occur.

- Performs multi-attempt deploy execution with bounded retries.
- Applies pattern-based fixes for common failure modes.
- Escalates only after autonomous recovery attempts are exhausted.

Example output:
> "Attempt 1 failed: missing runtime env. Applied fix and retried. Attempt 2 succeeded. Recovery pattern stored for future runs."

Differentiation: ⭐ Autonomous deployment recovery loop with learning.

#### Agent 6: Production Monitoring Analyst 📊

Role: Monitors early production health and recommends optimizations.

- Samples early runtime latency/error signals.
- Compares observed behavior with predicted allocation.
- Produces right-sizing and reliability recommendations.

Example output:
> "Early production sample: p95 latency within target, low error rate, no immediate optimization required."

Differentiation: ⭐ Post-deployment intelligence integrated into delivery lifecycle.

#### Agent 7: Knowledge Curation Engine 🧬

Role: Learns from deployment outcomes and serves pattern-based recommendations.

- Stores anonymized deployment patterns in vector search.
- Retrieves similar historical deployments for new runs.
- Recommends proactive actions based on successful precedents.

Example output:
> "Found high-confidence similar deployments. Applied proactive env and platform recommendations before deployment execution."

Differentiation: ⭐ Cross-deployment pattern intelligence.

⭐ = Not typically available as a built-in integrated workflow in single-provider hosting platforms.

### What You Get: Response Format

Legacy baseline response example:

```json
{
  "project_id": "abc123",
  "status": "deployed",
  "url": "https://your-app.vercel.app",
  "findings": []
}
```

Agentic-enhanced response (same fields + additive `agentic_insights`):

```json
{
  "project_id": "abc123",
  "status": "deployed",
  "url": "https://your-app.railway.app",
  "findings": [],
  "agentic_insights": {
    "code_profile": {
      "app_type": "backend",
      "framework": "fastapi",
      "runtime": "python",
      "deployment_complexity_score": 58
    },
    "security_reasoning": {
      "summary": "Findings enriched with exploit and business impact context"
    },
    "cost_optimization": {
      "provider": "railway",
      "recommended": {
        "config": {
          "memory_mb": 512,
          "cpu": 0.5
        },
        "monthly_cost_usd": 12.5
      }
    },
    "deployment_intelligence": {
      "chosen_platform": "railway",
      "rationale": "Capability fit + cost profile"
    },
    "self_healing_report": {
      "status": "success",
      "attempts": [
        {
          "attempt": 1,
          "provider": "railway",
          "status": "success"
        }
      ]
    },
    "production_insights": {
      "metrics": {
        "p95_ms": 140.2,
        "error_rate": 0.0
      }
    },
    "similar_deployments": [],
    "proactive_actions": [],
    "learning_recorded": true
  }
}
```

Field map:

- `code_profile`: Agent 1 understanding of architecture and complexity.
- `security_reasoning`: Agent 2 context around exploitability and impact.
- `platform_decision` equivalent: represented by `deployment_intelligence` from Agent 4.
- `cost_optimization`: Agent 3 benchmark and right-sizing recommendation.
- `self_healing`: represented by `self_healing_report` from Agent 5.
- `production_monitoring`: represented by `production_insights` from Agent 6.
- `learning_context`: represented by `similar_deployments` and `proactive_actions` from Agent 7.

### Performance & Cost Impact

Always-on agentic orchestration adds deliberate reasoning and planning overhead.

- ⏱️ **Pipeline time impact**: about 30-90 seconds depending on analysis depth.
  - Agent reasoning: typically 10-20s
  - Cost/benchmark path: up to ~60s
  - Pattern lookup: usually a few seconds
- 💵 **LLM API cost**: commonly about $0.02-0.05 per deployment.
- 💰 **Potential savings**: often $5-20/month per app from better sizing/platform fit.

Net result: paying roughly $0.03 per deployment for agentic reasoning can produce meaningful annual infrastructure savings for long-lived apps.

### Quick Start: Always-On Agentic Pipeline

Prerequisites:

```bash
# Required
Python 3.10+

# Recommended for optimization/simulation paths
Docker installed and running

# LLM provider keys (priority order)
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=...
GEMINI_API_KEY=...
```

Default behavior

```bash
# .env
AGENTIC_MODE_ENABLED=true
ANTHROPIC_API_KEY=sk-ant-your-key-here

# restart Nestify
python -m uvicorn app.main:app --reload
```

All uploads and imports execute through the agentic pipeline automatically.

### Sample Inputs For Quick Testing

Local ZIP fixtures are included in this repo:

- `sample_inputs/fastapi_todo_api.zip`
  - Expected result: clean analysis and successful deployment recommendation.
- `sample_inputs/broken_node_api.zip`
  - Expected result: deployment/runtime issue surfaced with plain-English fix suggestion (missing `DATABASE_URL`).

Public GitHub samples (paste directly in Upload -> GitHub Link):

- `https://github.com/tiangolo/fastapi`
- `https://github.com/vercel/next.js`
- `https://github.com/expressjs/express`

Quick validation flow:

1. Upload `sample_inputs/fastapi_todo_api.zip`.
2. Confirm agent feed, debate timeline, and deployment recommendation are visible.
3. Upload `sample_inputs/broken_node_api.zip`.
4. Confirm the control room shows a human-readable failure reason and recovery guidance.

What to expect on first deployment:

- Pipeline may take longer than baseline due to additional reasoning.
- Progress updates stream through WebSocket and status polling.
- Completed runs expose additive `project.agentic_insights`.

Progressive timeline:

- After ~10 deployments: clearer framework/platform patterning.
- After ~100 deployments: stronger proactive recommendations.
- After ~1,000 deployments: higher-confidence platform and remediation decisions.

Learning progress check:

```bash
# per-project learning context
GET /api/status/{project_id}

# aggregate learning metrics
GET /api/v1/learning/stats
```

## Core Nestify V2 Features

## What Is New In V2

- Graph-aware code intelligence with AST parsing and dependency edges.
- Multi-factor risk scoring (not simple severity subtraction).
- Simulation-gated fix application (syntax, lint, tests in sandbox).
- Impact analysis before patching.
- User choice after audit:
  - manual remediation by user
  - auto-fix and redeploy by Nestify
- Runtime deployment fallback for static apps to local preview URLs when provider deployment fails.

## Core Architecture

### Intelligence Layer

- `app/intelligence/graph_builder.py`
  - Builds `CodeGraph` from Python AST.
  - Node types: File, Function, Class, Import.
  - Edge types: CONTAINS, CALLS, IMPORTS, DEPENDS_ON, INHERITS.
- `app/intelligence/risk_engine.py`
  - Computes per-finding risk from:
    - exploitability
    - impact
    - reachability
    - sensitivity
- `app/intelligence/embeddings.py`
  - Embedding generation with LLM-first flow and TF-IDF/hash fallback.
- `app/intelligence/summarizer.py`
  - Summarizes modules/classes/functions with LLM and deterministic fallback.

### Agents

- `SecurityAgent`
  - Runs deterministic scan + optional LLM enrichment.
  - Uses graph context and risk engine for scoring.
- `ImpactAgent`
  - Traverses graph to estimate blast radius.
- `SimulationAgent`
  - Applies proposed patches in sandbox copy.
  - Runs syntax, lint, and tests before approval.
- `FixAgent`
  - Generates fixes.
  - Requires impact and simulation pass before file writes.
- `DeploymentAgent`
  - Routes static/backend/dockerized apps to provider targets.
  - Supports local static preview fallback.

### Orchestration

- `app/core/orchestrator.py` uses a finite state machine:
  - IDLE -> SCANNING -> ANALYZING -> IMPACT_ANALYSIS -> SIMULATION -> FIXING -> DEPLOYING -> MONITORING
- State transitions emit WebSocket progress events.
- Project state is persisted for resumability.

## Storage and Integrations

- Graph storage: `app/storage/neo4j_client.py`
  - Falls back to in-memory graph when Neo4j is unavailable.
- Vector storage: `app/storage/qdrant_client.py`
  - Falls back to in-memory vector index when Qdrant is unavailable.
- Metadata backend: `app/storage/postgres_client.py`
  - Falls back to SQLite backend when Postgres is unavailable.
- GitHub integration: `app/integrations/github.py`
  - Webhook verification/parsing.
  - PR file inspection and comment workflows.

## User Remediation Decision Flow

After scan completion, users can choose:

- Manual remediation:
  - Keep findings and apply changes manually.
- Auto-fix and redeploy:
  - Nestify applies safe fixes.
  - Reruns scan on updated code.
  - Attempts deployment again.
  - Returns a live URL when deployment succeeds.

Relevant API endpoints:

- `POST /api/fix/{project_id}/defer`
- `POST /api/fix/{project_id}/auto-apply-deploy`

## Deployment Behavior

- Static apps: Vercel/Netlify preferred if configured.
- Backend apps: Railway based on provider credentials.
- Static fallback:
  - If external provider deploy fails, Nestify can publish local preview URL:
  - `http://127.0.0.1:8000/preview/{project_id}`

## API Surface (Primary)

- Upload and pipeline
  - `POST /api/upload/`
  - `GET /api/status/{project_id}`
- Risk and graph
  - `GET /api/v1/risk/{project_id}`
  - `GET /api/v1/graph/{project_id}`
- GitHub webhook
  - `POST /api/v1/webhook/github`
- Health
  - `GET /api/health`

## Project Layout

```text
app/
  agents/
  api/v1/
  core/
  database/
  intelligence/
  integrations/
  routes/
  runtime/
  services/
  storage/
  utils/
frontend/
```

## Quick Start

### Prerequisites

- Python 3.10+
- At least one LLM key:
  - `GROQ_API_KEY` or `GEMINI_API_KEY`
- Optional deployment keys:
  - `VERCEL_TOKEN`, `NETLIFY_API_TOKEN`, `RAILWAY_API_KEY`

### Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Run

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Open

- App: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/api/health`
- Docs: `http://127.0.0.1:8000/docs`

## Architecture

```text
┌───────────────────────────────────────────────────────────┐
│          Unified Agentic Execution Engine (Always On)    │
│  1) Code Intelligence  2) Security Intelligence          │
│  3) Cost Optimization  4) Platform Strategy              │
│  5) Self-Healing Deploy 6) Production Monitoring         │
│  7) Knowledge Curation & Learning                        │
└───────────────────────────────┬───────────────────────────┘
                                │ powers end-to-end pipeline
                                ↓
┌───────────────────────────────────────────────────────────┐
│  Scan → Analyze → Fix → Deploy → Monitor                │
│  With explicit reasoning, debate trace, and learning     │
└───────────────────────────────┬───────────────────────────┘
                                │ persists telemetry and graph context
                                ↓
┌───────────────────────────────────────────────────────────┐
│  Storage: Neo4j • Qdrant • PostgreSQL/SQLite fallback   │
└───────────────────────────────────────────────────────────┘
```

Technical stack:

- Agent Framework: CrewAI 0.28+
- Primary LLM: Claude 3.5 Sonnet (Anthropic)
- Fallback LLMs: Groq, Gemini (existing)
- Container Runtime: Docker (isolated user code execution)
- Vector Store: Qdrant (pattern matching)
- Graph Database: Neo4j (code structure)
- Metadata: PostgreSQL (deployment records)

Integration points:

- Agentic agents hook into existing state machine transitions.
- Existing agents are enhanced, not replaced.
- Existing storage infrastructure is reused.
- API response shape remains backward compatible.

## Configuration

Agentic system (new):

```env
AGENTIC_MODE_ENABLED=true
AGENTIC_LEARNING_ENABLED=true
ANTHROPIC_API_KEY=
```

Docker isolation (new):

```env
DOCKER_MAX_MEMORY=1g
DOCKER_MAX_CPU=1.0
DOCKER_TIMEOUT=300
```

Cost optimization (new):

```env
LOAD_TEST_DURATION=60
LOAD_TEST_RPS=100
```

Production monitoring (new):

```env
MONITOR_DURATION_HOURS=24
OPTIMIZATION_THRESHOLD=0.6
```

Existing configuration (kept as-is):

```env
# LLM
GROQ_API_KEY=
GEMINI_API_KEY=

# Deployment providers
VERCEL_TOKEN=
NETLIFY_API_TOKEN=
RAILWAY_API_KEY=

# Graph and vector stores
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=
QDRANT_HOST=localhost
QDRANT_PORT=6333

# Metadata backend
POSTGRES_DSN=

# GitHub
GITHUB_TOKEN=
GITHUB_WEBHOOK_SECRET=
GITHUB_APP_ID=
GITHUB_PRIVATE_KEY=

# Security policy
NESTIFY_SECURITY_THRESHOLD=70
NESTIFY_ENFORCE_SECURITY_THRESHOLD=false
```

## Frequently Asked Questions

**Q: Will always-on agentic execution break my existing deployments?**  
A: No. Existing endpoints remain stable, and failures still degrade safely with explicit status and logs.

**Q: How much does always-on agentic execution cost?**  
A: Typical additional LLM cost is around $0.02-0.05 per deployment. For long-lived apps, optimization can offset this with lower monthly runtime costs.

**Q: Does the learning system store my source code?**  
A: No. The learning layer is designed around deployment metadata and pattern context, not raw source persistence.

**Q: Can I disable specific agents?**  
A: Not yet. The platform runs as a coordinated 7-agent system by default. Per-agent controls are planned.

**Q: What if I do not have Claude API access?**  
A: The system automatically falls back to Groq or Gemini based on availability.

**Q: Is agentic execution required?**  
A: Yes. Nestify V2 now uses always-on agentic orchestration as the primary pipeline.

## Roadmap

Coming soon:

- 🎯 Agent-specific controls.
- 📊 Learning analytics dashboard.
- 💬 Deployment chat interface for decision review.
- 🔄 Auto-optimization execution with policy guardrails.
- 🌐 Region-aware deployment recommendations.
- 📈 Cost forecasting at larger traffic scales.

Research directions:

- Deployment-pattern-tuned routing to reduce LLM cost.
- Privacy-preserving federated learning between instances.
- Predictive scaling suggestions from traffic behavior.

## Contributing

Always-on agentic learning contributes anonymized signals that improve:

- Pattern recognition across frameworks/providers.
- Cost recommendation quality.
- Self-healing fix coverage.
- Platform selection confidence.

Feedback and support:

- Report issues: [GitHub Issues]
- Suggest improvements: [Discussions]
- API Reference: `http://127.0.0.1:8000/docs`
- Documentation: [Full docs]
- Community: [Discord/Forum]

## Notes

- If external providers are unavailable, static projects can still become live through local preview fallback.
- Auto-fix is intentionally conservative; complex auth/database/security logic is left for manual review.
- Agentic insights are additive and surfaced in status response under `project.agentic_insights`.
