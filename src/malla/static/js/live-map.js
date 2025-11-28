(() => {
  let map;
  let markers = {};
  let nodeLocations = new Map();
  let polylines = [];
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

    gatewayLayerGroup = L.layerGroup().addTo(map);

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
      attachMarkerHover(node.node_id);
      updateMarkerStyle(node.node_id);
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
      label.addTo(nameLabelLayer);
      nameLabels.set(node.node_id, label);
    } else {
      label.setLatLng([node.latitude, node.longitude]);
      const el = label.getElement();
      if (el) el.innerHTML = `<div>${name}</div>`;
    }
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

  function drawLink(fromNodeId, toNodeId, packet, opts = {}) {
    const fromLoc = nodeLocations.get(fromNodeId);
    const toLoc = nodeLocations.get(toNodeId);
    if (!fromLoc || !toLoc) return;

    const color =
      portColors[packet.portnum_name] || (packet.processed_successfully ? "#6f42c1" : "#dc3545");

    const line = L.polyline(
      [
        [fromLoc.latitude, fromLoc.longitude],
        [toLoc.latitude, toLoc.longitude],
      ],
      {
        color,
        weight: opts.weight || 3,
        opacity: opts.opacity ?? 0.8,
        dashArray: opts.dashArray || "10 14",
        className: "live-arc",
      }
    ).addTo(map);

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
        }
        lastKnownId = nid;
      }
    } else {
      // Determine best available endpoints for animation
      const startLoc = fromLoc || gatewayLoc;
      const endLoc = toLoc || gatewayLoc;
      const startId = fromLoc?.node_id || fromId || gatewayId;
      const endId = endLoc?.node_id || toId || gatewayId;

      if (startLoc && endLoc && startId != null && endId != null && startId !== endId) {
        drawLink(startId, endId, packet);
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

  async function loadLocations() {
    try {
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
    } catch (e) {
      console.error("Failed to load locations", e);
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
    } catch (e) {
      console.error("Failed to load node stats", e);
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

  function startStream() {
    stopStream();
    retryDelayMs = 1000;
    if (liveStatus) {
      liveStatus.classList.remove("bg-danger", "paused");
      liveStatus.classList.add("bg-success", "pulse");
      liveStatus.textContent = "Live";
    }
    eventSource = new EventSource(`/api/stream/packets?last_id=${lastId}`);
    eventSource.onmessage = (evt) => {
      liveStatus.classList.remove("bg-danger");
      liveStatus.classList.add("bg-success", "pulse");
      liveStatus.classList.remove("paused");
      liveReconnectHint?.classList.add("d-none");
      liveReconnectHint?.classList.remove("text-warning");
      retryDelayMs = 1000; // reset backoff after a good message
      try {
        const packet = JSON.parse(evt.data);
        handlePacket(packet);
      } catch (e) {
        console.error("Bad packet event", e);
      }
    };
    eventSource.onerror = () => {
      liveStatus.classList.remove("bg-success", "pulse");
      liveStatus.classList.add("bg-danger");
      if (liveReconnectHint) {
        liveReconnectHint.textContent = "Reconnecting…";
        liveReconnectHint.classList.remove("d-none");
      }
      scheduleReconnect();
    };
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
})();
