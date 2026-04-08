# Nestify Architecture and Delivery Guide (April 2026)

This document is an implementation-focused architecture guide for Nestify. It complements the main README and is intended for contributors, maintainers, and release engineers.

## 1. Product Intent

Nestify is an intelligent deployment system, not a log viewer and not a fixed script. The platform is designed to:

- Analyze source and runtime constraints.
- Decide the next best action from current state.
- Apply controlled remediation and validation.
- Deploy with adaptive strategy and bounded retries.
- Explain decisions in a concise, high-signal UI feed.

## 2. Core Design Principles

- Decision over pipeline: state-aware action selection replaces rigid phase chaining.
- Safety over speed: fixes are simulation-gated before deployment retries.
- Signal over noise: UI shows decisions, actions, and outcomes only.
- Bounded autonomy: no blind retries, no unbounded loops, no repeated strategy spam.
- Backward compatibility: API response shape remains additive where possible.

## 3. System Architecture

### 3.1 Frontend

- Stack: React + Vite + TypeScript + Framer Motion.
- Primary screens:
  - Upload
  - Analysis
  - Deployment
- Real-time updates:
  - WebSocket subscription for progress events
  - Polling fallback for status/report/deployment snapshots
- UX model:
  - Compressed agent feed
  - Summary-first side panels
  - Minimal high-signal controls

### 3.2 Backend

- Stack: FastAPI.
- Execution engine:
  - Central orchestration logic in `app/core/execution_engine.py`.
  - Meta-agent decision loop with cycle-aware state updates.
- API layer:
  - Project-centric endpoints under `/api/v1/projects/*`.
  - Upload, status, report, deployment, and audit report endpoints.
- Persistence:
  - SQLite default with project/deployment/fix logs.

### 3.3 Intelligence and Agent Layer

Primary roles:

- Meta-Agent: decides next action, classifies failures, adapts strategy.
- Code Analyzer: stack/dependency/entry-point understanding.
- Security Agent: vulnerability and risk enrichment.
- Fix Agent: applies conservative remediation.
- Simulation Agent: validates patch safety before deploy retries.
- Deployment Agent: executes provider deployment and reports actionable failure details.

## 4. Execution Model

### 4.1 Analyze Path (controlled)

Analyze path is intentionally constrained to avoid accidental deployment during analysis.

- Allowed outcomes:
  - stack/code/security/debate completion
  - status marked complete for handoff
- Explicitly excluded in analysis-only mode:
  - auto-fix execution
  - deployment actions

### 4.2 Autonomous Fix and Deploy Path

When user starts Autonomous Fix and Deploy:

1. Attempt deploy
2. Classify failure if unsuccessful
3. Trigger remediation based on failure class
4. Run simulation validation gate
5. Retry deploy
6. Switch provider if strategy exhausted or provider cap reached
7. Retry with new strategy
8. Fallback to local preview if cloud paths fail

## 5. Failure Intelligence

Failure classes currently used by decision logic:

- `missing_env`
- `build_error`
- `dependency_issue`
- `infra_issue`
- `unknown`

These classes drive action selection and prevent blind retries.

## 6. State and Memory Contracts

Execution context tracks at least:

- `failures[]`
- `fixes_applied[]`
- `providers_tried[]`
- `provider_attempts{}`
- `last_failure_type`
- `simulation_validated`
- `decision_log[]`

These fields are persisted into agentic insights for traceability.

## 7. UI Contracts

### 7.1 Agent Feed

Rendering rules:

- One-line blocks: `[emoji] Agent: short message`
- Max 5-7 visible messages
- Collapse retries into one summary line
- Suppress reasoning-only payloads
- Merge duplicate/looping events

### 7.2 Deployment View

Deploy page is structured into three blocks:

1. Status Header (current action, platform, confidence)
2. Live Execution Feed (compressed)
3. Summary Panel (platform rationale, risk chips, fix bullets)

Bottom actions:

- Autonomous Fix and Deploy
- Download Full Audit Report

## 8. Security and Repository Hygiene

Required safeguards before publishing code:

- Never commit `.env` or secret material.
- Never commit local databases (`*.db`, `*.sqlite*`).
- Never commit runtime snapshots (`app/project_sources/`, outputs, caches).
- Keep dependency artifacts and build outputs out of source control.
- Prefer private repository on first push.

## 9. API Surface (High-value)

- `POST /api/v1/projects/upload`
- `POST /api/v1/projects/github`
- `GET /api/v1/projects/{project_id}/status`
- `GET /api/v1/projects/{project_id}/report`
- `GET /api/v1/projects/{project_id}/report/audit`
- `GET /api/v1/projects/{project_id}/report/pdf`
- `POST /api/v1/projects/{project_id}/autonomous-fix-deploy`

## 10. Operational Checklist

Before release:

- Run frontend build successfully.
- Run backend syntax/compile checks.
- Verify no secret/runtime artifacts are staged.
- Confirm analysis and deploy flows produce concise feed output.
- Verify fallback path messaging is explicit and non-noisy.

## 11. Contributor Notes

When extending orchestration:

- Add new actions through decision policy, not linear phase injection.
- Keep each action idempotent and state-driven.
- Emit concise progress events designed for UI consumption.
- Preserve the decision-action-outcome contract.

When extending UI:

- Do not reintroduce raw logs into primary views.
- Keep high-signal feed constraints intact.
- Prefer calm defaults over decorative complexity.

## 12. Future Work

- Better automatic dependency remediation for Node lockfiles.
- Richer simulation confidence outputs in feed-safe format.
- Explicit "next action" recommendation in status header.
- Scenario-based integration tests for failure class routing.
