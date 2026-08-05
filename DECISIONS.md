# Design Decisions — GridWatch

## D11: Split Deployment and Explicit API Base URL

**Decision**: Deploy the React/Vite console on Vercel and the FastAPI service
plus Postgres on Render. The Vercel build receives
`VITE_API_URL=https://gridwatch-api.onrender.com/api`.

**Why**: Vercel is a good fit for a static Vite build, while Render runs the
long-lived API, background workers, SSE stream, and managed Postgres. Keeping
the database private avoids exposing credentials to the browser.

**Important implementation detail**: Both REST requests and the SSE connection
use `VITE_API_URL`. A hard-coded `/api/events/stream` would work under the local
Vite proxy but would point to Vercel (and fail) in production.

**Tradeoff**: The free Render service spins down while idle, so the first API
request can be slow. This is documented in the README rather than hidden.

---

## D1: MST vs Clustering for Topology Inference

**Decision**: Minimum Spanning Tree (Kruskal's) oriented from DT root.

**Alternatives considered**:
- **DBSCAN clustering**: Would identify groups but not parent-child relationships
- **k-nearest neighbors**: Would create cycles, not a tree
- **Delaunay triangulation**: Overkill — distribution lines are trees, not meshes

**Why MST**: Distribution poles physically form a tree (no loops on the low-tension side).
A geographic MST rooted at the DT is the minimum-assumption estimator given only GPS coordinates.
It naturally produces the parent-child relationships needed for BFS boundary detection.

**Known weakness**: When two lines run close and parallel, MST may cross-connect poles
between lines. Mitigated by per-edge confidence scoring (long edges get penalized).

---

## D2: Debounce Window (30s) Before Dark

**Decision**: A `power_lost` event schedules a delayed check. If no `heartbeat` or
`power_restored` arrives within 30s, THEN mark the pole as dark.

**Why**: Flaky sensors occasionally send spurious `power_lost` followed by immediate
`heartbeat`. Without debounce, each flicker generates a false incident that annoys operators.

**Why 30s**: Short enough to stay within the 120s fault-to-ticket latency budget.
Long enough to absorb typical sensor flicker (observed at ~10-15s in the spec).

---

## D3: SSE over WebSocket

**Decision**: Server-Sent Events for real-time UI updates.

**Why not WebSocket**: The FAQ explicitly warns that WebSocket is a "classic deployment
failure" on free hosting tiers (Render, Railway). SSE works through reverse proxies
with zero configuration. We only need server→client push (no bidirectional needed).

**Tradeoff**: Can't push client→server via SSE. Not needed — API mutations use POST/PATCH.

---

## D4: No Redis

**Decision**: In-process `asyncio.Queue` instead of Redis for event buffering.

**Why**: At ~39 msg/s steady state and 5,000 msg burst, an in-process queue handles
the load without external dependencies. Adding Redis would:
- Add a Docker service (more failure modes on `docker compose up`)
- Add deployment complexity
- Add 0 value at this message rate

**When to add Redis**: If scaling to >1,000 msg/s sustained or multi-process deployment.
Documented in README as an honest scaling boundary.

---

## D5: System-Only Verification

**Decision**: `verified` and `closed` states can ONLY be set by the verification
watchdog, NEVER by the API. A crew marking an incident as `resolved` is a *claim*,
not a *fact*.

**Why**: The spec requires "telemetry verification of resolution". If a crew says
"fixed" but 30% of poles are still dark, the system must flag this as disputed —
not silently close the ticket.

**Implementation**: `validate_transition()` returns HTTP 403 for `verified`/`closed`
when `actor == "human"`.

---

## D6: Multiplicative Confidence with Named Reasons

**Decision**: Confidence = product of independent penalty factors, each with a
human-readable reason string.

**Alternatives considered**:
- **ML classifier**: No labeled training data. Would be a black box.
- **Rule-based scoring (additive)**: Doesn't correctly model independent uncertainties.
- **Bayesian network**: Overkill for 5 factors, harder to explain.

**Why multiplicative**: Each factor independently degrades confidence. A pole on inferred
topology (0.7) with 2 unobserved boundary poles (0.8) and only heartbeat-timeout
detection (0.75) correctly compounds to 0.42 — low confidence with three clear reasons.

---

## D7: One Incident per Boundary, Not per Pole

**Decision**: `find_fault_boundaries()` creates one `FaultCandidate` per live→dark
boundary, with all downstream dark poles as `affected_pole_ids`.

**Why**: If a wire snaps between poles #5 and #6, poles #6-#40 all go dark. That's ONE
fault, not 35 faults. The spec explicitly says "one ticket per fault, not per pole."

The boundary detection inherently produces this: BFS finds the single boundary edge,
then `collect_dark_subtree()` absorbs everything downstream.

---

## D8: Dead Sensor Exception

**Decision**: A single dark pole with live children is NOT a line fault. Skip it.

**Physical reasoning**: If the wire between poles #4 and #5 breaks, pole #5 AND all
poles downstream (#6, #7, ...) must be dark. If #5 is dark but #6 is live, electricity
is flowing through #5 to reach #6 — the wire is intact, but the sensor at #5 is broken.

This is the single most important noise filter in the system. Without it, every dead
battery would generate a false fault ticket.

---

## D9: AI for Briefings, Not Localization

**Decision**: An optional local LLM endpoint generates phone-readable crew briefings. All
localization is deterministic graph traversal.

**Why NOT use AI for localization**:
- Non-deterministic: same input could produce different output
- Unexplainable: can't show the reviewer "why this edge"
- Slower: API call vs in-memory BFS
- Less accurate: hallucination risk on spatial reasoning

**Why USE AI for briefings**: Translating structured fault data into a clear,
context-appropriate phone briefing IS an LLM strength. Template fallback ensures
the system works without an API key.

---

## D10: Scheduled Outage with Grace + Overrun

**Decision**: Suppress faults within `[start - 15min, end + 40min]`. Flag as
near-boundary within `[end + 40min, end + 80min]`.

**Why grace-before**: Field crews sometimes disconnect feeders 5-15 minutes before
the official start time. Without grace, their prep work triggers false incidents.

**Why overrun**: Restoration after maintenance takes time. Without overrun, the moment
`end` passes, every still-dark pole becomes a fault candidate. The 40-minute overrun
lets normal restoration complete. If STILL dark after 80 minutes → promote to real fault
with a confidence penalty.

---

## What Is Currently Fragile

- Topology inference is geometric and can select an incorrect connection for
  close parallel lines or dense branches. The UI reports inferred-edge
  confidence, but it cannot turn an uncertain inferred edge into surveyed fact.
- The ingest queue and SSE subscriber list are process-local. They are suitable
  for this single-instance exercise deployment, not multi-instance production.
- The public demo uses free hosting. Render can cold-start, and the free
  database has platform limits; the demo video is therefore an important
  submission backup.
- End-to-end p95 latency and public 5,000-event burst throughput have not been
  measured. The repository includes a load-test script instead of unsupported
  performance claims.

## With Two More Weeks

1. Validate inferred topology against a field-survey sample, expose a
   DT-level-only fallback when confidence is below an operator-safe threshold,
   and add an operator correction workflow.
2. Add durable ingestion (broker/queue), idempotent database constraints, and
   shared SSE/event infrastructure so multiple API instances can run safely.
3. Measure and publish end-to-end latency plus the 5,000-event burst result;
   profile the database path and add alerting for queue depth and stale devices.
4. Add integration tests for scheduled-outage suppression, restoration
   verification, and the deployed browser-to-API/SSE path.
