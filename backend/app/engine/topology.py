"""Topology inference — the central algorithm (§1).

For DTs with known topology (40%): builds edges from seq_on_line + parent_pole_id.
For DTs with unknown topology (60%): infers edges via MST on geographic distance.

Key design decision: MST + orient-from-root because distribution poles physically
form a tree (no loops on LT side). A geographic MST rooted at the DT is the natural
estimator of "which pole connects to which" given only coordinates.

Known failure modes:
- Dense clusters where two lines run close and parallel → MST may cross-connect
- T-junctions where a branch meets the main line → may pick wrong electrical connection
- Very long spurs → confidence degrades but spur is still identified as connected
"""
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

from app.config import settings


@dataclass
class TopoNode:
    """A node in the topology tree (DT or pole)."""
    id: str
    lat: float
    lon: float
    is_dt: bool = False
    parent_id: Optional[str] = None
    children: list[str] = field(default_factory=list)
    depth: int = 0
    device_id: Optional[str] = None


@dataclass
class TopoEdge:
    """A directed edge in the topology tree."""
    from_id: str  # parent
    to_id: str    # child
    distance_m: float
    source: str   # "known" or "inferred"
    confidence: float = 1.0


@dataclass
class TopologyTree:
    """A rooted tree representing a DT's topology."""
    dt_id: str
    root_id: str  # the DT node ID
    nodes: dict[str, TopoNode] = field(default_factory=dict)
    edges: list[TopoEdge] = field(default_factory=list)

    def all_pole_ids(self) -> list[str]:
        return [nid for nid, n in self.nodes.items() if not n.is_dt]

    def bfs_from_root(self) -> list[str]:
        """BFS traversal from root, returning node IDs in order."""
        visited = []
        queue = deque([self.root_id])
        seen = {self.root_id}
        while queue:
            nid = queue.popleft()
            visited.append(nid)
            node = self.nodes.get(nid)
            if node:
                for child_id in node.children:
                    if child_id not in seen:
                        seen.add(child_id)
                        queue.append(child_id)
        return visited

    def get_subtree(self, node_id: str) -> list[str]:
        """Get all descendants of a node (inclusive)."""
        result = []
        queue = deque([node_id])
        while queue:
            nid = queue.popleft()
            result.append(nid)
            node = self.nodes.get(nid)
            if node:
                queue.extend(node.children)
        return result

    def get_edge(self, from_id: str, to_id: str) -> Optional[TopoEdge]:
        for e in self.edges:
            if e.from_id == from_id and e.to_id == to_id:
                return e
        return None


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate haversine distance in meters between two GPS points."""
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def build_known_topology(dt_id: str, dt_lat: float, dt_lon: float,
                          poles: list[dict]) -> TopologyTree:
    """Build topology from registry data where seq_on_line and parent_pole_id are present.

    Args:
        dt_id: Distribution transformer ID
        dt_lat, dt_lon: DT GPS coordinates
        poles: List of pole dicts with pole_id, lat, lon, seq_on_line, parent_pole_id, device_id
    """
    tree = TopologyTree(dt_id=dt_id, root_id=dt_id)

    # Add DT as root node
    tree.nodes[dt_id] = TopoNode(id=dt_id, lat=dt_lat, lon=dt_lon, is_dt=True, depth=0)

    # Add all poles as nodes
    pole_map = {}
    for p in poles:
        node = TopoNode(
            id=p["pole_id"], lat=p["lat"], lon=p["lon"],
            device_id=p.get("device_id")
        )
        tree.nodes[p["pole_id"]] = node
        pole_map[p["pole_id"]] = p

    # Build edges from parent_pole_id
    for p in poles:
        parent = p.get("parent_pole_id")
        child_id = p["pole_id"]

        if parent and parent in tree.nodes:
            # Parent is another pole
            from_node = tree.nodes[parent]
            to_node = tree.nodes[child_id]
        elif p.get("seq_on_line") == 1 or not parent:
            # Root pole connects to DT
            from_node = tree.nodes[dt_id]
            to_node = tree.nodes[child_id]
            parent = dt_id
        else:
            # Parent not in our set — connect to DT as fallback
            from_node = tree.nodes[dt_id]
            to_node = tree.nodes[child_id]
            parent = dt_id

        dist = haversine_distance(from_node.lat, from_node.lon, to_node.lat, to_node.lon)
        tree.edges.append(TopoEdge(
            from_id=parent if parent else dt_id,
            to_id=child_id,
            distance_m=dist,
            source="known",
            confidence=1.0,
        ))
        to_node.parent_id = parent if parent else dt_id
        from_node.children.append(child_id)

    # Assign depths via BFS
    _assign_depths(tree)
    return tree


def infer_topology(dt_id: str, dt_lat: float, dt_lon: float,
                    poles: list[dict]) -> TopologyTree:
    """Infer topology via MST on geographic distance for DTs without registry topology.

    Algorithm:
    1. Build candidate edge set: all pairs within CANDIDATE_RADIUS_M
    2. Compute haversine distances as weights
    3. Run Kruskal's MST
    4. Orient tree from DT via BFS
    5. Compute per-edge confidence from local pole spacing

    Args:
        dt_id: Distribution transformer ID
        dt_lat, dt_lon: DT GPS coordinates
        poles: List of pole dicts with pole_id, lat, lon, device_id
    """
    tree = TopologyTree(dt_id=dt_id, root_id=dt_id)
    radius = settings.candidate_radius_m

    # Build nodes: DT + all poles
    all_nodes = [{"id": dt_id, "lat": dt_lat, "lon": dt_lon, "is_dt": True}]
    for p in poles:
        all_nodes.append({
            "id": p["pole_id"], "lat": p["lat"], "lon": p["lon"],
            "is_dt": False, "device_id": p.get("device_id"),
        })

    # Add to tree
    for n in all_nodes:
        tree.nodes[n["id"]] = TopoNode(
            id=n["id"], lat=n["lat"], lon=n["lon"],
            is_dt=n.get("is_dt", False),
            device_id=n.get("device_id"),
        )

    if len(all_nodes) <= 1:
        return tree

    # Build candidate edges within radius
    candidate_edges = []
    for i in range(len(all_nodes)):
        for j in range(i + 1, len(all_nodes)):
            a, b = all_nodes[i], all_nodes[j]
            dist = haversine_distance(a["lat"], a["lon"], b["lat"], b["lon"])
            # Always include edges to/from DT, and edges within radius
            if a["is_dt"] or b["is_dt"] or dist <= radius:
                candidate_edges.append((dist, a["id"], b["id"]))

    # If no candidate edges found within radius, use all edges (fallback for isolated poles)
    if not candidate_edges:
        for i in range(len(all_nodes)):
            for j in range(i + 1, len(all_nodes)):
                a, b = all_nodes[i], all_nodes[j]
                dist = haversine_distance(a["lat"], a["lon"], b["lat"], b["lon"])
                candidate_edges.append((dist, a["id"], b["id"]))

    # Kruskal's MST
    mst_edges = _kruskal_mst(all_nodes, candidate_edges)

    # Build adjacency list from MST
    adj = defaultdict(list)
    edge_weights = {}
    for dist, a_id, b_id in mst_edges:
        adj[a_id].append(b_id)
        adj[b_id].append(a_id)
        edge_weights[(a_id, b_id)] = dist
        edge_weights[(b_id, a_id)] = dist

    # Orient from DT via BFS → assign parent pointers
    visited = {dt_id}
    queue = deque([dt_id])
    while queue:
        nid = queue.popleft()
        node = tree.nodes[nid]
        for neighbor in adj[nid]:
            if neighbor not in visited:
                visited.add(neighbor)
                child_node = tree.nodes[neighbor]
                child_node.parent_id = nid
                node.children.append(neighbor)
                queue.append(neighbor)

    # Compute per-edge confidence and create TopoEdge objects
    _compute_edge_confidences(tree, edge_weights)

    # Handle disconnected poles (not reached by MST from DT)
    for n in all_nodes:
        if n["id"] not in visited and not n.get("is_dt", False):
            # Connect to DT directly with low confidence
            node = tree.nodes[n["id"]]
            node.parent_id = dt_id
            tree.nodes[dt_id].children.append(n["id"])
            dist = haversine_distance(dt_lat, dt_lon, n["lat"], n["lon"])
            tree.edges.append(TopoEdge(
                from_id=dt_id, to_id=n["id"],
                distance_m=dist, source="inferred", confidence=0.1,
            ))

    _assign_depths(tree)
    return tree


def _kruskal_mst(nodes: list[dict], edges: list[tuple]) -> list[tuple]:
    """Kruskal's MST using union-find."""
    # Sort edges by weight
    edges_sorted = sorted(edges, key=lambda e: e[0])

    # Union-Find
    parent = {n["id"]: n["id"] for n in nodes}
    rank = {n["id"]: 0 for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx == ry:
            return False
        if rank[rx] < rank[ry]:
            rx, ry = ry, rx
        parent[ry] = rx
        if rank[rx] == rank[ry]:
            rank[rx] += 1
        return True

    mst = []
    for dist, a_id, b_id in edges_sorted:
        if union(a_id, b_id):
            mst.append((dist, a_id, b_id))
            if len(mst) == len(nodes) - 1:
                break

    return mst


def _compute_edge_confidences(tree: TopologyTree, edge_weights: dict):
    """Compute per-edge confidence based on local pole spacing.

    Confidence = clamp(local_median_spacing / edge_length, 0.1, 1.0)
    Short edges (normal spacing) → ~1.0. Long edges (suspicious jumps) → low.
    """
    # Precompute distances from each node to k nearest neighbors
    node_list = [(nid, n.lat, n.lon) for nid, n in tree.nodes.items() if not n.is_dt]

    k_nearest_dists = {}
    for i, (nid, lat, lon) in enumerate(node_list):
        dists = []
        for j, (oid, olat, olon) in enumerate(node_list):
            if i != j:
                dists.append(haversine_distance(lat, lon, olat, olon))
        dists.sort()
        k_nearest_dists[nid] = dists[:4] if len(dists) >= 4 else dists

    for nid, node in tree.nodes.items():
        if node.parent_id and node.parent_id in tree.nodes:
            key = (node.parent_id, nid)
            dist = edge_weights.get(key, edge_weights.get((nid, node.parent_id), 0))

            # Compute local median spacing
            k_dists = k_nearest_dists.get(nid, [])
            if k_dists:
                local_median = sorted(k_dists)[len(k_dists) // 2]
            else:
                local_median = dist  # only node → confidence 1.0

            if dist > 0:
                conf = max(0.1, min(1.0, local_median / dist))
            else:
                conf = 1.0

            tree.edges.append(TopoEdge(
                from_id=node.parent_id, to_id=nid,
                distance_m=dist, source="inferred", confidence=conf,
            ))


def _assign_depths(tree: TopologyTree):
    """BFS from root to assign depth values."""
    queue = deque([tree.root_id])
    tree.nodes[tree.root_id].depth = 0
    visited = {tree.root_id}
    while queue:
        nid = queue.popleft()
        node = tree.nodes[nid]
        for child_id in node.children:
            if child_id not in visited:
                visited.add(child_id)
                tree.nodes[child_id].depth = node.depth + 1
                queue.append(child_id)
