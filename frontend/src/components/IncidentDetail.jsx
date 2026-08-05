import React, { useState } from 'react';
import {
  formatCoords, faultTypeLabel, statusLabel, timeAgo,
  confidenceLevel, confidenceLabel,
} from '../utils/formatters';
import { api } from '../utils/api';

export default function IncidentDetail({ incident, onStatusChange, onClose, addToast, onAction }) {
  const [briefing, setBriefing] = useState(null);
  const [loadingBriefing, setLoadingBriefing] = useState(false);
  const [showBriefing, setShowBriefing] = useState(false);

  if (!incident) return null;

  const confLevel = confidenceLevel(incident.confidence);
  let reasons = [];
  try {
    reasons = JSON.parse(incident.confidence_reason || '[]');
  } catch { reasons = []; }

  const nextStatus = {
    detected: 'acknowledged',
    acknowledged: 'crew_assigned',
    crew_assigned: 'resolved',
  };

  const handleBriefing = async () => {
    setLoadingBriefing(true);
    try {
      const result = await api.getBriefing(incident.id);
      setBriefing(result);
      setShowBriefing(true);
    } catch (e) {
      addToast('Failed to generate briefing: ' + e.message, 'error');
    } finally {
      setLoadingBriefing(false);
    }
  };

  return (
    <div className="incident-detail">
      <div className="detail-header">
        <div>
          <span className={`incident-type ${incident.fault_type}`} style={{ fontSize: 16 }}>
            {faultTypeLabel(incident.fault_type)}
          </span>
          <span className={`status-tag ${incident.status}`} style={{ marginLeft: 10 }}>
            {statusLabel(incident.status)}
          </span>
        </div>
        <button className="btn" onClick={onClose} style={{ padding: '4px 10px', fontSize: 12 }}>✕</button>
      </div>

      {incident.disputed && (
        <div className="dispute-banner">
          ⚠️ DISPUTED — {incident.dispute_reason || 'Telemetry disagrees with resolution'}
        </div>
      )}

      <div className="detail-grid">
        <div className="detail-item">
          <label>Location</label>
          <div className="value coords">{formatCoords(incident.lat, incident.lon)}</div>
        </div>
        <div className="detail-item">
          <label>PIN Code</label>
          <div className="value">{incident.pincode || 'Unknown'}</div>
        </div>
        <div className="detail-item">
          <label>Affected Poles</label>
          <div className="value">{incident.affected_pole_ids?.length || 0}</div>
        </div>
        <div className="detail-item">
          <label>Households</label>
          <div className="value">~{incident.households_estimate}</div>
        </div>
        <div className="detail-item">
          <label>DT / Feeder</label>
          <div className="value">{incident.dt_id} / {incident.feeder_id}</div>
        </div>
        <div className="detail-item">
          <label>Detected</label>
          <div className="value">{timeAgo(incident.created_at)}</div>
        </div>
      </div>

      {/* Boundary info */}
      {incident.boundary_from_pole && (
        <div className="detail-item" style={{ marginBottom: 12 }}>
          <label>Fault Boundary</label>
          <div className="value" style={{ fontSize: 13 }}>
            {incident.boundary_from_pole} → {incident.boundary_to_pole}
            <span style={{ marginLeft: 8, fontSize: 11, color: '#8b95a8' }}>
              ({incident.boundary_edge_source} topology
              {incident.boundary_edge_confidence && `, ${Math.round(incident.boundary_edge_confidence * 100)}% edge confidence`})
            </span>
          </div>
        </div>
      )}

      {/* Confidence */}
      <div className="detail-item" style={{ marginBottom: 12 }}>
        <label>Confidence</label>
        <div className="value" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className={`confidence-badge ${confLevel}`}>
            {Math.round(incident.confidence * 100)}% — {confidenceLabel(incident.confidence)}
          </span>
        </div>
        {reasons.length > 0 && (
          <ul className="confidence-reasons">
            {reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        )}
      </div>

      {/* Actions */}
      <div className="action-buttons">
        {nextStatus[incident.status] && (
          <button
            className="btn primary"
            onClick={() => onStatusChange(incident.id, nextStatus[incident.status])}
          >
            → {statusLabel(nextStatus[incident.status])}
          </button>
        )}
        <button
          className="btn"
          onClick={handleBriefing}
          disabled={loadingBriefing}
        >
          {loadingBriefing ? '⏳ Generating...' : '📋 AI Briefing'}
        </button>
        {['detected', 'acknowledged', 'crew_assigned'].includes(incident.status) && (
          <button
            className="btn success"
            onClick={async () => {
              try {
                await api.repair(incident.id);
                addToast('Repair initiated — watch for verification', 'success');
                if (onAction) setTimeout(onAction, 2000);
              } catch (e) {
                addToast('Repair failed: ' + e.message, 'error');
              }
            }}
          >
            🔧 Simulate Repair
          </button>
        )}
      </div>

      {/* Briefing Inline Panel */}
      {showBriefing && briefing && (
        <div style={{ marginTop: 16, padding: 16, background: 'var(--bg-card)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-light)' }}>
          <h3 style={{ fontSize: 14, marginBottom: 12, color: 'var(--text-primary)' }}>📋 Crew Briefing</h3>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5, fontFamily: 'inherit' }}>
            {briefing.briefing}
          </pre>
          <div className="source-tag" style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)' }}>
            Generated via: {briefing.source}
          </div>
          <div style={{ marginTop: 12 }}>
            <button className="btn" onClick={() => setShowBriefing(false)}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}
