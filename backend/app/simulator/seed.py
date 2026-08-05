"""Synthetic data seed generator (§8 — generation half).

Generates a realistic power distribution network around Bangalore coordinates.
Shapes match the spec from 02-data-and-systems.md:
- ~3,000 poles across ~40 DTs on ~5 feeders from 1 substation
- Lines with 1-5 branches, up to 1.4km from DT
- ~60% of DTs missing topology (no seq_on_line, no parent_pole_id)
- ~9% of poles without devices
- ~8% of devices on firmware 1.2.x
- ~3% of poles missing pincode
"""
import math
import random
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pole import Pole
from app.models.transformer import Transformer
from app.models.pole_state import PoleState, PoleStatus, StatusReason
from app.models.edge import Edge, EdgeSource

logger = logging.getLogger(__name__)

# Bangalore area center coordinates
BASE_LAT = 12.9716
BASE_LON = 77.5946

# Real Bangalore pincodes
PINCODES = [
    "560001", "560002", "560003", "560004", "560005",
    "560008", "560009", "560010", "560011", "560012",
    "560017", "560018", "560020", "560021", "560022",
    "560024", "560025", "560026", "560027", "560029",
    "560030", "560032", "560033", "560034", "560036",
    "560037", "560038", "560039", "560040", "560041",
    "560043", "560045", "560047", "560048", "560049",
    "560050", "560051", "560052", "560053", "560054",
    "560055", "560056", "560058", "560060", "560061",
    "560062", "560063", "560064", "560065", "560066",
    "560067", "560068", "560069", "560070", "560071",
    "560072", "560073", "560074", "560075", "560076",
    "560077", "560078", "560079", "560080", "560083",
    "560084", "560085", "560086", "560087", "560089",
    "560090", "560091", "560092", "560093", "560094",
    "560095", "560096", "560097", "560098", "560099",
    "560100", "560102", "560103", "560104", "560105",
]

FW_VERSIONS = ["1.2.0", "1.2.1", "1.3.0", "1.3.1", "1.4.0", "1.4.1", "1.4.2"]


def _offset_coords(lat: float, lon: float, bearing_deg: float, distance_m: float):
    """Offset GPS coordinates by distance along a bearing."""
    R = 6371000
    bearing = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)

    lat2 = math.asin(
        math.sin(lat1) * math.cos(distance_m / R) +
        math.cos(lat1) * math.sin(distance_m / R) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(distance_m / R) * math.cos(lat1),
        math.cos(distance_m / R) - math.sin(lat1) * math.sin(lat2)
    )

    return math.degrees(lat2), math.degrees(lon2)


def _add_gps_jitter(lat: float, lon: float, jitter_m: float = 4.0):
    """Add realistic GPS jitter (±4m accuracy from spec)."""
    bearing = random.uniform(0, 360)
    dist = random.gauss(0, jitter_m / 2)
    return _offset_coords(lat, lon, bearing, abs(dist))


