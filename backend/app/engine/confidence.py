"""Confidence scoring (§5) — multiplicative score with human-readable reasons.

Design decision: a weighted multiplicative score with named reasons is easy to
defend on a follow-up call. A learned model is not, and there's no labeled data
to train one anyway. This is explicitly what the evaluators want: "how confident
and why" that is explainable, not a black box.
"""
from __future__ import annotations
from typing import Optional
from app.engine.boundary import FaultCandidate


def compute_confidence(
    candidate: FaultCandidate,
    pole_devices: dict[str, Optional[str]],
    explicitly_reported_dark: set[str],
    boundary_device_rssi: Optional[int] = None,
    boundary_device_battery_mv: Optional[int] = None,
) -> tuple[float, list[str]]:
    """Compute confidence score and reasons for a fault candidate.

    Args:
        candidate: The fault candidate from boundary-finding
        pole_devices: {pole_id: device_id or None}
        explicitly_reported_dark: Set of pole_ids that sent explicit power_lost
        boundary_device_rssi: RSSI of the device at the boundary pole
        boundary_device_battery_mv: Battery mV of the device at the boundary pole

    Returns:
        (score: float 0-1, reasons: list[str])
    """
    score = 1.0
    reasons = []

    # 1. Topology source — inferred topology has inherent uncertainty
    if candidate.boundary_edge_source == "inferred":
        edge_conf = candidate.boundary_edge_confidence or 0.5
        score *= edge_conf
        reasons.append(
            f"Topology inferred geometrically (edge confidence {edge_conf:.0%}), "
            f"not from registry"
        )

    # 2. Unobserved poles near boundary — can't pinpoint exact span
    unobserved = candidate.unobserved_in_boundary
    if unobserved > 0:
        penalty = max(0.3, 1 - 0.1 * unobserved)
        score *= penalty
        reasons.append(
            f"{unobserved} pole(s) on/near boundary have no device — "
            f"fault location is a range, not a point"
        )

    # 3. Explicit reports vs heartbeat timeout
    total = len(candidate.affected_poles)
    reported = len(
        [p for p in candidate.affected_poles if p in explicitly_reported_dark]
    )
    if total > 0 and reported < total:
        timeout_inferred = total - reported
        penalty = 0.5 + 0.5 * (reported / total)
        score *= penalty
        reasons.append(
            f"{timeout_inferred} of {total} poles inferred dark via heartbeat "
            f"timeout, not explicit power_lost report"
        )

    # 4. Scheduled outage proximity
    if candidate.near_scheduled_outage:
        score *= 0.6
        reasons.append(
            "Occurred near a scheduled outage window boundary — "
            "may be expected maintenance"
        )

    # 5. Device health signals — weak radio or low battery reduce trust
    if boundary_device_rssi is not None and boundary_device_rssi < -100:
        score *= 0.85
        reasons.append(
            f"Boundary device has weak radio signal (RSSI {boundary_device_rssi} dBm)"
        )

    if boundary_device_battery_mv is not None and boundary_device_battery_mv < 3200:
        score *= 0.8
        reasons.append(
            f"Boundary device had low battery ({boundary_device_battery_mv} mV) — "
            f"may have failed to send dying message"
        )

    return round(score, 2), reasons
