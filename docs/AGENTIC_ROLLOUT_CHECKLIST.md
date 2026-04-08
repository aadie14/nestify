# Agentic Rollout Checklist

Use this checklist to safely roll out the agentic layer while preserving baseline Nestify behavior.

## 1. Pre-Deployment Gates

- [ ] Baseline pipeline smoke test passes (`agentic=false`).
- [ ] Agentic pipeline smoke test passes (`agentic=true`).
- [ ] `/api/status/{project_id}` includes additive `project.agentic_insights` only for agentic runs.
- [ ] `python -m compileall app` passes.
- [ ] Unit tests pass (`python -m unittest discover -s tests -p "test_*.py" -v`).

## 2. Feature Flag Rollout

- [ ] Keep `AGENTIC_MODE_ENABLED=false` initially in production.
- [ ] Enable agentic per request for internal users only (`/api/upload/?agentic=true`).
- [ ] Roll out by cohorts:
  - [ ] 5% internal traffic
  - [ ] 20% beta users
  - [ ] 50% mixed traffic
  - [ ] 100% eligible traffic
- [ ] Keep immediate rollback path: set `AGENTIC_MODE_ENABLED=false`.

## 3. Observability and SLOs

- [ ] Track these counters by mode (`agentic=false/true`):
  - [ ] upload requests
  - [ ] pipeline completions
  - [ ] pipeline failures
  - [ ] deployment attempts
  - [ ] deployment successes
- [ ] Track latency impact:
  - [ ] baseline pipeline duration
  - [ ] agentic pipeline duration
  - [ ] additional agentic overhead target < 30s
- [ ] Track self-healing performance:
  - [ ] failures auto-recovered
  - [ ] failures escalated
  - [ ] average retry count

## 4. Cost Guardrails

- [ ] Ensure `ANTHROPIC_API_KEY` and fallback keys are configured.
- [ ] Monitor model usage in `token_usage` table daily.
- [ ] Configure spend alert thresholds (daily and weekly).
- [ ] Validate fallback behavior (Claude failure -> Groq/Gemini).
- [ ] Enforce request budgets per tenant/project if multi-tenant.

## 5. Safety and Security Controls

- [ ] Confirm Docker isolation limits are set:
  - [ ] `DOCKER_MAX_MEMORY`
  - [ ] `DOCKER_MAX_CPU`
  - [ ] `DOCKER_TIMEOUT`
- [ ] Verify no privileged containers are used.
- [ ] Verify network isolation policy for user workload containers.
- [ ] Validate no raw user source code is stored in learning vectors.
- [ ] Validate learning opt-out behavior (`learning_opt_out`).

## 6. Learning Loop Quality

- [ ] Confirm pattern records are persisted after deployment completion.
- [ ] Confirm similarity recommendations are returned at DEPLOYING entry.
- [ ] Track learning effectiveness over time:
  - [ ] first-attempt deployment success rate
  - [ ] self-healing recovery rate
  - [ ] average cost per successful deployment

## 7. Operational Runbooks

- [ ] On-call runbook for agentic deployment failures.
- [ ] On-call runbook for LLM provider outages.
- [ ] On-call runbook for vector store outages (Qdrant fallback verification).
- [ ] Manual override process documented for forced non-agentic execution.

## 8. Acceptance Criteria

- [ ] Existing endpoint contracts unchanged.
- [ ] Agentic insights remain additive only.
- [ ] No increase in critical incident rate after rollout.
- [ ] Measured improvement after 100 deployments vs first 10:
  - [ ] higher first-attempt success
  - [ ] lower average cost
  - [ ] increased autonomous recovery rate
