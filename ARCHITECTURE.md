# Architecture — GridWatch

## System Overview

```mermaid
graph TB
    subgraph "Data Sources (Simulated)"
        HB[Heartbeat Simulator<br/>15-min intervals ±45s]
        FI[Fault Injector<br/>span / DT / feeder / dead sensor]
    end

    subgraph "Ingest Layer"
        EP[POST /api/ingest]
        SF[Staleness Filter<br/>reject if device_ts > 10min old]
        DD[Dedup<br/>UNIQUE device_id + seq]
        Q[asyncio.Queue<br/>50k capacity]
        BW[Batch Writer<br/>500 events / 100ms]
    end

    subgraph "State Layer"
        PS[(pole_states)]
        DB[Debounce Timer<br/>30s window]
        HW[Heartbeat Watchdog<br/>60s scan]
    end

    subgraph "Detection Engine"
        TP[Topology Builder<br/>known registry OR MST inference]
        BF[Boundary Finder<br/>BFS from DT root]
        GR[Grouping<br/>suppress downstream duplicates]
        CS[Confidence Scorer<br/>multiplicative + reasons]
    end

    subgraph "Incident Management"
        IC[(incidents)]
        LC[Lifecycle FSM<br/>detected→ack→crew→resolved→verified→closed]
        VW[Verification Watchdog<br/>30s scan, 95% threshold]
    end

    subgraph "Presentation"
        SSE[SSE Broadcaster]
        UI[React Console<br/>Leaflet map + sidebar]
        AI[AI Briefing<br/>Gemini Flash + template fallback]
    end

    HB --> EP
    FI --> EP
    EP --> SF --> DD --> Q --> BW
    BW --> PS
    BW --> DB
    DB -->|after 30s| PS
    HW -->|timeout detected| PS
    PS -->|state changed| TP
    TP --> BF
    BF --> GR
    GR --> CS
    CS --> IC
    IC --> LC
    LC --> VW
    VW -->|verified| IC
    IC --> SSE
    SSE --> UI
    IC --> AI
```

## Data Flow — Event to Ticket (< 120s budget)

| Step | Component | Time Budget | Notes |
|------|-----------|-------------|-------|
| 1 | Ingest + queue | ~5ms | Enqueue returns immediately |
| 2 | Batch write | ~50ms | Batch of up to 500 events |
| 3 | Debounce wait | 30,000ms | Configurable. Prevents flicker. |
| 4 | Pole state update | ~5ms | Single row upsert |
| 5 | Topology build | ~100ms | MST on ~80 poles (O(n² log n)) |
| 6 | Boundary BFS | ~10ms | Linear in tree size |
| 7 | Grouping + dedup | ~1ms | Filter pass |
| 8 | Confidence scoring | ~1ms | 5 multiplicative factors |
| 9 | Incident upsert | ~10ms | With overlap check |
| 10 | SSE broadcast | ~1ms | Non-blocking fanout |
| **Total** | | **~30.2s** | Well under 120s budget |

## Database Schema

```mermaid
erDiagram
    transformers {
        string dt_id PK
        string feeder_id
        float lat
        float lon
        int capacity_kva
        int households_served
    }

    poles {
        string pole_id PK
        float lat
        float lon
        string feeder_id FK
        string dt_id FK
        int seq_on_line "NULL for 60%"
        string parent_pole_id "NULL for 60%"
        string device_id "NULL for 9%"
        string pincode "NULL for 3%"
    }

    pole_states {
        string pole_id PK
        enum status "live|dark|unknown"
        timestamp last_heartbeat_ts
        enum reason "reported_dark|heartbeat_timeout|no_data|reported_live"
    }

    telemetry_events {
        uuid id PK
        string device_id
        string pole_id FK
        enum event "heartbeat|power_lost|power_restored|boot"
        bool energized
        timestamp device_ts
        timestamp received_ts
        int seq "UNIQUE with device_id"
    }

    edges {
        string dt_id PK
        string from_pole_id PK
        string to_pole_id PK
        enum source "known|inferred"
        float confidence
        float distance_m
    }

    incidents {
        uuid id PK
        enum fault_type "span|dt|feeder"
        string dt_id FK
        string feeder_id
        string boundary_from_pole
        string boundary_to_pole
        array affected_pole_ids
        float confidence
        text confidence_reason
        enum status "detected|acknowledged|crew_assigned|resolved|verified|closed"
        bool disputed
        int households_estimate
    }

    scheduled_outages {
        string id PK
        enum scope "feeder|dt"
        string target_id
        timestamp start
        timestamp end
    }

    transformers ||--o{ poles : "has"
    poles ||--o| pole_states : "has state"
    poles ||--o{ telemetry_events : "generates"
    transformers ||--o{ edges : "has topology"
    transformers ||--o{ incidents : "has faults"
```

## Topology Inference — The Central Algorithm

### Known Topology (40% of DTs)
Registry provides `seq_on_line` and `parent_pole_id` → direct tree construction.
Confidence: **1.0** for all edges.

### Inferred Topology (60% of DTs)
Only GPS coordinates available. Algorithm:

1. **Candidate edge set**: All pole pairs within 150m + all DT-to-pole pairs
2. **MST**: Kruskal's algorithm (union-find, O(E log E))
3. **Orient**: BFS from DT → assign parent pointers
4. **Confidence**: Per-edge score = `clamp(local_median_spacing / edge_length, 0.1, 1.0)`

**Why MST?** Distribution poles physically form a tree (no loops on LT side).
A geographic MST rooted at the DT is the minimum-assumption estimator.

### Known Failure Modes
- Dense parallel lines → MST may cross-connect
- T-junctions → may pick wrong electrical connection
- Very long spurs → low confidence but correctly identified

## Fault Detection — Boundary Finding

The key insight: **a fault is on an EDGE, but sensors report on NODES.**

BFS from DT root. At each parent→child edge:
- If parent is **live** and child is **dark** → **BOUNDARY FOUND**
- Collect the entire dark subtree below → one `FaultCandidate`

### Critical Exception: Dead Sensor
A single dark pole with **live children** is physically impossible as a line fault.
The wire can't be broken AND carry power past the break. This means the **sensor lied**.
→ Skip, do NOT create a ticket.

### No-Device Gap Widening
If a boundary pole has no device, we can't observe it directly.
→ Widen the boundary to the nearest observed ancestor/descendant pair.
→ Add a confidence penalty for the uncertainty.
