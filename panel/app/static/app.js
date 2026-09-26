"use strict";

const $ = (sel) => document.querySelector(sel);
const state = { config: { rtsp_port: 8556, hls_port: 8890, webrtc_port: 8891, playback_port: 8996, record_retention: "6h", max_upload_bytes: Infinity }, videos: [], editing: null };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtBytes(n) {
  if (!n) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1);
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}

function fmtDuration(s) {
  if (s == null) return "—";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return (h ? `${h}:${String(m).padStart(2, "0")}` : `${m}`) + `:${String(sec).padStart(2, "0")}`;
}

const rtspUrl = (v) => `rtsp://${location.hostname}:${state.config.rtsp_port}/${v.stream_name}`;
const webrtcUrl = (v) => `${location.protocol}//${location.hostname}:${state.config.webrtc_port}/${v.stream_name}/`;
const hlsUrl = (v) => `${location.protocol}//${location.hostname}:${state.config.hls_port}/${v.stream_name}/`;

// The template a client substitutes a time window into. {start} is RFC 3339 UTC,
// {duration} is whole seconds — the two things MediaMTX's playback server wants.
const archiveUrl = (v) =>
  `${location.protocol}//${location.hostname}:${state.config.playback_port}` +
  `/get?path=${encodeURIComponent(v.stream_name)}&start={start}&duration={duration}`;

function fmtWindow(r) {
  if (!r || !r.segments) return "nothing recorded yet";
  const t = (s) => new Date(s).toLocaleString([], { dateStyle: "short", timeStyle: "medium" });
  const span = r.first === r.last ? t(r.first) : `${t(r.first)} → ${t(r.last)}`;
  return `${r.segments} segment${r.segments === 1 ? "" : "s"} · ${span}`;
}

let toastTimer;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 3000);
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.status === 204 ? null : res.json();
}

/* ---------- list ---------- */

function statusPill(v) {
  if (v.status === "queued") return `<span class="pill pill-muted">Queued</span>`;
  if (v.status === "processing") return `<span class="pill pill-warn">Processing</span>`;
  if (v.status === "failed") return `<span class="pill pill-err">Failed</span>`;
  if (!v.enabled) return `<span class="pill pill-muted">Disabled</span>`;
  if (v.live.ready) {
    const n = v.live.readers;
    return `<span class="pill pill-ok">Live · ${n} viewer${n === 1 ? "" : "s"}</span>`;
  }
  if (v.live.registered) return `<span class="pill pill-ok">Ready${v.mode === "on_demand" ? " (on demand)" : ""}</span>`;
  return `<span class="pill pill-warn">Registering…</span>`;
}

function card(v) {
  const ready = v.status === "ready";
  const editing = state.editing === v.id;
  const meta = [
    ["Video", v.video_codec ? `${v.video_codec.toUpperCase()} ${v.width}×${v.height}${v.fps ? ` @ ${v.fps} fps` : ""}` : "—"],
    ["Audio", v.audio_codec ? v.audio_codec.toUpperCase() : "none"],
    ["Duration", fmtDuration(v.duration)],
    ["Size", fmtBytes(v.size_bytes)],
  ];
  return `
  <article class="card" data-id="${esc(v.id)}">
    <div class="card-top">
      <div class="card-title">
        ${editing
          ? `<input type="text" class="rename-input" value="${esc(v.stream_name)}" aria-label="Stream name">
             <button class="primary" data-act="rename-save">Save</button>
             <button data-act="rename-cancel">Cancel</button>`
          : `${esc(v.stream_name)}`}
        <div class="card-sub">${esc(v.original_name)}</div>
      </div>
      ${statusPill(v)}
    </div>
    ${v.status === "failed" ? `<div class="error-msg">${esc(v.error)}</div>` : ""}
    <div class="meta">${meta.map(([k, val]) => `<span>${k}: <b>${esc(val)}</b></span>`).join("")}</div>
    <div class="url-row">
      <code class="url" title="${esc(rtspUrl(v))}">${esc(rtspUrl(v))}</code>
      <button data-act="copy">Copy</button>
    </div>
    ${v.archive ? `
    <div class="url-row archive-row">
      <code class="url" title="${esc(archiveUrl(v))}">${esc(archiveUrl(v))}</code>
      <button data-act="copy-archive">Copy</button>
    </div>
    <div class="card-sub archive-note">Archive: ${esc(fmtWindow(v.recorded))} · kept ${esc(state.config.record_retention)}</div>` : ""}
    <div class="controls">
      <label class="switch"><input type="checkbox" data-act="toggle" ${v.enabled ? "checked" : ""} ${ready ? "" : "disabled"}> Enabled</label>
      <label>Mode
        <select data-act="mode" ${ready && !v.archive ? "" : "disabled"}
                title="${v.archive ? "Archiving needs the stream always on" : "When the stream publishes"}">
          <option value="on_demand" ${v.mode === "on_demand" ? "selected" : ""}>On demand</option>
          <option value="always_on" ${v.mode === "always_on" ? "selected" : ""}>Always on</option>
        </select>
      </label>
      <label class="switch" title="Record this stream so a time range can be played back later">
        <input type="checkbox" data-act="archive" ${v.archive ? "checked" : ""} ${ready ? "" : "disabled"}> Archive
      </label>
      <span class="spacer"></span>
      <a class="btn ${ready && v.enabled ? "" : "disabled"}" href="${esc(webrtcUrl(v))}" target="_blank" rel="noopener" title="Low-latency WebRTC player">Preview</a>
      <a class="btn ${ready && v.enabled ? "" : "disabled"}" href="${esc(hlsUrl(v))}" target="_blank" rel="noopener" title="HLS player (fallback, includes AAC audio)">HLS</a>
      <button data-act="rename" ${editing ? "disabled" : ""}>Rename</button>
      <button class="danger" data-act="delete">Delete</button>
    </div>
  </article>`;
}

