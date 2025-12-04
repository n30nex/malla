(() => {
  let map;
  let markers = {};
  let nodeLocations = new Map();
  let polylines = [];
  let polylineLayer = null;
  let gatewayHalos = new Map();
  let gatewayActivity = new Map(); // gatewayId -> {lastSeen, count}
  let markerLayer = null;
  let gatewayLayerGroup = null;
  let clusterLayer = null;
  let heatLayer = null;
  let heatEnabled = false;
  let clusterEnabled = false;
  let nameLabelLayer = null;
  let liveCounter = 0;
  let paused = false;
  let lastId = 0;
  let eventSource = null;
  let retryTimer = null;
  let retryDelayMs = 1000;
  let seenIds = new Set();
  let displayWindowMs = 900000; // default 15 minutes
  let arcLifeMs = 120000; // fade packet arcs after ~2 minutes
  let tracerouteLabels = [];
  let nameLabels = new Map();
  const MOBILE_THRESHOLD_METERS = 100; // Distance threshold for mobile node detection
  let followingNodeId = null; // Currently followed node ID
  let nodeTracks = new Map(); // nodeId -> Array of {lat, lng, timestamp}
  // Fallback used if MOBILE_THRESHOLD_METERS is not defined in some older bundles
  const MOBILE_THRESHOLD_FALLBACK = 100;
  let selectedNodeId = null; // Currently selected node for details panel
  let nodeDetailsPanel = null; // Reference to details panel element
  let neighborLayer = null; // Layer for neighbor connections
  let neighborsEnabled = false; // Toggle state for neighbor layer
  let neighborConnections = new Map(); // Map of "node1:node2" -> {lastSeen, count, avgRssi, avgSnr}
  let trailsLayer = null; // Layer for position history trails
  let trailsEnabled = false; // Toggle state for trails
  let nodeTrails = new Map(); // nodeId -> L.polyline for trail

  const portColors = {
    POSITION_APP: "#0d6efd",
    TEXT_MESSAGE_APP: "#20c997",
    TELEMETRY_APP: "#fd7e14",
    TRACEROUTE_APP: "#ffc107",
  };
  const roleColors = {
    gateway: { fill: "#0dcaf0", stroke: "#0a95b8" },
    router: { fill: "#d63384", stroke: "#9c1f60" },
    client: { fill: "#66b0ff", stroke: "#1c78c0" },
    sensor: { fill: "#20c997", stroke: "#0f7e63" },
    unknown: { fill: "#adb5bd", stroke: "#6c757d" },
  };

  const activityList = document.getElementById("activity-list");
  const liveStatus = document.getElementById("live-status");
  const liveCounterEl = document.getElementById("live-counter");
  const portFilter = document.getElementById("port-filter");
  const pauseBtn = document.getElementById("pause-btn");
  const gatewayFilter = document.getElementById("gateway-filter");
  const gatewaySolo = document.getElementById("gateway-solo");
  const gatewayClear = document.getElementById("gateway-clear");
  const toggleHeat = document.getElementById("toggle-heat");
  const toggleCluster = document.getElementById("toggle-cluster");
  const legendContainer = document.getElementById("live-map-legend");
  const legendToggle = document.getElementById("toggle-legend");
  const legendBody = document.getElementById("legend-body");
  const legendCompact = document.getElementById("legend-compact");
  const helpBox = document.getElementById("live-map-help");
  const dismissHelp = document.getElementById("dismiss-help");
  const resetOnboarding = document.getElementById("reset-onboarding");
  const liveStatsNodes = document.getElementById("live-nodes-count");
  const liveStatsGw = document.getElementById("live-gw-count");
  const liveReconnectHint = document.getElementById("live-reconnect-hint");
  const timeWindowSelect = document.getElementById("time-window");

  function initMap() {
    map = L.map("live-map", { worldCopyJump: true }).setView([20, 0], 2);

    const light = L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
      {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
      }
    );
    light.addTo(map);

    markerLayer = L.layerGroup().addTo(map);
    nameLabelLayer = L.layerGroup().addTo(map);
    clusterLayer = L.markerClusterGroup({ disableClusteringAtZoom: 12 });
    polylineLayer = L.layerGroup().addTo(map);
    neighborLayer = L.layerGroup().addTo(map);
    trailsLayer = L.layerGroup().addTo(map);

    gatewayLayerGroup = L.layerGroup().addTo(map);

    // Update name labels on zoom change
    map.on('zoomend', () => {
      updateAllNameLabels();
    });

    // Click passthrough for compact legend
    if (legendCompact) {
      legendCompact.addEventListener("click", () => {
        if (legendContainer) legendContainer.classList.toggle("d-none");
      });
    }
  }

  function applyTimeWindow(ms) {
    displayWindowMs = Math.max(60000, ms);
    arcLifeMs = Math.min(displayWindowMs / 3, 180000);
    refreshAges();
  }

  function getRoleStyle(role) {
    if (!role) return roleColors.unknown;
    const r = role.toLowerCase();
    if (r.includes("gateway")) return roleColors.gateway;
    if (r.includes("router") || r.includes("repeater")) return roleColors.router;
    if (r.includes("sensor")) return roleColors.sensor;
    return roleColors.client;
  }

  function formatRelative(ms) {
    const diff = Date.now() - ms;
    if (diff < 0 || !Number.isFinite(diff)) return "just now";
    if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return `${Math.floor(diff / 86400000)}d ago`;
  }

  function addMarker(node) {
    if (node.latitude == null || node.longitude == null) return;
    if (!node._lastSeenMs) {
      // best-effort last seen using provided timestamp or now
      const tsGuess =
        Number(node.last_seen || node.last_updated || node.timestamp || Date.now() / 1000) * 1000;
      node._lastSeenMs = Number.isFinite(tsGuess) ? tsGuess : Date.now();
    }
    if (markers[node.node_id]) {
      const marker = markers[node.node_id];
      const oldLatLng = marker.getLatLng();
      const newLatLng = L.latLng(node.latitude, node.longitude);

      // Mobile Detection Logic (defensive against missing constant in older bundles)
      const distance = oldLatLng.distanceTo(newLatLng);
      const mobileThreshold =
        typeof MOBILE_THRESHOLD_METERS === "number" ? MOBILE_THRESHOLD_METERS : MOBILE_THRESHOLD_FALLBACK;
      if (distance > mobileThreshold) {
        showMobileToast(node);
      }

      marker.setLatLng(newLatLng);

      // Update track if following or if track exists
      if (followingNodeId === node.node_id || nodeTracks.has(node.node_id)) {
        updateNodeTrack(node.node_id, newLatLng);
      }

      // Pan map if following
      if (followingNodeId === node.node_id) {
        map.panTo(newLatLng);
      }

      attachMarkerHover(node.node_id);
      updateMarkerStyle(node.node_id);

      // Ensure click handler is attached (in case marker was recreated)
      marker.off('click');
      marker.on('click', () => {
        showNodeDetails(node.node_id);
      });

      // Trigger highlight animation on update
      const el = marker.getElement();
      if (el) {
        el.classList.remove("live-map-marker-highlight");
        void el.offsetWidth; // trigger reflow
        el.classList.add("live-map-marker-highlight");
        setTimeout(() => el.classList.remove("live-map-marker-highlight"), 1200);
      }
      return;
    }

    const roleClass = getRoleClass(node.role);
    const roleStyle = getRoleStyle(node.role);
    const marker = L.circleMarker([node.latitude, node.longitude], {
      radius: 6,
      fillColor: roleStyle.fill,
      color: roleStyle.stroke,
      weight: 1,
      fillOpacity: 0.9,
      className: `live-map-marker ${roleClass}`,
    });

    marker.bindPopup(
      `<strong>${node.display_name || node.long_name || node.short_name || node.node_id}</strong>`
    );

    // Add click handler for node details panel
    marker.on('click', () => {
      showNodeDetails(node.node_id);
    });

    markers[node.node_id] = marker;
    attachMarkerHover(node.node_id);
    updateMarkerStyle(node.node_id);
    placeMarkerOnLayer(marker);
    ensureNameLabel(node);

    // Light halo flash on new marker creation
    const el = marker.getElement();
    if (el) {
      el.classList.add("live-map-marker-highlight");
      setTimeout(() => el.classList.remove("live-map-marker-highlight"), 1200);
    }
  }

  function attachMarkerHover(nodeId) {
    const marker = markers[nodeId];
    const loc = nodeLocations.get(nodeId);
    if (!marker || !loc) return;

    const name =
      loc.display_name ||
      loc.long_name ||
      loc.short_name ||
      loc.hex_id ||
      `Node ${nodeId}`;

    const metaBits = [];
    if (loc.role) metaBits.push(loc.role);
    if (loc.hw_model) metaBits.push(loc.hw_model);
    if (loc.primary_channel) metaBits.push(`Ch ${loc.primary_channel}`);

    const live = loc._live || {};
    const liveBits = [];
    if (live.last_seen) {
      try {
        const dt = new Date(live.last_seen * 1000);
        liveBits.push(`Last heard ${dt.toLocaleString()}`);
      } catch (_e) {
        /* noop */
      }
    } else if (loc.timestamp_str) {
      liveBits.push(`Last update ${loc.timestamp_str}`);
    }
    if (Number.isFinite(live.pkt_count)) liveBits.push(`Pkts ${live.pkt_count}`);
    if (Number.isFinite(live.avg_rssi)) liveBits.push(`RSSI ${live.avg_rssi.toFixed(1)} dBm`);
    if (Number.isFinite(live.avg_snr)) liveBits.push(`SNR ${live.avg_snr.toFixed(1)} dB`);
    if (Number.isFinite(live.avg_hops)) liveBits.push(`Hops ${live.avg_hops.toFixed(1)}`);

    const lines = [`<strong>${name}</strong>`];
    if (metaBits.length) lines.push(`<div class="small text-muted">${metaBits.join(" &middot; ")}</div>`);
    if (liveBits.length) lines.push(`<div class="small">${liveBits.join(" &middot; ")}</div>`);

    if (marker.unbindTooltip) marker.unbindTooltip();
    marker.bindTooltip(lines.join(""), { direction: "top", sticky: true, opacity: 0.9 });
  }

  function getRoleClass(role) {
    if (!role) return "role-unknown";
    const r = role.toLowerCase();
    if (r.includes("gateway")) return "role-gateway";
    if (r.includes("router") || r.includes("repeater")) return "role-router";
    if (r.includes("sensor")) return "role-sensor";
    return "role-client";
  }

  function ageClass(ageMs) {
    if (ageMs < 60000) return "age-fresh";
    if (ageMs < 300000) return "age-warm";
    if (ageMs < displayWindowMs) return "age-stale";
    return "age-ghost";
  }

  function updateMarkerStyle(nodeId) {
    const marker = markers[nodeId];
    const loc = nodeLocations.get(nodeId);
    if (!marker || !loc) return;
    const now = Date.now();
    const lastSeen = loc._lastSeenMs || 0;
    const age = Math.max(0, now - lastSeen);
    const roleCls = getRoleClass(loc.role);
    const ageCls = ageClass(age);
    if (marker.setStyle) {
      // adjust opacity
      const opacityMap = {
        "age-fresh": 0.95,
        "age-warm": 0.7,
        "age-stale": 0.5,
        "age-ghost": 0.25,
      };
      marker.setStyle({
        opacity: opacityMap[ageCls] ?? 0.6,
        fillOpacity: opacityMap[ageCls] ?? 0.6,
      });
    }
    const el = marker.getElement?.();
    if (el) {
      el.classList.remove("age-fresh", "age-warm", "age-stale", "age-ghost");
      el.classList.add("live-map-marker", roleCls, ageCls);
    }
    ensureNameLabel(loc);
  }

  function refreshAges() {
    nodeLocations.forEach((_loc, id) => updateMarkerStyle(id));
    prunePolylines();
    // Update trails when time window changes
    if (trailsEnabled) {
      updateAllTrails();
    }
  }

  function ensureNameLabel(node) {
    if (!nameLabelLayer || !node || node.latitude == null || node.longitude == null) return;
    const name =
      node.display_name ||
      node.long_name ||
      node.short_name ||
      node.hex_id ||
      `Node ${node.node_id}`;
    let label = nameLabels.get(node.node_id);
    if (!label) {
      label = L.marker([node.latitude, node.longitude], {
        icon: L.divIcon({
          className: "node-name-label",
          html: `<div>${name}</div>`,
          iconAnchor: [30, 20],
        }),
        interactive: false,
        keyboard: false,
      });
      nameLabels.set(node.node_id, label);
    } else {
      label.setLatLng([node.latitude, node.longitude]);
      const el = label.getElement();
      if (el) el.innerHTML = `<div>${name}</div>`;
    }
    // Update visibility based on cluster state and zoom
    updateNameLabelVisibility(label, node.node_id);
  }

  function updateNameLabelVisibility(label, nodeId) {
    if (!label || !map) return;
    const zoom = map.getZoom();
    const zoomThreshold = 10; // Show names when zoomed in past level 10

    // Show names if:
    // 1. Clusters are disabled, OR
    // 2. Clusters are enabled but zoom is above threshold
    const shouldShow = !clusterEnabled || zoom >= zoomThreshold;

    if (shouldShow) {
      if (!nameLabelLayer.hasLayer(label)) {
        label.addTo(nameLabelLayer);
      }
    } else {
      if (nameLabelLayer.hasLayer(label)) {
        nameLabelLayer.removeLayer(label);
      }
    }
  }

  function updateAllNameLabels() {
    nameLabels.forEach((label, nodeId) => {
      updateNameLabelVisibility(label, nodeId);
    });
  }

  function placeMarkerOnLayer(marker) {
    if (!marker) return;
    if (clusterEnabled) {
      if (markerLayer?.hasLayer(marker)) {
        markerLayer.removeLayer(marker);
      }
      if (!map.hasLayer(clusterLayer)) {
        map.addLayer(clusterLayer);
      }
      if (clusterLayer && !clusterLayer.hasLayer(marker)) {
        clusterLayer.addLayer(marker);
      }
      if (markerLayer && map.hasLayer(markerLayer) && markerLayer.getLayers().length === 0) {
        map.removeLayer(markerLayer);
      }
    } else {
      if (clusterLayer?.hasLayer(marker)) {
        clusterLayer.removeLayer(marker);
      }
      if (markerLayer && !markerLayer.hasLayer(marker)) {
        markerLayer.addLayer(marker);
      }
      if (markerLayer && !map.hasLayer(markerLayer)) {
        map.addLayer(markerLayer);
      }
    }
  }

  function prunePolylines() {
    const now = Date.now();
    polylines = polylines.filter((item) => {
      if (now - item.created > arcLifeMs) {
        map.removeLayer(item.line);
        return false;
      }
      return true;
    });
    tracerouteLabels = tracerouteLabels.filter((item) => {
      if (now - item.created > arcLifeMs) {
        nameLabelLayer?.removeLayer(item.layer);
        return false;
      }
      return true;
    });
    // Remove stale gateway halos (~60s)
    gatewayHalos.forEach((layer, gwId) => {
      const meta = gatewayActivity.get(gwId);
      if (!meta || now - meta.lastSeen > 60000) {
        map.removeLayer(layer);
        gatewayHalos.delete(gwId);
      }
    });
  }

  function getSignalQuality(rssi, snr) {
    // Determine signal quality based on RSSI and SNR
    // Excellent: RSSI > -90dBm, SNR > 10dB
    // Good: RSSI -90 to -100dBm, SNR 5-10dB
    // Fair: RSSI -100 to -110dBm, SNR 0-5dB
    // Poor: RSSI < -110dBm, SNR < 0dB
    if (rssi == null && snr == null) return null;

    const rssiVal = rssi != null ? Number(rssi) : -120;
    const snrVal = snr != null ? Number(snr) : -10;

    if (rssiVal > -90 && snrVal > 10) {
      return { quality: "excellent", color: "#28a745", weight: 4 };
    } else if (rssiVal > -100 && snrVal > 5) {
      return { quality: "good", color: "#7cb342", weight: 3.5 };
    } else if (rssiVal > -110 && snrVal > 0) {
      return { quality: "fair", color: "#ffc107", weight: 3 };
    } else {
      return { quality: "poor", color: "#dc3545", weight: 2 };
    }
  }

  function drawLink(fromNodeId, toNodeId, packet, opts = {}) {
    const fromLoc = nodeLocations.get(fromNodeId);
    const toLoc = nodeLocations.get(toNodeId);
    if (!fromLoc || !toLoc) return;

    // Determine color and weight based on signal strength if available
    let color, weight;
    const signalInfo = getSignalQuality(packet.rssi, packet.snr);

    if (signalInfo && opts.useSignalStrength !== false) {
      color = signalInfo.color;
      weight = signalInfo.weight;
    } else {
      // Fall back to port-based coloring
      color = portColors[packet.portnum_name] || (packet.processed_successfully ? "#6f42c1" : "#dc3545");
      weight = opts.weight || 3;
    }

    const line = L.polyline(
      [
        [fromLoc.latitude, fromLoc.longitude],
        [toLoc.latitude, toLoc.longitude],
      ],
      {
        color,
        weight: weight,
        opacity: opts.opacity ?? 0.8,
        dashArray: opts.dashArray || "6 12", // Tighter dash for better flow effect
        className: "live-arc",
      }
    );

    // Add signal strength tooltip if available
    if (signalInfo && (packet.rssi != null || packet.snr != null)) {
      const rssiStr = packet.rssi != null ? `${packet.rssi.toFixed(1)} dBm` : "N/A";
      const snrStr = packet.snr != null ? `${packet.snr.toFixed(1)} dB` : "N/A";
      line.bindTooltip(
        `Signal: ${signalInfo.quality.toUpperCase()}<br>RSSI: ${rssiStr}<br>SNR: ${snrStr}`,
        { permanent: false, direction: "top", className: "signal-tooltip" }
      );
    }

    // Add to polyline layer if it exists, otherwise add directly to map
    if (polylineLayer) {
      line.addTo(polylineLayer);
    } else {
      line.addTo(map);
    }

    // Ensure the SVG path has the animation class (Leaflet sometimes drops custom class on updates)
    const pathEl = line.getElement?.();
    if (pathEl) {
      pathEl.classList.add("live-arc");
      // Kick off animation by resetting dash offset
      pathEl.style.strokeDashoffset = "0";
      pathEl.style.strokeDasharray = line.options.dashArray || "10 14";
    }

    polylines.push({ line, created: Date.now() });
    prunePolylines();
  }

  function renderTraceroutePath(routeNodes) {
    if (!Array.isArray(routeNodes) || routeNodes.length === 0) return;
    const now = Date.now();
    let hopIdx = 0;
    routeNodes.forEach((nid) => {
      const loc = nodeLocations.get(nid);
      if (!loc) return;
      ensureNameLabel(loc);
      const label = L.marker([loc.latitude, loc.longitude], {
        icon: L.divIcon({
          className: "hop-label",
          html: `<div>${hopIdx}</div>`,
          iconAnchor: [6, 10],
        }),
        interactive: false,
      }).addTo(nameLabelLayer || map);
      tracerouteLabels.push({ layer: label, created: now });
      hopIdx += 1;
    });
  }

  function addActivityEntry(packet, fromLoc, toLoc) {
    const entry = document.createElement("div");
    entry.className = "mb-2";
    const portBadge = `<span class="badge" style="background:${portColors[packet.portnum_name] || "#6c757d"}">${packet.portnum_name || "UNKNOWN"}</span>`;
    const fromName =
      fromLoc?.display_name ||
      fromLoc?.long_name ||
      fromLoc?.short_name ||
      fromLoc?.node_id ||
      packet.from_node_id ||
      "Unknown";
    const toName =
      toLoc?.display_name ||
      toLoc?.long_name ||
      toLoc?.short_name ||
      toLoc?.node_id ||
      packet.gateway_id ||
      "Unknown";
    const heardBy = packet.gateway_id ? `<span class="badge bg-secondary ms-1 gateway-heard" data-gw="${packet.gateway_id}">${packet.gateway_id}</span>` : "";
    entry.innerHTML = `${portBadge} ${fromName || "?"} &rarr; ${toName || "?"} ${heardBy}
      <div class="text-muted">${packet.timestamp_str || ""}</div>`;
    activityList.prepend(entry);

    // Wire heard-by badge
    const gwBadge = entry.querySelector(".gateway-heard");
    if (gwBadge) {
      gwBadge.addEventListener("click", () => {
        if (gatewayFilter) {
          gatewayFilter.value = gwBadge.dataset.gw || "";
          gatewaySolo?.click();
        }
      });
    }

    // keep last 50 entries
    while (activityList.children.length > 50) {
      activityList.removeChild(activityList.lastChild);
    }
  }

  function updateNodeTrack(nodeId, latLng) {
    if (!nodeId || !latLng) return;
    if (!nodeTracks.has(nodeId)) {
      nodeTracks.set(nodeId, []);
    }
    const track = nodeTracks.get(nodeId);
    track.push({
      lat: latLng.lat,
      lng: latLng.lng,
      timestamp: Date.now()
    });
    // Keep only last 100 points per track
    if (track.length > 100) {
      track.shift();
    }

    // Update trail visualization if enabled
    if (trailsEnabled) {
      updateNodeTrail(nodeId);
    }
  }

  function updateNodeTrail(nodeId) {
    if (!trailsLayer || !nodeId) return;

    const track = nodeTracks.get(nodeId);
    if (!track || track.length < 2) return;

    // Remove existing trail for this node
    const existingTrail = nodeTrails.get(nodeId);
    if (existingTrail) {
      trailsLayer.removeLayer(existingTrail);
    }

    // Filter track to only include points within display window
    const now = Date.now();
    const filteredTrack = track.filter(point => now - point.timestamp <= displayWindowMs);

    if (filteredTrack.length < 2) return;

    // Create polyline with gradient opacity (fade from recent to old)
    const latlngs = filteredTrack.map(p => [p.lat, p.lng]);

    // Use a color based on node role or default
    const loc = nodeLocations.get(nodeId);
    const roleStyle = loc ? getRoleStyle(loc.role) : roleColors.unknown;
    const trailColor = roleStyle.fill;

    // Calculate opacity gradient - more recent = more opaque
    const oldestTime = filteredTrack[0].timestamp;
    const newestTime = filteredTrack[filteredTrack.length - 1].timestamp;
    const timeRange = newestTime - oldestTime;

    // Create a multi-segment polyline with varying opacity
    // For simplicity, use average opacity that fades based on age
    const avgAge = now - ((oldestTime + newestTime) / 2);
    const maxAge = displayWindowMs;
    const baseOpacity = Math.max(0.2, 1 - (avgAge / maxAge));

    const trail = L.polyline(latlngs, {
      color: trailColor,
      weight: 2,
      opacity: baseOpacity * 0.6,
      className: "node-trail",
    });

    trail.bindTooltip(
      `Trail: ${filteredTrack.length} points<br>${formatRelative(newestTime)}`,
      { permanent: false, direction: "top" }
    );

    trail.addTo(trailsLayer);
    nodeTrails.set(nodeId, trail);
  }

  function updateAllTrails() {
    if (!trailsEnabled) return;
    nodeTracks.forEach((_track, nodeId) => {
      updateNodeTrail(nodeId);
    });
  }

  function updateTrailsLayer() {
    if (trailsEnabled) {
      updateAllTrails();
      if (!map.hasLayer(trailsLayer)) {
        map.addLayer(trailsLayer);
      }
    } else {
      if (map.hasLayer(trailsLayer)) {
        map.removeLayer(trailsLayer);
      }
      trailsLayer.clearLayers();
      nodeTrails.clear();
    }
  }

  function showMobileToast(node) {
    // Optional: Show a notification when a node moves significantly
    // This is a placeholder - can be enhanced with actual toast notifications
    console.log(`Node ${node.node_id} moved significantly`);
  }

  function handleTextMessage(packet) {
    // Handle text message packets - can be extended to show messages in UI
    // For now, this is a no-op to prevent errors
    if (packet && packet.portnum_name === 'TEXT_MESSAGE_APP') {
      // Text messages are already handled in addActivityEntry
      // This function can be extended for additional text message features
    }
  }

  function handlePacket(packet) {
    if (paused) return;
    if (portFilter.value && packet.portnum_name !== portFilter.value) return;

    // Deduplicate by packet identity (mesh_packet_id if present, else id) to drop repeats
    const dedupKey =
      packet.mesh_packet_id != null
        ? `mesh:${packet.mesh_packet_id}`
        : packet.id != null
          ? `id:${packet.id}`
          : `from:${packet.from_node_id || "?"}-to:${packet.to_node_id || "?"}-ts:${packet.timestamp || "?"}`;
    if (seenIds.has(dedupKey)) return;
    seenIds.add(dedupKey);
    if (seenIds.size > 5000) {
      const iterator = seenIds.values();
      seenIds.delete(iterator.next().value);
    }

    lastId = Math.max(lastId, packet.id || 0);
    liveCounter += 1;
    liveCounterEl.textContent = liveCounter.toString();

    const fromId = packet.from_node_id ?? null;
    const toId = packet.to_node_id ?? null;
    const gatewayIdRaw = packet.gateway_id ? packet.gateway_id.replace("!", "") : null;
    const gatewayId = gatewayIdRaw ? Number.parseInt(gatewayIdRaw, 16) : null;

    const fromLoc = fromId != null ? nodeLocations.get(fromId) : null;
    const gatewayLoc = Number.isFinite(gatewayId) ? nodeLocations.get(gatewayId) : null;
    const toLoc = toId != null ? nodeLocations.get(toId) : gatewayLoc;

    const tsMs = Number.isFinite(packet.timestamp) ? packet.timestamp * 1000 : Date.now();

    if (fromLoc) {
      fromLoc._lastSeenMs = tsMs;
      addMarker(fromLoc);
      updateMarkerStyle(fromLoc.node_id);
    }
    if (toLoc) {
      toLoc._lastSeenMs = tsMs;
      addMarker(toLoc);
      updateMarkerStyle(toLoc.node_id);
    }
    if (gatewayLoc && gatewayId != null) {
      gatewayLoc._lastSeenMs = tsMs;
      updateMarkerStyle(gatewayId);
      updateGatewayHalo(gatewayId, gatewayLoc);
    }

    // Always add activity, even if we only know one side
    addActivityEntry(packet, fromLoc, toLoc);

    // Track neighbor relationships from packet communications
    if (neighborsEnabled) {
      trackNeighborConnection(fromId, toId, gatewayId, packet);
    }

    if (packet.portnum_name === "TRACEROUTE_APP") {
      // Build a path including source/route/destination
      const routeIds = [];
      if (fromId != null) routeIds.push(fromId);
      if (Array.isArray(packet.route_nodes) && packet.route_nodes.length > 0) {
        routeIds.push(...packet.route_nodes);
      }
      if (toId != null && toId !== 0) routeIds.push(toId);

      // Render hop labels for every known location in order
      renderTraceroutePath(routeIds);

      // Draw as much of the path as we can with known coordinates
      let lastKnownId = null;
      for (let i = 0; i < routeIds.length; i++) {
        const nid = routeIds[i];
        const loc = nodeLocations.get(nid);
        if (!loc) continue;
        if (lastKnownId != null && lastKnownId !== nid) {
          drawLink(lastKnownId, nid, packet, {
            weight: 4,
            dashArray: "4 8",
            opacity: 0.9,
          });
          // Track neighbor connection for traceroute hops
          if (neighborsEnabled) {
            trackNeighborConnection(lastKnownId, nid, null, packet);
          }
        }
        lastKnownId = nid;
      }
    } else {
      // Determine best available endpoints for animation
      // Try to find valid locations for both endpoints
      let startLoc = fromLoc;
      let endLoc = toLoc;
      let startId = fromId;
      let endId = toId;

      // If we don't have a from location, try using gateway as source
      if (!startLoc && gatewayLoc && gatewayId != null) {
        startLoc = gatewayLoc;
        startId = gatewayId;
      }

      // If we don't have a to location, try using gateway as destination
      // But only if it's different from the start
      if (!endLoc && gatewayLoc && gatewayId != null && gatewayId !== startId) {
        endLoc = gatewayLoc;
        endId = gatewayId;
      }

      // Draw arc if we have two different valid locations
      if (startLoc && endLoc && startId != null && endId != null && startId !== endId) {
        // Ensure we use the node_id from the location object for consistency
        const finalStartId = startLoc.node_id || startId;
        const finalEndId = endLoc.node_id || endId;
        if (finalStartId !== finalEndId) {
          drawLink(finalStartId, finalEndId, packet);
        }
      }
      // Broadcast pulse (no to_node_id)
      if (!toId && fromId && fromLoc && markers[fromId]) {
        const el = markers[fromId].getElement();
        if (el) {
          el.classList.add("live-map-broadcast");
          setTimeout(() => el.classList.remove("live-map-broadcast"), 1500);
        }
      }
    }
  }

  function showLoading() {
    const loadingEl = document.getElementById("live-map-loading");
    if (loadingEl) loadingEl.style.display = "flex";
    const mapEl = document.getElementById("live-map");
    if (mapEl) mapEl.style.opacity = "0.5";
  }

  function hideLoading() {
    const loadingEl = document.getElementById("live-map-loading");
    if (loadingEl) loadingEl.style.display = "none";
    const mapEl = document.getElementById("live-map");
    if (mapEl) mapEl.style.opacity = "1";
  }

  async function loadLocations() {
    try {
      showLoading();
      // Precache all known node locations so packet animations can render immediately
      const resp = await fetch("/api/locations?span=all");
      const data = await resp.json();
      if (liveStatsNodes) liveStatsNodes.textContent = String((data.locations || []).length || "--");
      if (liveStatsGw) {
        const gwCount = (data.locations || []).filter(
          (loc) =>
            (loc.role && loc.role.toLowerCase().includes("gateway")) ||
            (loc.hex_id && String(loc.hex_id).startsWith("!"))
        ).length;
        liveStatsGw.textContent = String(gwCount || "--");
      }
      (data.locations || []).forEach((loc) => {
        nodeLocations.set(loc.node_id, loc);
        addMarker(loc);
      });
      // If for some reason markers did not get painted, retry once
      if (Object.keys(markers).length === 0 && nodeLocations.size > 0) {
        nodeLocations.forEach((loc) => addMarker(loc));
      }
      // Auto-fit once after initial load so all known nodes are visible
      fitToNodes();
      updateHeatLayer();
      // preload node stats
      fetchNodeStats();

      // Populate gateway dropdown (simple heuristic: has gateway_id or role includes gateway)
      const gatewaySelect = gatewayFilter;
      if (gatewaySelect) {
        const gateways = (data.locations || []).filter(
          (loc) =>
            (loc.role && loc.role.toLowerCase().includes("gateway")) ||
            (loc.node_id && String(loc.node_id).length > 0 && loc.hex_id)
        );
        gateways.forEach((gw) => {
          const opt = document.createElement("option");
          opt.value = gw.node_id;
          opt.textContent = gw.display_name || gw.long_name || gw.short_name || gw.hex_id || gw.node_id;
          gatewaySelect.appendChild(opt);
        });
      }
      hideLoading();
    } catch (e) {
      console.error("Failed to load locations", e);
      hideLoading();
    }
  }

  async function fetchNodeStats() {
    try {
      const resp = await fetch("/api/live/node-stats");
      const data = await resp.json();
      if (!data.stats) return;
      data.stats.forEach((stat) => {
        const loc = nodeLocations.get(stat.node_id);
        if (loc) {
          loc._live = stat;
          if (stat.last_seen) {
            const tsMs = Number(stat.last_seen) * 1000;
            if (Number.isFinite(tsMs)) loc._lastSeenMs = tsMs;
          }
          attachMarkerHover(stat.node_id);
          updateMarkerStyle(stat.node_id);
        }
      });

      // Load neighbors after node stats
      loadNeighbors();
    } catch (e) {
      console.error("Failed to load node stats", e);
    }
  }

  async function loadNeighbors() {
    try {
      const resp = await fetch("/api/neighbors?hours=24&max_distance_km=100");
      const data = await resp.json();
      if (data.neighbors) {
        data.neighbors.forEach(n => {
          const key = `${n.node1}:${n.node2}`;
          // Only add if we don't have better live data
          if (!neighborConnections.has(key)) {
            neighborConnections.set(key, {
              lastSeen: n.last_seen * 1000,
              count: n.count,
              rssiSum: (n.avg_rssi || -100) * n.count,
              snrSum: (n.avg_snr || 0) * n.count,
              rssiCount: n.count,
              snrCount: n.count
            });
          }
        });
        updateNeighborLayer();
      }
    } catch (e) {
      console.error("Failed to load neighbors", e);
    }
  }

  function stopStream() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    if (retryTimer) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
    if (heartbeatTimer) {
      clearTimeout(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  function scheduleReconnect() {
    if (paused) return;
    if (retryTimer) return;
    retryTimer = setTimeout(() => {
      retryTimer = null;
      startStream();
      retryDelayMs = Math.min(15000, Math.max(1000, retryDelayMs * 1.5));
    }, retryDelayMs);
  }

  let lastPacketTime = Date.now();
  let heartbeatTimer = null;
  const HEARTBEAT_TIMEOUT_MS = 30000; // 30 seconds without packets = reconnect

  function startStream() {
    stopStream();
    retryDelayMs = 1000;
    lastPacketTime = Date.now();
    if (liveStatus) {
      liveStatus.classList.remove("bg-danger", "paused");
      liveStatus.classList.add("bg-success", "pulse");
      liveStatus.textContent = "Live";
    }
    eventSource = new EventSource(`/api/stream/packets?last_id=${lastId}`);

    // Heartbeat timeout detection
    function checkHeartbeat() {
      const timeSinceLastPacket = Date.now() - lastPacketTime;
      if (timeSinceLastPacket > HEARTBEAT_TIMEOUT_MS && !paused) {
        console.warn("Stream heartbeat timeout - reconnecting");
        liveStatus.classList.remove("bg-success", "pulse");
        liveStatus.classList.add("bg-danger");
        if (liveReconnectHint) {
          liveReconnectHint.textContent = "Connection stalled - reconnecting…";
          liveReconnectHint.classList.remove("d-none");
        }
        scheduleReconnect();
      } else if (!paused) {
        heartbeatTimer = setTimeout(checkHeartbeat, 5000); // Check every 5 seconds
      }
    }
    heartbeatTimer = setTimeout(checkHeartbeat, 5000);

    eventSource.onmessage = (evt) => {
      lastPacketTime = Date.now(); // Update last packet time
      liveStatus.classList.remove("bg-danger");
      liveStatus.classList.add("bg-success", "pulse");
      liveStatus.classList.remove("paused");
      liveReconnectHint?.classList.add("d-none");
      liveReconnectHint?.classList.remove("text-warning");
      retryDelayMs = 1000; // reset backoff after a good message
      try {
        const packet = JSON.parse(evt.data);

        // Process the packet to draw arcs and update markers
        handlePacket(packet);

        // Handle text messages
        if (packet.portnum_name === 'TEXT_MESSAGE_APP') {
          handleTextMessage(packet);
        }

        // Handle traceroutes explicitly
        if (packet.portnum_name === 'TRACEROUTE_APP') {
          // Already handled in handlePacket, but ensure it's visible
          // The traceroute path rendering happens in handlePacket
        }

        // Update stats
        liveCounter++;
        liveCounterEl.textContent = liveCounter.toString();
      } catch (e) {
        console.error("Bad packet event", e);
      }
    };
    eventSource.onerror = (error) => {
      if (heartbeatTimer) {
        clearTimeout(heartbeatTimer);
        heartbeatTimer = null;
      }
      liveStatus.classList.remove("bg-success", "pulse");
      liveStatus.classList.add("bg-danger");
      if (liveReconnectHint) {
        liveReconnectHint.textContent = "Connection error - reconnecting…";
        liveReconnectHint.classList.remove("d-none");
      }
      console.warn("SSE stream error, reconnecting:", error);
      // Close the event source before reconnecting
      if (eventSource) {
        try {
          eventSource.close();
        } catch (e) {
          // Ignore errors when closing
        }
        eventSource = null;
      }
      scheduleReconnect();
    };
  }

  async function showNodeDetails(nodeId) {
    if (!nodeId) return;
    selectedNodeId = nodeId;

    // Get node details panel element
    if (!nodeDetailsPanel) {
      nodeDetailsPanel = document.getElementById("node-details-panel");
    }
    if (!nodeDetailsPanel) return;

    // Show loading state
    nodeDetailsPanel.classList.remove("d-none");
    nodeDetailsPanel.querySelector(".node-details-content").innerHTML = `
      <div class="text-center py-4">
        <div class="spinner-border text-primary" role="status"></div>
        <p class="mt-2 text-muted small">Loading node details...</p>
      </div>
    `;

    try {
      // Fetch node info from API
      const response = await fetch(`/api/node/${nodeId}/info`);
      if (!response.ok) {
        throw new Error(`Failed to load node info: ${response.status}`);
      }
      const data = await response.json();
      const node = data.node;

      // Get location data if available
      const loc = nodeLocations.get(nodeId);

      // Format last seen
      let lastSeenStr = "Unknown";
      if (node.last_seen) {
        const lastSeen = new Date(node.last_seen * 1000);
        lastSeenStr = lastSeen.toLocaleString();
      } else if (loc?._lastSeenMs) {
        const lastSeen = new Date(loc._lastSeenMs);
        lastSeenStr = lastSeen.toLocaleString();
      }

      // Build node details HTML
      const displayName = node.long_name || node.short_name || node.display_name || `Node ${nodeId}`;
      const hexId = node.hex_id || `!${Number(nodeId).toString(16).padStart(8, '0')}`;

      let detailsHTML = `
        <div class="node-details-header mb-3">
          <div class="d-flex justify-content-between align-items-start">
            <div>
              <h6 class="mb-1">${escapeHtml(displayName)}</h6>
              <div class="small text-muted">${escapeHtml(hexId)}</div>
            </div>
            <button class="btn btn-sm btn-link text-white p-0" id="close-node-details" aria-label="Close">
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
        </div>
        <div class="node-details-body">
          <div class="mb-3">
            <strong class="small text-muted d-block mb-1">Hardware</strong>
            <div>${escapeHtml(node.hw_model || "Unknown")}</div>
          </div>
          ${node.role ? `
          <div class="mb-3">
            <strong class="small text-muted d-block mb-1">Role</strong>
            <div>${escapeHtml(node.role)}</div>
          </div>
          ` : ""}
          ${node.primary_channel ? `
          <div class="mb-3">
            <strong class="small text-muted d-block mb-1">Primary Channel</strong>
            <div>${escapeHtml(node.primary_channel)}</div>
          </div>
          ` : ""}
          <div class="mb-3">
            <strong class="small text-muted d-block mb-1">Last Seen</strong>
            <div>${lastSeenStr}</div>
          </div>
          ${node.packet_count_24h !== undefined ? `
          <div class="mb-3">
            <strong class="small text-muted d-block mb-1">Packets (24h)</strong>
            <div>${node.packet_count_24h.toLocaleString()}</div>
          </div>
          ` : ""}
          ${loc ? `
          <div class="mb-3">
            <strong class="small text-muted d-block mb-1">Location</strong>
            <div>${loc.latitude?.toFixed(6)}, ${loc.longitude?.toFixed(6)}</div>
          </div>
          ` : ""}
          ${loc?._live ? `
          ${loc._live.avg_rssi !== undefined ? `
          <div class="mb-3">
            <strong class="small text-muted d-block mb-1">Avg RSSI</strong>
            <div>${loc._live.avg_rssi.toFixed(1)} dBm</div>
          </div>
          ` : ""}
          ${loc._live.avg_snr !== undefined ? `
          <div class="mb-3">
            <strong class="small text-muted d-block mb-1">Avg SNR</strong>
            <div>${loc._live.avg_snr.toFixed(1)} dB</div>
          </div>
          ` : ""}
          ` : ""}
          <div class="mt-3 pt-3 border-top">
            <a href="/node/${nodeId}" class="btn btn-sm btn-primary w-100">
              <i class="bi bi-info-circle me-1"></i> View Full Details
            </a>
          </div>
        </div>
      `;

      nodeDetailsPanel.querySelector(".node-details-content").innerHTML = detailsHTML;

      // Wire up close button
      const closeBtn = nodeDetailsPanel.querySelector("#close-node-details");
      if (closeBtn) {
        closeBtn.addEventListener("click", closeNodeDetails);
      }

      // Center map on node if location available
      if (loc && loc.latitude && loc.longitude) {
        map.setView([loc.latitude, loc.longitude], Math.max(map.getZoom(), 13));
      }
    } catch (error) {
      console.error("Error loading node details:", error);
      nodeDetailsPanel.querySelector(".node-details-content").innerHTML = `
        <div class="text-center py-4 text-danger">
          <i class="bi bi-exclamation-triangle me-2"></i>
          <div class="small">Failed to load node details</div>
          <button class="btn btn-sm btn-outline-secondary mt-2" id="close-node-details">Close</button>
        </div>
      `;
      const closeBtn = nodeDetailsPanel.querySelector("#close-node-details");
      if (closeBtn) {
        closeBtn.addEventListener("click", closeNodeDetails);
      }
    }
  }

  function closeNodeDetails() {
    if (nodeDetailsPanel) {
      nodeDetailsPanel.classList.add("d-none");
    }
    selectedNodeId = null;
  }

  function escapeHtml(text) {
    if (text == null) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function wireUI() {
    if (toggleCluster) {
      toggleCluster.checked = true;
      clusterEnabled = true;
    }
    updateClusterLayer();
    const panel = document.getElementById("live-map-panel");
    const panelToggle = document.getElementById("live-map-panel-toggle");
    if (panel && panelToggle) {
      panel.classList.remove("collapsed");
      panelToggle.addEventListener("click", () => {
        const collapsed = panel.classList.toggle("collapsed");
        panelToggle.innerHTML = collapsed ? '<i class="bi bi-sliders"></i>' : '<i class="bi bi-x-lg"></i>';
        panelToggle.setAttribute("aria-expanded", String(!collapsed));
        if (collapsed) {
          panelToggle.classList.add("pulse");
        } else {
          panelToggle.classList.remove("pulse");
        }
      });
      // First-load cue if panel is auto-collapsed on mobile
      panelToggle.classList.add("pulse");
    }

    pauseBtn.addEventListener("click", () => {
      paused = !paused;
      pauseBtn.textContent = paused ? "Resume" : "Pause";
      liveStatus.textContent = paused ? "Paused" : "Live";
      if (paused) {
        liveStatus.classList.add("paused");
        liveStatus.classList.remove("bg-success", "pulse");
        stopStream();
      } else {
        liveStatus.classList.remove("paused");
        liveStatus.classList.add("bg-success", "pulse");
        startStream();
      }
    });
    portFilter.addEventListener("change", () => {
      // Simply resume stream; filter is applied client-side
    });

    if (legendToggle && legendBody) {
      legendToggle.addEventListener("click", () => {
        const isHidden = legendBody.classList.toggle("d-none");
        legendToggle.innerHTML = isHidden ? '<i class="bi bi-chevron-down"></i>' : '<i class="bi bi-chevron-up"></i>';
      });
    }

    const onboardingKey = "live-map-onboarding-dismissed";
    if (localStorage.getItem(onboardingKey)) {
      helpBox?.classList.add("d-none");
    }
    dismissHelp?.addEventListener("click", () => {
      helpBox?.classList.add("d-none");
      localStorage.setItem(onboardingKey, "1");
    });
    resetOnboarding?.addEventListener("click", (e) => {
      e.preventDefault();
      localStorage.removeItem(onboardingKey);
      helpBox?.classList.remove("d-none");
    });

    gatewaySolo?.addEventListener("click", () => {
      const val = gatewayFilter?.value;
      if (!val) return;
      // Apply simple filter: hide other halos
      gatewayHalos.forEach((layer, gwId) => {
        if (String(gwId) !== val) {
          layer.setStyle({ opacity: 0, fillOpacity: 0 });
        } else {
          const meta = gatewayActivity.get(gwId);
          const intensity = meta ? Math.min(0.8, 0.2 + meta.count / 20) : 0.4;
          layer.setStyle({ opacity: intensity, fillOpacity: intensity * 0.4 });
        }
      });
    });

    gatewayClear?.addEventListener("click", () => {
      gatewayFilter.value = "";
      gatewayHalos.forEach((layer, gwId) => {
        const meta = gatewayActivity.get(gwId);
        const intensity = meta ? Math.min(0.8, 0.2 + meta.count / 20) : 0.3;
        layer.setStyle({ opacity: intensity, fillOpacity: intensity * 0.4 });
      });
    });

    toggleHeat?.addEventListener("change", () => {
      heatEnabled = toggleHeat.checked;
      updateHeatLayer();
    });
    toggleCluster?.addEventListener("change", () => {
      clusterEnabled = toggleCluster.checked;
      updateClusterLayer();
      updateAllNameLabels();
    });

    const toggleNeighbors = document.getElementById("toggle-neighbors");
    toggleNeighbors?.addEventListener("change", () => {
      neighborsEnabled = toggleNeighbors.checked;
      updateNeighborLayer();
    });

    const toggleTrails = document.getElementById("toggle-trails");
    toggleTrails?.addEventListener("change", () => {
      trailsEnabled = toggleTrails.checked;
      updateTrailsLayer();
    });

    if (timeWindowSelect) {
      timeWindowSelect.addEventListener("change", () => {
        const val = Number(timeWindowSelect.value) || 900000;
        applyTimeWindow(val);
      });
    }

    // refresh hover tooltips
    Object.keys(markers).forEach((id) => attachMarkerHover(Number(id)));
  }

  document.addEventListener("DOMContentLoaded", async () => {
    initMap();
    wireUI();
    await loadLocations();
    applyTimeWindow(displayWindowMs);
    startStream();
    setInterval(prunePolylines, 5000);
    setInterval(refreshAges, 20000);
  });

  function fitToNodes() {
    if (!map || nodeLocations.size === 0) return;
    const coords = [];
    nodeLocations.forEach((loc) => {
      if (loc.latitude != null && loc.longitude != null) {
        coords.push([loc.latitude, loc.longitude]);
      }
    });
    if (coords.length === 0) return;
    const bounds = L.latLngBounds(coords);
    map.fitBounds(bounds.pad(0.1));
  }

  function updateGatewayHalo(gatewayId, gatewayLoc) {
    const now = Date.now();
    const meta = gatewayActivity.get(gatewayId) || { lastSeen: now, count: 0 };
    meta.lastSeen = now;
    meta.count += 1;
    gatewayActivity.set(gatewayId, meta);

    let halo = gatewayHalos.get(gatewayId);
    if (!halo) {
      halo = L.circle([gatewayLoc.latitude, gatewayLoc.longitude], {
        radius: 800,
        color: "#0dcaf0",
        fillColor: "#0dcaf0",
        opacity: 0.5,
        fillOpacity: 0.2,
        weight: 1,
      }).addTo(gatewayLayerGroup || map);
      gatewayHalos.set(gatewayId, halo);
    }
    const intensity = Math.min(0.8, 0.2 + meta.count / 20);
    const radius = 500 + Math.min(2000, meta.count * 50);
    halo.setStyle({
      opacity: intensity,
      fillOpacity: intensity * 0.4,
    });
    halo.setRadius(radius);
    halo.bindTooltip(`Gateway ${gatewayId}<br>Last heard ${formatRelative(meta.lastSeen)}`, {
      permanent: false,
      direction: "top",
    });
  }

  function updateHeatLayer() {
    if (!heatEnabled) {
      if (heatLayer) {
        map.removeLayer(heatLayer);
        heatLayer = null;
      }
      return;
    }
    const points = [];
    nodeLocations.forEach((loc) => {
      if (loc.latitude != null && loc.longitude != null) {
        const age = loc._lastSeenMs ? Date.now() - loc._lastSeenMs : Infinity;
        if (age <= displayWindowMs) {
          points.push([loc.latitude, loc.longitude, 0.5]);
        }
      }
    });
    if (!heatLayer) {
      heatLayer = L.heatLayer(points, { radius: 25, blur: 15, maxZoom: 12 });
      heatLayer.addTo(map);
    } else {
      heatLayer.setLatLngs(points);
    }
  }

  function updateClusterLayer() {
    if (!clusterLayer) return;
    Object.values(markers).forEach((m) => placeMarkerOnLayer(m));
    if (clusterEnabled) {
      if (!map.hasLayer(clusterLayer)) map.addLayer(clusterLayer);
      if (markerLayer && map.hasLayer(markerLayer) && markerLayer.getLayers().length === 0) {
        map.removeLayer(markerLayer);
      }
    } else {
      clusterLayer.clearLayers();
      if (map.hasLayer(clusterLayer)) map.removeLayer(clusterLayer);
      if (markerLayer && !map.hasLayer(markerLayer)) map.addLayer(markerLayer);
    }
  }

  function trackNeighborConnection(node1Id, node2Id, gatewayId, packet) {
    if (!node1Id || !node2Id || node1Id === node2Id) return;

    // Create a consistent key (always smaller:larger)
    const key = node1Id < node2Id ? `${node1Id}:${node2Id}` : `${node2Id}:${node1Id}`;

    const now = Date.now();
    const existing = neighborConnections.get(key) || {
      lastSeen: 0,
      count: 0,
      rssiSum: 0,
      snrSum: 0,
      rssiCount: 0,
      snrCount: 0,
    };

    existing.lastSeen = now;
    existing.count += 1;

    if (packet.rssi != null) {
      existing.rssiSum += Number(packet.rssi);
      existing.rssiCount += 1;
    }
    if (packet.snr != null) {
      existing.snrSum += Number(packet.snr);
      existing.snrCount += 1;
    }

    neighborConnections.set(key, existing);

    // Render neighbor connections if enabled
    if (neighborsEnabled) {
      renderNeighborConnections();
    }
  }

  // Calculate haversine distance between two coordinates (in km)
  function calculateDistance(lat1, lon1, lat2, lon2) {
    const R = 6371; // Earth's radius in km
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  }

  function renderNeighborConnections() {
    if (!neighborLayer) return;

    // Clear existing neighbor lines
    neighborLayer.clearLayers();

    const now = Date.now();
    const maxAge = displayWindowMs; // Use same window as other features
    const MAX_RF_DISTANCE_KM = 100; // Maximum plausible RF distance in km

    neighborConnections.forEach((conn, key) => {
      // Skip stale connections
      if (now - conn.lastSeen > maxAge) return;

      const [node1Id, node2Id] = key.split(':').map(Number);
      const loc1 = nodeLocations.get(node1Id);
      const loc2 = nodeLocations.get(node2Id);

      if (!loc1 || !loc2 || !loc1.latitude || !loc2.latitude) return;

      // Filter out unrealistic RF distances (e.g., MQTT server to all of Canada)
      const distanceKm = calculateDistance(
        loc1.latitude, loc1.longitude,
        loc2.latitude, loc2.longitude
      );
      if (distanceKm > MAX_RF_DISTANCE_KM) {
        return; // Skip this connection - too far for realistic RF
      }

      // Calculate average signal metrics
      const avgRssi = conn.rssiCount > 0 ? conn.rssiSum / conn.rssiCount : null;
      const avgSnr = conn.snrCount > 0 ? conn.snrSum / conn.snrCount : null;

      // Get signal quality for styling
      const signalInfo = getSignalQuality(avgRssi, avgSnr);
      const color = signalInfo ? signalInfo.color : "#6c757d";
      const weight = signalInfo ? signalInfo.weight : 2;

      // Determine if direct or multi-hop (based on connection count - more packets = likely direct)
      // Use dashed line for connections with fewer packets (likely multi-hop)
      const dashArray = conn.count < 3 ? "8 8" : null;

      const line = L.polyline(
        [[loc1.latitude, loc1.longitude], [loc2.latitude, loc2.longitude]],
        {
          color,
          weight,
          opacity: 0.6,
          dashArray,
          className: "neighbor-connection",
        }
      );

      // Add tooltip with connection info
      const tooltipText = `Neighbors<br>Packets: ${conn.count}<br>${
        avgRssi != null ? `Avg RSSI: ${avgRssi.toFixed(1)} dBm<br>` : ""
      }${avgSnr != null ? `Avg SNR: ${avgSnr.toFixed(1)} dB` : ""}`;
      line.bindTooltip(tooltipText, {
        permanent: false,
        direction: "top",
        className: "neighbor-tooltip",
      });

      line.addTo(neighborLayer);
    });
  }

  function updateNeighborLayer() {
    if (neighborsEnabled) {
      renderNeighborConnections();
      if (!map.hasLayer(neighborLayer)) {
        map.addLayer(neighborLayer);
      }
    } else {
      if (map.hasLayer(neighborLayer)) {
        map.removeLayer(neighborLayer);
      }
      neighborLayer.clearLayers();
    }
  }
})();
