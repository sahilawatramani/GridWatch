import React from 'react';
import { timeAgo, confidenceLevel, faultTypeLabel } from '../utils/formatters';

export default function IncidentList({ incidents, selected, onSelect }) {
  if (!incidents || incidents.length === 0) {
    return (
      <div className="incident-list">
        <div className="empty-state">
          <div className="icon">✅</div>
          <p>No incidents detected</p>
          <p style={{ fontSize: 12, marginTop: 4 }}>Use the simulator to inject faults</p>
        </div>
      </div>
    );
  }

  return (
    <div className="incident-list">
      {incidents.map(incident => {
        const isActive = selected?.id === incident.id;
        const confLevel = confidenceLevel(incident.confidence);

        return (
          <div
            key={incident.id}
            className={`incident-card ${incident.status} ${isActive ? 'active' : ''}`}
            onClick={() => onSelect(incident)}
          >
            <div className="incident-card-header">
              <div>
                <span className={`incident-type ${incident.fault_type}`}>
                  {faultTypeLabel(incident.fault_type)}
                </span>
                <span className={`status-tag ${incident.status}`} style={{ marginLeft: 8 }}>
                  {incident.status.replace('_', ' ')}
                </span>
              </div>
              <span className="incident-time">{timeAgo(incident.created_at)}</span>
            </div>

            <div className="incident-location">
              DT {incident.dt_id} • Feeder {incident.feeder_id}
              {incident.pincode && ` • PIN ${incident.pincode}`}
            </div>

            <div className="incident-meta">
              <span>⚡ {incident.affected_pole_ids?.length || 0} poles</span>
              <span>🏠 ~{incident.households_estimate} homes</span>
              <span className={`confidence-badge ${confLevel}`}>
                {Math.round(incident.confidence * 100)}%
              </span>
              {incident.disputed && (
                <span style={{ color: '#ef4444', fontWeight: 700 }}>⚠ DISPUTED</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
