/* API wrapper for GridWatch backend */

const BASE = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

export const api = {
  // Dashboard
  getStats: () => request('/dashboard/stats'),
  getPoles: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/poles${qs ? '?' + qs : ''}`);
  },
  getTransformers: () => request('/transformers'),
  getFeeders: () => request('/feeders'),
  getEdges: () => request('/edges'),

  // Incidents
  getIncidents: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/incidents${qs ? '?' + qs : ''}`);
  },
  getActiveIncidents: () => request('/incidents/active'),
  getIncident: (id) => request(`/incidents/${id}`),
  updateStatus: (id, status) => request(`/incidents/${id}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  }),
  getBriefing: (id) => request(`/incidents/${id}/briefing`, { method: 'POST' }),

  // Simulator
  seed: () => request('/simulator/seed', { method: 'POST' }),
  injectSpanFault: (dt_id, edge_index) => request('/simulator/inject-span-fault', {
    method: 'POST',
    body: JSON.stringify({ dt_id, edge_index }),
  }),
  injectDtFault: (dt_id) => request('/simulator/inject-dt-fault', {
    method: 'POST',
    body: JSON.stringify({ dt_id }),
  }),
  injectFeederFault: (feeder_id) => request('/simulator/inject-feeder-fault', {
    method: 'POST',
    body: JSON.stringify({ feeder_id }),
  }),
  injectDeadSensor: (pole_id) => request('/simulator/inject-dead-sensor', {
    method: 'POST',
    body: JSON.stringify({ pole_id }),
  }),
  injectScheduledOutage: (data) => request('/simulator/inject-scheduled-outage', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  repair: (incident_id) => request('/simulator/repair', {
    method: 'POST',
    body: JSON.stringify({ incident_id }),
  }),
};
