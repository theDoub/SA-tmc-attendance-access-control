const state = {
  factories: {},
  employees: [],
  activeTab: "attempts",
  currentToken: null,
  lastValidToken: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function renderQrMatrix(token) {
  const box = $("qr-visual-container");
  if (!token) {
    box.innerHTML = '<span style="font-size:11px;color:#6b7280">No QR</span>';
    return;
  }
  const size = 21;
  const cells = [];
  let h = 2166136261;
  for (let i = 0; i < token.length; i++) {
    h ^= token.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const isFinder = (r, c) =>
    (r < 7 && c < 7) || (r < 7 && c >= size - 7) || (r >= size - 7 && c < 7);
  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) {
      let on = false;
      if (isFinder(r, c)) {
        const lr = r >= size - 7 ? r - (size - 7) : r;
        const lc = c >= size - 7 ? c - (size - 7) : c;
        on = lr === 0 || lr === 6 || lc === 0 || lc === 6 || (lr >= 2 && lr <= 4 && lc >= 2 && lc <= 4);
      } else {
        const idx = (r * size + c) % token.length;
        on = ((token.charCodeAt(idx) + r * 3 + c * 7 + (h & 0xff)) % 2) === 0;
      }
      if (on) cells.push(`<rect x="${c}" y="${r}" width="1" height="1" fill="#111827"/>`);
    }
  }
  box.innerHTML = `<svg viewBox="0 0 ${size} ${size}" width="84" height="84">${cells.join("")}</svg>`;
}

function updateGateVisual(status, reasonCode) {
  const arm = $("gate-arm-group");
  const led = $("gate-led");
  const badge = $("gate-status-badge");
  const cap = $("gate-svg-caption");
  const banner = $("last-outcome-banner");

  arm.setAttribute("class", "gate-arm-locked");
  led.setAttribute("class", "led-neutral");
  badge.className = "pill pill-neutral";
  banner.className = "outcome-banner outcome-neutral";

  if (!status) {
    badge.textContent = "LOCKED";
    cap.textContent = "LOCKED - Awaiting Scan";
    return;
  }

  badge.textContent = status;
  if (status === "PASSAGE_CONFIRMED") {
    arm.setAttribute("class", "gate-arm-open");
    led.setAttribute("class", "led-ok");
    badge.className = "pill pill-online";
    cap.textContent = "PASSAGE CONFIRMED (Attendance Persisted)";
    banner.className = "outcome-banner outcome-ok";
    banner.textContent = `Access granted & passage confirmed (${status}).`;
  } else if (status === "PASSAGE_UNRESOLVED") {
    arm.setAttribute("class", "gate-arm-open");
    led.setAttribute("class", "led-warn");
    badge.className = "pill pill-warn";
    cap.textContent = `UNRESOLVED (${reasonCode || "NO_PASSAGE"})`;
    banner.className = "outcome-banner outcome-warn";
    banner.textContent = `Gate unlocked but passage unresolved: ${reasonCode}. No attendance recorded.`;
  } else if (status.startsWith("UNLOCK_")) {
    arm.setAttribute("class", "gate-arm-denied");
    led.setAttribute("class", "led-err");
    badge.className = "pill pill-offline";
    cap.textContent = `${status} (${reasonCode || ""})`;
    banner.className = "outcome-banner outcome-err";
    banner.textContent = `Turnstile failure: ${status} (${reasonCode || "GATE_ERROR"}). No attendance recorded.`;
  } else {
    arm.setAttribute("class", "gate-arm-denied");
    led.setAttribute("class", "led-err");
    badge.className = "pill pill-offline";
    cap.textContent = `DENIED (${reasonCode || ""})`;
    banner.className = "outcome-banner outcome-err";
    banner.textContent = `Access denied: ${reasonCode || "DENIED"}. Gate remained locked.`;
  }
}

function renderTimeline(steps) {
  const list = $("timeline-list");
  list.innerHTML = steps
    .map(
      (s) => `
    <li class="tl-item tl-${s.state}">
      <span class="tl-dot"></span>
      <div>
        <strong>${s.step}</strong>
        <p>${s.detail}</p>
      </div>
    </li>`
    )
    .join("");
}

