"""Fault boundary finding — turning pole states into fault candidates (§2).

The core insight: a fault is on an EDGE, but sensors report on NODES.
The answer is the frontier between the live region and the dark region.

Key physical rules encoded:
1. A single dark pole with live children is NOT a line fault — it's a broken sensor.
2. When a boundary pole has no device, widen to nearest observed pair.
3. Everything downstream of a live→dark boundary is one fault candidate.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from app.engine.topology import TopologyTree, TopoNode
from app.models.pole_state import PoleStatus


@dataclass
class FaultCandidate:
    """A candidate fault detected by boundary analysis."""
    fault_type: str  # "span", "dt", "feeder"
    dt_id: str
    feeder_id: str = ""
    boundary_from: Optional[str] = None  # last live pole
    boundary_to: Optional[str] = None    # first dark pole
    boundary_edge_source: Optional[str] = None
    boundary_edge_confidence: Optional[float] = None
    affected_poles: list[str] = field(default_factory=list)
    lat: float = 0.0
    lon: float = 0.0
    pincode: Optional[str] = None
    unobserved_in_boundary: int = 0  # poles without device in boundary zone
    near_scheduled_outage: bool = False


def find_fault_boundaries(
    tree: TopologyTree,
    pole_states: dict[str, str],
    pole_devices: dict[str, Optional[str]],
    pole_pincodes: dict[str, Optional[str]],
    feeder_id: str = "",
    is_feeder_wide: bool = False,
) -> list[FaultCandidate]:
    """Find fault boundaries in a DT's topology tree.

    Args:
        tree: Rooted topology tree for one DT
        pole_states: {pole_id: "live" | "dark" | "unknown"} for all poles in tree
        pole_devices: {pole_id: device_id or None} — which poles have devices
        pole_pincodes: {pole_id: pincode or None}
        feeder_id: The feeder this DT belongs to
        is_feeder_wide: If True, all DTs on this feeder are dark → feeder fault

    Returns:
        List of FaultCandidate objects
    """
    all_poles = tree.all_pole_ids()
    if not all_poles:
        return []

    # Check: all poles dark?
    all_dark = all(
        pole_states.get(p, "unknown") in ("dark", "unknown")
        for p in all_poles
    )

    if all_dark:
        if is_feeder_wide:
            return [FaultCandidate(
                fault_type="feeder",
                dt_id=tree.dt_id,
                feeder_id=feeder_id,
                affected_poles=all_poles,
                lat=tree.nodes[tree.root_id].lat,
                lon=tree.nodes[tree.root_id].lon,
            )]
        return [FaultCandidate(
            fault_type="dt",
            dt_id=tree.dt_id,
            feeder_id=feeder_id,
            affected_poles=all_poles,
            lat=tree.nodes[tree.root_id].lat,
            lon=tree.nodes[tree.root_id].lon,
            pincode=_best_pincode(all_poles, pole_pincodes),
        )]

    # BFS from root: find live→dark boundaries
    boundaries = []
    visited = set()
    queue = deque([tree.root_id])
    visited.add(tree.root_id)

    while queue:
        nid = queue.popleft()
        node = tree.nodes.get(nid)
        if not node:
            continue

        for child_id in node.children:
            if child_id in visited:
                continue
            visited.add(child_id)

            parent_status = _get_effective_status(nid, pole_states, tree)
            child_status = _get_effective_status(child_id, pole_states, tree)

            if child_status in ("dark", "unknown") and parent_status == "live":
                # CANDIDATE BOUNDARY: parent live, child dark
                subtree_dark = _collect_dark_subtree(child_id, tree, pole_states)

                # CRITICAL CHECK: isolated dead sensor
                # A single dark pole with live children is physically impossible
                # as a line fault. It means the sensor is lying.
                child_node = tree.nodes.get(child_id)
                if child_node and len(subtree_dark) == 1:
                    has_live_child = any(
                        pole_states.get(c, "unknown") == "live"
                        for c in child_node.children
                    )
                    if has_live_child:
                        # Sensor fault, not line fault — skip
                        queue.append(child_id)
                        continue

                # Handle no-device gap on boundary
                boundary_from = nid
                boundary_to = child_id
                unobserved = 0

                # If boundary node has no device, widen to nearest observed pair
                if nid != tree.root_id and not pole_devices.get(nid):
                    boundary_from, up_unobs = _find_nearest_observed_ancestor(
                        nid, tree, pole_devices, pole_states
                    )
                    unobserved += up_unobs

                if not pole_devices.get(child_id):
                    boundary_to, down_unobs = _find_nearest_observed_descendant(
                        child_id, tree, pole_devices, pole_states
                    )
                    unobserved += down_unobs

                # Compute location: midpoint of boundary edge
                from_node = tree.nodes.get(boundary_from, tree.nodes.get(tree.root_id))
                to_node = tree.nodes.get(boundary_to, tree.nodes.get(child_id))
                mid_lat = (from_node.lat + to_node.lat) / 2
                mid_lon = (from_node.lon + to_node.lon) / 2

                # Get edge info
                edge = tree.get_edge(nid, child_id)
                edge_source = edge.source if edge else "unknown"
                edge_confidence = edge.confidence if edge else 0.5

                boundaries.append(FaultCandidate(
                    fault_type="span",
                    dt_id=tree.dt_id,
                    feeder_id=feeder_id,
                    boundary_from=boundary_from,
                    boundary_to=boundary_to,
                    boundary_edge_source=edge_source,
                    boundary_edge_confidence=edge_confidence,
                    affected_poles=subtree_dark,
                    lat=mid_lat,
                    lon=mid_lon,
                    pincode=_best_pincode(subtree_dark, pole_pincodes),
                    unobserved_in_boundary=unobserved,
                ))
            else:
                # Continue BFS into live or dark subtrees
                queue.append(child_id)

    return boundaries


def _get_effective_status(node_id: str, pole_states: dict, tree: TopologyTree) -> str:
    """Get effective status. DT root is always considered 'live'."""
    if node_id == tree.root_id:
        return "live"
    return pole_states.get(node_id, "unknown")


def _collect_dark_subtree(node_id: str, tree: TopologyTree,
                          pole_states: dict) -> list[str]:
    """Collect all descendants of node that are dark or unknown.

    Stops at live poles (a live pole mid-subtree means a separate fault
    further down — it will be caught by its own boundary detection pass).
    """
    result = []
    queue = deque([node_id])
    while queue:
        nid = queue.popleft()
        status = pole_states.get(nid, "unknown")
        if status in ("dark", "unknown"):
            result.append(nid)
            node = tree.nodes.get(nid)
            if node:
                queue.extend(node.children)
        # If live, stop this branch (don't add to result, don't traverse children)
    return result


def _find_nearest_observed_ancestor(
    node_id: str, tree: TopologyTree,
    pole_devices: dict, pole_states: dict,
) -> tuple[str, int]:
    """Walk up toward root to find nearest ancestor with a device that reported live."""
    unobserved = 0
    current = node_id
    while current and current != tree.root_id:
        node = tree.nodes.get(current)
        if not node:
            break
        parent_id = node.parent_id
        if parent_id and pole_devices.get(parent_id) and pole_states.get(parent_id) == "live":
            return parent_id, unobserved
        unobserved += 1
        current = parent_id
    return tree.root_id, unobserved


def _find_nearest_observed_descendant(
    node_id: str, tree: TopologyTree,
    pole_devices: dict, pole_states: dict,
) -> tuple[str, int]:
    """Walk down to find nearest descendant with a device that reported dark."""
    unobserved = 0
    queue = deque([node_id])
    while queue:
        nid = queue.popleft()
        node = tree.nodes.get(nid)
        if not node:
            continue
        for child_id in node.children:
            if pole_devices.get(child_id):
                return child_id, unobserved
            unobserved += 1
            queue.append(child_id)
    return node_id, unobserved


def _best_pincode(pole_ids: list[str], pole_pincodes: dict) -> Optional[str]:
    """Get the most common pincode from a list of poles."""
    pincodes = [pole_pincodes.get(p) for p in pole_ids if pole_pincodes.get(p)]
    if not pincodes:
        return None
    # Return most common
    from collections import Counter
    return Counter(pincodes).most_common(1)[0][0]
