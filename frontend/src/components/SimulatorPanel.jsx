import React, { useState } from 'react';
import { api } from '../utils/api';

export default function SimulatorPanel({ open, onToggle, transformers, feeders, poles, incidents, addToast, onAction }) {
  const [selectedDt, setSelectedDt] = useState('');
  const [selectedFeeder, setSelectedFeeder] = useState('');
  const [selectedPole, setSelectedPole] = useState('');

  const polesWithDevice = poles.filter(p => p.device_id);

  const handleAction = async (fn, label) => {
    try {
      const result = await fn();
      addToast(`✅ ${label}: ${JSON.stringify(result).substring(0, 100)}`, 'success');
      // Wait a bit for events to propagate, then refresh
      setTimeout(onAction, 2000);
    } catch (e) {
      addToast(`❌ ${label} failed: ${e.message}`, 'error');
    }
  };

  return (
    <div className="simulator-panel">
      <div className="sim-toggle" onClick={onToggle}>
        <h3>🧪 Fault Simulator</h3>
        <span style={{ color: '#8b95a8', fontSize: 18 }}>{open ? '▼' : '▶'}</span>
      </div>

      {open && (
        <div className="sim-content">
          {/* Target selectors */}
          <div className="sim-section">
            <label>Target DT</label>
            <select value={selectedDt} onChange={e => setSelectedDt(e.target.value)}>
              <option value="">Select a DT...</option>
              {transformers.map(dt => (
                <option key={dt.dt_id} value={dt.dt_id}>
                  {dt.dt_id} ({dt.feeder_id}, {dt.capacity_kva} kVA)
                </option>
              ))}
            </select>
          </div>

          <div className="sim-section">
            <label>Target Feeder</label>
            <select value={selectedFeeder} onChange={e => setSelectedFeeder(e.target.value)}>
              <option value="">Select a feeder...</option>
              {feeders.map(f => (
                <option key={f.feeder_id} value={f.feeder_id}>{f.feeder_id}</option>
              ))}
            </select>
          </div>

          <div className="sim-section">
            <label>Target Pole (for dead sensor)</label>
            <select value={selectedPole} onChange={e => setSelectedPole(e.target.value)}>
              <option value="">Select a pole...</option>
              {polesWithDevice.slice(0, 100).map(p => (
                <option key={p.pole_id} value={p.pole_id}>
                  {p.pole_id} ({p.dt_id})
                </option>
              ))}
            </select>
          </div>

          {/* Fault injection buttons */}
          <div className="sim-section">
            <label>Inject Faults</label>
            <div className="sim-buttons">
              <button
                className="sim-btn fault"
                disabled={!selectedDt}
                onClick={() => handleAction(
                  () => api.injectSpanFault(selectedDt),
                  'Span fault'
                )}
              >
                ⚡ Span Fault
              </button>
              <button
                className="sim-btn fault"
                disabled={!selectedDt}
                onClick={() => handleAction(
                  () => api.injectDtFault(selectedDt),
                  'DT fault'
                )}
              >
                🔌 DT Fault
              </button>
              <button
                className="sim-btn fault"
                disabled={!selectedFeeder}
                onClick={() => handleAction(
                  () => api.injectFeederFault(selectedFeeder),
                  'Feeder fault'
                )}
              >
                💥 Feeder Fault
              </button>
            </div>
          </div>

          <div className="sim-section">
            <label>Noise / Edge Cases</label>
            <div className="sim-buttons">
              <button
                className="sim-btn noise"
                disabled={!selectedPole}
                onClick={() => handleAction(
                  () => api.injectDeadSensor(selectedPole),
                  'Dead sensor'
                )}
              >
                📡 Dead Sensor
              </button>
            </div>
          </div>

          {/* Repair */}
          {incidents.filter(i => !['closed', 'verified'].includes(i.status)).length > 0 && (
            <div className="sim-section">
              <label>Repair Active Incidents</label>
              <div className="sim-buttons">
                {incidents
                  .filter(i => !['closed', 'verified'].includes(i.status))
                  .slice(0, 5)
                  .map(i => (
                    <button
                      key={i.id}
                      className="sim-btn repair"
                      onClick={() => handleAction(
                        () => api.repair(i.id),
                        `Repair ${i.fault_type}`
                      )}
                    >
                      🔧 {i.fault_type} ({i.dt_id})
                    </button>
                  ))
                }
              </div>
            </div>
          )}

          {/* Reseed */}
          <div className="sim-section" style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 10, marginTop: 8 }}>
            <div className="sim-buttons">
              <button
                className="sim-btn noise"
                onClick={() => handleAction(api.seed, 'Reseed')}
              >
                🔄 Reseed Network
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