function applyState(s) {
  state.factories = s.factories;
  state.employees = s.employees;

  if ($("select-factory").options.length === 0) {
    for (const [fid, info] of Object.entries(s.factories)) {
      const opt = new Option(`${fid} - ${info.name}`, fid);
      $("select-factory").add(opt);
    }
    syncFactorySelection();
  }
  if ($("select-employee").options.length === 0) {
    for (const emp of s.employees) {
      const opt = new Option(`${emp.display_name} (${emp.role})`, emp.employee_id);
      $("select-employee").add(opt);
    }
    updateEmployeeNote();
  }

  $("select-gate-scenario").value = s.gate_scenario;

  const hubOnline = s.connectivity.connected;
  const pill = $("hub-status-pill");
  pill.textContent = hubOnline ? "Hub: ONLINE" : "Hub: OFFLINE";
  pill.className = hubOnline ? "pill pill-online" : "pill pill-offline";
  $("btn-toggle-hub").textContent = hubOnline ? "Switch Hub OFFLINE" : "Switch Hub ONLINE";
  $("chk-lose-ack").checked = s.connectivity.lose_ack_once;

  $("kpi-pending").textContent = s.outbox_counts.PENDING;
  $("kpi-synced").textContent = s.outbox_counts.SYNCED;
  $("kpi-rejected").textContent = s.outbox_counts.REJECTED;
  $("kpi-conflict").textContent = s.outbox_counts.CONFLICT;
  $("kpi-hub").textContent = s.hub_event_count;
  $("kpi-failures").textContent = s.retry_worker.failures;

  $("cnt-attempts").textContent = s.attempt_count;
  $("cnt-attendance").textContent = s.attendance_count;
  $("cnt-outbox").textContent =
    s.outbox_counts.PENDING +
    s.outbox_counts.SYNCED +
    s.outbox_counts.REJECTED +
    s.outbox_counts.CONFLICT;

  const wBadge = $("sync-worker-badge");
  if (s.retry_worker.failures > 0) {
    wBadge.textContent = `Backoff: ${s.retry_worker.next_backoff_seconds}s`;
    wBadge.className = "pill pill-warn";
  } else {
    wBadge.textContent = "Worker Ready";
    wBadge.className = "pill pill-neutral";
  }
  $("sync-status-msg").textContent = s.retry_worker.last_message;
}

function syncFactorySelection() {
  const fid = $("select-factory").value;
  const info = state.factories[fid];
  if (!info) return;
  $("input-station").value = info.station_id;
  const gateSel = $("select-gate");
  const prev = gateSel.value;
  gateSel.innerHTML = "";
  for (const g of info.gates) {
    gateSel.add(new Option(g, g));
  }
  if (info.gates.includes(prev)) gateSel.value = prev;
}

function updateEmployeeNote() {
  const eid = $("select-employee").value;
  const emp = state.employees.find((e) => e.employee_id === eid);
  $("employee-policy-note").textContent = emp ? emp.policy_summary : "";
}

async function issueQr(malformed = false) {
  const employee_id = $("select-employee").value;
  const station_id = $("input-station").value;
  const data = await api("/demo/credentials", {
    method: "POST",
    body: JSON.stringify({ employee_id, station_id, malformed }),
  });
  state.currentToken = data.token;
  if (!malformed) state.lastValidToken = data.token;
  $("qr-token-preview").textContent = `${data.token.slice(0, 42)}... (${data.token.length} chars)`;
  $("qr-claims-preview").textContent = JSON.stringify(data.claims, null, 2);
  renderQrMatrix(data.token);
  return data.token;
}

async function performScan(token) {
  const res = await api("/demo/scan", {
    method: "POST",
    body: JSON.stringify({
      factory_id: $("select-factory").value,
      station_id: $("input-station").value,
      gate_id: $("select-gate").value,
      direction: $("select-direction").value,
      payload: token,
      gate_scenario: $("select-gate-scenario").value,
    }),
  });
  updateGateVisual(res.attempt.status, res.attempt.reason_code);
  renderTimeline(res.timeline);
  applyState(res.state);
  await loadTable();
}

