"""FastAPI application — Nestify V2 AI DevSecOps Autopilot."""

import os
import json
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import configure_logging, settings
from app.database import init_db
from app.routes import deploy, fix, scan, status, upload
from app.api.v1 import (
    agentic_routes as agentic_api,
    graph as graph_api,
    learning as learning_api,
    metrics as metrics_api,
    optimization as optimization_api,
    projects as projects_api,
    risk as risk_api,
    webhook as webhook_api,
)
from app.services.project_source_service import get_project_source_dir


# ─── Lifespan ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    init_db()
    print("""
  ╔═══════════════════════════════════════════════════════╗
  ║  🪺  NESTIFY V2 — AI DevSecOps Intelligence Platform ║
  ║  📡  http://localhost:8000                            ║
  ║  🔌  WebSocket: ws://localhost:8000/ws                ║
  ║  📊  Graph API: /api/v1/graph                         ║
  ║  🛡️  Risk API:  /api/v1/risk                          ║
  ║  🐙  Webhook:   /api/v1/webhook/github                ║
  ╚═══════════════════════════════════════════════════════╝
    """)
    try:
        yield
    finally:
        # Cleanup: close Neo4j connection if open
        try:
            from app.storage.neo4j_client import _client
            if _client:
                await _client.close()
        except Exception:
            pass


app = FastAPI(
    title="Nestify V2 AI DevSecOps Intelligence Platform",
    version="2.0.0",
    description=(
        "Production-grade autonomous DevSecOps system with graph-based code intelligence, "
        "multi-factor risk scoring, simulation-gated fixes, and intelligent deployment."
    ),
    lifespan=lifespan,
)

# ─── Middleware ───────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Legacy API Routes (backward compatible) ─────────────────────────────

app.include_router(upload.router, prefix="/api/upload", tags=["Upload"])
app.include_router(scan.router, prefix="/api/scan", tags=["Scan"])
app.include_router(fix.router, prefix="/api/fix", tags=["Fix"])
app.include_router(deploy.router, prefix="/api/deploy", tags=["Deploy"])
app.include_router(status.router, prefix="/api/status", tags=["Status"])

# ─── V2 API Routes ───────────────────────────────────────────────────────

app.include_router(graph_api.router, prefix="/api/v1/graph", tags=["Graph Intelligence"])
app.include_router(risk_api.router, prefix="/api/v1/risk", tags=["Risk Engine"])
app.include_router(learning_api.router, prefix="/api/v1/learning", tags=["Learning"])
app.include_router(optimization_api.router, prefix="/api/v1/optimization", tags=["Optimization"])
app.include_router(agentic_api.router, prefix="/api/v1/agentic", tags=["Agentic"])
app.include_router(projects_api.router, prefix="/api/v1/projects", tags=["Projects"])
app.include_router(metrics_api.router, prefix="/api/v1", tags=["Metrics"])
app.include_router(webhook_api.router, prefix="/api/v1/webhook", tags=["Webhooks"])

# Compatibility aliases for simplified endpoints.
app.include_router(graph_api.router, prefix="/graph", tags=["Graph Intelligence"])
app.include_router(risk_api.router, prefix="/risk", tags=["Risk Engine"])
app.include_router(learning_api.router, prefix="/learning", tags=["Learning"])
app.include_router(optimization_api.router, prefix="/optimization", tags=["Optimization"])
app.include_router(agentic_api.router, prefix="/agentic", tags=["Agentic"])
app.include_router(projects_api.router, prefix="/projects", tags=["Projects"])
app.include_router(metrics_api.router, prefix="", tags=["Metrics"])
app.include_router(webhook_api.router, prefix="/webhook", tags=["Webhooks"])


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    # Check Neo4j connectivity
    neo4j_status = "unknown"
    qdrant_status = "unknown"
    postgres_status = "unknown"
    try:
        from app.storage.neo4j_client import get_neo4j_client
        client = await get_neo4j_client()
        neo4j_status = "connected" if client.is_connected else "fallback (in-memory)"
    except Exception:
        neo4j_status = "fallback (in-memory)"

    try:
        from app.storage.qdrant_client import get_qdrant_client

        qdrant = await get_qdrant_client()
        qdrant_status = "connected" if qdrant.is_connected else "fallback (in-memory)"
    except Exception:
        qdrant_status = "fallback (in-memory)"

    try:
        from app.storage.postgres_client import get_postgres_client

        postgres = await get_postgres_client()
        postgres_status = "connected" if postgres.is_connected else "fallback (sqlite)"
    except Exception:
        postgres_status = "fallback (sqlite)"

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
        "services": {
            "neo4j": neo4j_status,
            "qdrant": qdrant_status,
            "postgres": postgres_status,
            "llm": "configured" if settings.anthropic_api_key or settings.groq_api_key or settings.gemini_api_key else "not configured",
            "github": "configured" if settings.github_token else "not configured",
        },
    }


