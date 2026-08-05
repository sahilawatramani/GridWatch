import React, { useEffect, useRef, useMemo } from 'react';
import L from 'leaflet';

const STATUS_COLORS = {
  live: '#22c55e',
  dark: '#ef4444',
  unknown: '#5a6478',
};

const FAULT_COLORS = {
  span: '#ef4444',
  dt: '#f59e0b',
  feeder: '#a855f7',
};

export default function MapView({ poles, transformers, incidents, edges = [], selectedIncident, onSelectIncident }) {
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const layersRef = useRef({
    poles: null,
    transformers: null,
    faults: null,
    lines: null,
  });

  // Initialize map
  useEffect(() => {
    if (mapInstanceRef.current) return;

    const map = L.map(mapRef.current, {
      center: [12.9716, 77.5946],
      zoom: 14,
      zoomControl: true,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap',
      maxZoom: 19,
    }).addTo(map);

    mapInstanceRef.current = map;
    layersRef.current.poles = L.layerGroup().addTo(map);
    layersRef.current.transformers = L.layerGroup().addTo(map);
    layersRef.current.faults = L.layerGroup().addTo(map);
    layersRef.current.lines = L.layerGroup().addTo(map);

    return () => {
      map.remove();
      mapInstanceRef.current = null;
    };
  }, []);

  // Render poles
  useEffect(() => {
    const layer = layersRef.current.poles;
    if (!layer || !poles.length) return;
    layer.clearLayers();

    poles.forEach(pole => {
      const color = STATUS_COLORS[pole.status] || STATUS_COLORS.unknown;
      const radius = pole.status === 'dark' ? 5 : 3;
      const opacity = pole.device_id ? 1 : 0.4;

      const circle = L.circleMarker([pole.lat, pole.lon], {
        radius,
        color: color,
        fillColor: color,
        fillOpacity: opacity * 0.7,
        weight: pole.status === 'dark' ? 2 : 1,
        opacity,
      });

      circle.bindTooltip(
        `<b>${pole.pole_id}</b><br/>` +
        `Status: ${pole.status}<br/>` +
        `DT: ${pole.dt_id}<br/>` +
        `Device: ${pole.device_id || 'None'}`,
        { className: 'dark-tooltip' }
      );
      layer.addLayer(circle);
    });
  }, [poles]);

  // Render transformers
  useEffect(() => {
    const layer = layersRef.current.transformers;
    if (!layer || !transformers.length) return;
    layer.clearLayers();

    transformers.forEach(dt => {
      const marker = L.circleMarker([dt.lat, dt.lon], {
        radius: 8,
        color: '#3b82f6',
        fillColor: '#3b82f6',
        fillOpacity: 0.8,
        weight: 2,
      });

      marker.bindTooltip(
        `<b>DT: ${dt.dt_id}</b><br/>` +
        `Feeder: ${dt.feeder_id}<br/>` +
        `${dt.capacity_kva} kVA • ${dt.households_served} households`,
        { className: 'dark-tooltip' }
      );
      layer.addLayer(marker);
    });
  }, [transformers]);

  // Render edges (topology)
  useEffect(() => {
    const layer = layersRef.current.lines;
    if (!layer || !edges.length || !poles.length || !transformers.length) return;
    layer.clearLayers();

    // Create a fast lookup for node coordinates (poles + DTs)
    const nodeCoords = {};
    poles.forEach(p => nodeCoords[p.pole_id] = [p.lat, p.lon]);
    transformers.forEach(dt => nodeCoords[dt.dt_id] = [dt.lat, dt.lon]);

    edges.forEach(edge => {
      const fromCoord = nodeCoords[edge.from_id];
      const toCoord = nodeCoords[edge.to_id];
      if (!fromCoord || !toCoord) return;

      const isKnown = edge.source === 'known';
      
      const polyline = L.polyline([fromCoord, toCoord], {
        color: isKnown ? '#10b981' : '#f59e0b', // Green for known, Amber for inferred
        weight: isKnown ? 2 : 1.5,
        opacity: isKnown ? 0.8 : 0.6,
        dashArray: isKnown ? null : '4, 6', // Dashed for inferred
      });

      polyline.bindTooltip(
        `<b>Edge</b><br/>${edge.from_id} → ${edge.to_id}<br/>Source: ${edge.source}<br/>Confidence: ${Math.round(edge.confidence * 100)}%`,
        { className: 'dark-tooltip' }
      );

      layer.addLayer(polyline);
    });
  }, [edges, poles, transformers]);

  // Render fault markers
  useEffect(() => {
    const layer = layersRef.current.faults;
    if (!layer) return;
    layer.clearLayers();

    const activeIncidents = incidents.filter(
      i => !['closed', 'verified'].includes(i.status)
    );

    activeIncidents.forEach(incident => {
      const color = FAULT_COLORS[incident.fault_type] || '#ef4444';
      const isSelected = selectedIncident?.id === incident.id;

      // Pulsing circle for fault location
      const pulseClass = incident.status === 'detected'
        ? 'fault-marker-detected'
        : 'fault-marker-acknowledged';

      const icon = L.divIcon({
        className: '',
        html: `<div class="${pulseClass}" style="
          width: ${isSelected ? 28 : 20}px;
          height: ${isSelected ? 28 : 20}px;
          border-radius: 50%;
          background: ${color};
          opacity: 0.9;
          border: 2px solid white;
          cursor: pointer;
        "></div>`,
        iconSize: [isSelected ? 28 : 20, isSelected ? 28 : 20],
        iconAnchor: [isSelected ? 14 : 10, isSelected ? 14 : 10],
      });

      const marker = L.marker([incident.lat, incident.lon], { icon });

      marker.bindTooltip(
        `<b>${incident.fault_type.toUpperCase()} FAULT</b><br/>` +
        `DT: ${incident.dt_id}<br/>` +
        `${incident.affected_pole_ids?.length || 0} poles affected<br/>` +
        `Confidence: ${Math.round(incident.confidence * 100)}%<br/>` +
        `Status: ${incident.status}`,
        { className: 'dark-tooltip' }
      );

      marker.on('click', () => onSelectIncident(incident));
      layer.addLayer(marker);

      // Draw affected pole highlights
      if (isSelected && incident.affected_pole_ids) {
        incident.affected_pole_ids.forEach(pid => {
          const pole = poles.find(p => p.pole_id === pid);
          if (pole) {
            const highlight = L.circleMarker([pole.lat, pole.lon], {
              radius: 7,
              color: color,
              fillColor: color,
              fillOpacity: 0.3,
              weight: 2,
              dashArray: '4 4',
            });
            layer.addLayer(highlight);
          }
        });
      }
    });
  }, [incidents, selectedIncident, poles, onSelectIncident]);

  // Pan to selected incident
  useEffect(() => {
    if (selectedIncident && mapInstanceRef.current) {
      mapInstanceRef.current.flyTo(
        [selectedIncident.lat, selectedIncident.lon],
        16,
        { duration: 0.8 }
      );
    }
  }, [selectedIncident]);

  return <div ref={mapRef} className="map-container" style={{ height: '100%' }} />;
}
