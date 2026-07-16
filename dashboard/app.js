const API     = "";
const POLL_MS = 3000;

const state = {
  agents:        [],
  alerts:        [],
  selectedAgent: null,
  chart:         null,
  renderedAlerts: new Set(),   // tracks alert IDs already in the DOM
  agentDetails:  {},           // caches { name: { events, avgLatency, lastActiveStr } }
  timeRange:     "all",        // chart filter: "all", "24h", "1h"
};

// ── Immersive background floating particles ──────────────────────────────────

function initParticles() {
  const canvas = document.getElementById("particles-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  let animationFrameId;

  let width = canvas.width = window.innerWidth;
  let height = canvas.height = window.innerHeight;

  window.addEventListener("resize", () => {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  });

  const particles = [];
  const particleCount = 45;

  class Particle {
    constructor() {
      this.reset();
      this.y = Math.random() * height;
    }

    reset() {
      this.x = Math.random() * width;
      this.y = height + 10;
      this.size = Math.random() * 1.6 + 0.4;
      this.speedY = -(Math.random() * 0.25 + 0.08);
      this.speedX = (Math.random() - 0.5) * 0.08;
      this.alpha = Math.random() * 0.35 + 0.15;
    }

    update() {
      this.y += this.speedY;
      this.x += this.speedX;
      if (this.y < -10 || this.x < -10 || this.x > width + 10) {
        this.reset();
      }
    }

    draw() {
      ctx.fillStyle = `rgba(77, 216, 255, ${this.alpha})`;
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  for (let i = 0; i < particleCount; i++) {
    particles.push(new Particle());
  }

  function animate() {
    ctx.clearRect(0, 0, width, height);
    for (let i = 0; i < particles.length; i++) {
      particles[i].update();
      particles[i].draw();
    }
    animationFrameId = requestAnimationFrame(animate);
  }

  animate();
}

// ── Value Counter (Apple Easing Animation) ───────────────────────────────────

function animateCounter(id, targetVal) {
  const el = document.getElementById(id);
  if (!el) return;

  const currentText = el.textContent || "";
  if (currentText === String(targetVal) || currentText === "—") {
    if (currentText === "—") el.textContent = targetVal;
    return;
  }

  const startNum = parseFloat(currentText.replace(/[^0-9.]/g, "")) || 0;
  const endNum = parseFloat(String(targetVal).replace(/[^0-9.]/g, "")) || 0;

  if (isNaN(startNum) || isNaN(endNum) || startNum === endNum || endNum === 0) {
    el.textContent = targetVal;
    return;
  }

  const isUSD = String(targetVal).includes("$");
  const duration = 700; // ms
  const startTime = performance.now();

  function update(now) {
    const elapsed = now - startTime;
    const progress = Math.min(elapsed / duration, 1);
    
    // Easing: easeOutCubic (spring decelerate)
    const ease = 1 - Math.pow(1 - progress, 3);
    const val = startNum + (endNum - startNum) * ease;

    if (isUSD) {
      el.textContent = `$${val.toFixed(4)}`;
    } else {
      el.textContent = Math.round(val);
    }

    if (progress < 1) {
      requestAnimationFrame(update);
    } else {
      el.textContent = targetVal;
    }
  }
  requestAnimationFrame(update);
}

// ── Fetch ──────────────────────────────────────────────────────────────────

async function apiFetch(path) {
  try {
    const r = await fetch(`${API}${path}`);
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

// ── Format helpers ─────────────────────────────────────────────────────────

const fmt$  = v => `$${Number(v).toFixed(4)}`;
const fmt$6 = v => `$${Number(v).toFixed(6)}`;

function timeAgo(iso) {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 5)    return "just now";
  if (s < 60)   return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// ── Stats row — only touch text nodes, never recreate elements ─────────────

function renderStats() {
  const totalCost  = state.agents.reduce((s, a) => s + a.cost_today, 0);
  const totalCalls = state.agents.reduce((s, a) => s + a.calls_today, 0);
  const p1Count    = state.alerts.filter(a => a.severity === "P1").length;

  animateCounter("stat-agents",    state.agents.length);
  animateCounter("stat-cost",      fmt$(totalCost));
  animateCounter("stat-calls",     totalCalls);
  animateCounter("stat-alerts-val", p1Count);
  setText("last-updated",   "SOC Sync: " + new Date().toLocaleTimeString());

  const kpiAlertsPanel = document.getElementById("kpi-alerts");
  if (kpiAlertsPanel) {
    if (p1Count > 0) {
      kpiAlertsPanel.classList.add("alerting-active");
    } else {
      kpiAlertsPanel.classList.remove("alerting-active");
    }
  }

  const alertsBadge = document.getElementById("alerts-count");
  if (alertsBadge) {
    alertsBadge.textContent = state.alerts.length;
    alertsBadge.className   = state.alerts.length > 0 ? "capsule-badge red-glow" : "capsule-badge green-glow";
  }
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el && el.textContent !== String(val)) el.textContent = val;
}

// ── SVG Sparkline Generator ────────────────────────────────────────────────

function generateSparklineSVG(events) {
  if (!events || events.length === 0) {
    return `<svg class="sparkline-svg" viewBox="0 0 120 30"><path d="M 0 15 L 120 15" stroke="rgba(255,255,255,0.06)" stroke-width="1.5" fill="none"/></svg>`;
  }

  const sorted = [...events].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  const costs = sorted.slice(-12).map(e => Number(e.cost_usd));

  if (costs.length < 2) {
    return `<svg class="sparkline-svg" viewBox="0 0 120 30"><circle cx="60" cy="15" r="2.5" fill="var(--primary-cyan)"/><path d="M 0 15 L 120 15" stroke="var(--primary-cyan)" stroke-dasharray="2,3" stroke-width="1" fill="none"/></svg>`;
  }

  const maxVal = Math.max(...costs, 0.0001);
  const minVal = Math.min(...costs);
  const range  = maxVal - minVal || 1;

  const w = 120;
  const h = 30;
  const padding = 3;

  const points = costs.map((val, idx) => {
    const x = (idx / (costs.length - 1)) * w;
    const y = h - padding - ((val - minVal) / range) * (h - padding * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  return `
    <svg class="sparkline-svg" viewBox="0 0 ${w} ${h}">
      <path d="M ${points.join(" L ")}" stroke="var(--primary-cyan)" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  `;
}

// ── Agents grid — diff existing cards, only write what changed ─────────────

function buildAgentCardHTML(ag) {
  const pct    = Math.min((ag.cost_today / ag.budget_per_run_usd) * 100, 100);
  const barCls = pct < 60 ? "safe" : pct < 90 ? "warn" : "danger";
  const costClr = ag.is_alerting ? "var(--danger-red)" : "var(--success-emerald)";

  const details = state.agentDetails[ag.name] || { avgLatency: 0, lastActiveStr: "—", events: [] };
  const sparklineSVG = generateSparklineSVG(details.events);

  return `
    <div class="agent-top">
      <div class="agent-name">${ag.name}</div>
      <div class="status-badge ${ag.is_alerting ? "alert" : "ok"}">
        ${ag.is_alerting ? "⚠ ALERT" : "● OK"}
      </div>
    </div>
    <div class="agent-divider"></div>
    <div class="agent-metrics-row">
      <div class="agent-metric-item accent-cost">
        <span class="key">Cost Today</span>
        <span class="val cost-val" style="color:${costClr}">${fmt$(ag.cost_today)}</span>
      </div>
      <div class="agent-metric-item">
        <span class="key">Calls Today</span>
        <span class="val calls-val">${ag.calls_today}</span>
      </div>
      <div class="agent-metric-item">
        <span class="key">Budget / Run</span>
        <span class="val">${fmt$(ag.budget_per_run_usd)}</span>
      </div>
    </div>
    
    <div class="budget-bar-section">
      <div class="budget-bar-labels">
        <span class="label-title">Budget usage today</span>
        <span class="pct pct-val">${pct.toFixed(0)}%</span>
      </div>
      <div class="budget-track">
        <div class="budget-fill ${barCls}" style="width:${pct}%"></div>
      </div>
    </div>

    <div class="sparkline-wrapper">
      <span class="sparkline-title">Usage Profile</span>
      <div class="sparkline-container">
        ${sparklineSVG}
      </div>
    </div>

    <div class="agent-card-footer">
      <div class="footer-item">
        <i data-lucide="clock"></i>
        <span>Active <span class="highlight activity-val">${details.lastActiveStr}</span></span>
      </div>
      <div class="footer-item">
        <i data-lucide="cpu"></i>
        <span>Latency <span class="highlight latency-val">${details.avgLatency ? details.avgLatency + "ms" : "—"}</span></span>
      </div>
    </div>`;
}

function patchAgentCard(el, ag) {
  const pct    = Math.min((ag.cost_today / ag.budget_per_run_usd) * 100, 100);
  const barCls = pct < 60 ? "safe" : pct < 90 ? "warn" : "danger";
  const costClr = ag.is_alerting ? "var(--danger-red)" : "var(--success-emerald)";
  const isSelected = state.selectedAgent === ag.name;

  el.className = [
    "agent-card",
    ag.is_alerting ? "alerting" : "",
    isSelected      ? "selected"  : "",
  ].filter(Boolean).join(" ");

  const badge = el.querySelector(".status-badge");
  if (badge) {
    badge.className   = `status-badge ${ag.is_alerting ? "alert" : "ok"}`;
    badge.textContent = ag.is_alerting ? "⚠ ALERT" : "● OK";
  }

  const costEl = el.querySelector(".cost-val");
  if (costEl) { costEl.textContent = fmt$(ag.cost_today); costEl.style.color = costClr; }

  const callsEl = el.querySelector(".calls-val");
  if (callsEl && callsEl.textContent !== String(ag.calls_today))
    callsEl.textContent = ag.calls_today;

  const pctEl = el.querySelector(".pct-val");
  if (pctEl) pctEl.textContent = `${pct.toFixed(0)}%`;

  const fill = el.querySelector(".budget-fill");
  if (fill) { fill.style.width = `${pct}%`; fill.className = `budget-fill ${barCls}`; }

  const details = state.agentDetails[ag.name];
  if (details) {
    const sparklineBox = el.querySelector(".sparkline-container");
    if (sparklineBox) {
      const newSpark = generateSparklineSVG(details.events);
      if (sparklineBox.innerHTML.trim() !== newSpark.trim()) {
        sparklineBox.innerHTML = newSpark;
      }
    }

    const actEl = el.querySelector(".activity-val");
    if (actEl && actEl.textContent !== details.lastActiveStr) {
      actEl.textContent = details.lastActiveStr;
    }

    const latEl = el.querySelector(".latency-val");
    const latStr = details.avgLatency ? `${details.avgLatency}ms` : "—";
    if (latEl && latEl.textContent !== latStr) {
      latEl.textContent = latStr;
    }
  }
}

function renderAgents() {
  const grid = document.getElementById("agents-grid");

  if (!state.agents.length) {
    grid.innerHTML = `<div class="empty-state">No agents registered yet.<br>Add <code>aegis.init()</code> to your code.</div>`;
    return;
  }

  const existing = new Map();
  grid.querySelectorAll("[data-agent]").forEach(el => existing.set(el.dataset.agent, el));

  const current = new Set(state.agents.map(a => a.name));
  existing.forEach((el, name) => { if (!current.has(name)) el.remove(); });

  state.agents.forEach(ag => {
    if (existing.has(ag.name)) {
      patchAgentCard(existing.get(ag.name), ag);
    } else {
      const el = document.createElement("div");
      el.className    = `agent-card ${ag.is_alerting ? "alerting" : ""} ${state.selectedAgent === ag.name ? "selected" : ""}`;
      el.dataset.agent = ag.name;
      el.innerHTML    = buildAgentCardHTML(ag);
      el.onclick      = () => selectAgent(ag.name);
      grid.appendChild(el);
    }
  });
}

// ── Alerts feed ─────────────────────────────────────────────────────────────

function isAtlasUnavailable(explanation) {
  return !explanation || explanation === "Atlas unavailable — explanation could not be generated.";
}

function buildAtlasHTML(al) {
  if (isAtlasUnavailable(al.atlas_explanation)) return "";
  const conf = al.atlas_confidence || "low";
  const fix  = al.atlas_suggested_fix && al.atlas_suggested_fix !== "null"
    ? al.atlas_suggested_fix : null;
  return `
    <div class="atlas-block">
      <div class="atlas-header">
        <span class="atlas-label">⬡ Atlas</span>
        <span class="atlas-conf atlas-conf-${conf}">${conf}</span>
      </div>
      <p class="atlas-explanation">${al.atlas_explanation}</p>
      ${fix ? `<div class="atlas-fix"><span class="atlas-fix-label">Fix</span><span class="atlas-fix-text">${fix}</span></div>` : ""}
    </div>`;
}

function isVeritasAbsent(status) {
  return !status;
}

function buildVeritasHTML(al) {
  if (isVeritasAbsent(al.veritas_status)) return "";

  const status = al.veritas_status;

  let regs = [];
  if (al.veritas_regulations) {
    try { regs = JSON.parse(al.veritas_regulations); } catch {}
  }

  let piiTypes = [];
  if (al.veritas_pii_types) {
    try { piiTypes = JSON.parse(al.veritas_pii_types); } catch {}
  }

  const statusIcons = { violation: "✕", warning: "⚠", compliant: "✓" };
  const statusIcon  = statusIcons[status] || "·";

  const regTags = regs.map(r =>
    `<span class="veritas-reg-tag">${r}</span>`
  ).join("");

  const piiPills = piiTypes.map(p =>
    `<span class="veritas-pii-pill">${p.type.toUpperCase()} ×${p.count} · ${p.sample_masked}</span>`
  ).join("");

  return `
    <div class="veritas-block veritas-${status}">
      <div class="veritas-header">
        <span class="veritas-label">⚖ Veritas</span>
        <span class="veritas-status-badge veritas-badge-${status}">${statusIcon} ${status.toUpperCase()}</span>
        ${regTags}
      </div>
      ${al.veritas_pii_summary ? `<p class="veritas-summary">${al.veritas_pii_summary}</p>` : ""}
      ${piiPills ? `<div class="veritas-pii-row">${piiPills}</div>` : ""}
    </div>`;
}

function buildAlertEl(al) {
  const sev       = al.severity.toLowerCase();
  const typeLabel = al.alert_type === "budget_exceeded" ? "Budget Exceeded" : "Cost Spike";
  const el        = document.createElement("div");
  el.className    = `alert-item ${sev}`;
  el.dataset.alertId = al.id;
  
  const iconName = sev === "p1" ? "alert-octagon" : "alert-circle";
  
  el.innerHTML = `
    <div class="alert-row-top">
      <span class="alert-chip">${al.severity} · ${typeLabel}</span>
      <span class="alert-time">${timeAgo(al.created_at)}</span>
    </div>
    <div class="alert-agent-wrap">
      <i data-lucide="${iconName}" class="alert-agent-icon"></i>
      <div class="alert-agent">${al.agent_name}</div>
    </div>
    <div class="alert-msg">${al.message}</div>
    ${buildAtlasHTML(al)}
    ${buildVeritasHTML(al)}`;
  return el;
}

function renderAlerts() {
  const list = document.getElementById("alerts-list");

  if (!state.alerts.length) {
    if (!list.querySelector(".empty-state")) {
      list.innerHTML = `<div class="empty-state">No alerts — all agents within budget.</div>`;
    }
    state.renderedAlerts.clear();
    return;
  }

  const placeholder = list.querySelector(".empty-state");
  if (placeholder) { placeholder.remove(); state.renderedAlerts.clear(); }

  const newAlerts = state.alerts.filter(al => !state.renderedAlerts.has(al.id));
  newAlerts.reverse().forEach(al => {
    list.insertBefore(buildAlertEl(al), list.firstChild);
    state.renderedAlerts.add(al.id);
  });

  const currentIds = new Set(state.alerts.map(a => a.id));
  list.querySelectorAll("[data-alert-id]").forEach(el => {
    const id = Number(el.dataset.alertId);
    if (!currentIds.has(id)) { el.remove(); state.renderedAlerts.delete(id); }
  });

  list.querySelectorAll("[data-alert-id]").forEach(el => {
    const id = Number(el.dataset.alertId);
    const al = state.alerts.find(a => a.id === id);
    if (!al) return;

    const lbl = el.querySelector(".alert-time");
    if (lbl) lbl.textContent = timeAgo(al.created_at);

    // Patch Atlas block if Atlas data arrived after the initial render
    if (!el.querySelector(".atlas-block") && !isAtlasUnavailable(al.atlas_explanation)) {
      const atlasHTML = buildAtlasHTML(al);
      if (atlasHTML) {
        const msgEl = el.querySelector(".alert-msg");
        if (msgEl) msgEl.insertAdjacentHTML("afterend", atlasHTML);
      }
    }

    // Patch Veritas block if Veritas data arrived after the initial render
    if (!el.querySelector(".veritas-block") && !isVeritasAbsent(al.veritas_status)) {
      const veritasHTML = buildVeritasHTML(al);
      if (veritasHTML) {
        const insertAfter = el.querySelector(".atlas-block") || el.querySelector(".alert-msg");
        if (insertAfter) insertAfter.insertAdjacentHTML("afterend", veritasHTML);
      }
    }
  });
}

// ── Chart.js Crosshair Plugin ────────────────────────────────────────────────

const crosshairPlugin = {
  id: "crosshair",
  afterDraw: (chart) => {
    if (chart.tooltip?._active?.length) {
      const activePoint = chart.tooltip._active[0];
      const ctx = chart.ctx;
      const x = activePoint.element.x;
      const topY = chart.scales.y.top;
      const bottomY = chart.scales.y.bottom;

      ctx.save();
      ctx.beginPath();
      ctx.moveTo(x, topY);
      ctx.lineTo(x, bottomY);
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.restore();
    }
  }
};

// ── Chart ───────────────────────────────────────────────────────────────────

async function loadChart(agentName) {
  const events = await apiFetch(`/agents/${encodeURIComponent(agentName)}/events`);
  const emptyEl = document.getElementById("chart-empty");

  if (!events || !events.length) {
    emptyEl.classList.remove("hidden");
    return;
  }

  emptyEl.classList.add("hidden");
  document.getElementById("chart-agent-label").textContent = agentName;

  let filtered = [...events].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  const now = new Date();
  if (state.timeRange === "24h") {
    const oneDayAgo = now.getTime() - (24 * 60 * 60 * 1000);
    filtered = filtered.filter(e => new Date(e.created_at).getTime() >= oneDayAgo);
  } else if (state.timeRange === "1h") {
    const oneHourAgo = now.getTime() - (60 * 60 * 1000);
    filtered = filtered.filter(e => new Date(e.created_at).getTime() >= oneHourAgo);
  }

  const chartPoints = filtered.slice(-40);
  const labels     = chartPoints.map((_, i) => `#${i + 1}`);
  const costs      = chartPoints.map(e => Number(e.cost_usd));
  const cumulative = costs.reduce((acc, c, i) => { acc.push(i === 0 ? c : acc[i - 1] + c); return acc; }, []);

  if (state.chart) {
    state.chart.data.labels              = labels;
    state.chart.data.datasets[0].data   = costs;
    state.chart.data.datasets[1].data   = cumulative;
    state.chart.update("none");
    return;
  }

  // Create neon gradients
  const canvasEl = document.getElementById("cost-chart");
  const chartCtx = canvasEl.getContext("2d");
  
  const gradientCyan = chartCtx.createLinearGradient(0, 0, 0, 300);
  gradientCyan.addColorStop(0, "rgba(77, 216, 255, 0.18)");
  gradientCyan.addColorStop(1, "rgba(77, 216, 255, 0.0)");

  const gradientEmerald = chartCtx.createLinearGradient(0, 0, 0, 300);
  gradientEmerald.addColorStop(0, "rgba(0, 245, 160, 0.12)");
  gradientEmerald.addColorStop(1, "rgba(0, 245, 160, 0.0)");

  state.chart = new Chart(canvasEl, {
    type: "line",
    plugins: [crosshairPlugin],
    data: {
      labels,
      datasets: [
        {
          label:                "Per-call cost ($)",
          data:                 costs,
          borderColor:          "#4dd8ff",
          backgroundColor:      gradientCyan,
          borderWidth:          2.5,
          pointRadius:          3,
          pointBackgroundColor: "#4dd8ff",
          pointBorderColor:     "rgba(0, 0, 0, 0.6)",
          pointBorderWidth:     1,
          tension:              0.38,
          fill:                 true,
          yAxisID:              "y",
        },
        {
          label:                "Cumulative cost ($)",
          data:                 cumulative,
          borderColor:          "#00f5a0",
          backgroundColor:      gradientEmerald,
          borderWidth:          2.5,
          pointRadius:          2,
          pointBackgroundColor: "#00f5a0",
          tension:              0.38,
          fill:                 true,
          borderDash:           [5, 4],
          yAxisID:              "y1",
        },
      ],
    },
    options: {
      responsive:          true,
      maintainAspectRatio: false,
      interaction:         { mode: "index", intersect: false },
      animation:           { duration: 450, easing: "easeOutQuart" },
      plugins: {
        legend: {
          labels: {
            color:    "#9ca8b8",
            font:     { family: "SF Pro Text, Geist", size: 11, weight: 600 },
            boxWidth: 12,
            boxHeight: 2,
          },
        },
        tooltip: {
          backgroundColor: "rgba(12, 18, 28, 0.95)",
          borderColor:     "rgba(255, 255, 255, 0.08)",
          borderWidth:     1,
          titleColor:      "#f8fafc",
          bodyColor:       "#9ca8b8",
          titleFont:       { family: "SF Pro Display, Geist", size: 12, weight: 700 },
          bodyFont:        { family: "Space Mono", size: 11 },
          padding:         12,
          cornerRadius:    10,
          callbacks: {
            label: ctx => ` ${ctx.dataset.label}: $${ctx.parsed.y.toFixed(6)}`,
          },
        },
      },
      scales: {
        x: {
          ticks: { color: "#5a6a80", font: { family: "Space Mono", size: 9 } },
          grid:  { color: "rgba(255, 255, 255, 0.015)", drawTicks: false },
        },
        y: {
          position: "left",
          ticks: {
            color:    "#4dd8ff",
            font:     { family: "Space Mono", size: 9 },
            callback: v => `$${v.toFixed(4)}`,
          },
          grid: { color: "rgba(255, 255, 255, 0.02)", drawTicks: false },
        },
        y1: {
          position: "right",
          ticks: {
            color:    "#00f5a0",
            font:     { family: "Space Mono", size: 9 },
            callback: v => `$${v.toFixed(4)}`,
          },
          grid: { drawOnChartArea: false },
        },
      },
    },
  });
}

// ── Agent selection ────────────────────────────────────────────────────────

async function selectAgent(name) {
  if (state.selectedAgent !== name && state.chart) {
    state.chart.destroy();
    state.chart = null;
  }

  state.selectedAgent = name;
  renderAgents();
  await loadChart(name);

  const events = await apiFetch(`/agents/${encodeURIComponent(name)}/events`);
  if (!events) return;

  const sorted = [...events].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  document.getElementById("modal-title").textContent = `${name} Trace Logs (${sorted.length})`;
  
  document.getElementById("modal-body").innerHTML = sorted.length
    ? sorted.reverse().map((e, i) => {
        const totalTokens = e.input_tokens + e.output_tokens;
        const maxLimit = Math.max(totalTokens, 1);
        const inputPct = (e.input_tokens / maxLimit) * 100;
        const outputPct = (e.output_tokens / maxLimit) * 100;

        return `
        <div class="event-row">
          <div class="event-left">
            <div class="event-idx">${sorted.length - i}</div>
          </div>
          <div class="event-detail">
            <div class="event-meta-top">
              <span class="event-model">${e.model}</span>
              <span class="event-time">${fmtTime(e.created_at)}</span>
            </div>
            
            <div class="event-tags">
              <span class="event-tag">In: ${e.input_tokens}</span>
              <span class="event-tag">Out: ${e.output_tokens}</span>
              <span class="event-tag tag-latency"><i data-lucide="cpu" style="width:11px;height:11px;display:inline-block;margin-right:3px;"></i>${e.latency_ms}ms</span>
              <span class="event-tag tag-cost">${fmt$6(e.cost_usd)}</span>
            </div>

            <div class="token-bar-wrapper">
              <div class="token-bar-label">
                <span>Token Split</span>
                <div class="token-bar-labels-row">
                  <span class="in-tokens">In: ${Math.round(inputPct)}%</span>
                  <span class="out-tokens">Out: ${Math.round(outputPct)}%</span>
                </div>
              </div>
              <div class="token-track">
                <div class="token-fill-input" style="width: ${inputPct}%"></div>
                <div class="token-fill-output" style="width: ${outputPct}%"></div>
              </div>
            </div>
          </div>
        </div>`;
      }).join("")
    : `<div class="empty-state">No events traced.</div>`;

  document.getElementById("modal-overlay").classList.add("open");
  lucide.createIcons();
}

function closeModal() {
  document.getElementById("modal-overlay").classList.remove("open");
}

// ── Poll loop ──────────────────────────────────────────────────────────────

async function poll() {
  const [agents, alerts] = await Promise.all([
    apiFetch("/agents"),
    apiFetch("/alerts"),
  ]);

  if (agents) state.agents = agents;
  if (alerts) state.alerts = alerts;

  if (agents) {
    await Promise.all(
      agents.map(async (ag) => {
        const events = await apiFetch(`/agents/${encodeURIComponent(ag.name)}/events`) || [];
        
        const avgLatency = events.length
          ? Math.round(events.reduce((sum, e) => sum + e.latency_ms, 0) / events.length)
          : 0;

        let lastActiveStr = "—";
        if (events.length) {
          lastActiveStr = timeAgo(events[0].created_at);
        } else {
          lastActiveStr = timeAgo(ag.created_at);
        }

        state.agentDetails[ag.name] = {
          events,
          avgLatency,
          lastActiveStr
        };
      })
    );
  }

  renderStats();
  renderAgents();
  renderAlerts();

  if (state.selectedAgent) await loadChart(state.selectedAgent);
  await loadHelm();

  lucide.createIcons();
}

// ── Setup Click Controls & Listeners ────────────────────────────────────────

function initControls() {
  document.querySelectorAll(".capsule-btn").forEach(btn => {
    btn.onclick = async (e) => {
      document.querySelectorAll(".capsule-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.timeRange = btn.dataset.range;
      if (state.selectedAgent) {
        if (state.chart) {
          state.chart.destroy();
          state.chart = null;
        }
        await loadChart(state.selectedAgent);
      }
    };
  });

  const exportBtn = document.getElementById("export-chart-btn");
  if (exportBtn) {
    exportBtn.onclick = async () => {
      if (!state.selectedAgent) {
        alert("Please select an agent to export data.");
        return;
      }
      const events = await apiFetch(`/agents/${encodeURIComponent(state.selectedAgent)}/events`);
      if (!events || !events.length) {
        alert("No trace events found to export.");
        return;
      }

      const headers = ["ID", "Run ID", "Model", "Input Tokens", "Output Tokens", "Latency (ms)", "Cost (USD)", "Timestamp"];
      const rows = events.map(e => [
        e.id,
        e.run_id,
        e.model,
        e.input_tokens,
        e.output_tokens,
        e.latency_ms,
        e.cost_usd,
        e.created_at
      ]);

      const csvContent = [
        headers.join(","),
        ...rows.map(r => r.map(val => `"${String(val).replace(/"/g, '""')}"`).join(","))
      ].join("\n");

      const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.setAttribute("href", url);
      link.setAttribute("download", `aegis_${state.selectedAgent}_trace_export.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    };
  }
}

// ── Helm: Cost Intelligence ─────────────────────────────────────────────────

async function loadHelm() {
  const data = await apiFetch("/helm/costs");
  if (!data) return;
  renderHelm(data);
}

function renderHelm(data) {
  const ts = data.total_spend || {};

  setText("helm-total-all",   ts.all_time_usd != null ? fmt$(ts.all_time_usd) : "—");
  setText("helm-total-today", ts.today_usd    != null ? fmt$(ts.today_usd)    : "—");
  setText("helm-total-calls", ts.total_calls  != null ? ts.total_calls        : "—");
  setText("helm-calls-today", ts.calls_today  != null ? ts.calls_today        : "—");

  // By agent
  const byAgentEl = document.getElementById("helm-by-agent");
  if (byAgentEl) {
    byAgentEl.innerHTML = (data.by_agent && data.by_agent.length)
      ? data.by_agent.map(a => `
          <div class="helm-row">
            <span class="helm-row-name">${a.agent_name}</span>
            <div class="helm-row-right">
              <span class="helm-row-cost">${fmt$(a.total_cost_usd)}</span>
              <span class="helm-row-sub">${a.call_count} calls · avg ${fmt$6(a.avg_cost_per_call)}/call</span>
            </div>
          </div>`).join("")
      : `<div class="helm-empty">No agent data yet.</div>`;
  }

  // By model (with share bar)
  const byModelEl = document.getElementById("helm-by-model");
  if (byModelEl) {
    byModelEl.innerHTML = (data.by_model && data.by_model.length)
      ? data.by_model.map(m => `
          <div class="helm-row">
            <span class="helm-row-name helm-model-name">${m.model}</span>
            <div class="helm-row-right">
              <span class="helm-row-cost">${fmt$(m.total_cost_usd)}</span>
              <span class="helm-row-sub">${m.call_count} calls · ${m.share_percent}% of total</span>
            </div>
            <div class="helm-share-bar"><div class="helm-share-fill" style="width:${Math.min(m.share_percent,100)}%"></div></div>
          </div>`).join("")
      : `<div class="helm-empty">No model data yet.</div>`;
  }

  // Illustrative cloud infra
  const cloud = data.cloud_infra_cost;
  if (cloud && cloud.monthly_usd) {
    const cloudTableEl = document.getElementById("helm-cloud-table");
    if (cloudTableEl) {
      cloudTableEl.innerHTML = Object.entries(cloud.monthly_usd).map(([key, v]) => `
        <div class="helm-cloud-row">
          <div class="helm-cloud-left">
            <span class="helm-cloud-category">${key.charAt(0).toUpperCase() + key.slice(1)}</span>
            <span class="helm-cloud-service">${v.service}</span>
            <span class="helm-cloud-note">${v.note}</span>
          </div>
          <span class="helm-cloud-cost">$${v.cost_usd.toFixed(2)}/mo</span>
        </div>`).join("");
    }
    const cloudTotalEl = document.getElementById("helm-cloud-total");
    if (cloudTotalEl) {
      cloudTotalEl.innerHTML = `
        <span class="helm-cloud-total-label">Est. Monthly Total</span>
        <span class="helm-cloud-total-value">$${cloud.total_monthly_usd.toFixed(2)}/mo</span>`;
    }
  }

  // Cost alert tracking
  const costAlertsEl = document.getElementById("helm-cost-alerts");
  if (costAlertsEl) {
    if (!data.cost_alerts || !data.cost_alerts.length) {
      costAlertsEl.innerHTML = `<div class="helm-empty">No cost alerts tracked yet.</div>`;
    } else {
      costAlertsEl.innerHTML = data.cost_alerts.map(a => {
        const isP1    = a.alert_type === "budget_exceeded";
        const typeLabel = isP1 ? "P1 · Budget Exceeded" : "P2 · Cost Spike";
        const firedAgo  = a.fired_at ? timeAgo(a.fired_at) : "";
        return `
          <div class="helm-alert-item">
            <div class="helm-alert-top">
              <span class="helm-alert-type ${isP1 ? "helm-alert-p1" : "helm-alert-p2"}">${typeLabel}</span>
              <span class="helm-alert-agent">${a.agent_name}</span>
            </div>
            <span class="helm-alert-driver">${a.driver_summary}</span>
            <div class="helm-alert-meta">
              <span class="helm-alert-cost">Cost at alert: $${a.cost_at_alert.toFixed(4)}</span>
              ${firedAgo ? `<span class="helm-alert-time">${firedAgo}</span>` : ""}
            </div>
          </div>`;
      }).join("");
    }
  }

  // Recommendations (from static map)
  const recsEl = document.getElementById("helm-recommendations");
  if (recsEl) {
    if (!data.recommendations || !data.recommendations.length) {
      recsEl.innerHTML = `<div class="helm-empty">No issues detected — keep monitoring.</div>`;
    } else {
      recsEl.innerHTML = data.recommendations.map(r => `
        <div class="helm-rec-card">
          <div class="helm-rec-header">
            <span class="helm-rec-issue">${r.issue}</span>
            ${r.agent_name ? `<span class="helm-rec-agent">${r.agent_name}</span>` : ""}
          </div>
          <p class="helm-rec-text">${r.recommendation}</p>
          <span class="helm-rec-impact">${r.est_impact}</span>
        </div>`).join("");
    }
  }
}

// ── Boot ───────────────────────────────────────────────────────────────────

(async () => {
  initParticles();
  initControls();
  await poll();
  setInterval(poll, POLL_MS);
})();