async function loadTable() {
  const rows = await api(`/demo/${state.activeTab}`);
  const thead = $("db-thead");
  const tbody = $("db-tbody");

  if (state.activeTab === "attempts") {
    thead.innerHTML =
      "<tr><th>Attempt ID</th><th>Subject</th><th>Station / Gate</th><th>Dir</th><th>Status</th><th>Reason</th><th>Received At</th></tr>";
    tbody.innerHTML = rows
      .map(
        (r) => `<tr>
        <td><code>${r.access_attempt_id}</code></td>
        <td>${r.subject_id || "-"}</td>
        <td>${r.station_id} / ${r.gate_id}</td>
        <td>${r.direction}</td>
        <td><strong>${r.status}</strong></td>
        <td>${r.reason_code || "-"}</td>
        <td>${r.received_at}</td>
      </tr>`
      )
      .join("");
  } else if (state.activeTab === "attendance") {
    thead.innerHTML =
      "<tr><th>Seq</th><th>Transaction ID</th><th>Attempt ID</th><th>Employee</th><th>Gate</th><th>Dir</th><th>Policy</th><th>ACK</th><th>Evidence</th><th>Outbox</th><th>Event Time</th></tr>";
    tbody.innerHTML = rows
      .map(
        (r) => `<tr>
        <td><strong>${r.source_sequence}</strong></td>
        <td><code>${r.transaction_id.slice(0, 13)}...</code></td>
        <td><code>${r.access_attempt_id}</code></td>
        <td>${r.employee_id}</td>
        <td>${r.gate_id}</td>
        <td>${r.direction}</td>
        <td>${r.policy_version}</td>
        <td>${r.controller_ack}</td>
        <td>${r.confirmation_evidence}</td>
        <td><strong>${r.sync_status}</strong></td>
        <td>${r.event_time}</td>
      </tr>`
      )
      .join("");
  } else {
    thead.innerHTML =
      "<tr><th>Transaction ID</th><th>Sync Status</th><th>Seq</th><th>Employee</th><th>Gate</th><th>Created At</th><th>Rejection</th></tr>";
    tbody.innerHTML = rows
      .map(
        (r) => `<tr>
        <td><code>${r.transaction_id.slice(0, 13)}...</code></td>
        <td><strong>${r.sync_status}</strong></td>
        <td>${r.source_sequence}</td>
        <td>${r.employee_id}</td>
        <td>${r.gate_id}</td>
        <td>${r.created_at}</td>
        <td>${r.rejection_reason || "-"}</td>
      </tr>`
      )
      .join("");
  }
}

async function init() {
  const s = await api("/demo/state");
  applyState(s);
  renderQrMatrix(null);
  updateGateVisual(null, null);
  await loadTable();
}

$("select-factory").addEventListener("change", syncFactorySelection);
$("select-employee").addEventListener("change", updateEmployeeNote);
$("select-gate-scenario").addEventListener("change", async () => {
  const s = await api("/demo/connectivity", {
    method: "POST",
    body: JSON.stringify({ gate_scenario: $("select-gate-scenario").value }),
  });
  applyState(s);
});

$("btn-gen-qr").addEventListener("click", () => issueQr(false));
$("btn-new-qr").addEventListener("click", () => issueQr(false));
$("btn-scan-qr").addEventListener("click", async () => {
  const tok = state.currentToken || (await issueQr(false));
  await performScan(tok);
});
$("btn-replay-qr").addEventListener("click", async () => {
  const tok = state.lastValidToken || state.currentToken;
  if (!tok) {
    alert("Generate and scan a valid QR first.");
    return;
  }
  await performScan(tok);
});
$("btn-malformed-qr").addEventListener("click", async () => {
  const tok = await issueQr(true);
  await performScan(tok);
});

$("btn-toggle-hub").addEventListener("click", async () => {
  const currentlyOnline = $("hub-status-pill").textContent.includes("ONLINE");
  const s = await api("/demo/connectivity", {
    method: "POST",
    body: JSON.stringify({ connected: !currentlyOnline }),
  });
  applyState(s);
});

$("chk-lose-ack").addEventListener("change", async () => {
  const s = await api("/demo/connectivity", {
    method: "POST",
    body: JSON.stringify({ lose_ack_once: $("chk-lose-ack").checked }),
  });
  applyState(s);
});

$("btn-sync-now").addEventListener("click", async () => {
  const res = await api("/demo/sync", { method: "POST", body: JSON.stringify({ mode: "sync" }) });
  applyState(res.state);
  await loadTable();
});

$("btn-retry-now").addEventListener("click", async () => {
  const res = await api("/demo/sync", { method: "POST", body: JSON.stringify({ mode: "retry" }) });
  applyState(res.state);
  await loadTable();
});

$("btn-refresh").addEventListener("click", async () => {
  applyState(await api("/demo/state"));
  await loadTable();
});

$("btn-reset").addEventListener("click", async () => {
  const s = await api("/demo/reset", { method: "POST" });
  state.currentToken = null;
  state.lastValidToken = null;
  $("qr-token-preview").textContent = "None issued yet";
  $("qr-claims-preview").textContent = "{}";
  renderQrMatrix(null);
  updateGateVisual(null, null);
  $("timeline-list").innerHTML =
    '<li class="tl-item tl-skipped"><span class="tl-dot"></span><div><strong>Demo reset</strong><p>SQLite demo tables and ReplayGuardStore cleared.</p></div></li>';
  applyState(s);
  await loadTable();
});

$("btn-demo-mode").addEventListener("click", () => {
  document.body.classList.toggle("presentation-mode");
});

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.activeTab = btn.dataset.tab;
    await loadTable();
  });
});

init();
