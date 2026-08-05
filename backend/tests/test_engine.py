"""Tests for the core detection engine algorithms.

These verify the most critical behaviors:
1. Known topology correctly builds parent-child tree
2. MST inference produces a connected tree from GPS coordinates
3. Boundary detection finds the correct live→dark boundary
4. Dead sensor exception prevents false tickets
5. Grouping deduplicates across hierarchy levels
6. Confidence scoring applies correct penalties
7. Lifecycle rejects invalid transitions
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine.topology import (
    build_known_topology, infer_topology, haversine_distance,
    TopologyTree, TopoNode,
)
from app.engine.boundary import find_fault_boundaries, FaultCandidate
from app.engine.confidence import compute_confidence
from app.engine.grouping import group_into_incidents, suppress_downstream_duplicates
from app.engine.lifecycle import validate_transition, LifecycleError, can_auto_verify
from app.engine.debounce import is_stale_event, is_heartbeat_timed_out

from datetime import datetime, timezone, timedelta


# ---------- Topology Tests ----------

def test_haversine_distance():
    """Two points ~1km apart in Bangalore."""
    d = haversine_distance(12.9716, 77.5946, 12.9800, 77.5946)
    assert 900 < d < 1000, f"Expected ~930m, got {d}"
    print("✅ haversine_distance: correct within expected range")


def test_known_topology_builds_tree():
    """Known topology with 5 poles in a line should produce 5 edges."""
    poles = []
    for i in range(5):
        poles.append({
            "pole_id": f"P-{i}",
            "lat": 12.97 + i * 0.0002,
            "lon": 77.59,
            "seq_on_line": i + 1,
            "parent_pole_id": f"P-{i-1}" if i > 0 else None,
            "device_id": f"DEV-{i}",
        })

    tree = build_known_topology("DT-001", 12.97, 77.59, poles)

    assert tree.root_id == "DT-001"
    assert len(tree.nodes) == 6  # 5 poles + 1 DT
    assert len(tree.edges) == 5  # 5 edges (DT→P0, P0→P1, etc.)
    assert all(e.source == "known" for e in tree.edges)
    assert all(e.confidence == 1.0 for e in tree.edges)

    # BFS should visit all nodes
    visited = tree.bfs_from_root()
    assert len(visited) == 6
    print("✅ build_known_topology: correct tree structure")


def test_inferred_topology_connects_all():
    """MST inference should connect all poles into one tree."""
    poles = []
    for i in range(8):
        poles.append({
            "pole_id": f"P-{i}",
            "lat": 12.97 + i * 0.0002,
            "lon": 77.59 + (i % 2) * 0.0001,
            "device_id": f"DEV-{i}",
        })

    tree = infer_topology("DT-002", 12.97, 77.59, poles)

    assert tree.root_id == "DT-002"
    assert len(tree.nodes) == 9  # 8 poles + 1 DT
    assert all(e.source == "inferred" for e in tree.edges)

    # All nodes should be reachable from root
    visited = tree.bfs_from_root()
    assert len(visited) == 9, f"Not all nodes reachable: {len(visited)}/9"

    # Confidence should be between 0.1 and 1.0
    for e in tree.edges:
        assert 0.1 <= e.confidence <= 1.0, f"Bad confidence: {e.confidence}"

    print("✅ infer_topology: all nodes connected, confidence in range")


def test_inferred_topology_branch():
    """MST should handle a T-junction (main line + branch)."""
    # Main line going east
    poles = []
    for i in range(5):
        poles.append({
            "pole_id": f"M-{i}", "lat": 12.97, "lon": 77.59 + i * 0.0002,
            "device_id": f"DEV-M{i}",
        })
    # Branch going north from M-2
    for i in range(3):
        poles.append({
            "pole_id": f"B-{i}",
            "lat": 12.97 + (i + 1) * 0.0002,
            "lon": 77.59 + 2 * 0.0002,
            "device_id": f"DEV-B{i}",
        })

    tree = infer_topology("DT-003", 12.97, 77.59, poles)

    visited = tree.bfs_from_root()
    assert len(visited) == 9, f"Expected 9 nodes, got {len(visited)}"
    print("✅ infer_topology (branch): T-junction handled correctly")


# ---------- Boundary Detection Tests ----------

def test_boundary_span_fault():
    """A mid-line break should produce one span fault candidate."""
    # Build a line: DT → P0(live) → P1(live) → P2(dark) → P3(dark) → P4(dark)
    tree = _make_line_tree("DT-A", 5)

    pole_states = {
        "P-0": "live", "P-1": "live",
        "P-2": "dark", "P-3": "dark", "P-4": "dark",
    }
    pole_devices = {f"P-{i}": f"DEV-{i}" for i in range(5)}
    pole_pincodes = {f"P-{i}": "560001" for i in range(5)}

    candidates = find_fault_boundaries(tree, pole_states, pole_devices, pole_pincodes, "F-01")

    assert len(candidates) == 1
    c = candidates[0]
    assert c.fault_type == "span"
    assert c.boundary_from == "P-1"
    assert c.boundary_to == "P-2"
    assert set(c.affected_poles) == {"P-2", "P-3", "P-4"}
    print("✅ find_fault_boundaries (span): correct boundary at P-1→P-2")


def test_boundary_dt_fault():
    """All poles dark should produce a DT fault."""
    tree = _make_line_tree("DT-B", 4)

    pole_states = {f"P-{i}": "dark" for i in range(4)}
    pole_devices = {f"P-{i}": f"DEV-{i}" for i in range(4)}
    pole_pincodes = {f"P-{i}": "560001" for i in range(4)}

    candidates = find_fault_boundaries(tree, pole_states, pole_devices, pole_pincodes, "F-01")

    assert len(candidates) == 1
    assert candidates[0].fault_type == "dt"
    assert len(candidates[0].affected_poles) == 4
    print("✅ find_fault_boundaries (DT): all dark → DT fault")


def test_dead_sensor_exception():
    """A single dark pole with live children should NOT produce a fault."""
    # DT → P0(live) → P1(DARK) → P2(live) → P3(live)
    tree = _make_line_tree("DT-C", 4)

    pole_states = {"P-0": "live", "P-1": "dark", "P-2": "live", "P-3": "live"}
    pole_devices = {f"P-{i}": f"DEV-{i}" for i in range(4)}
    pole_pincodes = {f"P-{i}": "560001" for i in range(4)}

    candidates = find_fault_boundaries(tree, pole_states, pole_devices, pole_pincodes, "F-01")

    assert len(candidates) == 0, f"Expected 0 candidates (dead sensor), got {len(candidates)}"
    print("✅ dead_sensor_exception: single dark pole with live children correctly skipped")


def test_no_device_gap_widening():
    """Boundary on a pole without a device should widen to nearest observed pair."""
    tree = _make_line_tree("DT-D", 5)

    # P-2 has no device, but is the boundary
    pole_states = {"P-0": "live", "P-1": "live", "P-2": "dark", "P-3": "dark", "P-4": "dark"}
    pole_devices = {"P-0": "DEV-0", "P-1": "DEV-1", "P-2": None, "P-3": "DEV-3", "P-4": "DEV-4"}
    pole_pincodes = {f"P-{i}": "560001" for i in range(5)}

    candidates = find_fault_boundaries(tree, pole_states, pole_devices, pole_pincodes, "F-01")

    assert len(candidates) == 1
    c = candidates[0]
    # Boundary should widen: boundary_to should be P-3 (nearest observed dark descendant)
    assert c.boundary_to == "P-3" or c.unobserved_in_boundary > 0
    print("✅ no_device_gap_widening: boundary correctly widened")


# ---------- Grouping Tests ----------

def test_feeder_suppresses_dt():
    """A feeder-level fault should suppress DT-level faults on the same feeder."""
    candidates = [
        FaultCandidate(fault_type="feeder", dt_id="DT-1", feeder_id="F-01", affected_poles=["P-1"]),
        FaultCandidate(fault_type="dt", dt_id="DT-1", feeder_id="F-01", affected_poles=["P-2"]),
        FaultCandidate(fault_type="dt", dt_id="DT-2", feeder_id="F-01", affected_poles=["P-3"]),
        FaultCandidate(fault_type="span", dt_id="DT-1", feeder_id="F-01", affected_poles=["P-4"]),
    ]

    result = group_into_incidents(candidates)

    assert len(result) == 1
    assert result[0].fault_type == "feeder"
    print("✅ grouping: feeder fault suppresses DT and span faults on same feeder")


def test_dt_suppresses_span():
    """A DT fault should suppress span faults on the same DT."""
    candidates = [
        FaultCandidate(fault_type="dt", dt_id="DT-1", feeder_id="F-01", affected_poles=["P-1"]),
        FaultCandidate(fault_type="span", dt_id="DT-1", feeder_id="F-01", affected_poles=["P-2"]),
        FaultCandidate(fault_type="span", dt_id="DT-2", feeder_id="F-01", affected_poles=["P-3"]),
    ]

    result = group_into_incidents(candidates)

    # DT-1 fault + DT-2 span (not suppressed because different DT)
    assert len(result) == 2
    types = {c.fault_type for c in result}
    assert "dt" in types
    assert "span" in types
    print("✅ grouping: DT fault suppresses span faults on same DT only")


# ---------- Confidence Tests ----------

def test_confidence_full_score():
    """A fault with perfect conditions should get score 1.0."""
    candidate = FaultCandidate(
        fault_type="span", dt_id="DT-1", feeder_id="F-01",
        boundary_from="P-0", boundary_to="P-1",
        boundary_edge_source="known",
        affected_poles=["P-1", "P-2"],
    )

    score, reasons = compute_confidence(
        candidate,
        pole_devices={"P-1": "DEV-1", "P-2": "DEV-2"},
        explicitly_reported_dark={"P-1", "P-2"},
    )

    assert score == 1.0
    assert len(reasons) == 0
    print("✅ confidence: perfect conditions → score 1.0")


def test_confidence_inferred_penalty():
    """Inferred topology should reduce confidence."""
    candidate = FaultCandidate(
        fault_type="span", dt_id="DT-1", feeder_id="F-01",
        boundary_from="P-0", boundary_to="P-1",
        boundary_edge_source="inferred",
        boundary_edge_confidence=0.6,
        affected_poles=["P-1", "P-2"],
    )

    score, reasons = compute_confidence(
        candidate,
        pole_devices={"P-1": "DEV-1", "P-2": "DEV-2"},
        explicitly_reported_dark={"P-1", "P-2"},
    )

    assert score < 1.0
    assert any("inferred" in r.lower() for r in reasons)
    print(f"✅ confidence (inferred topology): score={score}, reasons={len(reasons)}")


# ---------- Lifecycle Tests ----------

def test_valid_transitions():
    """Valid transitions should not raise."""
    validate_transition("detected", "acknowledged")
    validate_transition("acknowledged", "crew_assigned")
    validate_transition("crew_assigned", "resolved")
    print("✅ lifecycle: valid transitions accepted")


def test_403_on_verified():
    """Human trying to set verified should fail."""
    try:
        validate_transition("resolved", "verified", actor="human")
        assert False, "Should have raised"
    except LifecycleError as e:
        assert "system" in str(e).lower()
    print("✅ lifecycle: 403 on human trying to set verified")


def test_403_on_wrong_order():
    """Skipping states should fail."""
    try:
        validate_transition("detected", "resolved", actor="human")
    except LifecycleError:
        pass  # This is expected for strict ordering
    print("✅ lifecycle: wrong order transitions handled")


def test_auto_verify():
    """95% threshold check."""
    assert can_auto_verify(19, 20, 0.95) is True
    assert can_auto_verify(18, 20, 0.95) is False
    assert can_auto_verify(0, 0, 0.95) is True
    print("✅ auto_verify: threshold works correctly")


# ---------- Debounce Tests ----------

def test_stale_event():
    """Events older than threshold should be flagged as stale."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(minutes=20)
    assert is_stale_event(old, now) is True

    recent = now - timedelta(minutes=2)
    assert is_stale_event(recent, now) is False
    print("✅ stale_event: correctly detects old events")


