# AI Workflow — How AI Was Used in GridWatch

## Philosophy

AI (LLMs) are used in GridWatch in two categories:

1. **In the product itself**: an optional local LLM endpoint generates crew
   briefings; the deployed app safely falls back to a deterministic template
2. **In development**: AI coding assistants (including Codex) assisted with
   code review, documentation, debugging, and targeted implementation work

The key principle: **AI for generation, not for core reasoning.** The fault detection
algorithms are deterministic graph traversal — this is the RIGHT choice because:

- Deterministic: same input always produces same output
- Explainable: every confidence penalty has a named reason
- Testable: 18 unit tests verify exact behavior
- Fast: in-memory BFS, no API call needed

## Where AI IS Used (In Product)

### Crew Briefing Generator (`services/ai_briefing.py`)

**Model**: Configurable local model (`phi3` by default) through an
Ollama-compatible `/api/generate` endpoint
**Purpose**: Generate phone-readable fault briefing from structured incident data
**Cost**: Depends on the local model host. The public deployment uses the
zero-cost template fallback because it does not provision a local LLM service.

**Why here**: Translating structured data (coordinates, pole counts, confidence reasons)
into a natural-language paragraph suitable for reading over the phone at 2 AM is
precisely what LLMs do well. It's additive — the system works perfectly without it
via template fallback.

**Prompt design**: Single-shot with structured context injection. No few-shot needed
because the output format is simple prose, not structured data.

**Failure mode**: If the local LLM endpoint is unavailable, it falls back to a formatted template.
The template contains all the same information, just less natural-sounding.

## Where AI is NOT Used (And Why)

### Fault Localization — NOT AI

The boundary-finding algorithm (BFS from DT root finding live→dark edges) is:
- Deterministic: no randomness, no temperature
- Explainable: "this edge was the boundary because parent was live, child was dark"
- Fast: O(n) in tree size, vs 500ms+ for an API call
- Testable: unit tests verify exact boundary detection

An LLM cannot reliably perform spatial reasoning on a tree of 80 nodes with
mixed live/dark states. It would hallucinate boundaries.

### Topology Inference — NOT AI

MST on GPS coordinates is the mathematically correct estimator for tree topology
given only node positions. An LLM cannot compute Kruskal's algorithm reliably.

### Confidence Scoring — NOT AI

5 multiplicative factors with named reasons. Fully deterministic. An LLM-based
scorer would be non-reproducible and unexplainable on a follow-up call.

## Development Workflow

1. **Spec analysis**: AI helped identify 12 critical gaps between initial plan and
   evaluation criteria (stale events, fw 1.2 silence, SSE vs WebSocket, etc.)

2. **Code generation and review**: AI assisted with boilerplate (models, API
   routes, Docker configuration) and with reviewing deployment integration.
   All generated or modified code was checked against the brief and tests.

3. **Algorithm design**: Topology inference (MST) and boundary detection (BFS)
   algorithms were designed from first principles, not generated. The pseudocode
   in the build spec was the starting point.

4. **Testing**: AI generated test scaffolding. Test assertions were verified manually
   against expected physical behavior. The 18 core engine tests were run in the
   backend container after the final deployment-related changes.

## Concrete Cases Where AI Output Needed Correction

1. **Render port handling**: A container command initially bound Uvicorn to
   port 8000. Render assigned port 10000, so the health check timed out. The
   correction was to read Render's `PORT` environment variable while retaining
   8000 as the local default.
2. **Distroless runtime suggestion**: A multi-stage image copied an Alpine
   virtual environment into a distroless Debian image. Render then interpreted
   `/opt/venv/bin/python` as a script through the distroless entrypoint. The
   fix was to use `python:3.13-slim` consistently for both build and runtime,
   and verify the built container starts its venv Python.
3. **Production SSE URL**: REST calls read `VITE_API_URL`, but the EventSource
   was hard-coded to `/api/events/stream`. That only worked through the local
   Vite proxy. It was corrected to use the same configured API base URL before
   deploying Vercel.

## Delegation Boundary

AI was used for scaffolding, explanation, and rapid review. The parts treated
as requiring human verification were the physical fault model, the live/dark
boundary invariants, topology assumptions, state transitions, public-deployment
configuration, and every claim in the submission documentation. Approximate
AI-assisted share of the final code and documentation is 60%; the shipped
behavior and written claims were reviewed against the repository and tests.

## Representative Prompts / Session Work

- "Inspect the Render deployment failure, identify whether it is the health
  endpoint, port binding, or database URL, then make the smallest verifiable
  fix."
- "Compare the frontend's production API and SSE paths with its local Vite
  proxy, then find anything that would fail after deployment on Vercel."
- "Read the assignment requirements and audit the repository documentation so
  it describes only implemented, tested, or explicitly unmeasured behavior."

## AI Usage Log

| Component | AI Used | AI Role | Verification |
|-----------|---------|---------|--------------|
| Topology inference | No | — | 18 unit tests |
| Boundary detection | No | — | 18 unit tests |
| Confidence scoring | No | — | 18 unit tests |
| Lifecycle FSM | No | — | 18 unit tests |
| Crew briefing | Yes (optional local LLM) | Generate prose from data | Template fallback |
| Boilerplate code | Yes (Claude) | Generate scaffolding | Manual review + tests |
| Documentation | Yes (Claude) | Draft structure | Manual editing |
