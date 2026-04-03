/* Ultra Job Agent — vanilla dashboard v2 */

// Register service worker for PWA / offline support
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/sw.js").catch(() => {});
}

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function wsUrl(path) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${path}`;
}

async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${url} ${r.status}`);
  return r.json();
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function showModal(title, body) {
  const ov = $("#modal-overlay");
  if (!ov) return;
  $("#modal-title").textContent = title;
  $("#modal-body").textContent = body;
  ov.hidden = false;
}

function hideModal() {
  const ov = $("#modal-overlay");
  if (ov) ov.hidden = true;
}

function showToast(msg, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const t = document.createElement("div");
  t.className = `toast ${type}`;
  t.textContent = msg;
  container.appendChild(t);
  setTimeout(() => t.remove(), 3000);
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

function drawLineChart(canvas, points) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const pad = 24;
  const xs = points.map((_, i) => i);
  const ys = points.map((p) => p.count || 0);
  const maxY = Math.max(1, ...ys);
  ctx.strokeStyle = "#6c63ff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  xs.forEach((_, i) => {
    const x = pad + (i / Math.max(1, xs.length - 1)) * (w - pad * 2);
    const y = h - pad - (ys[i] / maxY) * (h - pad * 2);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = "#9090a8";
  ctx.font = "9px 'Space Mono', monospace";
  points.forEach((p, i) => {
    if (i % 3 !== 0 && i !== points.length - 1) return;
    const x = pad + (i / Math.max(1, points.length - 1)) * (w - pad * 2);
    ctx.fillText((p.date || "").slice(5), x - 10, h - 6);
  });
}

function drawFunnel(canvas, funnel) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const order = ["DISCOVERED", "FILTERED", "TAILORED", "APPLIED", "INTERVIEW", "OFFER"];
  const rows = [];
  order.forEach((k) => {
    if (funnel[k] != null) rows.push({ key: k, val: Number(funnel[k]) || 0 });
  });
  if (!rows.length) return;
  const max = Math.max(1, ...rows.map((r) => r.val));
  const bh = (h - 40) / rows.length;
  rows.forEach((row, i) => {
    const width = (row.val / max) * (w - 80) + 40;
    const y = 20 + i * bh;
    const hue = 250 - i * 28;
    ctx.fillStyle = `hsl(${hue}, 70%, 55%)`;
    ctx.fillRect(40, y, width, bh - 6);
    ctx.fillStyle = "#c8c8d8";
    ctx.font = "10px 'Space Mono', monospace";
    ctx.fillText(`${row.key} ${row.val}`, 8, y + bh / 2 + 4);
  });
}

function drawKeywordHeat(canvas, keywords) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const max = Math.max(1, keywords.length);
  keywords.forEach((word, i) => {
    const x = 16 + (i % 8) * ((w - 32) / 8);
    const y = 24 + Math.floor(i / 8) * 36;
    const intensity = 0.35 + (0.5 * (max - i)) / max;
    ctx.fillStyle = `rgba(108, 99, 255, ${intensity})`;
    ctx.fillRect(x, y, (w - 48) / 8 - 4, 28);
    ctx.fillStyle = "#e8e8f0";
    ctx.font = "11px 'DM Sans', sans-serif";
    ctx.fillText(String(word).slice(0, 12), x + 6, y + 18);
  });
}

function atsBadge(score) {
  const s = Number(score) || 0;
  let cls = "ats-na";
  let g = "—";
  if (s >= 80) {
    cls = "ats-a";
    g = `${s}%`;
  } else if (s >= 65) {
    cls = "ats-b";
    g = `${s}%`;
  } else if (s >= 50) {
    cls = "ats-c";
    g = `${s}%`;
  } else if (s > 0) {
    cls = "ats-d";
    g = `${s}%`;
  }
  return `<span class="ats-badge ${cls}">${g}</span>`;
}

let statsTimer = null;
let appsCache = [];
let appFilter = "all";
let appSearch = "";