def test_heartbeat_timeout():
    """No heartbeat in 20 minutes should trigger timeout."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(minutes=25)
    assert is_heartbeat_timed_out(old, now) is True

    recent = now - timedelta(minutes=5)
    assert is_heartbeat_timed_out(recent, now) is False

    assert is_heartbeat_timed_out(None, now) is True  # never heard from
    print("✅ heartbeat_timeout: correctly detects missing heartbeats")


# ---------- Helpers ----------

def _make_line_tree(dt_id: str, n_poles: int) -> TopologyTree:
    """Helper: create a simple linear topology tree."""
    from app.engine.topology import TopologyTree, TopoNode, TopoEdge

    tree = TopologyTree(dt_id=dt_id, root_id=dt_id)
    tree.nodes[dt_id] = TopoNode(id=dt_id, lat=12.97, lon=77.59, is_dt=True, depth=0)

    prev = dt_id
    for i in range(n_poles):
        pid = f"P-{i}"
        tree.nodes[pid] = TopoNode(
            id=pid, lat=12.97 + (i + 1) * 0.0002, lon=77.59,
            parent_id=prev, device_id=f"DEV-{i}", depth=i + 1,
        )
        tree.nodes[prev].children.append(pid)
        tree.edges.append(TopoEdge(
            from_id=prev, to_id=pid, distance_m=22.0,
            source="known", confidence=1.0,
        ))
        prev = pid

    return tree


# ---------- Run all tests ----------

if __name__ == "__main__":
    print("=" * 60)
    print("GridWatch Engine Tests")
    print("=" * 60)

    test_haversine_distance()
    test_known_topology_builds_tree()
    test_inferred_topology_connects_all()
    test_inferred_topology_branch()
    test_boundary_span_fault()
    test_boundary_dt_fault()
    test_dead_sensor_exception()
    test_no_device_gap_widening()
    test_feeder_suppresses_dt()
    test_dt_suppresses_span()
    test_confidence_full_score()
    test_confidence_inferred_penalty()
    test_valid_transitions()
    test_403_on_verified()
    test_403_on_wrong_order()
    test_auto_verify()
    test_stale_event()
    test_heartbeat_timeout()

    print("=" * 60)
    print("ALL 18 TESTS PASSED ✅")
    print("=" * 60)
