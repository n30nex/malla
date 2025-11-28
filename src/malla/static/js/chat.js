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

  function renderMessage(msg) {
    if (seenIds.has(msg.id)) return;
    seenIds.add(msg.id);

    const wrapper = document.createElement("div");
    wrapper.className = "mb-3 pb-2 border-bottom";
    const from = msg.from_name || msg.from_hex || msg.from_node_id || "Unknown";
    const to = msg.to_name || msg.to_hex || msg.to_node_id || msg.gateway_id || "";
    const header = document.createElement("div");
    header.className = "d-flex justify-content-between align-items-center";
    header.innerHTML = `<div><strong>${from}</strong> ${to ? "&rarr; " + to : ""}</div><small class="text-muted">${msg.timestamp_str}</small>`;
    const body = document.createElement("div");
    body.className = "mt-1";
    body.textContent = msg.text || "[no content]";

    let heardByLine = "";
    if (msg.heard_by && msg.heard_by.length) {
      const heard = msg.heard_by.map((h) => h.display || h.id || h.hex || "").filter(Boolean);
      if (heard.length) {
        heardByLine = `<div class="text-muted small mt-1">Heard by: ${heard.join(", ")}</div>`;
      }
    }
    if (heardByLine) {
      const heardDiv = document.createElement("div");
      heardDiv.innerHTML = heardByLine;
      body.appendChild(heardDiv);
    }

    wrapper.appendChild(header);
    wrapper.appendChild(body);
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
