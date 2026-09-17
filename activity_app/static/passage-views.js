"use strict";
const $ = (selector) => document.querySelector(selector);
const P = {
  view: "recall",
  rows: [],
  sessions: [],
  timeline: [],
  selected: null,
  generation: 0,
  detailGeneration: 0,
  status: null,
  offset: 0,
};
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
const clock = (ts) =>
  new Date(ts * 1000).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
const longDate = (ts) =>
  new Date(ts * 1000).toLocaleString([], {
    weekday: "long",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
const bytes = (value) =>
  value < 1024
    ? value + " B"
    : value < 1024 ** 2
      ? (value / 1024).toFixed(1) + " KB"
      : value < 1024 ** 3
        ? (value / 1024 ** 2).toFixed(1) + " MB"
        : (value / 1024 ** 3).toFixed(2) + " GB";
const imageURL = (id) => "/api/memory/image/" + encodeURIComponent(id);
function button(text, action, cls = "") {
  const b = el("button", cls, text);
  b.type = "button";
  b.addEventListener("click", () => run(action));
  return b;
}
async function api(path, body) {
  const options =
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Tracker-Action": "1",
          },
          body: JSON.stringify(body),
        };
  const r = await fetch(path, options);
  const result = await r.json();
  if (!r.ok) throw Error(result.error || "Local request failed.");
  return result;
}
async function run(fn) {
  try {
    await fn();
  } catch (error) {
    $("#error-banner").hidden = false;
    $("#error-banner").textContent = error.message;
  }
}
function clearError() {
  $("#error-banner").hidden = true;
}
function emptyList(target, title, description) {
  const box = el("div", "empty-list");
  box.append(el("strong", "", title), el("p", "", description));
  target.replaceChildren(box);
}
function makeCard(item, action, session = false) {
  const card = button("", action, "moment-card");
  card.dataset.id = item.id;
  card.setAttribute("aria-pressed", "false");
  const img = el("img");
  img.src = imageURL(item.id);
  img.alt = "";
  img.loading = "lazy";
  const copy = el("div", "card-copy"),
    top = el("div", "card-top");
  top.append(
    el("strong", "", item.app || "Unknown app"),
    el("time", "", clock(item.ts)),
  );
  copy.append(
    top,
    el("div", "card-title", item.title || "Untitled"),
    el(
      "div",
      "card-subtitle",
      session
        ? Math.max(1, Math.round((item.end - item.start) / 60)) +
            " min · " +
            item.moments +
            " moments"
        : item.text || "Screenshot saved · no readable text",
    ),
  );
  card.append(img, copy);
  return card;
}
async function detail(item, target, session = false, reveal = false) {
  const seq = ++P.detailGeneration;
  const full = await api("/api/memory/moment/" + encodeURIComponent(item.id));
  if (seq !== P.detailGeneration) return;
  const parent = $(target);
  parent.replaceChildren();
  parent.append(
    button(
      "‹ Back to list",
      () => parent.closest(".split-view").classList.remove("show-detail"),
      "mobile-back",
    ),
  );
  const preview = el("div", "preview-card"),
    img = el("img");
  img.src = imageURL(item.id);
  img.alt = "Saved screenshot of " + full.app;
  preview.append(img);
  const foot = el("div", "preview-footer");
  foot.append(
    el("span", "", full.app),
    el("span", "", clock(full.ts) + " · still image"),
  );
  preview.append(foot);
  parent.append(preview);
  const meta = el("div", "detail-meta");
  meta.append(
    el("span", "app-monogram", (full.app || "?").slice(0, 1).toUpperCase()),
    el("span", "app-name", full.app),
  );
  parent.append(
    meta,
    el("h1", "", full.title || "Untitled"),
    el(
      "div",
      "detail-date",
      longDate(full.ts) + (session ? " · " + item.moments + " moments" : ""),
    ),
  );
  const actions = el("div", "detail-actions");
  actions.append(
    button(
      "Hand Off Context",
      () => handoff(session ? item.ids : [full.id]),
      "primary",
    ),
  );
  if (session)
    actions.append(
      button("View Moment", async () => {
        await navigate("recall");
        await detail(full, "#moment-detail", false, true);
      }),
    );
  actions.append(
    button(
      "Delete moment",
      () =>
        confirmAction(
          "Delete this moment?",
          "The encrypted screenshot and extracted text will be removed. Your earlier activity history is not affected.",
          async () => {
            await api("/api/memory/delete", { id: full.id });
            P.selected = null;
            await refresh();
          },
        ),
      "danger",
    ),
  );
  parent.append(actions);
  if (session)
    parent.append(
      el(
        "p",
        "muted",
        "A session ends when the app changes or nothing is saved for five minutes. Handoffs include up to 20 recent moments.",
      ),
    );
  const ocr = el("section", "ocr-panel");
  ocr.append(
    el("h2", "", session ? "Latest captured text" : "Text from this screen"),
    el("span", "muted", "Read on this device · never sent to a model"),
  );
  const text = el(
    "pre",
    "",
    full.text || "No readable text was found in this screenshot.",
  );
  text.id = session ? "session-text" : "detail-text";
  ocr.append(text);
  parent.append(ocr);
  if (reveal) parent.closest(".split-view").classList.add("show-detail");
}
async function handoff(ids) {
  const value = await api("/api/memory/handoff", { ids });
  $("#handoff-text").value = value.text;
  $("#handoff-receipt").textContent =
    "Receipt " +
    value.receipt.id +
    " · " +
    value.receipt.sources +
    " sources · " +
    bytes(value.receipt.bytes) +
    " released locally";
  $("#copy-status").textContent = "";
  $("#handoff-dialog").showModal();
}
function confirmAction(title, description, action) {
  $("#confirm-title").textContent = title;
  $("#confirm-body").textContent = description;
  $("#confirm-action").onclick = () =>
    run(async () => {
      $("#confirm-dialog").close();
      await action();
    });
  $("#confirm-dialog").showModal();
}
function markSelected(list, id) {
  document
    .querySelectorAll(list + " .moment-card")
    .forEach((card) =>
      card.setAttribute("aria-pressed", String(card.dataset.id === id)),
    );
}
async function recall(append = false) {
  const seq = ++P.generation;
  const params = new URLSearchParams({
    q: $("#search").value,
    app: $("#app-filter").value,
    offset: String(append ? P.rows.length : 0),
  });
  const period = $("#period").value;
  if (period !== "all") {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    if (period === "week") start.setDate(start.getDate() - 6);
    params.set("start", String(start.getTime() / 1000));
  }
  const result = await api("/api/memory?" + params);
  if (seq !== P.generation || P.view !== "recall") return;
  P.rows = append ? P.rows.concat(result.items) : result.items;
  updateStatus(result);
  const current = $("#app-filter").value;
  $("#app-filter").replaceChildren(
    new Option("All apps", ""),
    ...result.apps.map((a) => new Option(a, a)),
  );
  $("#app-filter").value = current;
  $("#result-count").textContent =
    P.rows.length + " shown · " + result.total + " matches";
  $("#load-more").hidden = !result.has_more;
  const list = $("#moment-list");
  list.replaceChildren();
  for (const item of P.rows)
    list.append(
      makeCard(item, async () => {
        P.selected = item.id;
        markSelected("#moment-list", item.id);
        await detail(item, "#moment-detail", false, true);
      }),
    );
  if (!P.rows.length) {
    emptyList(
      list,
      result.count ? "No matching moments" : "No saved moments yet",
      result.count
        ? "Try another word, app or time period."
        : "Enable screenshot capture in Settings. Existing window-title history is still available there.",
    );
    $("#moment-detail").replaceChildren(
      el(
        "div",
        "empty-detail",
        "Saved screenshots and their readable text will appear here.",
      ),
    );
    return;
  }
  const selected = P.rows.find((r) => r.id === P.selected) || P.rows[0];
  P.selected = selected.id;
  markSelected("#moment-list", selected.id);
  await detail(selected, "#moment-detail");
}
async function sessionView() {
  const seq = ++P.generation;
  const r = await api("/api/memory/sessions");
  if (seq !== P.generation || P.view !== "sessions") return;
  P.sessions = r.items;
  $("#session-count").textContent =
    r.items.length + " sessions" + (r.has_more ? " · latest 500" : "");
  renderSessions();
}
function renderSessions() {
  const list = $("#session-list"),
    q = $("#session-filter").value.toLowerCase();
  const items = P.sessions.filter((r) =>
    (r.title + " " + r.app).toLowerCase().includes(q),
  );
  list.replaceChildren();
  for (const item of items)
    list.append(
      makeCard(
        item,
        async () => {
          markSelected("#session-list", item.id);
          await detail(item, "#session-detail", true, true);
        },
        true,
      ),
    );
  if (items.length) {
    markSelected("#session-list", items[0].id);
    run(() => detail(items[0], "#session-detail", true));
  } else {
    emptyList(
      list,
      "No sessions found",
      "Saved moments are grouped as you work.",
    );
    $("#session-detail").replaceChildren(
      el("div", "empty-detail", "Select a session to revisit your work."),
    );
  }
}
async function accessView() {
  const seq = ++P.generation;
  const r = await api("/api/memory/access");
  if (seq !== P.generation || P.view !== "access") return;
  const list = $("#access-list");
  list.replaceChildren();
  for (const item of r.items) {
    const row = el("article", "receipt"),
      head = el("div", "receipt-header");
    head.append(
      el("strong", "", "✓ " + item.client),
      el("time", "", clock(item.ts)),
    );
    row.append(
      head,
      el("h2", "", item.action),
      el(
        "p",
        "",
        item.sources +
          (item.sources === 1 ? " source · " : " sources · ") +
          bytes(item.bytes) +
          " · " +
          longDate(item.ts),
      ),
    );
    const sources = item.scope || [];
    const preview = sources.find((source) => !source.deleted);
    if (preview)
      row.append(el("p", "receipt-preview", preview.excerpt || preview.title));
    const scope = el("details", "receipt-scope");
    scope.append(
      el("summary", "", sources.length ? "Inspect sources" : "Receipt details"),
    );
    for (const source of sources) {
      const line = el("div", "receipt-source");
      line.append(
        el("strong", "", source.title),
        el("span", "muted", source.app),
      );
      if (!source.deleted)
        line.append(
          button("Open saved moment", async () => {
            await navigate("recall");
            await detail(source, "#moment-detail", false, true);
          }),
        );
      else
        line.append(
          el(
            "span",
            "muted",
            "The source was deleted. No text is retained in this receipt.",
          ),
        );
      scope.append(line);
    }
    scope.append(el("p", "receipt-id", item.id));
    row.append(scope);
    list.append(row);
  }
  if (!r.items.length)
    emptyList(
      list,
      "No context has been handed off",
      "Use Hand Off Context on a moment or session. A receipt is committed before any text is released.",
    );
}
function localDay(date = new Date()) {
  return (
    date.getFullYear() +
    "-" +
    String(date.getMonth() + 1).padStart(2, "0") +
    "-" +
    String(date.getDate()).padStart(2, "0")
  );
}
async function timelineView() {
  const seq = ++P.generation;
  const start = new Date($("#timeline-day").value + "T00:00:00");
  if (!Number.isFinite(start.getTime()))
    throw Error("Choose a valid timeline date.");
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  const r = await api(
    "/api/memory?" +
      new URLSearchParams({
        start: start.getTime() / 1000,
        end: end.getTime() / 1000,
        limit: 5000,
      }),
  );
  if (seq !== P.generation || P.view !== "timeline") return;
  P.timeline = r.items.slice().reverse();
  $("#timeline-count").textContent =
    P.timeline.length +
    " of " +
    r.total +
    " moments · " +
    new Set(r.items.map((x) => x.app)).size +
    " apps" +
    (r.has_more ? " · latest 5,000 shown" : "");
  $("#timeline-position").max = String(Math.max(0, P.timeline.length - 1));
  $("#timeline-position").value = String(Math.max(0, P.timeline.length - 1));
  $("#timeline-position").disabled = !P.timeline.length;
  drawTrack();
  showTimeline();
}
function drawTrack() {
  const canvas = $("#activity-track");
  canvas.width = Math.max(1, canvas.clientWidth * devicePixelRatio);
  canvas.height = 42 * devicePixelRatio;
  const ctx = canvas.getContext("2d");
  ctx.scale(devicePixelRatio, devicePixelRatio);
  const width = canvas.clientWidth;
  ctx.fillStyle = "#e6e8ef";
  ctx.fillRect(0, 0, width, 42);
  const colors = ["#92b9ad", "#9699cb", "#d3b782", "#819dbc", "#b993aa"];
  P.timeline.forEach((r, i) => {
    let hash = 0;
    for (const c of r.app) hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
    ctx.fillStyle = colors[hash % colors.length];
    const step = (width - 14) / Math.max(1, P.timeline.length - 1);
    ctx.fillRect(7 + i * step, 10, Math.max(2, step - 1), 22);
  });
}
function showTimeline() {
  const stage = $("#timeline-stage");
  stage.replaceChildren();
  if (!P.timeline.length) {
    stage.append(
      el(
        "div",
        "empty-detail",
        "No moments saved on this day. Try another date.",
      ),
    );
    $("#track-start").textContent = "";
    $("#track-end").textContent = "";
    $("#track-current").textContent = "";
    return;
  }
  const r = P.timeline[Number($("#timeline-position").value)] || P.timeline[0];
  $("#timeline-position").setAttribute(
    "aria-valuetext",
    clock(r.ts) + " · " + r.app,
  );
  const card = el("div", "preview-card"),
    head = el("div", "timeline-meta"),
    copy = el("div");
  copy.append(
    el("strong", "", r.title || "Untitled"),
    el("p", "", r.app + " · " + clock(r.ts)),
  );
  head.append(
    copy,
    button("Open details", async () => {
      await navigate("recall");
      await detail(r, "#moment-detail", false, true);
    }),
  );
  const img = el("img");
  img.id = "timeline-preview";
  img.src = imageURL(r.id);
  img.alt = "Saved screenshot of " + r.app;
  card.append(head, img, el("div", "preview-footer", longDate(r.ts)));
  stage.append(card);
  $("#track-start").textContent = clock(P.timeline[0].ts);
  $("#track-end").textContent = clock(P.timeline.at(-1).ts);
  $("#track-current").textContent = clock(r.ts) + " · " + r.app;
}