function render() {
  const list = $("#videos");
  $("#empty").hidden = state.videos.length > 0;
  $("#count").textContent = state.videos.length ? `${state.videos.length} total` : "";
  list.innerHTML = state.videos.map(card).join("");
  if (state.editing) list.querySelector(".rename-input")?.focus();
}

async function refresh() {
  try {
    const data = await api("GET", "/api/videos");
    state.videos = data.videos;
    const s = $("#server-status");
    s.className = `pill ${data.server_ok ? "pill-ok" : "pill-err"}`;
    s.textContent = data.server_ok ? "RTSP server online" : "RTSP server unreachable";
    // Don't clobber an in-progress rename.
    if (!document.activeElement?.classList.contains("rename-input")) render();
  } catch (e) {
    const s = $("#server-status");
    s.className = "pill pill-err";
    s.textContent = "Panel API unreachable";
  }
}

async function patch(id, body) {
  try {
    await api("PATCH", `/api/videos/${id}`, body);
  } catch (e) {
    toast(e.message);
  }
  await refresh();
}

$("#videos").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("[data-act]");
  if (!btn || btn.tagName === "SELECT" || btn.type === "checkbox") return;
  const id = btn.closest(".card").dataset.id;
  const v = state.videos.find((x) => x.id === id);
  switch (btn.dataset.act) {
    case "copy":
      try { await navigator.clipboard.writeText(rtspUrl(v)); toast("RTSP URL copied"); }
      catch { toast(rtspUrl(v)); }
      break;
    case "copy-archive":
      try { await navigator.clipboard.writeText(archiveUrl(v)); toast("Archive URL template copied"); }
      catch { toast(archiveUrl(v)); }
      break;
    case "rename":
      state.editing = id; render();
      break;
    case "rename-cancel":
      state.editing = null; render();
      break;
    case "rename-save": {
      const name = btn.closest(".card").querySelector(".rename-input").value.trim();
      state.editing = null;
      if (name && name !== v.stream_name) await patch(id, { stream_name: name });
      else render();
      break;
    }
    case "delete":
      if (confirm(`Delete "${v.stream_name}"? The stream stops and the file is removed.`)) {
        try { await api("DELETE", `/api/videos/${id}`); } catch (e) { toast(e.message); }
        await refresh();
      }
      break;
  }
});

$("#videos").addEventListener("change", (ev) => {
  const el = ev.target;
  const id = el.closest(".card")?.dataset.id;
  if (el.dataset.act === "toggle") patch(id, { enabled: el.checked });
  if (el.dataset.act === "mode") patch(id, { mode: el.value });
  if (el.dataset.act === "archive") patch(id, { archive: el.checked });
});

$("#videos").addEventListener("keydown", (ev) => {
  if (!ev.target.classList.contains("rename-input")) return;
  if (ev.key === "Enter") ev.target.closest(".card").querySelector('[data-act="rename-save"]').click();
  if (ev.key === "Escape") { state.editing = null; render(); }
});

/* ---------- uploads ---------- */

const queue = [];
let uploading = false;

function addUploads(files) {
  for (const file of files) {
    const li = document.createElement("li");
    li.innerHTML = `<div class="row"><span class="name">${esc(file.name)}</span><span class="pct">Queued</span></div><div class="bar"><span></span></div>`;
    $("#uploads").prepend(li);
    if (file.size > state.config.max_upload_bytes) {
      li.classList.add("error");
      li.querySelector(".pct").textContent = "Too large";
      continue;
    }
    queue.push({ file, li });
  }
  pump();
}

function uploadOne({ file, li }) {
  return new Promise((resolve) => {
    const pct = li.querySelector(".pct");
    const bar = li.querySelector(".bar > span");
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/videos?filename=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const p = Math.round((e.loaded / e.total) * 100);
      bar.style.width = `${p}%`;
      pct.textContent = `${p}%`;
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        bar.style.width = "100%";
        pct.textContent = "Uploaded";
        setTimeout(() => li.remove(), 4000);
      } else {
        li.classList.add("error");
        let msg = `Error ${xhr.status}`;
        try { msg = JSON.parse(xhr.responseText).detail || msg; } catch {}
        pct.textContent = msg;
      }
      resolve();
    };
    xhr.onerror = () => { li.classList.add("error"); pct.textContent = "Network error"; resolve(); };
    xhr.send(file);
  });
}

async function pump() {
  if (uploading) return;
  uploading = true;
  while (queue.length) {
    await uploadOne(queue.shift());
    refresh();
  }
  uploading = false;
}

const dz = $("#dropzone");
const input = $("#file-input");
$("#browse").addEventListener("click", () => input.click());
dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
input.addEventListener("change", () => { addUploads(input.files); input.value = ""; });
["dragenter", "dragover"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
dz.addEventListener("drop", (e) => addUploads(e.dataTransfer.files));

/* ---------- boot ---------- */

(async () => {
  try { state.config = await api("GET", "/api/config"); } catch {}
  await refresh();
  setInterval(refresh, 3000);
})();
