# AI Workflow — How AI Was Used in GridWatch

## Philosophy

AI (LLMs) are used in GridWatch in two categories:

1. **In the product itself**: Gemini Flash generates crew briefings
2. **In development**: Claude/Gemini assisted with code generation

The key principle: **AI for generation, not for core reasoning.** The fault detection
algorithms are deterministic graph traversal — this is the RIGHT choice because:

- Deterministic: same input always produces same output
- Explainable: every confidence penalty has a named reason
- Testable: 18 unit tests verify exact behavior
- Fast: in-memory BFS, no API call needed

## Where AI IS Used (In Product)

### Crew Briefing Generator (`services/ai_briefing.py`)

**Model**: Gemini 2.0 Flash
**Purpose**: Generate phone-readable fault briefing from structured incident data
**Cost**: ~$0.001 per briefing

**Why here**: Translating structured data (coordinates, pole counts, confidence reasons)
into a natural-language paragraph suitable for reading over the phone at 2 AM is
precisely what LLMs do well. It's additive — the system works perfectly without it
via template fallback.

**Prompt design**: Single-shot with structured context injection. No few-shot needed
because the output format is simple prose, not structured data.

**Failure mode**: If Gemini API is down, falls back to a formatted template.
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

2. **Code generation**: AI generated boilerplate (models, API routes, Docker config).
   All generated code was reviewed against the spec and tested.

3. **Algorithm design**: Topology inference (MST) and boundary detection (BFS)
   algorithms were designed from first principles, not generated. The pseudocode
   in the build spec was the starting point.

4. **Testing**: AI generated test scaffolding. Test assertions were verified manually
   against expected physical behavior.

## AI Usage Log

| Component | AI Used | AI Role | Verification |
|-----------|---------|---------|--------------|
| Topology inference | No | — | 18 unit tests |
| Boundary detection | No | — | 18 unit tests |
| Confidence scoring | No | — | 18 unit tests |
| Lifecycle FSM | No | — | 18 unit tests |
| Crew briefing | Yes (Gemini) | Generate prose from data | Template fallback |
| Boilerplate code | Yes (Claude) | Generate scaffolding | Manual review + tests |
| Documentation | Yes (Claude) | Draft structure | Manual editing |
