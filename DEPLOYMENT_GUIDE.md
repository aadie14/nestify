# Nestify V2 Deployment Guide

## Prerequisites

- Python 3.11+
- Node.js 18+
- SQLite (default) or PostgreSQL for scale
- Optional services for full intelligence mode:
  - Qdrant
  - Neo4j

## Backend Setup

1. Install dependencies

```bash
pip install -r requirements.txt
```

2. Configure environment variables

Create a `.env` file in the repo root:

```env
ANTHROPIC_API_KEY=
GROQ_API_KEY=
GEMINI_API_KEY=

RAILWAY_API_KEY=
RENDER_API_KEY=
VERCEL_TOKEN=
NETLIFY_API_TOKEN=

GITHUB_TOKEN=

QDRANT_HOST=localhost
QDRANT_PORT=6333
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=neo4j

AGENTIC_MODE_ENABLED=true
AGENTIC_LEARNING_ENABLED=true
```

3. Start API server

```bash
uvicorn app.main:app --reload --port 8000
```

## Frontend Setup

1. Install packages

```bash
cd frontend
npm install
```

2. Run dev server

```bash
npm run dev
```

3. Build production assets

```bash
npm run build
```

## Validation Commands

Run backend tests:

```bash
python -m unittest tests.test_agentic_coordinator -v
python -m unittest tests.test_self_healing_agent -v
python -m unittest tests.test_agentic_flow -v
```

## Feature Verification Checklist

1. Agent debate transcript appears in deployment view.
2. Agent reasoning cards stream during execution.
3. Cost comparison table renders with recommended tier.
4. PDF report download works from deployment page.
5. `/api/v1/metrics/learning-proof` returns trend metrics.
6. Railway backend deploy returns public URL when available.

## Operations Notes

- If no external provider keys are configured, static apps fall back to local preview deployment.
- Backend deployment requires a valid GitHub repository URL (or GITHUB_TOKEN for auto-publishing), unless using Cloud Run (which builds from local source).
- Qdrant and Neo4j have in-memory fallback modes for local development.
- Cloud Run deployments require gcloud and docker CLIs to be installed on the Nestify host.

## GCP Cloud Run Setup

Nestify supports deploying backend and Docker-based applications to Google Cloud Run. This is the preferred cloud provider when `deploy_intent=cloud` is selected.

### Prerequisites

- A GCP project with billing enabled
- Cloud Run API enabled: `gcloud services enable run.googleapis.com`
- Artifact Registry / Container Registry API enabled: `gcloud services enable containerregistry.googleapis.com`
- A service account with the following IAM roles:
  - `roles/run.admin`
  - `roles/storage.admin`
  - `roles/iam.serviceAccountUser`
- `gcloud` CLI installed on the host running Nestify
- `docker` CLI installed on the host running Nestify
- Your project source must contain a `Dockerfile`

### Environment Variables

Add these to your `.env` file alongside the existing provider keys:

```env
# GCP / Cloud Run
GCP_ENABLED=true
GCP_PROJECT_ID=your-gcp-project-id
GCP_REGION=us-central1

# Base64-encoded service account JSON key (never commit this value)
# Generate with: base64 -i your-service-account-key.json | tr -d '\n'
GCP_SERVICE_ACCOUNT_JSON_BASE64=

# Demo-safe cost guardrails (these are the hard defaults)
GCP_CLOUD_RUN_MAX_INSTANCES=1
GCP_CLOUD_RUN_MIN_INSTANCES=0
GCP_CLOUD_RUN_MEMORY=512Mi
GCP_CLOUD_RUN_CPU=1
GCP_CLOUD_RUN_CONCURRENCY=80
GCP_CLOUD_RUN_TIMEOUT=60
```

### Cost Guardrails

The following defaults keep Cloud Run in the free/low-cost tier for demo workloads:

| Setting | Default | Max enforced by Nestify |
|---|---|---|
| max-instances | 1 | 5 |
| min-instances | 0 (scale-to-zero) | 1 |
| memory | 512Mi | — |
| cpu | 1 | — |
| concurrency | 80 | 200 |
| timeout | 60s | 60s |

Always set up [Cloud Billing budget alerts](https://cloud.google.com/billing/docs/how-to/budgets) on your GCP project to catch unexpected spend.

### Deploy Intent

The `deploy_intent` field controls how Nestify selects a provider:

| Value | Behavior |
|---|---|
| `auto` | Default routing: Cloud Run for docker/dockerized apps, Railway for other backend apps, Vercel/Netlify for static |
| `cloud` | Attempt Cloud Run first; fall back to Railway if no Dockerfile or GCP not configured |
| `local` | Skip all cloud providers; use local preview URL |

### Security Notes

- The `GCP_SERVICE_ACCOUNT_JSON_BASE64` value is **never logged** by Nestify
- The decoded key file is written to a temporary path under `/tmp` and deleted immediately after authentication
- Use the principle of least privilege: grant only the IAM roles listed above


