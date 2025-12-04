(() => {
  let lastId = 0;
  let paused = false;
  let timer = null;
  let seenIds = new Set();
  const chatList = document.getElementById("chat-list");
  const chatStatus = document.getElementById("chat-status");
  const chatCountEl = document.getElementById("chat-count");
  const filterText = document.getElementById("filter-text");
  const filterFrom = document.getElementById("filter-from");
  const filterLimit = document.getElementById("filter-limit");
  const refreshBtn = document.getElementById("chat-refresh");
  const pauseBtn = document.getElementById("chat-pause");

  // Mini-map state
  let minimap = null;
  let minimapMarkers = new Map();
  let minimapMessageBubbles = new Map();
  let minimapLinks = [];
  const minimapCard = document.getElementById("chat-minimap-card");
  const minimapBody = document.getElementById("chat-minimap-body");
  const toggleMinimapBtn = document.getElementById("toggle-minimap");

  // Helper to generate consistent colors from strings
  function stringToColor(str) {
    if (!str) return '#6c757d';
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }
    const c = (hash & 0x00FFFFFF).toString(16).toUpperCase();
    return '#' + '00000'.substring(0, 6 - c.length) + c;
  }

  // Helper to get initials from name
  function getInitials(name) {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return name.substring(0, 2).toUpperCase();
  }

  // Helper to get role badge element
  function getRoleBadge(role) {
    if (!role) return null;
    const roleColors = {
      'ROUTER': 'bg-success',
      'CLIENT': 'bg-primary',
      'REPEATER': 'bg-warning',
      'CLIENT_MUTE': 'bg-secondary',
      'ROUTER_CLIENT': 'bg-info',
      'SENSOR': 'bg-danger'
    };
    const color = roleColors[role] || 'bg-secondary';
    const badge = document.createElement("span");
    badge.className = `badge ${color} badge-sm ms-1`;
    badge.textContent = role.replace(/_/g, ' ');
    return badge;
  }

  function initMinimap() {
    if (!document.getElementById("chat-minimap")) return;

    const isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
    const tileUrl = isDark
      ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
      : 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';

    minimap = L.map("chat-minimap", { zoomControl: false }).setView([40.0, -95.0], 3);
    L.tileLayer(tileUrl, {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 18
    }).addTo(minimap);

    // Toggle minimap visibility
    if (toggleMinimapBtn) {
      toggleMinimapBtn.addEventListener("click", () => {
        const isHidden = minimapBody.classList.contains("d-none");
        if (isHidden) {
          minimapBody.classList.remove("d-none");
          toggleMinimapBtn.querySelector("i").classList.remove("bi-chevron-down");
          toggleMinimapBtn.querySelector("i").classList.add("bi-chevron-up");
          setTimeout(() => minimap.invalidateSize(), 100);
        } else {
          minimapBody.classList.add("d-none");
          toggleMinimapBtn.querySelector("i").classList.remove("bi-chevron-up");
          toggleMinimapBtn.querySelector("i").classList.add("bi-chevron-down");
        }
      });
    }
  }

  function updateMinimap(messages) {
    if (!minimap) return;

    // Clear old message bubbles (older than 5 minutes)
    const now = Date.now();
    minimapMessageBubbles.forEach((bubble, msgId) => {
      if (now - bubble.created > 300000) { // 5 minutes
        minimap.removeLayer(bubble.marker);
        minimapMessageBubbles.delete(msgId);
      }
    });

    // Clear old links
    minimapLinks.forEach(link => minimap.removeLayer(link));
    minimapLinks = [];

    // Get unique nodes with locations from recent messages
    const nodeMap = new Map();
    messages.slice(0, 100).forEach(msg => {
      if (msg.from_node_id && msg.from_latitude && msg.from_longitude) {
        if (!nodeMap.has(msg.from_node_id)) {
          nodeMap.set(msg.from_node_id, {
            id: msg.from_node_id,
            name: msg.from_name || msg.from_hex || `!${msg.from_node_id.toString(16).padStart(8, '0')}`,
            lat: msg.from_latitude,
            lon: msg.from_longitude,
            city: msg.from_city,
            color: stringToColor(msg.from_node_id.toString()),
            messages: []
          });
        }
        nodeMap.get(msg.from_node_id).messages.push(msg);
      }
    });

    // Update or create markers for nodes
    const bounds = [];
    nodeMap.forEach((node, nodeId) => {
      bounds.push([node.lat, node.lon]);

      if (!minimapMarkers.has(nodeId)) {
        const marker = L.circleMarker([node.lat, node.lon], {
          radius: 8,
          fillColor: node.color,
          color: '#fff',
          weight: 2,
          fillOpacity: 0.8
        });
        marker.bindTooltip(`${node.name}${node.city ? ` (${node.city})` : ''}`, { permanent: false });
        marker.addTo(minimap);
        minimapMarkers.set(nodeId, marker);
      }

      // Add message bubble for most recent message from this node
      const recentMsg = node.messages[0];
      if (recentMsg && !minimapMessageBubbles.has(recentMsg.id)) {
        const bubbleMarker = L.marker([node.lat, node.lon], {
          icon: L.divIcon({
            className: 'chat-message-bubble',
            html: `<div style="background: ${node.color}; color: white; padding: 2px 6px; border-radius: 10px; font-size: 10px; white-space: nowrap; max-width: 150px; overflow: hidden; text-overflow: ellipsis;">${(recentMsg.text || '').substring(0, 30)}</div>`,
            iconSize: [150, 20],
            iconAnchor: [75, 10]
          })
        });
        bubbleMarker.setOpacity(0.7);
        bubbleMarker.addTo(minimap);
        minimapMessageBubbles.set(recentMsg.id, { marker: bubbleMarker, created: now });

        // Auto-remove after 2 minutes
        setTimeout(() => {
          if (minimapMessageBubbles.has(recentMsg.id)) {
            minimap.removeLayer(bubbleMarker);
            minimapMessageBubbles.delete(recentMsg.id);
          }
        }, 120000);
      }

      // Draw links to nodes that heard messages from this node
      if (recentMsg && recentMsg.heard_by) {
        recentMsg.heard_by.forEach(heard => {
          if (heard.node_id && nodeMap.has(heard.node_id)) {
            const targetNode = nodeMap.get(heard.node_id);
            const link = L.polyline(
              [[node.lat, node.lon], [targetNode.lat, targetNode.lon]],
              { color: node.color, weight: 2, opacity: 0.4, dashArray: '5, 5' }
            );
            link.addTo(minimap);
            minimapLinks.push(link);

            // Auto-remove link after 1 minute
            setTimeout(() => {
              const idx = minimapLinks.indexOf(link);
              if (idx >= 0) {
                minimap.removeLayer(link);
                minimapLinks.splice(idx, 1);
              }
            }, 60000);
          }
        });
      }
    });

    // Fit map to show all nodes
    if (bounds.length > 0) {
      minimap.fitBounds(bounds, { padding: [20, 20] });
    }
  }

  function renderMessage(msg) {
    if (seenIds.has(msg.id)) return;
    seenIds.add(msg.id);

    const from = msg.from_name || msg.from_hex || msg.from_node_id || "Unknown";
    const fromId = msg.from_node_id || msg.from_hex || from;
    const to = msg.to_name || msg.to_hex || msg.to_node_id || msg.gateway_id || "";
    const fromColor = stringToColor(fromId.toString());
    const initials = getInitials(from);

    const wrapper = document.createElement("div");
    wrapper.className = "chat-message";

    // Create message bubble
    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";

    // Header with avatar and name - compact inline layout
    const header = document.createElement("div");
    header.className = "chat-header d-flex align-items-center";
    const avatar = document.createElement("div");
    avatar.className = "chat-avatar me-2";
    avatar.style.backgroundColor = fromColor;
    avatar.textContent = initials;

    const meta = document.createElement("div");
    meta.className = "chat-meta flex-grow-1 d-flex align-items-center flex-wrap";

    const sender = document.createElement("strong");
    sender.className = "chat-sender text-truncate";
    sender.textContent = from;
    meta.appendChild(sender);

    if (msg.from_city) {
      const cityBadge = document.createElement("span");
      cityBadge.className = "badge bg-secondary bg-opacity-50 ms-1 small";
      cityBadge.textContent = msg.from_city;
      meta.appendChild(cityBadge);
    }

    const roleBadge = getRoleBadge(msg.from_role);
    if (roleBadge) meta.appendChild(roleBadge);

    if (to) {
      const toWrap = document.createElement("span");
      toWrap.className = "text-muted small d-flex align-items-center gap-1";
      const toIcon = document.createElement("i");
      toIcon.className = "bi bi-arrow-right-short";
      const toText = document.createElement("span");
      toText.className = "text-truncate";
      toText.textContent = String(to);
      toWrap.appendChild(toIcon);
      toWrap.appendChild(toText);
      meta.appendChild(toWrap);
    }

    const timeLabel = document.createElement("small");
    timeLabel.className = "text-muted ms-auto";
    timeLabel.textContent = msg.timestamp_str || "";
    meta.appendChild(timeLabel);

    header.appendChild(avatar);
    header.appendChild(meta);

    // Message body
    const body = document.createElement("div");
    body.className = "chat-body";
    body.textContent = msg.text || "[no content]";

    // Heard by section with badges
    if (msg.heard_by && msg.heard_by.length) {
      const heardDiv = document.createElement("div");
      heardDiv.className = "chat-heard-by border-top";

      const label = document.createElement("small");
      label.className = "text-muted d-inline me-2";
      const icon = document.createElement("i");
      icon.className = "bi bi-broadcast me-1";
      label.appendChild(icon);
      label.appendChild(document.createTextNode("Heard by:"));
      heardDiv.appendChild(label);

      const badgesContainer = document.createElement("span");
      badgesContainer.className = "d-inline-flex flex-wrap gap-1";

      msg.heard_by.forEach((h) => {
        const display = h.display || h.id || h.hex || "";
        if (!display) return;
        const badge = document.createElement("span");
        badge.className = "badge bg-light text-dark border me-1 mb-1";
        badge.style.setProperty("border-color", stringToColor(display), "important");
        badge.textContent = String(display);
        badgesContainer.appendChild(badge);
      });

      if (badgesContainer.children.length) {
        heardDiv.appendChild(badgesContainer);
        body.appendChild(heardDiv);
      }
    }

    bubble.appendChild(header);
    bubble.appendChild(body);
    wrapper.appendChild(bubble);

    chatList.prepend(wrapper);
    while (chatList.children.length > 500) {
      chatList.removeChild(chatList.lastChild);
    }
  }

  function applyFilters(data) {
    const search = filterText.value.trim().toLowerCase();
    const fromFilter = filterFrom.value.trim().toLowerCase();
    return data.filter((msg) => {
      const matchesText = !search || (msg.text || "").toLowerCase().includes(search);
      const matchesFrom =
        !fromFilter ||
        (msg.from_hex && msg.from_hex.toLowerCase().includes(fromFilter)) ||
        (msg.from_name && msg.from_name.toLowerCase().includes(fromFilter));
      return matchesText && matchesFrom;
    });
  }

  async function fetchMessages(reset = false) {
    if (paused) return;
    const limit = parseInt(filterLimit.value, 10) || 500;
    if (reset) {
      seenIds.clear();
      chatList.innerHTML = "";
      chatCountEl.textContent = "0";
      lastId = 0;
    }
    const params = new URLSearchParams({ limit: limit.toString() });
    if (!reset && lastId > 0) {
      params.append("after_id", lastId.toString());
    }
    try {
      const resp = await fetch(`/api/chat/messages?${params.toString()}`);
      const data = await resp.json();
      const messages = Array.isArray(data.messages) ? data.messages : [];
      if (messages.length === 0) return;
      messages.forEach((m) => {
        lastId = Math.max(lastId, m.id || 0);
      });
      const filtered = applyFilters(messages);
      let added = 0;
      filtered.reverse().forEach((m) => {
        const before = seenIds.size;
        renderMessage(m); // oldest first for prepend order
        if (seenIds.size > before) added += 1;
      });
      chatCountEl.textContent = (parseInt(chatCountEl.textContent, 10) + added).toString();
      chatStatus.classList.remove("bg-danger");
      chatStatus.classList.add("bg-success");

      // Update mini-map with all messages (for node positions and links)
      if (minimap && messages.length > 0) {
        updateMinimap(messages);
      }
    } catch (e) {
      console.error("Chat fetch failed", e);
      chatStatus.classList.remove("bg-success");
      chatStatus.classList.add("bg-danger");
    }
  }

  function startPolling() {
    if (timer) clearInterval(timer);
    timer = setInterval(() => fetchMessages(false), 3000);
  }

  document.addEventListener("DOMContentLoaded", () => {
    initMinimap();
    refreshBtn.addEventListener("click", () => fetchMessages(true));
    pauseBtn.addEventListener("click", () => {
      paused = !paused;
      pauseBtn.textContent = paused ? "Resume" : "Pause";
      chatStatus.textContent = paused ? "Paused" : "Live";
    });
    filterText.addEventListener("input", () => {}); // filters applied on next fetch
    filterFrom.addEventListener("input", () => {});
    filterLimit.addEventListener("change", () => fetchMessages(true));
    fetchMessages(true);
    startPolling();
  });
})();
