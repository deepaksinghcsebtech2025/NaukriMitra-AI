/* Ultra Job Agent — vanilla dashboard */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function wsUrl(path) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${path}`;
}

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} ${r.status}`);
  return r.json();
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function drawBarChart(canvas, labels, values, colors) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const max = Math.max(1, ...values);
  const pad = 28;
  const barW = (w - pad * 2) / labels.length - 8;
  labels.forEach((lab, i) => {
    const v = values[i] || 0;
    const bh = ((h - pad * 2) * v) / max;
    const x = pad + i * (barW + 8);
    const y = h - pad - bh;
    ctx.fillStyle = colors[i % colors.length];
    ctx.fillRect(x, y, barW, bh);
    ctx.fillStyle = "#9090a8";
    ctx.font = "10px 'Space Mono', monospace";
    ctx.fillText(String(v), x, y - 4);
    ctx.save();
    ctx.translate(x + barW / 2, h - pad + 12);
    ctx.rotate(-0.2);
    ctx.textAlign = "center";
    ctx.fillText(lab, 0, 0);
    ctx.restore();
  });
}

let statsTimer = null;
let appsCache = [];
let appFilter = "all";
let appSearch = "";

async function refreshStats() {
  try {
    const s = await fetchJSON("/api/stats");
    setText("stat-discovered", s.total_discovered ?? "0");
    setText("stat-applied", s.total_applied ?? "0");
    setText("stat-interviews", s.interviews ?? "0");
    setText("stat-avg", `${s.avg_match_score ?? 0}%`);
    updateWorkflow(s);
    $("#conn-pill").textContent = "API OK";
    $("#conn-pill").classList.add("pill-ok");
    const jobs = await fetchJSON("/api/jobs?limit=500");
    renderCharts(s, jobs.jobs || []);
  } catch (e) {
    $("#conn-pill").textContent = "API down";
    console.error(e);
  }
}

function updateWorkflow(stats) {
  const steps = $$(".wf-step");
  steps.forEach((el) => el.classList.remove("active"));
  let idx = 0;
  const d = stats.DISCOVERED || 0;
  const f = stats.FILTERED || 0;
  const t = stats.TAILORED || 0;
  const a = (stats.APPLIED || 0) + (stats.SUBMITTED || 0);
  const iv = stats.INTERVIEW || 0;
  if (d > 0) idx = 0;
  if (f > 0) idx = 1;
  if (t > 0) idx = 2;
  if (a > 0) idx = 3;
  if ((stats.total_applied || 0) > 0 || a > 0) idx = 4;
  idx = Math.min(5, Math.max(0, idx + (iv > 0 ? 1 : 0)));
  const active = steps[idx] || steps[0];
  if (active) active.classList.add("active");
}

function renderCharts(stats, jobs) {
  const boards = { linkedin: 0, indeed: 0, other: 0 };
  (jobs || []).forEach((j) => {
    const src = (j.source || "").toLowerCase();
    if (src.includes("linkedin")) boards.linkedin += 1;
    else if (src.includes("indeed")) boards.indeed += 1;
    else boards.other += 1;
  });
  const c1 = $("#chart-boards");
  drawBarChart(
    c1,
    ["LinkedIn", "Indeed", "Other"],
    [boards.linkedin, boards.indeed, boards.other],
    ["#6c63ff", "#ff6584", "#43e97b"]
  );

  let b90 = 0,
    b80 = 0,
    b75 = 0,
    low = 0;
  (jobs || []).forEach((j) => {
    const sc = j.match_score || 0;
    if (sc >= 90) b90++;
    else if (sc >= 80) b80++;
    else if (sc >= 75) b75++;
    else low++;
  });
  const c2 = $("#chart-scores");
  drawBarChart(
    c2,
    ["90+", "80-90", "75-80", "<75"],
    [b90, b80, b75, low],
    ["#43e97b", "#6c63ff", "#f7971e", "#ff6584"]
  );
}

