let activeNodeId = localStorage.getItem("blockchainActiveNode") || "";
let setupVisible = false;
let cachedNodes = [];

async function api(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.message || "Request failed");
  return data;
}

function setResult(id, message, ok = true) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = message;
  el.className = ok ? "result success" : "result error";
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

function shortKey(value, size = 34) {
  const text = String(value ?? "");
  return text.length <= size ? text : text.slice(0, size) + "…";
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function toggleSetup(force) {
  setupVisible = typeof force === "boolean" ? force : !setupVisible;
  document.getElementById("setup").classList.toggle("hidden", !setupVisible);
  if (setupVisible) {
    suggestPort(cachedNodes);
    document.getElementById("name").focus();
  }
}

function selectNode(id) {
  activeNodeId = id;
  localStorage.setItem("blockchainActiveNode", id);
  refresh();
}

function suggestPort(nodes) {
  const used = new Set((nodes || []).map(n => Number(n.port)));
  let port = 5003;
  while (used.has(port)) port += 1;
  document.getElementById("p2p").value = port;
}

function renderNodeManager(nodes) {
  cachedNodes = nodes || [];
  const select = document.getElementById("activeNode");
  if (!nodes.length) {
    select.innerHTML = '<option value="">No nodes running</option>';
    document.getElementById("nodeCards").innerHTML = '<div class="muted">Create your first node above.</div>';
    document.getElementById("dashboard").classList.add("hidden");
    return;
  }

  if (!nodes.some(n => n.id === activeNodeId)) activeNodeId = nodes[0].id;
  localStorage.setItem("blockchainActiveNode", activeNodeId);
  select.innerHTML = nodes.map(n => `<option value="${esc(n.id)}">${esc(n.name)} · :${esc(n.port)}</option>`).join("");
  select.value = activeNodeId;

  document.getElementById("nodeCards").innerHTML = nodes.map(n => `
    <button class="node-card ${n.id === activeNodeId ? "selected" : ""}" onclick="selectNode('${esc(n.id)}')">
      <div class="row-between"><strong>${esc(n.name)}</strong><span class="node-status ${esc(n.status)}">${esc(n.status)}</span></div>
      <div class="mono">${esc(n.host)}:${esc(n.port)}</div>
      <div class="node-meta">${esc(String(n.consensus).toUpperCase())} · ${esc(n.room_id)}</div>
    </button>`).join("");

  document.getElementById("dashboard").classList.remove("hidden");
}

async function startNode() {
  try {
    const name = document.getElementById("name").value.trim();
    const p2p = Number(document.getElementById("p2p").value);
    if (!name) throw new Error("Enter a unique node name.");
    if (!p2p) throw new Error("Enter a valid P2P port.");
    document.getElementById("setupError").textContent = "Starting node process…";

    const result = await api("/api/nodes", {
      method: "POST",
      body: JSON.stringify({
        name,
        host: document.getElementById("host").value.trim() || "127.0.0.1",
        p2p_port: p2p,
        room_id: document.getElementById("room").value.trim(),
        signalling_url: document.getElementById("signal").value.trim(),
        consensus: document.getElementById("consensus").value,
        staker: document.getElementById("staker").checked,
        malicious: document.getElementById("malicious").checked,
        load: document.getElementById("load").value === "1",
        save: document.getElementById("save").checked
      })
    });

    activeNodeId = result.node.id;
    localStorage.setItem("blockchainActiveNode", activeNodeId);
    document.getElementById("setupError").textContent = "";
    toggleSetup(false);
    setResult("nodeManagerMessage", `${name} is starting.`, true);
    await refresh();
  } catch (error) {
    document.getElementById("setupError").textContent = error.message;
  }
}

async function sendTx() {
  if (!activeNodeId) return setResult("txResult", "Select a running node first.", false);
  try {
    const receiver = document.getElementById("receiver").value.trim();
    const amount = Number(document.getElementById("amount").value);
    if (!receiver) throw new Error("Enter a receiver name or public key.");
    if (!(amount > 0)) throw new Error("Amount must be positive.");
    const result = await api(`/api/nodes/${encodeURIComponent(activeNodeId)}/transaction`, { method: "POST", body: JSON.stringify({ receiver, amount }) });
    localStorage.setItem("blockchainLastTx", JSON.stringify({ tx_id: result.tx_id || "", receiver, amount, sender_node: activeNodeId, created_at: Date.now() }));
    setResult("txResult", "Transaction broadcast to the P2P network.");
    await refresh();
  } catch (error) { setResult("txResult", error.message, false); }
}

async function stake() {
  if (!activeNodeId) return setResult("stakeResult", "Select a running node first.", false);
  try {
    const amount = Number(document.getElementById("stakeAmount").value);
    if (!(amount > 0)) throw new Error("Stake amount must be positive.");
    await api(`/api/nodes/${encodeURIComponent(activeNodeId)}/stake`, { method: "POST", body: JSON.stringify({ amount }) });
    setResult("stakeResult", "Stake announcement broadcast.");
    await refresh();
  } catch (error) { setResult("stakeResult", error.message, false); }
}

async function stopNode() {
  if (!activeNodeId) return;
  try {
    await api(`/api/nodes/${encodeURIComponent(activeNodeId)}/stop`, { method: "POST" });
    setResult("nodeManagerMessage", "Selected node stopped.", true);
    activeNodeId = "";
    localStorage.removeItem("blockchainActiveNode");
    await refresh();
  } catch (error) { setResult("nodeManagerMessage", error.message, false); }
}

function renderPeers(peers) {
  const container = document.getElementById("peerList");
  document.getElementById("peerBadge").textContent = `${peers.length} peer${peers.length === 1 ? "" : "s"}`;
  document.getElementById("peersCount").textContent = peers.length;
  if (!peers.length) { container.innerHTML = '<div class="muted">No peers discovered yet.</div>'; return; }
  container.innerHTML = peers.map(peer => `
    <div class="item">
      <div class="row-between"><strong>${esc(peer.name)}</strong><span class="live-label">KNOWN</span></div>
      <div class="mono">${esc(peer.host)}:${esc(peer.port)}</div>
      <div class="mono">${esc(shortKey(peer.public_key, 90))}</div>
    </div>`).join("");
}

function renderMempool(items) {
  const container = document.getElementById("mempool");
  document.getElementById("mempoolBadge").textContent = `${items.length} pending`;
  if (!items.length) { container.innerHTML = '<div class="muted">Mempool is empty.</div>'; return; }
  container.innerHTML = items.map(tx => `
    <div class="item">
      <div class="row-between"><strong>${esc(shortKey(tx.sender, 24))}</strong><span class="arrow">→</span><strong>${esc(shortKey(tx.receiver, 24))}</strong></div>
      <div class="tx-amount">Amount: ${esc(formatValue(tx.payload))}</div>
      <div class="mono">TX ${esc(tx.id)}</div>
    </div>`).join("");
}

function renderStakers(stakers) {
  const container = document.getElementById("currentStakers");
  const entries = Object.entries(stakers || {});
  document.getElementById("stakerBadge").textContent = `${entries.length} staker${entries.length === 1 ? "" : "s"}`;
  if (!entries.length) { container.innerHTML = '<div class="muted">No active stakers.</div>'; return; }
  container.innerHTML = entries.map(([key, amount]) => `
    <div class="staker-card"><div class="staker-icon">◎</div><div><strong>${esc(shortKey(key, 38))}</strong><span>Stake: ${esc(amount)}</span></div></div>`).join("");
}

function renderChain(blocks, chainLength) {
  const container = document.getElementById("chain");
  document.getElementById("chainBadge").textContent = `${chainLength} block${chainLength === 1 ? "" : "s"}`;
  if (!blocks.length) { container.innerHTML = '<div class="muted">Blockchain is not initialized yet.</div>'; return; }
  container.innerHTML = blocks.slice().reverse().map((block, reverseIndex) => {
    const number = chainLength - reverseIndex - 1;
    const txs = Array.isArray(block.transactions) ? block.transactions : [];
    const stakers = Array.isArray(block.stakers) ? block.stakers : [];
    const valid = block.is_valid !== false;
    const slashed = block.slash_creator === true;
    const status = slashed ? "⚠ SLASHED — EQUIVOCATION" : (valid ? "✓ VALID" : "✕ INVALID");
    const statusClass = slashed ? "invalid" : (valid ? "valid" : "invalid");
    return `<details class="block" ${reverseIndex === 0 ? "open" : ""}>
      <summary><span class="block-number">#${number}</span><span class="block-creator">${esc(shortKey(block.creator || "Genesis", 44))}</span>${slashed ? '<span class="latest">SLASHED</span>' : (reverseIndex === 0 ? '<span class="latest">LATEST</span>' : '')}</summary>
      <div class="block-grid">
        <div class="block-field"><span>Hash</span><div class="mono">${esc(block.hash)}</div></div>
        <div class="block-field"><span>Previous hash</span><div class="mono">${esc(block.prevHash || "Genesis")}</div></div>
        <div class="block-field"><span>Timestamp</span><strong>${esc(block.ts)}</strong></div>
        <div class="block-field"><span>Selected stake</span><strong>${esc(block.staked_amt ?? 0)}</strong></div>
        <div class="block-field"><span>Creator</span><div class="mono">${esc(block.creator || "Genesis")}</div></div>
        <div class="block-field"><span>Validation</span><strong class="${statusClass}">${status}</strong></div>
      </div>
      ${block.seed || block.vrf_proof ? `<div class="vrf-box"><div class="vrf-title">PoS / VRF verification</div><div class="vrf-grid"><div><span>Seed</span><div class="mono">${esc(block.seed)}</div></div><div><span>VRF proof</span><div class="mono">${esc(shortKey(block.vrf_proof, 120))}</div></div></div></div>` : ""}
      <div class="block-section"><div class="subheading"><span>Transactions</span><b>${txs.length}</b></div>${txs.length ? txs.map(tx => `<div class="mini-card"><div class="row-between"><span>${esc(shortKey(tx.sender, 28))} → ${esc(shortKey(tx.receiver, 28))}</span><b>${esc(formatValue(tx.payload))}</b></div><div class="mono">${esc(tx.id || "")}</div></div>`).join("") : '<span class="muted">No transactions</span>'}</div>
      <div class="block-section"><div class="subheading"><span>Stakers</span><b>${stakers.length}</b></div>${stakers.length ? stakers.map(s => `<div class="mini-card"><div class="row-between"><span>${esc(shortKey(s.staker, 32))}</span><b>${esc(s.amount ?? 0)}</b></div><div class="mono">${esc(s.id || "")}</div></div>`).join("") : '<span class="muted">No stakers recorded</span>'}</div>
    </details>`;
  }).join("");
}

function renderPropagation(data) {
  const saved = JSON.parse(localStorage.getItem("blockchainLastTx") || "null");
  const txs = data.mempool || [];
  const blocks = data.blocks || [];
  const txId = saved?.tx_id || "";
  const foundPending = txId ? txs.some(tx => tx.id === txId) : txs.length > 0;
  const foundBlock = txId ? blocks.some(block => (block.transactions || []).some(tx => tx.id === txId)) : false;
  const hasBroadcast = !!saved;
  const hasPeerReceived = foundPending || (hasBroadcast && (data.known_peers || []).length > 0);
  const badge = document.getElementById("propagationBadge");
  const title = document.getElementById("propagationTx");
  const steps = [document.getElementById("propStep1"), document.getElementById("propStep2"), document.getElementById("propStep3")];
  steps.forEach(x => x?.classList.remove("done", "active"));
  if (!hasBroadcast) {
    badge.textContent = "Waiting";
    title.textContent = "Send a transaction to see its live network path.";
    return;
  }
  title.innerHTML = `<strong>${esc(data.name || "Node")}</strong> → <strong>${esc(saved.receiver)}</strong> · Amount: ${esc(saved.amount)}${txId ? ` · TX ${esc(shortKey(txId, 18))}` : ""}`;
  if (hasBroadcast) steps[0]?.classList.add("done");
  if (hasPeerReceived) steps[1]?.classList.add(foundPending ? "done" : "active");
  if (foundBlock) steps[2]?.classList.add("done"); else steps[2]?.classList.add("active");
  badge.textContent = foundBlock ? "Confirmed" : (foundPending ? "Peer received" : "Broadcast");
}

function renderActivity(events) {
  const container = document.getElementById("activity");
  if (!events.length) { container.innerHTML = '<div class="muted">Waiting for backend activity…</div>'; return; }
  container.innerHTML = events.map(event => `
    <div class="activity-item ${esc(event.level)}"><span class="activity-time">${esc(event.time)}</span><div><strong>${esc(event.message)}</strong>${event.detail ? `<div class="activity-detail">${esc(event.detail)}</div>` : ""}</div></div>`).join("");
}

function render(data) {
  const nodes = data.nodes || [];
  renderNodeManager(nodes);

  if (!activeNodeId || !nodes.some(n => n.id === activeNodeId)) return;
  document.getElementById("status").textContent = data.status || "unknown";
  document.getElementById("statusDot").className = `status-dot ${data.status === "running" ? "online" : ""}`;
  document.getElementById("nodeName").textContent = data.name || "—";
  document.getElementById("balance").textContent = data.balance === null || data.balance === undefined ? "—" : data.balance;
  document.getElementById("height").textContent = data.chain_length || 0;
  document.getElementById("stakeValue").textContent = data.staked_amount ?? 0;
  document.getElementById("roomValue").textContent = data.room_id || "—";
  document.getElementById("consensusValue").textContent = String(data.consensus || "—").toUpperCase();
  document.getElementById("modeValue").textContent = String(data.node_mode || "normal").toUpperCase();
  document.getElementById("syncValue").textContent = String(data.chain_sync || "—").toUpperCase();
  renderPeers(data.known_peers || []);
  renderMempool(data.mempool || []);
  renderStakers(data.current_stakers || {});
  renderChain(data.blocks || [], data.chain_length || 0);
  renderActivity(data.activity || []);
  renderPropagation(data);
}

async function refresh() {
  try {
    const query = activeNodeId ? `?node_id=${encodeURIComponent(activeNodeId)}` : "";
    render(await api(`/api/state${query}`));
  } catch (error) { console.error("State refresh failed:", error); }
}

async function refreshNodesOnly() {
  try {
    const data = await api("/api/nodes");
    renderNodeManager(data.nodes || []);
    if (!activeNodeId && data.nodes?.length) suggestPort(data.nodes);
  } catch (error) { console.error(error); }
}

setInterval(refresh, 1500);
refresh();
refreshNodesOnly();