@app.get("/api/v1/status")
async def pipeline_status():
    """Return available pipeline capabilities."""
    return {
        "version": "2.0.0",
        "pipeline": [
            "SCANNING", "ANALYZING", "IMPACT_ANALYSIS",
            "SIMULATION", "FIXING", "DEPLOYING", "MONITORING",
        ],
        "agents": [
            "SecurityAgent", "RiskEngine", "ImpactAgent",
            "SimulationAgent", "FixAgent", "DeploymentAgent",
        ],
        "intelligence": ["GraphBuilder", "RiskEngine", "SemanticSearch"],
        "integrations": ["GitHub"],
    }


# ─── WebSocket for Real-Time Progress ───────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    project_id = None
    last_sent_index = 0

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                msg = json.loads(data)
                if msg.get("type") == "subscribe" and msg.get("projectId"):
                    project_id = msg["projectId"]
                    last_sent_index = 0
                    from app.routes.upload import pipeline_progress
                    progress = pipeline_progress.get(project_id, [])
                    for p in progress:
                        await websocket.send_json(p)
                    last_sent_index = len(progress)
            except asyncio.TimeoutError:
                pass
            except json.JSONDecodeError:
                pass

            if project_id is not None:
                from app.routes.upload import pipeline_progress
                progress = pipeline_progress.get(project_id, [])
                for i in range(last_sent_index, len(progress)):
                    await websocket.send_json(progress[i])
                last_sent_index = len(progress)
    except WebSocketDisconnect:
        pass


# ─── Serve Frontend ─────────────────────────────────────────────────────

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
REACT_DIST_DIR = os.path.join(FRONTEND_DIR, "dist")

if os.path.isdir(os.path.join(FRONTEND_DIR, "css")):
    app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
if os.path.isdir(os.path.join(FRONTEND_DIR, "js")):
    app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")
if os.path.isdir(REACT_DIST_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(REACT_DIST_DIR, "assets")), name="assets")
    app.mount("/react/assets", StaticFiles(directory=os.path.join(REACT_DIST_DIR, "assets")), name="react-assets")


@app.get("/")
async def serve_frontend():
    """Serve the main frontend page."""
    react_index = os.path.join(REACT_DIST_DIR, "index.html")
    if os.path.isfile(react_index):
        with open(react_index, "r", encoding="utf-8") as handle:
            html = handle.read()
        # Route compiled asset URLs through the known-good /react/assets mount.
        html = html.replace('src="/assets/', 'src="/react/assets/')
        html = html.replace('href="/assets/', 'href="/react/assets/')
        return HTMLResponse(content=html)

    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"message": "Nestify V2 API is running. Frontend not found."}


@app.get("/react")
@app.get("/react/{path:path}")
async def serve_react_frontend(path: str = ""):
    """Serve compiled React app if available (additive route)."""
    react_index = os.path.join(REACT_DIST_DIR, "index.html")
    if os.path.isfile(react_index):
        with open(react_index, "r", encoding="utf-8") as handle:
            html = handle.read()
        html = html.replace('src="/assets/', 'src="/react/assets/')
        html = html.replace('href="/assets/', 'href="/react/assets/')
        return HTMLResponse(content=html)
    return {
        "message": "React frontend not built yet. Run frontend build to enable /react.",
        "hint": "From frontend/: npm install && npm run build",
    }


@app.get("/preview/{project_id}")
async def serve_preview_index(project_id: int):
    """Serve locally deployed static app entrypoint."""
    source_dir = Path(get_project_source_dir(project_id)) / "source"
    index_file = source_dir / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Preview index not found")
    return FileResponse(str(index_file))


@app.get("/preview/{project_id}/{asset_path:path}")
async def serve_preview_asset(project_id: int, asset_path: str):
    """Serve static preview assets for local fallback deployments."""
    source_dir = (Path(get_project_source_dir(project_id)) / "source").resolve()
    target = (source_dir / asset_path).resolve()
    if source_dir not in target.parents and target != source_dir:
        raise HTTPException(status_code=400, detail="Invalid preview asset path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Preview asset not found")
    return FileResponse(str(target))


@app.get("/{full_path:path}")
async def serve_spa_fallback(full_path: str):
    """Serve React index for client-side routes (for example /analysis/42)."""
    blocked_prefixes = (
        "api/",
        "docs",
        "openapi.json",
        "redoc",
        "ws",
        "css/",
        "js/",
        "assets/",
        "react/",
        "preview/",
    )
    if full_path.startswith(blocked_prefixes):
        raise HTTPException(status_code=404, detail="Not Found")

    react_index = os.path.join(REACT_DIST_DIR, "index.html")
    if os.path.isfile(react_index):
        with open(react_index, "r", encoding="utf-8") as handle:
            html = handle.read()
        html = html.replace('src="/assets/', 'src="/react/assets/')
        html = html.replace('href="/assets/', 'href="/react/assets/')
        return HTMLResponse(content=html)

    raise HTTPException(status_code=404, detail="Not Found")


# ─── Run: python -m uvicorn app.main:app --reload ────────────────────────
