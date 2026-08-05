"""Ticket lifecycle state machine (§6).

States: detected → acknowledged → crew_assigned → resolved → verified → closed

Key rules:
- 'verified' and 'closed' can ONLY be set by the system (verification_watchdog)
- 'resolved' by a human is a claim, not a fact — triggers verification
- If verification disagrees, ticket stays 'resolved' with disputed=True
- Does NOT silently revert to 'detected' — preserving that a human made a
  false claim is itself useful information
"""
from __future__ import annotations

VALID_TRANSITIONS = {
    "detected": ["acknowledged"],
    "acknowledged": ["crew_assigned"],
    "crew_assigned": ["resolved"],
    "resolved": [],  # verified/closed only via system
    "verified": [],   # auto-transitions to closed
    "closed": [],
}

# These statuses can only be set by the system, never by API
SYSTEM_ONLY_STATUSES = {"verified", "closed"}

# Human-callable transitions
HUMAN_CALLABLE = {"acknowledged", "crew_assigned", "resolved"}


class LifecycleError(Exception):
    pass


def validate_transition(current_status: str, new_status: str, actor: str = "human") -> None:
    """Validate a status transition.

    Raises LifecycleError if the transition is invalid.
    """
    if actor == "human" and new_status in SYSTEM_ONLY_STATUSES:
        raise LifecycleError(
            f"Status '{new_status}' can only be set by the system, not manually. "
            f"Tickets are verified automatically from telemetry data."
        )

    if new_status not in HUMAN_CALLABLE and actor == "human":
        raise LifecycleError(f"Cannot manually set status to '{new_status}'")

    valid_from = {
        "acknowledged": ["detected"],
        "crew_assigned": ["acknowledged"],
        "resolved": ["crew_assigned", "acknowledged", "detected"],
    }

    if actor == "human":
        allowed = valid_from.get(new_status, [])
        if current_status not in allowed:
            raise LifecycleError(
                f"Cannot transition from '{current_status}' to '{new_status}'. "
                f"Valid source states: {allowed}"
            )


def can_auto_verify(
    live_count: int, total_count: int,
    restoration_threshold: float = 0.95,
) -> bool:
    """Check if enough poles are live to auto-verify restoration."""
    if total_count == 0:
        return True
    return (live_count / total_count) >= restoration_threshold