function connectLogsWS() {
  const logEl = $("#log-stream");
  const status = $("#log-status");
  let ws;
  let dead = false;

  function renderLogs(lines) {
    logEl.innerHTML = "";
    (lines || []).forEach((line) => {
      const div = document.createElement("span");
      div.className = "log-line";
      const low = (line || "").toLowerCase();
      if (low.includes("error") || low.includes("failed")) div.classList.add("err");
      else if (low.includes("warn")) div.classList.add("warn");
      div.textContent = line;
      logEl.appendChild(div);
    });
    logEl.scrollTop = logEl.scrollHeight;
  }

  function open() {
    ws = new WebSocket(wsUrl("/ws/logs"));
    ws.onopen = () => {
      status.textContent = "live";
      status.classList.add("pill-ok");
      $("#ws-pill").textContent = "Logs live";
      $("#ws-pill").classList.add("pill-ok");
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "logs") renderLogs(msg.data);
      } catch {
        /* ignore */
      }
    };
    ws.onclose = () => {
      status.textContent = "reconnecting…";
      $("#ws-pill").textContent = "Logs WS";
      $("#ws-pill").classList.remove("pill-ok");
      if (!dead) setTimeout(open, 2000);
    };
    ws.onerror = () => {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    };
  }
  open();
  return () => {
    dead = true;
    try {
      ws.close();
    } catch {
      /* ignore */
    }
  };
}

let jarvisWs = null;
function connectJarvis() {
  const box = $("#jarvis-messages");
  function appendBubble(text, who) {
    const b = document.createElement("div");
    b.className = `bubble ${who}`;
    b.textContent = text;
    box.appendChild(b);
    box.scrollTop = box.scrollHeight;
  }

  function open() {
    jarvisWs = new WebSocket(wsUrl("/ws/jarvis"));
    jarvisWs.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "connected" || msg.type === "thinking") {
        appendBubble(msg.msg, "jarvis");
      } else if (msg.type === "reply") {
        const line = msg.data || msg.msg || "";
        appendBubble(line, "jarvis");
      } else if (msg.type === "error") {
        appendBubble(`Error: ${msg.msg}`, "jarvis");
      }
    };
    jarvisWs.onclose = () => setTimeout(open, 2500);
  }
  open();

  function send(text) {
    if (!text) return;
    appendBubble(text, "user");
    if (jarvisWs && jarvisWs.readyState === 1) {
      jarvisWs.send(JSON.stringify({ message: text }));
    } else {
      appendBubble("Jarvis socket not ready — retrying…", "jarvis");
    }
  }

  $("#jarvis-send").onclick = () => {
    const input = $("#jarvis-input");
    send(input.value.trim());
    input.value = "";
  };
  $("#jarvis-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("#jarvis-send").click();
  });
  $$(".quick-cmd").forEach((btn) =>
    btn.addEventListener("click", () => send(btn.dataset.q || ""))
  );
}

async function loadPipeline() {
  const stats = await fetchJSON("/api/pipeline");
  const jobsResp = await fetchJSON("/api/jobs?limit=300");
  const jobs = jobsResp.jobs || [];
  const cols = ["DISCOVERED", "FILTERED", "TAILORED", "APPLIED", "INTERVIEW", "REJECTED"];
  const root = $("#kanban");
  root.innerHTML = "";
  cols.forEach((col) => {
    const wrap = document.createElement("div");
    wrap.className = "kcol";
    const h = document.createElement("h4");
    h.textContent = `${col} (${stats[col] || 0})`;
    wrap.appendChild(h);
    jobs
      .filter((j) => (j.app_status || "") === col)
      .forEach((j) => {
        const card = document.createElement("div");
        card.className = "kcard";
        card.innerHTML = `
          <div class="co">${j.company || ""}</div>
          <div class="ti">${j.title || ""}</div>
          <div class="meta"><span>${j.location || ""}</span><span class="badge-score">${j.match_score || 0}%</span></div>`;
        wrap.appendChild(card);
      });
    root.appendChild(wrap);
  });
}