async function refreshDbStatus() {
  const pill = $("#db-pill");
  if (!pill) return;
  try {
    const r = await fetchJSON("/api/db-status");
    if (r.status === "ok") {
      pill.textContent = "DB OK";
      pill.className = "pill pill-ok";
    } else if (r.status === "unreachable") {
      pill.textContent = "DB paused";
      pill.className = "pill pill-warn";
      pill.title = r.message || "Supabase project may be paused";
    } else {
      pill.textContent = "DB not set";
      pill.className = "pill pill-muted";
      pill.title = r.message || "";
    }
  } catch {
    pill.textContent = "DB ?";
    pill.className = "pill pill-muted";
  }
}

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
  refreshDbStatus();
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
  const boards = { linkedin: 0, indeed: 0, naukri: 0, glassdoor: 0, other: 0 };
  (jobs || []).forEach((j) => {
    const src = (j.source || "").toLowerCase();
    if (src.includes("linkedin")) boards.linkedin += 1;
    else if (src.includes("indeed")) boards.indeed += 1;
    else if (src.includes("naukri")) boards.naukri += 1;
    else if (src.includes("glassdoor")) boards.glassdoor += 1;
    else boards.other += 1;
  });
  const c1 = $("#chart-boards");
  if (c1)
    drawBarChart(
      c1,
      ["LinkedIn", "Indeed", "Naukri", "Glassdoor", "Other"],
      [boards.linkedin, boards.indeed, boards.naukri, boards.glassdoor, boards.other],
      ["#6c63ff", "#ff6584", "#43e97b", "#f7971e", "#9090a8"]
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
  if (c2)
    drawBarChart(
      c2,
      ["90+", "80-90", "75-80", "<75"],
      [b90, b80, b75, low],
      ["#43e97b", "#6c63ff", "#f7971e", "#ff6584"]
    );
}

