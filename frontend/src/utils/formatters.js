/* Time/distance formatting utilities */

export function timeAgo(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  const now = new Date();
  const seconds = Math.floor((now - date) / 1000);

  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function formatTime(dateStr) {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false,
  });
}

export function formatCoords(lat, lon) {
  return `${lat?.toFixed(6)}°N, ${lon?.toFixed(6)}°E`;
}

export function confidenceLevel(score) {
  if (score >= 0.8) return 'high';
  if (score >= 0.5) return 'medium';
  return 'low';
}

export function confidenceLabel(score) {
  if (score >= 0.8) return 'High';
  if (score >= 0.5) return 'Medium';
  return 'Low';
}

export function faultTypeLabel(type) {
  switch (type) {
    case 'span': return 'Span Fault';
    case 'dt': return 'DT Fault';
    case 'feeder': return 'Feeder Fault';
    default: return type;
  }
}

export function statusLabel(status) {
  switch (status) {
    case 'detected': return 'Detected';
    case 'acknowledged': return 'Acknowledged';
    case 'crew_assigned': return 'Crew Assigned';
    case 'resolved': return 'Resolved';
    case 'verified': return 'Verified';
    case 'closed': return 'Closed';
    default: return status;
  }
}
