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
- Backend deployment requires a valid GitHub repository URL.
- Qdrant and Neo4j have in-memory fallback modes for local development.