async function loadAnalytics() {
  const a = await fetchJSON("/api/analytics/overview");
  setText("an-total-applied", String(a.total_applied ?? "0"));
  setText("an-response-rate", `${a.response_rate ?? 0}%`);
  setText("an-avg-match", `${a.avg_match_score ?? 0}%`);
  setText("an-open-rate", `${a.recruiter_email_open_rate ?? 0}%`);

  const cf = $("#chart-funnel");
  if (cf) drawFunnel(cf, a.status_funnel || {});

  const cd = $("#chart-daily");
  if (cd) drawLineChart(cd, a.daily_applied || []);

  const src = a.top_sources || {};
  const labels = Object.keys(src);
  const vals = labels.map((k) => src[k]);
  const cs = $("#chart-source-an");
  if (cs && labels.length)
    drawBarChart(
      cs,
      labels.map((x) => x.slice(0, 8)),
      vals,
      ["#6c63ff", "#ff6584", "#43e97b", "#f7971e", "#8b7bff"]
    );

  const vs = a.resume_variant_stats || {};
  const vlabels = Object.keys(vs);
  const vvals = vlabels.map((k) => vs[k].responses || 0);
  const cv = $("#chart-variants");
  if (cv && vlabels.length) drawBarChart(cv, vlabels, vvals, ["#6c63ff", "#43e97b", "#ff6584", "#f7971e"]);

  const ck = $("#chart-keywords");
  if (ck) drawKeywordHeat(ck, a.best_performing_keywords || []);
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
        const line = typeof msg.data === "string" ? msg.data : msg.msg || JSON.stringify(msg.data);
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
  const srcF = ($("#app-source") && $("#app-source").value) || "";
  const smin = ($("#app-score-min") && $("#app-score-min").value) || "";
  const smax = ($("#app-score-max") && $("#app-score-max").value) || "100";
  const dfrom = ($("#app-date-from") && $("#app-date-from").value) || "";
  appsCache.forEach((row) => {
    const job = row.job || {};
    const st = row.status || "";
    if (appFilter !== "all") {
      if (appFilter === "APPLIED" && st !== "APPLIED" && st !== "SUBMITTED") return;
      if (appFilter === "INTERVIEW" && st !== "INTERVIEW") return;
      if (appFilter === "OFFER" && st !== "OFFER") return;
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
    if (srcF) {
      const s = (job.source || "").toLowerCase();
      if (!s.includes(srcF.toLowerCase())) return;
    }
    const score = Number(job.match_score) || 0;
    if (smin !== "" && score < Number(smin)) return;
    if (smax !== "" && score > Number(smax)) return;
    const applied = (row.applied_at || "").slice(0, 10);
    if (dfrom && applied && applied < dfrom) return;

    const tr = document.createElement("tr");
    const aid = row.id;
    const jid = job.id;
    // Format salary
    let salaryText = "—";
    if (job.salary_min && job.salary_max) {
      const fmt = (n) => n >= 100000 ? `₹${(n/100000).toFixed(1)}L` : `₹${n.toLocaleString()}`;
      salaryText = `${fmt(job.salary_min)}–${fmt(job.salary_max)}`;
    } else if (job.salary_estimate) {
      salaryText = job.salary_estimate.slice(0, 14);
    }
    // Remote type badge
    const remoteType = job.remote_type || "unknown";
    const remoteBadge = remoteType !== "unknown"
      ? `<span class="status-pill status-${remoteType === 'remote' ? 'APPLIED' : remoteType === 'hybrid' ? 'FILTERED' : 'DISCOVERED'}">${remoteType}</span>`
      : "—";
    tr.innerHTML = `
      <td>${job.company || ""}</td>
      <td>${job.title || ""}</td>
      <td><span class="status-pill">${job.source || "—"}</span></td>
      <td><div class="score-wrap"><div class="score-bar" style="width:${Math.min(100, score)}%"></div>${score}%</div></td>
      <td>${atsBadge(row.ats_score)}</td>
      <td style="font-size:12px;white-space:nowrap;">${salaryText}</td>
      <td>${remoteBadge}</td>
      <td><span class="status-pill status-${st}">${st}</span></td>
      <td>${(row.applied_at || "").slice(0, 10)}</td>
      <td>${
        row.resume_path
          ? `<a href="/${row.resume_path}" target="_blank" rel="noopener">PDF</a>`
          : "—"
      }</td>
      <td class="action-btns">
        <button type="button" class="btn ghost btn-ats" data-job="${jid || ""}">ATS</button>
        <button type="button" class="btn ghost btn-outreach" data-app="${aid || ""}">Outreach</button>
        <button type="button" class="btn ghost btn-prep" data-app="${aid || ""}">Prep</button>
        <button type="button" class="btn ghost btn-letter" data-app="${aid || ""}">Cover letter</button>
      </td>`;
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll(".btn-ats").forEach((b) =>
    b.addEventListener("click", async () => {
      const id = b.getAttribute("data-job");
      if (!id) return;
      try {
        const r = await fetchJSON(`/api/ats-check/${id}`);
        showModal("ATS check", JSON.stringify(r, null, 2));
      } catch (e) {
        showModal("ATS check", String(e));
      }
    })
  );
  tbody.querySelectorAll(".btn-outreach").forEach((b) =>
    b.addEventListener("click", async () => {
      const id = b.getAttribute("data-app");
      if (!id) return;
      try {
        const r = await fetchJSON(`/api/applications/${id}/recruiter-outreach`, { method: "POST" });
        showModal("Recruiter outreach", JSON.stringify(r, null, 2));
      } catch (e) {
        showModal("Recruiter outreach", String(e));
      }
    })
  );
  tbody.querySelectorAll(".btn-prep").forEach((b) =>
    b.addEventListener("click", async () => {
      const id = b.getAttribute("data-app");
      if (!id) return;
      try {
        const r = await fetchJSON(`/api/applications/${id}/interview-prep/generate`, { method: "POST" });
        showModal("Interview prep generated", JSON.stringify(r, null, 2));
      } catch (e) {
        showModal("Interview prep", String(e));
      }
    })
  );
  tbody.querySelectorAll(".btn-letter").forEach((b) =>
    b.addEventListener("click", async () => {
      const id = b.getAttribute("data-app");
      if (!id) return;
      try {
        const r = await fetchJSON(`/api/applications/${id}/cover-letter`);
        showModal("Cover letter", r.cover_letter || "(empty)");
      } catch (e) {
        showModal("Cover letter", String(e));
      }
    })
  );
}

async function loadApplications() {
  const data = await fetchJSON("/api/applications?limit=500");
  appsCache = data.applications || [];
  filterApplicationsRows();
  populatePrepSelect();
}

function populatePrepSelect() {
  const sel = $("#prep-app-select");
  if (!sel) return;
  const cur = sel.value;
  sel.innerHTML = "";
  appsCache.forEach((row) => {
    const job = row.job || {};
    const opt = document.createElement("option");
    opt.value = row.id;
    opt.textContent = `${job.company || "?"} — ${job.title || "Role"}`;
    sel.appendChild(opt);
  });
  if (cur) sel.value = cur;
}

function prepLocalKey(id) {
  return `prep_notes_${id}`;
}

function loadPrepLocal(id) {
  const notes = $("#prep-company-notes");
  const list = $("#prep-cal-list");
  if (notes) notes.value = localStorage.getItem(prepLocalKey(id)) || "";
  if (list) {
    list.innerHTML = "";
    const raw = localStorage.getItem(`prep_cal_${id}`) || "[]";
    let items = [];
    try {
      items = JSON.parse(raw);
    } catch {
      items = [];
    }
    items.forEach((t) => {
      const li = document.createElement("li");
      li.textContent = t;
      list.appendChild(li);
    });
  }
}

async function setupPrepPanel() {
  const sel = $("#prep-app-select");
  const loadBtn = $("#prep-load");
  const genBtn = $("#prep-generate");
  const saveNotes = $("#prep-notes-save");
  const calAdd = $("#prep-cal-add");
  if (!sel || !loadBtn) return;

  sel.addEventListener("change", () => loadPrepLocal(sel.value));

  loadBtn.addEventListener("click", async () => {
    const id = sel.value;
    if (!id) return;
    try {
      const r = await fetchJSON(`/api/applications/${id}/interview-prep`);
      $("#prep-json").textContent = JSON.stringify(r.interview_prep || {}, null, 2);
      loadPrepLocal(id);
    } catch (e) {
      $("#prep-json").textContent = String(e);
    }
  });

  genBtn &&
    genBtn.addEventListener("click", async () => {
      const id = sel.value;
      if (!id) return;
      try {
        const r = await fetchJSON(`/api/applications/${id}/interview-prep/generate`, { method: "POST" });
        $("#prep-json").textContent = JSON.stringify(r, null, 2);
      } catch (e) {
        $("#prep-json").textContent = String(e);
      }
    });

  saveNotes &&
    saveNotes.addEventListener("click", () => {
      const id = sel.value;
      if (!id) return;
      localStorage.setItem(prepLocalKey(id), $("#prep-company-notes").value || "");
    });

  calAdd &&
    calAdd.addEventListener("click", () => {
      const id = sel.value;
      if (!id) return;
      const v = ($("#prep-cal-input") && $("#prep-cal-input").value) || "";
      if (!v) return;
      const raw = localStorage.getItem(`prep_cal_${id}`) || "[]";
      let items = [];
      try {
        items = JSON.parse(raw);
      } catch {
        items = [];
      }
      items.push(v);
      localStorage.setItem(`prep_cal_${id}`, JSON.stringify(items));
      loadPrepLocal(id);
    });
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

function setupConfigForm() {
  const form = $("#config-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = {};
    new FormData(e.target).forEach((v, k) => {
      data[k] = v;
    });
    try {
      await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      showToast("Overrides saved to Redis.", "success");
    } catch (err) {
      showToast("Failed to save overrides.", "error");
    }
  });
}

function switchTab(tab) {
  // Update sidebar buttons
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  // Update mobile nav buttons
  $$(".mobile-nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  // Show panel
  $$(".panel").forEach((p) => p.classList.remove("active"));
  const panel = $(`#panel-${tab}`);
  if (panel) panel.classList.add("active");
  // Load data
  if (tab === "pipeline") loadPipeline().catch(console.error);
  if (tab === "applications") loadApplications().catch(console.error);
  if (tab === "analytics") loadAnalytics().catch(console.error);
  if (tab === "config") loadConfigForm().catch(console.error);
}

function setupTabs() {
  $$(".nav-btn").forEach((btn) =>
    btn.addEventListener("click", () => switchTab(btn.dataset.tab))
  );
  // Mobile nav mirrors sidebar
  $$(".mobile-nav-btn").forEach((btn) =>
    btn.addEventListener("click", () => switchTab(btn.dataset.tab))
  );
  // Deep-link: ?tab=applications
  const urlTab = new URLSearchParams(location.search).get("tab");
  if (urlTab) switchTab(urlTab);
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
  ["app-source", "app-score-min", "app-score-max", "app-date-from"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", () => filterApplicationsRows());
    if (el) el.addEventListener("change", () => filterApplicationsRows());
  });
}

async function fireAgent(name) {
  await fetch(`/api/agents/${name}/run`, { method: "POST" });
}

function setupAgentToggles() {
  const names = [
    "scraper",
    "filter",
    "resume",
    "apply",
    "notify",
    "ats_checker",
    "recruiter_outreach",
    "interview_coach",
    "linkedin_optimizer",
    "resume_variant",
  ];
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
  setupPrepPanel();
  setupConfigForm();
  $("#modal-close") &&
    $("#modal-close").addEventListener("click", () => hideModal());
  $("#modal-overlay") &&
    $("#modal-overlay").addEventListener("click", (e) => {
      if (e.target.id === "modal-overlay") hideModal();
    });

  $("#btn-linkedin-run") &&
    $("#btn-linkedin-run").addEventListener("click", async () => {
      const out = $("#linkedin-result");
      if (out) out.textContent = "Running…";
      try {
        const r = await fetchJSON("/api/linkedin-optimize", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        if (out) out.textContent = JSON.stringify(r, null, 2);
      } catch (e) {
        if (out) out.textContent = String(e);
      }
    });

  // Resume upload handler
  const uploadBtn = document.getElementById("btn-upload-resume");
  const uploadInput = document.getElementById("resume-upload-input");
  const uploadStatus = document.getElementById("upload-status");
  if (uploadBtn && uploadInput) {
    uploadBtn.addEventListener("click", async () => {
      const file = uploadInput.files && uploadInput.files[0];
      if (!file) {
        showToast("Please select a file first.", "error");
        return;
      }
      const formData = new FormData();
      formData.append("file", file);
      uploadBtn.disabled = true;
      if (uploadStatus) uploadStatus.textContent = "Uploading…";
      try {
        const resp = await fetch("/api/resume/upload", { method: "POST", body: formData });
        const result = await resp.json();
        if (!resp.ok) throw new Error(result.detail || resp.statusText);
        showToast(`Resume uploaded: ${result.filename}`, "success");
        if (uploadStatus) {
          uploadStatus.textContent = result.saved_as_base
            ? `✓ Saved as base resume. Text extracted: ${result.text_extracted ? "yes" : "no"}.`
            : `✓ Uploaded (no text extracted — use TXT for best results).`;
        }
      } catch (err) {
        showToast(`Upload failed: ${err.message}`, "error");
        if (uploadStatus) uploadStatus.textContent = `Error: ${err.message}`;
      } finally {
        uploadBtn.disabled = false;
      }
    });
  }

  // PWA install prompt
  let deferredInstallPrompt = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    const banner = document.getElementById("pwa-install-banner");
    if (banner) banner.style.display = "block";
  });
  const installBanner = document.getElementById("pwa-install-banner");
  if (installBanner) {
    installBanner.addEventListener("click", async () => {
      if (!deferredInstallPrompt) return;
      deferredInstallPrompt.prompt();
      const { outcome } = await deferredInstallPrompt.userChoice;
      if (outcome === "accepted") installBanner.style.display = "none";
      deferredInstallPrompt = null;
    });
  }

  refreshStats();
  statsTimer = setInterval(refreshStats, 30000);
  connectLogsWS();
  connectJarvis();
});
