(() => {
"use strict";

const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

const LS_SESSIONS = "daa_sessions";
const LS_PINNED = "daa_pinned";

const state = {
  database: "grocery",
  messages: [],
  streaming: false,
  sessionId: null,
  lastQuestion: null,
  lastSql: "",
  mmCounter: 1000,
  stick: true,
  schemaOpen: false,
  schemaLoaded: {},
};

const msgEls = new Map();

const els = {
  sidebar: $("#sidebar"),
  dbSelect: $("#db-select"),
  newChat: $("#new-chat-btn"),
  sessionList: $("#session-list"),
  historyList: $("#history-list"),
  pinnedList: $("#pinned-list"),
  schemaToggle: $("#schema-toggle"),
  schemaPanel: $("#schema-panel"),
  topbarDb: $("#topbar-db"),
  sidebarToggle: $("#sidebar-toggle"),
  sidebarFade: $("#sidebar-fade"),
  errorBanner: $("#error-banner"),
  errorText: $("#error-text"),
  errorClose: $("#error-close"),
  errorRetry: $("#error-retry"),
  scrollBottom: $("#scroll-bottom"),
  statusBar: $("#status-bar"),
  statusDot: $("#status-dot"),
  statusText: $("#status-text"),
  messages: $("#messages"),
  welcome: $("#welcome"),
  welcomeNote: $("#welcome-note"),
  input: $("#input"),
  sendBtn: $("#send-btn"),
};

if (window.marked) marked.setOptions({ breaks: true, gfm: true });

if (window.mermaid) mermaid.initialize({ startOnLoad: false, theme: "dark" });

const TOOL_LABELS = {
  get_schema: "View schema",
  execute_query: "Query data",
  generate_chart: "Generate chart",
  generate_flowchart: "Generate diagram",
  explain_data: "Explain analysis",
};

/* ------------------------------------------------------------------ */
/* utils                                                               */
/* ------------------------------------------------------------------ */

function esc(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function md(text) {
  try {
    return marked.parse(esc(text));
  } catch (err) {
    return "<p>" + esc(text) + "</p>";
  }
}

function makeEl(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text != null) el.textContent = text;
  return el;
}

function button(cls, html, title, onClick) {
  const b = makeEl("button", cls);
  b.innerHTML = html;
  if (title) b.title = title;
  b.addEventListener("click", onClick);
  return b;
}

function toolLabel(name) {
  return TOOL_LABELS[name] || name;
}

function isNumeric(val) {
  return typeof val === "number" || (typeof val === "string" && val !== "" && !isNaN(val));
}

function cellValue(val) {
  if (val === null || val === undefined) return "NULL";
  if (typeof val === "object") return JSON.stringify(val);
  return String(val);
}

function trunc(str, n) {
  str = String(str);
  return str.length > n ? str.slice(0, n - 1) + "…" : str;
}

function formatDate(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function api(path, opts) {
  const init = opts || {};
  init.headers = Object.assign({ "Content-Type": "application/json" }, init.headers || {});
  return fetch(path, init).then((res) => {
    if (!res.ok) throw new Error("Request failed: " + res.status);
    return res.json();
  });
}

function autoscroll() {
  if (!state.stick) return;
  els.messages.scrollTop = els.messages.scrollHeight;
}

/* ------------------------------------------------------------------ */
/* schema panel                                                        */
/* ------------------------------------------------------------------ */

function loadSchema() {
  const db = state.database;
  els.schemaPanel.innerHTML = "";
  els.schemaPanel.hidden = false;
  els.schemaPanel.classList.add("open");
  els.schemaToggle.textContent = "Hide schema";
  els.schemaPanel.innerHTML = '<div class="schema-loading">Loading schema…</div>';
  api("/api/schema?database=" + encodeURIComponent(db))
    .then((schema) => {
      els.schemaPanel.innerHTML = "";
      Object.keys(schema)
        .sort()
        .forEach((table) => {
          const info = schema[table];
          const head = makeEl("div", "schema-table-head");
          const name = makeEl("span", null, table);
          const count = makeEl("span", "schema-count", info.row_count + " rows");
          head.append(name, count);
          const body = makeEl("div", "schema-table-body");
          info.columns.forEach((col) => {
            const row = makeEl("div", "schema-col");
            const nm = makeEl("b", null, col.name);
            const ty = makeEl("span", "type", col.type || "TEXT");
            row.append(nm, ty);
            if (col.primary_key) row.append(makeEl("span", "badge", "PK"));
            body.append(row);
          });
          info.foreign_keys.forEach((fk) => {
            body.append(
              makeEl("div", "schema-fk", fk.column + " → " + fk.references_table + "." + fk.references_column)
            );
          });
          const box = makeEl("div", "schema-table");
          box.append(head, body);
          head.addEventListener("click", () => box.classList.toggle("open"));
          els.schemaPanel.append(box);
        });
      state.schemaLoaded[db] = true;
    })
    .catch((err) => {
      els.schemaPanel.innerHTML = '<div class="schema-loading">Schema unavailable: ' + esc(err.message) + "</div>";
    });
}

function toggleSchema(force) {
  const willOpen = force !== undefined ? force : !state.schemaOpen;
  state.schemaOpen = willOpen;
  if (!willOpen) {
    els.schemaPanel.hidden = true;
    els.schemaPanel.classList.remove("open");
    els.schemaToggle.textContent = "View schema";
    return;
  }
  loadSchema();
}

/* ------------------------------------------------------------------ */
/* pinned dashboard                                                    */
/* ------------------------------------------------------------------ */

function getPinned() {
  try {
    const raw = localStorage.getItem(LS_PINNED);
    return raw ? JSON.parse(raw) : [];
  } catch (err) {
    return [];
  }
}

function savePinned(list) {
  localStorage.setItem(LS_PINNED, JSON.stringify(list));
}

function isPinned(title) {
  return getPinned().some((p) => p.title === title);
}

function togglePin(figure, title) {
  const list = getPinned();
  const idx = list.findIndex((p) => p.title === title);
  if (idx >= 0) {
    list.splice(idx, 1);
  } else {
    list.push({ figure, title });
  }
  savePinned(list);
  renderPinned();
  refreshPinButtons();
  return idx < 0;
}

function renderPinned() {
  els.pinnedList.innerHTML = "";
  const list = getPinned();
  if (!list.length) {
    els.pinnedList.append(makeEl("div", "side-empty", "No pinned charts yet"));
    return;
  }
  list.forEach((p) => {
    const card = makeEl("div", "pin-card");
    const head = makeEl("div", "pin-card-head");
    head.append(makeEl("span", "pin-card-title", trunc(p.title, 34)));
    head.append(
      button("mini-btn", "✕", "Remove from dashboard", () => {
        togglePin(p.figure, p.title);
      })
    );
    const plot = makeEl("div", "pin-plot");
    card.append(head, plot);
    els.pinnedList.append(card);
    try {
      Plotly.newPlot(plot, p.figure.data || [], brandChartLayout(p.figure.layout), { responsive: true, displayModeBar: false });
    } catch (err) {
      plot.textContent = "Chart unavailable";
    }
  });
}

function refreshPinButtons() {
  $$(".pin-btn").forEach((b) => {
    const title = b.dataset.title;
    b.classList.toggle("pinned", isPinned(title));
    b.title = isPinned(title) ? "Unpin from dashboard" : "Pin to dashboard";
  });
}

/* ------------------------------------------------------------------ */
/* history                                                             */
/* ------------------------------------------------------------------ */

function loadHistory() {
  api("/api/history").then(renderHistory).catch(() => {});
}

function renderHistory(entries) {
  els.historyList.innerHTML = "";
  if (!entries.length) {
    els.historyList.append(makeEl("div", "side-empty", "No saved queries yet"));
    return;
  }
  entries.forEach((entry) => {
    const li = makeEl("li", "side-item");
    const main = makeEl("button", "side-item-main");
    const q = makeEl("span", null, trunc(entry.question, 46));
    const dbLine = makeEl("span", "side-item-db", entry.database + " · " + formatDate(entry.created_at));
    main.append(q, dbLine);
    main.title = "Ask this question again";
    main.addEventListener("click", () => reAsk(entry));
    const actions = makeEl("div", "side-item-actions");
    const fav = button("mini-btn" + (entry.favorite ? " starred" : ""), entry.favorite ? "★" : "☆", entry.favorite ? "Unfavorite" : "Favorite", (e) => {
      e.stopPropagation();
      toggleFavorite(entry, !entry.favorite);
    });
    const del = button("mini-btn", "🗑", "Delete", (e) => {
      e.stopPropagation();
      api("/api/history/" + entry.id, { method: "DELETE" }).then(loadHistory).catch(() => {});
    });
    actions.append(fav, del);
    li.append(main, actions);
    els.historyList.append(li);
  });
}

function toggleFavorite(entry, favorite) {
  api("/api/history/" + entry.id + "?favorite=" + favorite, { method: "PATCH" }).then(loadHistory).catch(() => {});
}

function reAsk(entry) {
  if (entry.database && entry.database !== state.database) {
    state.database = entry.database;
    els.dbSelect.value = entry.database;
    els.topbarDb.textContent = entry.database;
    if (state.schemaOpen) loadSchema();
  }
  focusWelcomeOut();
  sendMessage(entry.question);
}

/* ------------------------------------------------------------------ */
/* chat sessions (localStorage)                                        */
/* ------------------------------------------------------------------ */

function getSessions() {
  try {
    return JSON.parse(localStorage.getItem(LS_SESSIONS) || "[]");
  } catch (err) {
    return [];
  }
}

function saveSessions(list) {
  localStorage.setItem(LS_SESSIONS, JSON.stringify(list));
}

function sessionTitle() {
  const first = state.messages.find((m) => m.role === "user");
  return first ? trunc(first.content, 44) : "Untitled chat";
}

function saveCurrentSession() {
  if (!state.messages.length) return;
  const list = getSessions();
  if (state.sessionId) {
    const idx = list.findIndex((s) => s.id === state.sessionId);
    if (idx >= 0) {
      list[idx].messages = state.messages;
      list[idx].database = state.database;
      list[idx].title = sessionTitle();
    }
  } else {
    const session = {
      id: "s" + Date.now(),
      title: sessionTitle(),
      database: state.database,
      created_at: Date.now(),
      messages: state.messages,
    };
    list.unshift(session);
    state.sessionId = session.id;
  }
  saveSessions(list);
  renderSessions();
}

function renderSessions() {
  els.sessionList.innerHTML = "";
  const list = getSessions();
  if (!list.length) {
    els.sessionList.append(makeEl("div", "side-empty", "No saved sessions"));
    return;
  }
  list.forEach((session) => {
    const li = makeEl("li", "side-item" + (session.id === state.sessionId ? " active" : ""));
    const main = makeEl("button", "side-item-main");
    const t = makeEl("span", null, trunc(session.title, 42));
    const d = makeEl("span", "side-item-db", session.database);
    main.append(t, d);
    main.title = "Load this conversation";
    main.addEventListener("click", () => loadSession(session.id));
    const del = button("mini-btn", "✕", "Delete session", (e) => {
      e.stopPropagation();
      const remaining = getSessions().filter((s) => s.id !== session.id);
      saveSessions(remaining);
      if (state.sessionId === session.id) state.sessionId = null;
      renderSessions();
    });
    li.append(main, del);
    els.sessionList.append(li);
  });
}

function loadSession(id) {
  if (state.streaming) return;
  const list = getSessions();
  const session = list.find((s) => s.id === id);
  if (!session) return;
  saveCurrentSession();
  state.sessionId = id;
  state.messages = JSON.parse(JSON.stringify(session.messages || []));
  state.database = session.database || state.database;
  els.dbSelect.value = state.database;
  els.topbarDb.textContent = state.database;
  if (state.schemaOpen) loadSchema();
  renderAll();
  hideWelcome();
  state.stick = true;
  autoscroll();
  renderSessions();
}

function newChat() {
  if (state.streaming) return;
  saveCurrentSession();
  state.messages = [];
  state.sessionId = null;
  state.lastQuestion = null;
  state.lastSql = "";
  renderAll();
  showWelcome();
  focusInput();
  renderSessions();
}

/* ------------------------------------------------------------------ */
/* message rendering                                                   */
/* ------------------------------------------------------------------ */

function renderAll() {
  els.messages.innerHTML = "";
  msgEls.clear();
  state.messages.forEach((m) => renderMessage(m));
}

function renderMessage(message) {
  const index = state.messages.indexOf(message);
  if (message.role === "user") {
    const wrap = makeEl("div", "msg msg-user");
    const avatar = makeEl("div", "msg-avatar", "You");
    const body = makeEl("div", "msg-body");
    body.append(makeEl("div", "user-bubble", message.content));
    wrap.append(body, avatar);
    els.messages.append(wrap);
    return;
  }

  const wrap = makeEl("div", "msg msg-agent");
  const avatar = makeEl("div", "msg-avatar", "✦");
  wrap.append(avatar);

  const body = makeEl("div", "msg-body");
  const head = makeEl("div", "msg-head", "Data Agent");
  const copyAnswer = button("tool-btn", "Copy", "Copy answer", () => {
    navigator.clipboard.writeText(message.content || "").then(() => {
      copyAnswer.textContent = "Copied!";
      setTimeout(() => (copyAnswer.textContent = "Copy"), 1400);
    }).catch(() => {});
  });
  head.append(copyAnswer);
  const content = makeEl("div", "msg-content");
  content.innerHTML = md(message.content);
  const artifacts = makeEl("div", "artifacts");
  const chips = makeEl("div", "chips-row");
  body.append(head, content, chips, artifacts);

  (message.artifacts || []).forEach((artifact) => {
    const card = renderArtifact(artifact);
    artifacts.append(card);
    if (artifact.kind === "chart") plotChart(card, artifact);
  });

  wrap.append(body);
  els.messages.append(wrap);

  msgEls.set(index, { wrap, contentEl: content, chipsEl: chips, artifactsEl: artifacts });
}

function getMsgEl(index) {
  return msgEls.get(index);
}

function focusWelcomeOut() {
  els.welcome.hidden = true;
}

function hideWelcome() {
  els.welcome.hidden = true;
  els.messages.style.display = "block";
}

function showWelcome() {
  els.welcome.hidden = false;
  els.messages.style.display = "block";
}

/* ------------------------------------------------------------------ */
/* artifact cards                                                      */
/* ------------------------------------------------------------------ */

function renderArtifact(artifact) {
  if (artifact.kind === "chart") return chartCard(artifact);
  if (artifact.kind === "diagram") return diagramCard(artifact);
  if (artifact.kind === "sql") return sqlCard(artifact);
  if (artifact.kind === "table") return tableCard(artifact);
  return makeEl("div", "side-empty", "Unknown artifact");
}

function chartCard(artifact) {
  const card = makeEl("div", "card chart-card");
  const head = makeEl("div", "card-head");
  head.append(makeEl("span", null, artifact.title || "Chart"));
  const pin = button("pin-btn", "📌", "Pin to dashboard", () => {
    const pinned = togglePin(artifact.figure, artifact.title || "Chart");
    pin.classList.toggle("pinned", pinned);
    pin.title = pinned ? "Unpin from dashboard" : "Pin to dashboard";
  });
  pin.dataset.title = artifact.title || "Chart";
  pin.classList.toggle("pinned", isPinned(artifact.title || "Chart"));
  head.append(pin);
  card.append(head, makeEl("div", "chart-plot"));
  return card;
}

function brandChartLayout(layout) {
  const base = layout && typeof layout === "object" ? layout : {};
  return Object.assign({}, base, {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(16,17,28,0.85)",
    font: Object.assign({}, base.font, {
      color: "#A7A4B8",
      family: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
      size: 12,
    }),
    colorway: ["#8B5CF6", "#9B6CFF", "#B59CFF", "#34D399", "#22D3EE"],
    margin: Object.assign({ l: 56, r: 20, t: 30, b: 44 }, base.margin),
    xaxis: Object.assign({}, base.xaxis, {
      gridcolor: "rgba(255,255,255,0.07)",
      zerolinecolor: "rgba(255,255,255,0.1)",
      linecolor: "rgba(255,255,255,0.12)",
      tickfont: Object.assign({}, (base.xaxis && base.xaxis.tickfont) || {}, { color: "#6F6C80" }),
    }),
    yaxis: Object.assign({}, base.yaxis, {
      gridcolor: "rgba(255,255,255,0.07)",
      zerolinecolor: "rgba(255,255,255,0.1)",
      linecolor: "rgba(255,255,255,0.12)",
      tickfont: Object.assign({}, (base.yaxis && base.yaxis.tickfont) || {}, { color: "#6F6C80" }),
    }),
  });
}

function plotChart(card, artifact) {
  const plot = $(".chart-plot", card);
  if (!plot) return;
  try {
    Plotly.newPlot(plot, artifact.figure.data || [], brandChartLayout(artifact.figure.layout), {
      responsive: true,
      displayModeBar: false,
    });
  } catch (err) {
    plot.textContent = "Could not render chart.";
  }
}

function diagramCard(artifact) {
  const card = makeEl("div", "card diagram-card");
  const head = makeEl("div", "card-head");
  head.append(makeEl("span", null, artifact.title || "Diagram"));
  if (artifact.diagramType) head.append(makeEl("span", "meta", artifact.diagramType));
  const holder = makeEl("div", "diagram-holder");
  card.append(head, holder);
  renderMermaid(holder, artifact.mermaid, card);
  return card;
}

function renderMermaid(holder, code, card) {
  if (!window.mermaid) {
    holder.textContent = "Mermaid library not loaded.";
    return;
  }
  const id = "mm" + (++state.mmCounter);
  let result;
  try {
    result = mermaid.render(id, code);
  } catch (err) {
    holder.textContent = "Could not render diagram.";
    return;
  }
  const done = (svg) => {
    holder.innerHTML = svg;
    autoscroll();
  };
  if (result && typeof result.then === "function") {
    result.then(({ svg }) => done(svg)).catch(() => {
      holder.textContent = "Could not render diagram.";
    });
  } else if (result && typeof result === "string") {
    done(result);
  } else if (result && result.svg) {
    done(result.svg);
  } else {
    holder.textContent = "Could not render diagram.";
  }
}

function sqlCard(artifact) {
  const card = makeEl("div", "card sql-card open");
  const head = makeEl("div", "card-head");
  head.append(makeEl("span", "chevron", "▶"), makeEl("span", null, "Generated SQL"));
  const actions = makeEl("div", "card-actions");
  const copyBtn = button("tool-btn", "Copy", "Copy SQL", () => {
    navigator.clipboard.writeText(artifact.sql).then(() => {
      copyBtn.textContent = "Copied!";
      setTimeout(() => (copyBtn.textContent = "Copy"), 1400);
    });
  });
  const runBtn = button("tool-btn", "Run", "Run this query", () => runSqlButton(runBtn, card, artifact));
  actions.append(copyBtn, runBtn);
  head.append(actions);
  head.addEventListener("click", (e) => {
    if (e.target.closest(".card-actions")) return;
    card.classList.toggle("open");
  });
  const body = makeEl("div", "sql-body");
  const pre = makeEl("pre", null, artifact.sql);
  body.append(pre);
  if (artifact.result) body.append(renderQueryResult(artifact.result));
  card.append(head, body);
  return card;
}

function runSqlButton(btn, card, artifact) {
  btn.disabled = true;
  btn.textContent = "Running…";
  api("/api/query", {
    method: "POST",
    body: JSON.stringify({ sql: artifact.sql, database: state.database }),
  })
    .then((result) => {
      artifact.result = result;
      const existing = $(".query-result", card);
      if (existing) existing.remove();
      $(".sql-body", card).append(renderQueryResult(result));
      card.classList.add("open");
      autoscroll();
    })
    .catch((err) => {
      const note = makeEl("div", "query-err", "Query failed: " + err.message);
      const body = $(".sql-body", card);
      const existing = $(".query-result", card);
      if (existing) existing.remove();
      body.append(note);
      autoscroll();
    })
    .finally(() => {
      btn.disabled = false;
      btn.textContent = "Run";
    });
}

function renderQueryResult(result) {
  const box = makeEl("div", "query-result");
  if (!result || !result.success) {
    box.append(makeEl("div", "query-err", (result && result.error) || "Query failed."));
    return box;
  }
  const note = makeEl("div", "row-note", result.row_count + " row(s) returned");
  box.append(note, buildTable(result.columns || [], result.rows || [], result.row_count || 0));
  return box;
}

function buildTable(columns, rows, rowCount) {
  const wrap = makeEl("div", "table-wrap");
  const table = makeEl("table", "data-table");
  const thead = makeEl("thead");
  const trHead = makeEl("tr");
  columns.forEach((col) => trHead.append(makeEl("th", null, col)));
  thead.append(trHead);
  const tbody = makeEl("tbody");
  rows.forEach((row) => {
    const tr = makeEl("tr");
    columns.forEach((col) => {
      const val = row[col];
      const td = makeEl("td", null, cellValue(val));
      if (isNumeric(val)) td.dataset.num = "true";
      tr.append(td);
    });
    tbody.append(tr);
  });
  table.append(thead, tbody);
  wrap.append(table);
  if (rowCount > 5 && rows.length > 5) {
    const hidden = rows.slice(5);
    const more = button("show-more-btn", "Show all " + rowCount + " rows", "Expand table", () => {
      hidden.forEach((row) => {
        const tr = makeEl("tr");
        columns.forEach((col) => {
          const val = row[col];
          const td = makeEl("td", null, cellValue(val));
          if (isNumeric(val)) td.dataset.num = "true";
          tr.append(td);
        });
        tbody.append(tr);
      });
      more.remove();
      autoscroll();
    });
    wrap.append(more);
  }
  return wrap;
}

function tableCard(artifact) {
  const card = makeEl("div", "card table-card");
  const head = makeEl("div", "card-head");
  head.append(
    makeEl("span", null, "Query result"),
    makeEl("span", "meta", artifact.rowCount + " row(s)")
  );
  card.append(head);
  card.append(buildTable(artifact.columns || [], artifact.rows || [], artifact.rowCount || 0));
  return card;
}

/* ------------------------------------------------------------------ */
/* SSE chat streaming                                                  */
/* ------------------------------------------------------------------ */

function historyPayload() {
  return state.messages
    .filter((m) => m && m.content && String(m.content).trim())
    .map((m) => ({ role: m.role === "assistant" ? "assistant" : "user", content: m.content }));
}

function sendMessage(text) {
  text = (text || "").trim();
  if (!text || state.streaming) return;

  hideWelcome();
  hideError();
  state.streaming = true;
  state.lastQuestion = text;
  state.lastSql = "";

  state.messages.push({ role: "user", content: text });
  renderMessage(state.messages[state.messages.length - 1]);

  const assistant = { role: "assistant", content: "", artifacts: [] };
  state.messages.push(assistant);
  renderMessage(assistant);
  const aIndex = state.messages.indexOf(assistant);
  const aEl = getMsgEl(aIndex);

  const cursor = makeEl("span", "cursor");
  aEl.contentEl.append(cursor);

  setStreamingUI(true);
  els.input.value = "";
  autosizeInput();
  state.stick = true;
  autoscroll();

  const chipMap = new Map();
  let failed = false;

  setStatus("ok", "Agent is working…");
  const thinkStart = Date.now();
  const STAGES = { get_schema: "Reading schema…", execute_query: "Running SQL…", generate_chart: "Drawing chart…", generate_flowchart: "Drawing diagram…", explain_data: "Crunching stats…" };
  const thinkTimer = setInterval(() => {
    const secs = Math.round((Date.now() - thinkStart) / 1000);
    setStatus("ok", (state.stage || "Agent is working…") + " (" + secs + "s)");
  }, 2000);

  const handleEvent = (ev) => {
    if (ev.type === "delta") {
      state.stage = "Writing answer…";
      assistant.content += ev.text || "";
      aEl.contentEl.innerHTML = md(assistant.content) + (state.streaming ? '<span class="cursor"></span>' : "");
      autoscroll();
    } else if (ev.type === "sql") {
      state.lastSql = ev.sql || "";
      const artifact = { kind: "sql", sql: state.lastSql };
      assistant.artifacts.push(artifact);
      aEl.artifactsEl.append(sqlCard(artifact));
      autoscroll();
    } else if (ev.type === "tool") {
      state.stage = STAGES[ev.name] || ("Running " + toolLabel(ev.name || "") + "…");
      setStatus("ok", state.stage);
      const name = toolLabel(ev.name || "");
      const chip = makeEl("div", "chip");
      chip.append(makeEl("span", "spinner"), document.createTextNode("Running " + name + "…"));
      chipMap.set(ev.name, chip);
      aEl.chipsEl.append(chip);
      autoscroll();
    } else if (ev.type === "tool_result") {
      const name = ev.name || "";
      const chip = chipMap.get(name);
      if (chip) {
        chip.classList.add(ev.status === "done" ? (ev.summary && ev.summary.indexOf("failed") >= 0 ? "failed" : "done") : "waiting");
        if (ev.summary) chip.textContent = ev.summary;
      } else {
        const c = makeEl("div", "chip");
        c.append(makeEl("span", "spinner"), document.createTextNode(ev.summary || name));
        if (ev.status === "done") c.classList.add("done");
        else if (ev.summary && ev.summary.indexOf("failed") >= 0) c.classList.add("failed");
        else c.classList.add("waiting");
        aEl.chipsEl.append(c);
        autoscroll();
      }
      if (ev.chart) {
        const artifact = {
          kind: "chart",
          figure: JSON.parse(JSON.stringify(ev.chart)),
          title: ev.title || "Chart",
        };
        assistant.artifacts.push(artifact);
        const chartCardEl = chartCard(artifact);
        aEl.artifactsEl.append(chartCardEl);
        plotChart(chartCardEl, artifact);
        autoscroll();
      }
      if (ev.diagram) {
        const artifact = {
          kind: "diagram",
          mermaid: ev.diagram,
          title: ev.title || "Diagram",
          diagramType: ev.diagram_type || "",
        };
        assistant.artifacts.push(artifact);
        aEl.artifactsEl.append(diagramCard(artifact));
        autoscroll();
      }
      if (ev.columns && ev.rows) {
        const sqlArtifact = [...assistant.artifacts].reverse().find((a) => a.kind === "sql" && !a.result);
        if (sqlArtifact) {
          sqlArtifact.result = {
            success: true,
            columns: ev.columns,
            rows: ev.rows,
            row_count: ev.row_count || ev.rows.length,
          };
          const bodies = $$(".sql-card", aEl.artifactsEl);
          bodies.forEach((b) => {
            if (!$(".query-result", b)) {
              const art = assistant.artifacts.find((a) => a.kind === "sql");
              if (art && art.result) {
                $(".sql-body", b).append(renderQueryResult(art.result));
                b.classList.add("open");
              }
            }
          });
        } else {
          const artifact = {
            kind: "table",
            columns: ev.columns,
            rows: ev.rows,
            rowCount: ev.row_count || ev.rows.length,
          };
          assistant.artifacts.push(artifact);
          aEl.artifactsEl.append(tableCard(artifact));
        }
        autoscroll();
      }
    } else if (ev.type === "done") {
      if (ev.text) assistant.content = ev.text;
      aEl.contentEl.innerHTML = md(assistant.content);
      cursor.remove();
      setStatus("ok", "Done");
    } else if (ev.type === "error") {
      failed = true;
      setStatus("err", ev.message || "Unknown error.");
      showError(ev.message || "Unknown error.");
      aEl.contentEl.innerHTML = '<div class="err-inline">' + esc(ev.message || "Something went wrong.") + "</div>";
      cursor.remove();
    }
  };

  const payload = {
    messages: historyPayload(),
    database: state.database,
  };

  fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then((res) => {
      if (!res.ok) throw new Error("Chat request failed (" + res.status + ")");
      return res.json();
    })
    .then((data) => {
      if (!data || !Array.isArray(data.events)) {
        let raw = "";
        try { raw = JSON.stringify(data); } catch (err) { raw = String(data); }
        throw new Error("Unexpected response from agent: " + String(raw).slice(0, 250));
      }
      data.events.forEach((ev) => {
        try {
          handleEvent(ev);
        } catch (evErr) {
          setStatus("warn", "Event error: " + (evErr.message || "unknown"));
        }
      });
    })
    .catch((err) => {
      failed = true;
      setStatus("err", "Chat failed: " + err.message);
      showError(err.message || "Could not reach the agent.");
    })
    .finally(() => {
      state.streaming = false;
      clearInterval(thinkTimer);
      cursor.remove();
      if (!failed) {
        setStatus("ok", "Done");
        hideError();
      }
      try {
        aEl.contentEl.innerHTML = md(assistant.content);
      } catch (renderErr) {
        setStatus("err", "Render error: " + renderErr.message);
      }
      setStreamingUI(false);
      saveHistoryEntry();
      saveCurrentSession();
      autoscroll();
    });
}

function saveHistoryEntry() {
  if (!state.lastQuestion) return;
  api("/api/history", {
    method: "POST",
    body: JSON.stringify({
      question: state.lastQuestion,
      sql: state.lastSql || "",
      database: state.database,
    }),
  }).then(loadHistory).catch(() => {});
}

/* ------------------------------------------------------------------ */
/* error banner                                                        */
/* ------------------------------------------------------------------ */

let errorTimer = null;

function showError(message) {
  const msg = String(message == null ? "" : message).trim();
  if (!msg) {
    hideError();
    return;
  }
  els.errorText.textContent = msg;
  els.errorBanner.hidden = false;
  if (els.errorRetry) els.errorRetry.hidden = !state.lastQuestion || state.streaming;
  clearTimeout(errorTimer);
  errorTimer = setTimeout(hideError, 12000);
}

function hideError() {
  clearTimeout(errorTimer);
  errorTimer = null;
  if (els.errorText) els.errorText.textContent = "";
  if (els.errorBanner) els.errorBanner.hidden = true;
}

function setStatus(kind, msg) {
  els.statusBar.classList.remove("ok", "warn", "err");
  els.statusBar.classList.add(kind);
  els.statusText.textContent = msg;
}

function fillWelcomeNote() {
  if (!els.welcomeNote) return;
  els.welcomeNote.textContent = "Try: \"Top 3 products by revenue\", \"Show a chart\", or \"Explain the data\".";
  els.welcomeNote.hidden = false;
}

function checkServer() {
  api("/api/databases")
    .then((dbs) => {
      if (dbs.length && els.dbSelect.options.length === 0) {
        dbs.forEach((db) => {
          const opt = makeEl("option", null, db.name + " — " + db.description);
          opt.value = db.name;
          els.dbSelect.append(opt);
        });
        state.database = dbs[0].name;
        els.dbSelect.value = state.database;
        els.topbarDb.textContent = state.database;
      }
      setStatus("ok", "Connected · " + (dbs.length ? dbs[0].name : "no databases"));
    })
    .catch(() => {
      setStatus("err", "Agent offline — cannot reach /api/databases");
    });
}

function pingServer() {
  api("/api/databases")
    .then((dbs) => {
      setStatus("ok", "Connected · " + (dbs.length ? dbs[0].name : "no databases"));
    })
    .catch(() => {
      setStatus("err", "Agent offline — cannot reach /api/databases");
    });
}

window.addEventListener("error", (e) => {
  setStatus("err", "Page error: " + (e.message || "unknown"));
});

window.addEventListener("unhandledrejection", (e) => {
  const err = (e && e.reason && e.reason.message) || "unhandled promise rejection";
  setStatus("err", "JS error: " + err);
});

/* ------------------------------------------------------------------ */
/* input & streaming UI                                                */
/* ------------------------------------------------------------------ */

function setStreamingUI(streaming) {
  els.sendBtn.disabled = streaming;
  els.newChat.disabled = streaming;
  els.input.readOnly = streaming;
  els.input.placeholder = streaming ? "Agent is working…" : "Ask anything about the database...";
  if (!streaming) focusInput();
}

function focusInput() {
  if (!state.streaming) els.input.focus();
}

function autosizeInput() {
  els.input.style.height = "auto";
  els.input.style.height = Math.min(els.input.scrollHeight, 150) + "px";
}

function sendFromInput() {
  sendMessage(els.input.value);
}

/* ------------------------------------------------------------------ */
/* table modal                                                         */
/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */
/* database explorer modal                                             */
/* ------------------------------------------------------------------ */

function closeDbModal() {
  const modal = document.getElementById("db-modal");
  if (modal) modal.hidden = true;
}

function loadTableData(tableName, bodyEl) {
  bodyEl.innerHTML = '<div class="db-modal-spinner">Loading stored records for ' + esc(tableName) + '…</div>';
  const sql = 'SELECT * FROM "' + tableName + '" LIMIT 250;';
  api("/api/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql: sql, database: state.database }),
  })
    .then((result) => {
      bodyEl.innerHTML = "";
      const rows = (result && (result.data || result.rows)) || [];
      if (!result || !result.success || rows.length === 0) {
        bodyEl.innerHTML = '<div class="db-modal-spinner">No records stored in table "' + esc(tableName) + '".</div>';
        return;
      }
      const info = makeEl("div", "db-table-info");
      const titleSpan = makeEl("span", null);
      titleSpan.innerHTML = "Table: <b>" + esc(tableName) + "</b>";
      const countSpan = makeEl("span", null, (result.row_count || rows.length) + " row(s)" + (result.truncated ? " (showing first 250)" : ""));
      info.append(titleSpan, countSpan);

      const tableWrap = buildTable(result.columns || [], rows, result.row_count || rows.length);
      bodyEl.append(info, tableWrap);
    })
    .catch((err) => {
      bodyEl.innerHTML = '<div class="db-modal-spinner">Failed to load table data: ' + esc(err.message || err) + '</div>';
    });
}

function openDatabaseExplorer() {
  const modal = document.getElementById("db-modal");
  const tabsEl = document.getElementById("db-modal-tabs");
  const bodyEl = document.getElementById("table-modal-body");
  const titleEl = document.getElementById("db-modal-title");

  if (!modal || !tabsEl || !bodyEl) return;

  if (titleEl) {
    titleEl.textContent = (state.database || "Grocery").toUpperCase() + " DATABASE";
  }

  tabsEl.innerHTML = "";
  bodyEl.innerHTML = '<div class="db-modal-spinner">Discovering stored tables…</div>';
  modal.hidden = false;
  modal.style.display = "flex";

  api("/api/schema?database=" + encodeURIComponent(state.database))
    .then((schema) => {
      tabsEl.innerHTML = "";
      const tables = Object.keys(schema).sort();
      if (!tables.length) {
        bodyEl.innerHTML = '<div class="db-modal-spinner">No tables found in this database.</div>';
        return;
      }

      tables.forEach((tableName, idx) => {
        const info = schema[tableName];
        const btn = makeEl("button", "db-tab-btn" + (idx === 0 ? " active" : ""));
        const nameSpan = makeEl("span", null, tableName);
        const countSpan = makeEl("span", "db-tab-count", info.row_count + "");
        btn.append(nameSpan, countSpan);

        btn.addEventListener("click", () => {
          $$(".db-tab-btn", tabsEl).forEach((b) => b.classList.remove("active"));
          btn.classList.add("active");
          loadTableData(tableName, bodyEl);
        });

        tabsEl.append(btn);
      });

      // Load first table data by default
      loadTableData(tables[0], bodyEl);
    })
    .catch((err) => {
      bodyEl.innerHTML = '<div class="db-modal-spinner">Failed to load schema: ' + esc(err.message || err) + '</div>';
    });
}

function closeDbModal() {
  const modal = document.getElementById("db-modal");
  if (modal) {
    modal.hidden = true;
    modal.style.display = "none";
  }
}

const showTablesBtn = document.getElementById("show-tables-btn");
if (showTablesBtn) {
  showTablesBtn.addEventListener("click", openDatabaseExplorer);
}

document.addEventListener("click", (e) => {
  if (e.target.closest("#table-modal-close") || e.target.id === "db-modal-backdrop") {
    closeDbModal();
  }
});

window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeDbModal();
  }
});