function filterApplicationsRows() {
  const tbody = $("#apps-body");
  tbody.innerHTML = "";
  appsCache.forEach((row) => {
    const job = row.job || {};
    const st = row.status || "";
    if (appFilter !== "all") {
      if (appFilter === "APPLIED" && st !== "APPLIED" && st !== "SUBMITTED") return;
      if (appFilter === "INTERVIEW" && st !== "INTERVIEW") return;
      if (appFilter === "REJECTED" && st !== "REJECTED") return;
    }
    if (appSearch) {
      const q = appSearch.toLowerCase();
      if (
        !(job.title || "").toLowerCase().includes(q) &&
        !(job.company || "").toLowerCase().includes(q)
      ) {
        return;
      }
    }
    const tr = document.createElement("tr");
    const score = job.match_score || 0;
    tr.innerHTML = `
      <td>${job.company || ""}</td>
      <td>${job.title || ""}</td>
      <td>${job.location || ""}</td>
      <td><div class="score-wrap"><div class="score-bar" style="width:${Math.min(100, score)}%"></div>${score}%</div></td>
      <td><span class="status-pill status-${st}">${st}</span></td>
      <td>${(row.applied_at || "").slice(0, 10)}</td>
      <td>${
        row.resume_path
          ? `<a href="/${row.resume_path}" target="_blank" rel="noopener">PDF</a>`
          : "—"
      }</td>`;
    tbody.appendChild(tr);
  });
}

async function loadApplications() {
  const data = await fetchJSON("/api/applications?limit=500");
  appsCache = data.applications || [];
  filterApplicationsRows();
}

async function loadConfigForm() {
  const cfg = await fetchJSON("/api/config");
  const form = $("#config-form");
  Object.keys(cfg).forEach((k) => {
    const input = form.elements.namedItem(k);
    if (input) input.value = cfg[k];
  });
  const th = form.elements.namedItem("match_threshold");
  const mx = form.elements.namedItem("max_applications_per_day");
  const tv = $("#thresh-val");
  const mv = $("#maxapp-val");
  const sync = () => {
    if (th) tv.textContent = th.value;
    if (mx) mv.textContent = mx.value;
  };
  th && th.addEventListener("input", sync);
  mx && mx.addEventListener("input", sync);
  sync();
}

$("#config-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const data = {};
  new FormData(form).forEach((v, k) => {
    data[k] = v;
  });
  await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  alert("Saved overrides to Redis.");
});

function setupTabs() {
  $$(".nav-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      $$(".nav-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      $$(".panel").forEach((p) => p.classList.remove("active"));
      $(`#panel-${tab}`).classList.add("active");
      if (tab === "pipeline") loadPipeline().catch(console.error);
      if (tab === "applications") loadApplications().catch(console.error);
      if (tab === "config") loadConfigForm().catch(console.error);
    })
  );
}

function setupApplicationsFilters() {
  $("#app-search").addEventListener("input", (e) => {
    appSearch = e.target.value || "";
    filterApplicationsRows();
  });
  $$("#app-chips .chip").forEach((c) =>
    c.addEventListener("click", () => {
      $$("#app-chips .chip").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
      appFilter = c.dataset.filter || "all";
      filterApplicationsRows();
    })
  );
}

async function fireAgent(name) {
  await fetch(`/api/agents/${name}/run`, { method: "POST" });
}

function setupAgentToggles() {
  const names = ["scraper", "filter", "resume", "apply", "notify"];
  const root = $("#agent-toggles");
  root.innerHTML = "";
  names.forEach((n) => {
    const row = document.createElement("div");
    row.className = "toggle-row";
    row.innerHTML = `<span>${n}</span><div class="switch" data-agent="${n}"></div>`;
    const sw = row.querySelector(".switch");
    sw.addEventListener("click", () => {
      sw.classList.toggle("on");
      if (sw.classList.contains("on")) {
        fireAgent(n).catch(console.error);
        setTimeout(() => sw.classList.remove("on"), 800);
      }
    });
    root.appendChild(row);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupApplicationsFilters();
  setupAgentToggles();
  refreshStats();
  statsTimer = setInterval(refreshStats, 30000);
  connectLogsWS();
  connectJarvis();
});
