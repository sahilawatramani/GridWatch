import React, { useState, useEffect, useCallback, useRef } from 'react';
import MapView from './components/MapView';
import IncidentList from './components/IncidentList';
import IncidentDetail from './components/IncidentDetail';
import SimulatorPanel from './components/SimulatorPanel';
import { api, API_BASE } from './utils/api';

export default function App() {
  const [stats, setStats] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [poles, setPoles] = useState([]);
  const [transformers, setTransformers] = useState([]);
  const [feeders, setFeeders] = useState([]);
  const [edges, setEdges] = useState([]);
  const [toasts, setToasts] = useState([]);
  const [simOpen, setSimOpen] = useState(false);
  const sseRef = useRef(null);

  const addToast = useCallback((msg, type = 'info') => {
    const id = Date.now();
    setToasts(prev => [...prev, { id, msg, type }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 5000);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [s, inc, p, t, f, e] = await Promise.all([
        api.getStats(),
        api.getIncidents({ limit: 50 }),
        api.getPoles(),
        api.getTransformers(),
        api.getFeeders(),
        api.getEdges(),
      ]);
      setStats(s);
      setIncidents(inc);
      setPoles(p);
      setTransformers(t);
      setFeeders(f);
      setEdges(e);
    } catch (e) {
      console.error('Refresh failed:', e);
    }
  }, []);

  // Initial load
  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 10000);
    return () => clearInterval(interval);
  }, [refresh]);

  // SSE for real-time updates
  useEffect(() => {
    const sse = new EventSource(`${API_BASE}/events/stream`);
    sseRef.current = sse;

    sse.addEventListener('update', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'incident_created') {
          addToast(`⚡ New ${data.data.fault_type} fault detected — ${data.data.affected_count} poles`, 'error');
          refresh();
        } else if (data.type === 'incident_closed') {
          addToast('✅ Incident verified and closed', 'success');
          refresh();
        } else if (data.type === 'incident_disputed') {
          addToast(`⚠️ Disputed: ${data.data.dark_count} of ${data.data.total} poles still dark`, 'error');
          refresh();
        } else if (data.type === 'incident_updated') {
          refresh();
        }
      } catch (err) { /* ignore parse errors */ }
    });

    sse.onerror = () => {
      // SSE will auto-reconnect
    };

    return () => sse.close();
  }, [refresh, addToast]);

  return (
    <div className="app-layout">
      {/* Sidebar: Incidents */}
      <div className="sidebar">
        <div className="header">
          <div className="header-logo">
            <h1>⚡ GridWatch</h1>
            <span className="subtitle">Fault Detection Console</span>
          </div>
        </div>

        {stats && (
          <div style={{ display: 'flex', gap: 6, padding: '10px 16px', flexWrap: 'wrap' }}>
            <div className={`stat-badge ${stats.active_incidents > 0 ? 'danger' : ''}`}>
              <span className={`stat-dot ${stats.active_incidents > 0 ? 'danger' : 'success'}`}></span>
              {stats.active_incidents} Active
            </div>
            <div className="stat-badge warning">
              <span className="stat-dot warning"></span>
              {stats.poles_dark} Dark
            </div>
            <div className="stat-badge success">
              <span className="stat-dot success"></span>
              {stats.resolved_today} Resolved
            </div>
          </div>
        )}

        <div className="sidebar-header">
          <h2>Incidents</h2>
        </div>

        <IncidentList
          incidents={incidents}
          selected={selectedIncident}
          onSelect={setSelectedIncident}
        />

        {selectedIncident && (
          <IncidentDetail
            incident={selectedIncident}
            onStatusChange={async (id, status) => {
              try {
                await api.updateStatus(id, status);
                addToast(`Status updated to ${status}`, 'success');
                refresh();
              } catch (e) {
                addToast(e.message, 'error');
              }
            }}
            onClose={() => setSelectedIncident(null)}
            addToast={addToast}
            onAction={refresh}
          />
        )}

        <SimulatorPanel
          open={simOpen}
          onToggle={() => setSimOpen(!simOpen)}
          transformers={transformers}
          feeders={feeders}
          poles={poles}
          incidents={incidents}
          addToast={addToast}
          onAction={refresh}
        />
      </div>

      {/* Main: Map */}
      <div className="main-content">
        <MapView
          poles={poles}
          transformers={transformers}
          incidents={incidents}
          edges={edges}
          selectedIncident={selectedIncident}
          onSelectIncident={setSelectedIncident}
        />
      </div>

      {/* Toasts */}
      <div className="toast-container">
        {toasts.map(t => (
          <div key={t.id} className={`toast ${t.type}`}>{t.msg}</div>
        ))}
      </div>
    </div>
  );
}