async def seed_network(session: AsyncSession, num_feeders: int = 5, dts_per_feeder: int = 8):
    """Generate complete synthetic network and seed into database."""
    logger.info("Seeding synthetic network...")

    # Clear existing data
    await session.execute(text(
        "TRUNCATE TABLE incidents, pole_states, edges, telemetry_events, poles, transformers, scheduled_outages RESTART IDENTITY CASCADE"
    ))

    all_poles = []
    all_transformers = []
    all_pole_states = []
    all_edges = []

    pole_counter = 1
    dt_counter = 1

    for f_idx in range(1, num_feeders + 1):
        feeder_id = f"F-{f_idx:02d}"
        # Spread feeders across the area
        feeder_lat = BASE_LAT + random.uniform(-0.03, 0.03)
        feeder_lon = BASE_LON + random.uniform(-0.03, 0.03)

        for d_idx in range(1, dts_per_feeder + 1):
            dt_id = f"D-{dt_counter:04d}"
            dt_counter += 1

            # Place DT near feeder with some spread
            dt_lat = feeder_lat + random.uniform(-0.008, 0.008)
            dt_lon = feeder_lon + random.uniform(-0.008, 0.008)

            # DT properties
            capacity = random.choice([100, 250, 315, 500, 630])
            poles_count = random.randint(15, 120)  # Vary pole count
            households = int(poles_count * random.uniform(3, 7))

            all_transformers.append(Transformer(
                dt_id=dt_id, feeder_id=feeder_id,
                lat=dt_lat, lon=dt_lon,
                capacity_kva=capacity,
                households_served=households,
            ))

            # Decide topology knowledge (~40% known, ~60% unknown)
            has_known_topology = random.random() < 0.40

            # Ward and pincode for this area
            ward = f"W-{random.randint(1, 198):03d}"
            local_pincode = random.choice(PINCODES)

            # Generate pole layout: main trunk + branches
            num_branches = random.randint(1, 5)
            trunk_poles_count = int(poles_count * 0.6)
            branch_poles_count = poles_count - trunk_poles_count

            # Main trunk direction
            trunk_bearing = random.uniform(0, 360)
            spacing = random.uniform(15, 25)  # meters between poles

            # Generate trunk poles
            dt_poles = []
            current_lat, current_lon = dt_lat, dt_lon
            seq = 1
            prev_pole_id = None

            for i in range(trunk_poles_count):
                p_id = f"P-{pole_counter:06d}"
                pole_counter += 1

                # Walk along trunk
                current_lat, current_lon = _offset_coords(
                    current_lat, current_lon, trunk_bearing, spacing
                )
                plat, plon = _add_gps_jitter(current_lat, current_lon)

                # Device assignment (~9% no device)
                has_device = random.random() > 0.09
                device_id = None
                fw = None
                if has_device:
                    device_id = f"KSPDB-SD{f_idx:02d}-{dt_id}-{pole_counter}"
                    # ~8% on fw 1.2.x
                    if random.random() < 0.08:
                        fw = random.choice(["1.2.0", "1.2.1"])
                    else:
                        fw = random.choice(["1.3.0", "1.3.1", "1.4.0", "1.4.1", "1.4.2"])

                # Pincode (~3% missing)
                pole_pincode = local_pincode if random.random() > 0.03 else None

                pole = Pole(
                    pole_id=p_id,
                    lat=plat, lon=plon,
                    feeder_id=feeder_id,
                    dt_id=dt_id,
                    seq_on_line=seq if has_known_topology else None,
                    parent_pole_id=prev_pole_id if has_known_topology else None,
                    pole_type=random.choice(["LT-9m-PCC", "LT-8m-Steel", "LT-11m-PCC"]),
                    ward=ward,
                    pincode=pole_pincode,
                    device_id=device_id,
                )
                all_poles.append(pole)
                dt_poles.append({
                    "pole_id": p_id, "lat": plat, "lon": plon,
                    "seq": seq, "parent": prev_pole_id,
                    "device_id": device_id, "fw": fw,
                })

                # Pole state — starts as live if has device, unknown otherwise
                all_pole_states.append(PoleState(
                    pole_id=p_id,
                    status=PoleStatus.live if has_device else PoleStatus.unknown,
                    reason=StatusReason.reported_live if has_device else StatusReason.no_data,
                ))

                prev_pole_id = p_id
                seq += 1

            # Generate branch poles
            branch_points = random.sample(
                range(max(1, len(dt_poles) - 1)),
                min(num_branches, max(1, len(dt_poles) - 1))
            ) if dt_poles else []

            for branch_idx, branch_start_idx in enumerate(branch_points):
                branch_parent = dt_poles[branch_start_idx]
                branch_bearing = trunk_bearing + random.uniform(60, 120) * random.choice([1, -1])
                branch_len = branch_poles_count // num_branches

                b_lat, b_lon = branch_parent["lat"], branch_parent["lon"]
                b_prev = branch_parent["pole_id"]

                for j in range(branch_len):
                    p_id = f"P-{pole_counter:06d}"
                    pole_counter += 1

                    b_lat, b_lon = _offset_coords(b_lat, b_lon, branch_bearing, spacing)
                    plat, plon = _add_gps_jitter(b_lat, b_lon)

                    has_device = random.random() > 0.09
                    device_id = None
                    fw = None
                    if has_device:
                        device_id = f"KSPDB-SD{f_idx:02d}-{dt_id}-{pole_counter}"
                        if random.random() < 0.08:
                            fw = random.choice(["1.2.0", "1.2.1"])
                        else:
                            fw = random.choice(["1.3.0", "1.3.1", "1.4.0", "1.4.1", "1.4.2"])

                    pole_pincode = local_pincode if random.random() > 0.03 else None

                    pole = Pole(
                        pole_id=p_id,
                        lat=plat, lon=plon,
                        feeder_id=feeder_id,
                        dt_id=dt_id,
                        seq_on_line=seq if has_known_topology else None,
                        parent_pole_id=b_prev if has_known_topology else None,
                        pole_type=random.choice(["LT-9m-PCC", "LT-8m-Steel"]),
                        ward=ward,
                        pincode=pole_pincode,
                        device_id=device_id,
                    )
                    all_poles.append(pole)
                    dt_poles.append({
                        "pole_id": p_id, "lat": plat, "lon": plon,
                        "seq": seq, "parent": b_prev,
                        "device_id": device_id, "fw": fw,
                    })

                    all_pole_states.append(PoleState(
                        pole_id=p_id,
                        status=PoleStatus.live if has_device else PoleStatus.unknown,
                        reason=StatusReason.reported_live if has_device else StatusReason.no_data,
                    ))

                    b_prev = p_id
                    seq += 1

    # Bulk insert
    session.add_all(all_transformers)
    session.add_all(all_poles)
    session.add_all(all_pole_states)

    await session.commit()

    total_poles = len(all_poles)
    devices = sum(1 for p in all_poles if p.device_id)
    known_topo = sum(1 for p in all_poles if p.seq_on_line is not None)
    missing_pin = sum(1 for p in all_poles if p.pincode is None)

    logger.info(
        f"Seeded: {len(all_transformers)} DTs, {total_poles} poles, "
        f"{devices} with devices ({100*devices/total_poles:.0f}%), "
        f"{known_topo} with known topology ({100*known_topo/total_poles:.0f}%), "
        f"{missing_pin} missing pincode ({100*missing_pin/total_poles:.0f}%)"
    )
    return {
        "transformers": len(all_transformers),
        "poles": total_poles,
        "poles_with_device": devices,
        "poles_with_known_topology": known_topo,
    }
