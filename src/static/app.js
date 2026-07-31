// Water Information Display — live card updates over WebSocket.
(function () {
  "use strict";

  const connStatus = document.getElementById("conn-status");
  const lastRefresh = document.getElementById("last-refresh");
  let ws = null;

  function setConn(online) {
    if (!connStatus) return;
    connStatus.textContent = online ? "live" : "reconnecting…";
    connStatus.className = online ? "conn-online" : "conn-offline";
  }

  function applyCard(card) {
    const el = document.querySelector(`.card[data-sensor="${CSS.escape(card.sensor)}"]`);
    if (!el) return;

    const valueBox = el.querySelector('[data-field="value"]');
    if (valueBox) valueBox.className = `card-value ${card.value_class}`;

    const setText = (field, text) => {
      const node = el.querySelector(`[data-field="${field}"]`);
      if (node) node.textContent = text;
    };
    setText("value_int", card.value_int);
    setText("value_dec", card.value_dec);
    setText("min", card.min_str);
    setText("max", card.max_str);

    const status = el.querySelector('[data-field="status"]');
    if (status) {
      status.textContent = card.status_label;
      status.className = `card-status status-${card.status}`;
    }
  }

  function esc(value) {
    const div = document.createElement("div");
    div.textContent = value === null || value === undefined ? "—" : value;
    return div.innerHTML;
  }

  function renderDiagnostics(sensors) {
    const body = document.getElementById("diagnostics-body");
    if (!body) return;
    const only = body.dataset.sensor;
    const list = only ? sensors.filter((s) => s.sensor === only) : sensors;
    const rows = list.map((s) => {
      const fields = Object.entries(s.fields || {}).map(([key, value]) => {
        const raw = key.replace(/_/g, " ");
        const label = esc(raw.charAt(0).toUpperCase() + raw.slice(1));
        return `<div class="system-row"><span class="system-key diag-field-key">${label}</span>` +
          `<span class="system-val">${esc(value)}</span></div>`;
      }).join("");
      return `<div class="system-card"><div class="system-row diag-head">` +
        `<span class="system-key diag-name">${esc(s.display_name)}</span>` +
        `<span class="system-val diag-raw">${esc(s.sensor)}</span></div>${fields}</div>`;
    }).join("");
    body.innerHTML = rows || '<div class="system-card"><div class="system-row">' +
      '<span class="system-val">No sensor data yet.</span></div></div>';
  }

  function updateDiagnostics(state) {
    const body = document.getElementById("diagnostics-body");
    if (!body) return; // not on the diagnostics page

    const apiStatus = document.querySelector('[data-field="diag_api"]');
    if (apiStatus && typeof state.api_ok === "boolean") {
      apiStatus.textContent = state.api_ok ? "Online" : "Offline";
      apiStatus.className = `system-val ${state.api_ok ? "status-ok" : "status-error"}`;
    }
    const lastValid = document.querySelector('[data-field="diag_last_valid"]');
    if (lastValid && state.last_valid_response) {
      lastValid.textContent = state.last_valid_response;
    }
    if (state.diagnostics) renderDiagnostics(state.diagnostics);
  }

  function applyState(state) {
    (state.cards || []).forEach(applyCard);
    updateDiagnostics(state);
    if (lastRefresh && state.last_valid_response) {
      lastRefresh.textContent = state.last_valid_response;
    }
  }

  function connect() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
      setConn(true);
      // Ask the backend to poll fast while the diagnostics page is open.
      if (document.getElementById("diagnostics-body")) ws.send("diagnostics");
    };
    ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch (e) { return; }
      if (msg.type === "state_update" && msg.state) applyState(msg.state);
    };
    ws.onclose = () => { setConn(false); ws = null; setTimeout(connect, 2000); };
    ws.onerror = () => { if (ws) ws.close(); };
  }

  connect();
})();
