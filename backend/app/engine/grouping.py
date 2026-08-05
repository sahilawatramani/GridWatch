"""Incident grouping (§4) — turning fault candidates into incidents.

The trick that makes "one ticket per fault" work is upstream in boundary.py:
you only create a candidate at a *maximal* boundary (parent live, node dark),
and its subtree absorbs every downstream dark pole. So 40 dark poles from one
snapped wire become exactly one FaultCandidate with 40 affected_pole_ids.

The one place real grouping logic is needed is across DT/feeder levels:
a feeder fault shouldn't also show as N separate DT faults.
"""
from __future__ import annotations
from app.engine.boundary import FaultCandidate


def group_into_incidents(fault_candidates: list[FaultCandidate]) -> list[FaultCandidate]:
    """Group fault candidates into incidents, deduplicating across hierarchy levels.

    Each candidate from find_fault_boundaries IS already one incident by construction.
    This function handles cross-DT dedup: if a feeder-level fault is detected,
    suppress per-DT and per-span candidates on that feeder.
    """
    return suppress_downstream_duplicates(fault_candidates)


def suppress_downstream_duplicates(
    candidates: list[FaultCandidate],
) -> list[FaultCandidate]:
    """If a feeder-level fault is detected, suppress per-DT candidates under it.

    Also: if a DT-level fault is detected, suppress per-span candidates under that DT
    (they're all symptoms of the same DT outage).
    """
    # Collect feeder-level fault scopes
    feeder_faults = {c.feeder_id for c in candidates if c.fault_type == "feeder"}

    # Collect DT-level fault scopes
    dt_faults = {c.dt_id for c in candidates if c.fault_type == "dt"}

    result = []
    for c in candidates:
        # Skip span/DT faults if their feeder has a feeder-level fault
        if c.fault_type != "feeder" and c.feeder_id in feeder_faults:
            continue
        # Skip span faults if their DT has a DT-level fault
        if c.fault_type == "span" and c.dt_id in dt_faults:
            continue
        result.append(c)

    return result