/* ------------------------------------------------------------------ */
/* init & events                                                       */
/* ------------------------------------------------------------------ */

function init() {
  checkServer();
  setInterval(pingServer, 30000);

  loadHistory();
  renderSessions();
  renderPinned();
  showWelcome();
  fillWelcomeNote();
  focusInput();

  els.dbSelect.addEventListener("change", () => {
    state.database = els.dbSelect.value;
    els.topbarDb.textContent = state.database;
    if (state.schemaOpen) loadSchema();
  });

  els.newChat.addEventListener("click", newChat);
  els.sendBtn.addEventListener("click", sendFromInput);

  els.input.addEventListener("input", autosizeInput);
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!state.streaming) sendFromInput();
    }
  });

  els.messages.addEventListener("scroll", () => {
    const el = els.messages;
    state.stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 40;
    if (els.scrollBottom) els.scrollBottom.hidden = state.stick;
  });

  els.schemaToggle.addEventListener("click", () => toggleSchema());

  els.errorClose.addEventListener("click", hideError);

  if (els.errorRetry) {
    els.errorRetry.addEventListener("click", () => {
      hideError();
      if (!state.streaming && state.lastQuestion) {
        sendMessage(state.lastQuestion);
      }
    });
  }

  if (els.scrollBottom) {
    els.scrollBottom.addEventListener("click", () => {
      state.stick = true;
      els.scrollBottom.hidden = true;
      autoscroll();
    });
  }

  $$(".chip", els.welcome).forEach((chip) => {
    chip.addEventListener("click", () => sendMessage(chip.dataset.prompt));
  });

  els.sidebarToggle.addEventListener("click", () => {
    els.sidebar.classList.add("open");
    els.sidebarFade.hidden = false;
  });
  els.sidebarFade.addEventListener("click", () => {
    els.sidebar.classList.remove("open");
    els.sidebarFade.hidden = true;
  });
  window.addEventListener("resize", () => {
    if (window.innerWidth > 880) {
      els.sidebar.classList.remove("open");
      els.sidebarFade.hidden = true;
    }
  });
  window.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      newChat();
    }
  });
}

init();
})();