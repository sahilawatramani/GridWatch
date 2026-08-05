"""AI crew briefing generator — the AI feature.

Uses Gemini to generate natural-language briefings suitable for reading
over the phone to a field crew at 2 AM.

Why this spot and not elsewhere:
- Localization is deterministic graph traversal — an LLM would be slower,
  non-deterministic, and unexplainable
- But translating structured fault data into a clear phone briefing IS
  an LLM's strength
- Falls back gracefully to template when API is unavailable

Cost: ~$0.001 per briefing (Gemini Flash, small context)
"""
from __future__ import annotations
import json
import logging
from typing import Optional
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BRIEFING_PROMPT = """You are a power grid operations assistant. Generate a concise crew briefing
for a field repair team. This will be read over the phone at 2 AM — be clear, direct, no jargon.

Fault details:
- Type: {fault_type}
- Location: {lat:.6f}°N, {lon:.6f}°E
- PIN code: {pincode}
- DT: {dt_id} on feeder {feeder_id}
- Affected poles: {affected_count}
- Estimated households without power: {households}
- Confidence: {confidence:.0%}
- Confidence notes: {confidence_reasons}
- Topology: {topology_source}
- Detected at: {detected_at}

{boundary_info}

Generate a briefing under 150 words covering:
1. What happened and where (use coordinates and PIN code)
2. Scale of the outage (poles and households)
3. Any uncertainty the crew should know about
4. Suggested approach based on fault type

Be direct and actionable. No pleasantries."""

TEMPLATE_BRIEFING = """FAULT BRIEFING — {fault_type_upper} FAULT

Location: {lat:.6f}°N, {lon:.6f}°E — PIN {pincode}
DT: {dt_id} | Feeder: {feeder_id}

{boundary_info}

Scale: {affected_count} poles affected, ~{households} households without power
Confidence: {confidence:.0%}
{confidence_notes}

Detected: {detected_at}"""


async def generate_briefing(incident_data: dict) -> dict:
    """Generate a crew briefing from incident data.

    Returns dict with 'briefing' text and 'source' ('ai' or 'template').
    """
    # Build context
    context = {
        "fault_type": incident_data.get("fault_type", "unknown"),
        "fault_type_upper": incident_data.get("fault_type", "UNKNOWN").upper(),
        "lat": incident_data.get("lat", 0),
        "lon": incident_data.get("lon", 0),
        "pincode": incident_data.get("pincode", "unknown"),
        "dt_id": incident_data.get("dt_id", ""),
        "feeder_id": incident_data.get("feeder_id", ""),
        "affected_count": len(incident_data.get("affected_pole_ids", [])),
        "households": incident_data.get("households_estimate", 0),
        "confidence": incident_data.get("confidence", 0),
        "confidence_reasons": incident_data.get("confidence_reason", "[]"),
        "topology_source": incident_data.get("boundary_edge_source", "unknown"),
        "detected_at": str(incident_data.get("created_at", "")),
        "boundary_info": _format_boundary(incident_data),
        "confidence_notes": _format_confidence_notes(incident_data),
    }

    # Try AI generation using Local LLM
    try:
        briefing = await _generate_ai_briefing(context)
        if briefing:
            return {"briefing": briefing, "source": "Local LLM"}
    except Exception as e:
        logger.warning(f"Local LLM briefing failed, falling back to template: {e}")

    # Template fallback
    briefing = TEMPLATE_BRIEFING.format(**context)
    return {"briefing": briefing, "source": "template"}


async def _generate_ai_briefing(context: dict) -> Optional[str]:
    """Call Local LLM API for AI-generated briefing."""
    prompt = BRIEFING_PROMPT.format(**context)
    
    payload = {
        "model": settings.local_llm_model,
        "prompt": prompt,
        "stream": False
    }
    
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(settings.local_llm_url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()


def _format_boundary(data: dict) -> str:
    bf = data.get("boundary_from_pole")
    bt = data.get("boundary_to_pole")
    if bf and bt:
        source = data.get("boundary_edge_source", "unknown")
        return f"Fault boundary: span from {bf} to {bt} (topology: {source})"
    elif data.get("fault_type") == "dt":
        return f"DT-level fault — entire transformer {data.get('dt_id', '')} is down"
    elif data.get("fault_type") == "feeder":
        return f"Feeder-level fault — entire feeder {data.get('feeder_id', '')} is down"
    return "Boundary: unresolved"


def _format_confidence_notes(data: dict) -> str:
    reasons_str = data.get("confidence_reason", "[]")
    try:
        reasons = json.loads(reasons_str) if isinstance(reasons_str, str) else reasons_str
        if reasons:
            return "Notes:\n" + "\n".join(f"  - {r}" for r in reasons)
    except (json.JSONDecodeError, TypeError):
        pass
    return ""
