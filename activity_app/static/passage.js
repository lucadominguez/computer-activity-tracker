"use strict";
let pollTimer = null;
function updateStatus(result) {
  P.status = result;
  $("#moment-count").textContent = Number(result.count || 0).toLocaleString();
  $("#media-size").textContent = bytes(result.bytes || 0);
  const capture = result.capture,
    main = result.recorder;
  const paused = main.state === "paused",
    enabled = capture.settings.enabled;
  let title = "Remembering",
    caption = "Only changed windows are saved",
    icon = "Ⅱ",
    active = true;
  if (!enabled) {
    title = "Remembering is off";
    caption = "Screenshots and OCR are off";
    icon = "▷";
    active = false;
  } else if (paused) {
    title = "Remembering paused";
    caption = "Nothing new is being saved";
    icon = "▷";
    active = false;
  } else if (main.state === "error" || capture.state === "error") {
    title = "Capture needs attention";
    caption = "Open Settings to check recording";
    icon = "!";
    active = false;
  } else if (capture.state === "private") {
    title = "Private window";
    caption = "This window is not being saved";
    icon = "◇";
    active = false;
  }
  $("#remember-title").textContent = title;
  $("#remember-caption").textContent = caption;
  $("#remember-icon").textContent = icon;
  $("#remember-toggle").dataset.active = String(active);
  $("#remember-toggle").setAttribute(
    "aria-label",
    enabled
      ? paused
        ? "Resume recording"
        : "Pause recording"
      : "Enable screenshot capture",
  );
}
async function refreshStatus() {
  updateStatus(await api("/api/memory/status"));
}
async function navigate(view) {
  if (!["recall", "timeline", "sessions", "access"].includes(view))
    view = "recall";
  P.view = view;
  P.generation++;
  P.detailGeneration++;
  document.querySelectorAll("nav a").forEach((a) => {
    if (a.dataset.view === view) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  for (const name of ["recall", "timeline", "sessions", "access"])
    $("#" + name + "-view").hidden = name !== view;
  document
    .querySelectorAll(".show-detail")
    .forEach((n) => n.classList.remove("show-detail"));
  history.replaceState(null, "", "/?view=" + view);
  clearError();
  await refresh();
}
async function refresh() {
  if (P.view === "recall") await recall();
  else if (P.view === "sessions") await sessionView();
  else if (P.view === "timeline") await timelineView();
  else await accessView();
}
async function settings() {
  await refreshStatus();
  const c = P.status.capture.settings;
  $("#capture-enabled").checked = c.enabled;
  $("#capture-interval").value = c.interval;
  $("#keep-days").value = c.days;
  $("#max-gb").value = c.max_gb;
  $("#excluded-apps").value = c.exclude_apps.join("\n");
  $("#excluded-titles").value = c.exclude_titles.join("\n");
  $("#settings-dialog").showModal();
}
function notice(text) {
  $("#toast").textContent = text;
  $("#toast").hidden = false;
  setTimeout(() => ($("#toast").hidden = true), 4500);
}
async function init() {
  const fragment = location.hash.slice(1);
  if (/^[A-Za-z0-9_-]{43}$/.test(fragment)) {
    history.replaceState(null, "", location.pathname + location.search);
    await api("/api/session", { token: fragment });
  }
  $("#timeline-day").value = localDay();
  document.querySelectorAll("nav a").forEach((a) =>
    a.addEventListener("click", (event) => {
      event.preventDefault();
      run(() => navigate(a.dataset.view));
    }),
  );
  document
    .querySelectorAll("[data-close]")
    .forEach((b) =>
      b.addEventListener("click", () => $("#" + b.dataset.close).close()),
    );
  $("#refresh").onclick = () =>
    run(async () => {
      await refreshStatus();
      await refresh();
    });
  $("#focus-search").onclick = () =>
    run(async () => {
      if (P.view !== "recall") await navigate("recall");
      $("#search").focus();
    });
  let searchTimer;
  for (const target of ["#search", "#period", "#app-filter"])
    $(target).addEventListener(
      target === "#search" ? "input" : "change",
      () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => run(() => recall()), 160);
      },
    );
  $("#load-more").onclick = () => run(() => recall(true));
  $("#session-filter").oninput = renderSessions;
  $("#timeline-day").onchange = () => run(timelineView);
  $("#timeline-position").oninput = showTimeline;
  for (const [id, delta] of [
    ["#previous-day", -1],
    ["#next-day", 1],
  ])
    $(id).onclick = () =>
      run(async () => {
        const day = new Date($("#timeline-day").value + "T12:00:00");
        day.setDate(day.getDate() + delta);
        $("#timeline-day").value = localDay(day);
        await timelineView();
      });
  $("#activity-track").onclick = (e) => {
    if (!P.timeline.length) return;
    const rect = e.currentTarget.getBoundingClientRect();
    $("#timeline-position").value = String(
      Math.min(
        P.timeline.length - 1,
        Math.max(
          0,
          Math.round(
            ((e.clientX - rect.left) / rect.width) * (P.timeline.length - 1),
          ),
        ),
      ),
    );
    showTimeline();
  };
  addEventListener("resize", () => {
    if (P.view === "timeline") drawTrack();
  });
  $("#settings-open").onclick = () => run(settings);
  $("#remember-toggle").onclick = () =>
    run(async () => {
      await refreshStatus();
      if (!P.status.capture.settings.enabled) {
        await settings();
        return;
      }
      await api("/api/control", {
        action: P.status.recorder.state === "paused" ? "resume" : "pause",
      });
      await refreshStatus();
    });
  $("#settings-form").addEventListener("submit", (e) => {
    e.preventDefault();
    run(async () => {
      const list = (id) =>
        $(id)
          .value.split("\n")
          .map((v) => v.trim())
          .filter(Boolean);
      await api("/api/memory/settings", {
        enabled: $("#capture-enabled").checked,
        interval: Number($("#capture-interval").value),
        days: Number($("#keep-days").value),
        max_gb: Number($("#max-gb").value),
        exclude_apps: list("#excluded-apps"),
        exclude_titles: list("#excluded-titles"),
      });
      $("#settings-dialog").close();
      await refreshStatus();
      notice("Capture settings saved locally.");
    });
  });
  $("#copy-handoff").onclick = () =>
    run(async () => {
      try {
        await navigator.clipboard.writeText($("#handoff-text").value);
        $("#copy-status").textContent = "Copied to clipboard";
      } catch {
        const area = $("#handoff-text");
        area.focus();
        area.select();
        $("#copy-status").textContent = "Press Ctrl+C to copy selected text.";
      }
    });
  $("#quit").onclick = () => {
    $("#settings-dialog").close();
    confirmAction(
      "Quit Passage?",
      "This stops screenshot capture and activity recording. Closing the browser alone does not stop them.",
      async () => {
        await api("/api/control", { action: "quit" });
        clearInterval(pollTimer);
        $("#remember-title").textContent = "Stopped";
        $("#remember-caption").textContent = "Reopen your desktop shortcut";
        $("#remember-toggle").disabled = true;
        notice("Recorder stopped. You can close this window.");
      },
    );
  };
  document.addEventListener("keydown", (e) => {
    if (
      (e.ctrlKey || e.metaKey) &&
      e.key.toLowerCase() === "f" &&
      !document.querySelector("dialog[open]")
    ) {
      e.preventDefault();
      $("#focus-search").click();
    }
  });
  await navigate(new URLSearchParams(location.search).get("view") || "recall");
  pollTimer = setInterval(() => {
    if (!document.hidden) run(refreshStatus);
  }, 4000);
}
run(init);
