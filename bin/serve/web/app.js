"use strict";

// conductor's web page: Runs, a goal, and Settings, over the service's REST API.

const POLL = 3000;
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem("cond." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("cond." + k, JSON.stringify(v)); } catch (e) { /* private window */ } },
};

let timer = null;
let view = null;

async function api(method, path, body) {
  const res = await fetch(path, {
    method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
  setConn(true);
  if (!res.ok) throw new Error((data && data.error) || res.statusText);
  return data;
}

function setConn(ok) {
  const el = $("#conn");
  el.textContent = ok ? "" : "the service does not answer";
  el.classList.toggle("bad", !ok);
}

function toast(text, bad) {
  const el = $("#toast");
  el.textContent = text;
  el.className = "toast" + (bad ? " bad" : "");
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { el.hidden = true; }, bad ? 6000 : 2500);
}

async function act(fn, done) {
  try { const r = await fn(); if (done) toast(done); return r; } catch (e) { toast(e.message, true); }
}

function md(text) {
  if (!text) return "";
  if (window.marked && window.DOMPurify) {
    return DOMPurify.sanitize(marked.parse(text));
  }
  return "<pre>" + esc(text) + "</pre>";
}

// --- formatting -------------------------------------------------------------

function ago(t) {
  if (!t) return "";
  const s = Date.now() / 1000 - t;
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + " min ago";
  if (s < 86400) return Math.floor(s / 3600) + " h ago";
  return Math.floor(s / 86400) + " d ago";
}

function span(s) {
  if (s == null || s < 0) return "";
  if (s < 60) return Math.round(s) + "s";
  if (s < 3600) return Math.round(s / 60) + "m";
  return Math.floor(s / 3600) + "h " + Math.round((s % 3600) / 60) + "m";
}

const money = (c) => (c ? "$" + c.toFixed(2) : "");
const clock = (t) => new Date(t * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
const shortModel = (m) => (m || "").replace(/^claude-/, "").replace(/-\d{8}$/, "");

function mini(p, label) {
  if (!p || !p.total) return "";
  const pct = Math.round((100 * p.done) / p.total);
  return `<span class="mini" title="${esc(label)}: ${p.done} of ${p.total}">${esc(label)}
    <span class="track"><span class="fill" style="width:${pct}%"></span></span>${p.done}/${p.total}</span>`;
}

const state = (g) => g.state || { text: g.status || "", tone: "", label: g.status || "" };

// --- router -----------------------------------------------------------------

function route() {
  clearTimeout(timer);
  const hash = location.hash.replace(/^#/, "") || "/";
  const parts = hash.split("/").filter(Boolean).map(decodeURIComponent);
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on",
    a.dataset.nav === (parts[0] === "settings" ? "settings" : "runs")));
  if (parts[0] === "settings") return settingsPage();
  if (parts[0] === "g" && parts[1] && parts[2]) return goalPage(parts[1], parts[2]);
  return runsPage();
}

function poll(fn) {
  clearTimeout(timer);
  const mine = view;
  const tick = async () => {
    if (view !== mine) return;
    try { await fn(); } catch (e) { setConn(false); }
    if (view === mine) timer = setTimeout(tick, document.hidden ? POLL * 5 : POLL);
  };
  tick();
}

// --- runs -------------------------------------------------------------------

async function runsPage() {
  view = {};
  $("#main").innerHTML = `
    <div class="panel composer" id="composer">
      <textarea id="prompt" placeholder="What should be built? Text, Asana links, or both. Paste or drop images and files. ⌘⏎ starts it."></textarea>
      <div class="chips" id="chips"></div>
      <div class="bar">
        <button id="attach" title="Attach files">+ Files</button>
        <input type="file" id="file" multiple hidden>
        <label>repo <select id="repo"></select></label>
        <label>into <input id="into" placeholder="main"></label>
        <span class="grow"></span>
        <button class="primary" id="start">Start goal</button>
      </div>
    </div>
    <h2>Goals</h2>
    <div id="list"></div>`;
  const files = [];
  const chips = () => {
    $("#chips").innerHTML = files.map((f, i) => `<span class="chip">${f.preview ? `<img src="${f.preview}">` : ""}
      ${esc(f.name)}<button data-i="${i}" title="Remove">×</button></span>`).join("");
  };
  $("#chips").onclick = (e) => { if (e.target.dataset.i) { files.splice(+e.target.dataset.i, 1); chips(); } };
  const add = (list) => Array.from(list || []).forEach((file, n) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = String(reader.result);
      const name = file.name && file.name !== "image.png" ? file.name : `pasted-${Date.now()}-${n}.png`;
      files.push({ name, data: url.slice(url.indexOf(",") + 1), preview: file.type.startsWith("image/") ? url : null });
      chips();
    };
    reader.readAsDataURL(file);
  });
  $("#attach").onclick = () => $("#file").click();
  $("#file").onchange = (e) => { add(e.target.files); e.target.value = ""; };
  $("#prompt").addEventListener("paste", (e) => {
    if (e.clipboardData && e.clipboardData.files.length) { e.preventDefault(); add(e.clipboardData.files); }
  });
  const box = $("#composer");
  box.addEventListener("dragover", (e) => { e.preventDefault(); box.classList.add("drag"); });
  box.addEventListener("dragleave", () => box.classList.remove("drag"));
  box.addEventListener("drop", (e) => { e.preventDefault(); box.classList.remove("drag"); add(e.dataTransfer.files); });
  $("#prompt").value = store.get("draft", "");
  $("#prompt").addEventListener("input", (e) => store.set("draft", e.target.value));

  const repos = await api("GET", "/api/repos");
  const sel = $("#repo");
  sel.innerHTML = repos.map((r) => `<option value="${esc(r.id)}">${esc(r.name)}</option>`).join("")
    || `<option value="">no repo yet</option>`;
  sel.value = store.get("repo", repos[0] && repos[0].id) || "";
  if (!sel.value && repos[0]) sel.value = repos[0].id;
  const intoHint = async () => {
    store.set("repo", sel.value);
    if (!sel.value) return;
    const s = await api("GET", `/api/repos/${encodeURIComponent(sel.value)}/settings`);
    $("#into").placeholder = s.base || "main";
  };
  sel.onchange = intoHint;
  intoHint();
  const start = async () => {
    const prompt = $("#prompt").value.trim();
    if (!prompt) return toast("Write what to build first", true);
    if (!sel.value) return toast("Register a repo in Settings first", true);
    $("#start").disabled = true;
    const r = await act(() => api("POST", `/api/repos/${encodeURIComponent(sel.value)}/goals`, {
      prompt, base: $("#into").value.trim() || null, files: files.map(({ name, data }) => ({ name, data })),
    }), "Goal started");
    $("#start").disabled = false;
    if (r) {
      store.set("draft", "");
      location.hash = `#/g/${encodeURIComponent(sel.value)}/${encodeURIComponent(r.goal)}`;
    }
  };
  $("#start").onclick = start;
  $("#prompt").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) start(); });

  const many = repos.length > 1;
  let showAll = false;
  const render = (goals) => {
    const tops = goals.filter((g) => !g.parent);
    const rank = (g) => (g.waiting ? 0 : !g.finished ? 1 : 2);
    tops.sort((a, b) => rank(a) - rank(b) || (b.created || 0) - (a.created || 0));
    const finishedCount = tops.filter((g) => g.finished).length;
    const shown = tops.filter((g) => showAll || !g.finished || tops.indexOf(g) < 8);
    if (!tops.length) {
      $("#list").innerHTML = `<div class="panel empty">No goals yet. Write a prompt above to start one.</div>`;
      return;
    }
    const row = (g, part) => {
      const st = state(g);
      return `<div class="goal-row${part ? " part" : ""}" data-repo="${esc(g.repo)}" data-id="${esc(g.id)}">
        <span class="dot ${st.tone}"></span>
        <div class="grow">
          <div class="title">${esc(part ? g.part || g.name : g.title || g.name)}
            ${many && !part ? `<span class="badge">${esc(g.repo)}</span>` : ""}</div>
          <div class="doing">${esc(st.text)}</div>
        </div>
        <div class="meta">
          ${g.agents_running ? `<span>${g.agents_running} agent${g.agents_running === 1 ? "" : "s"}</span>` : ""}
          ${mini(g.plan, "plan")}${mini(g.criteria, "criteria")}
          ${g.round ? `<span>round ${g.round}</span>` : ""}
          ${g.cost ? `<span>${money(g.cost)}</span>` : ""}
          <span class="badge ${st.tone}">${esc(st.label)}</span>
          <span class="faint">${esc(ago(g.updated || g.created))}</span>
        </div></div>`;
    };
    $("#list").innerHTML = `<div class="panel goals">${shown.map((g) => row(g) + goals
      .filter((p) => p.parent === g.id && !g.finished).map((p) => row(p, true)).join("")).join("")}
      ${finishedCount > 8 && !showAll ? `<div class="more"><a href="" id="all">Show all ${tops.length} goals</a></div>` : ""}</div>`;
    const all = $("#all");
    if (all) all.onclick = (e) => { e.preventDefault(); showAll = true; render(goals); };
    document.querySelectorAll(".goal-row").forEach((el) => {
      el.onclick = () => { location.hash = `#/g/${encodeURIComponent(el.dataset.repo)}/${encodeURIComponent(el.dataset.id)}`; };
    });
  };
  poll(async () => render(await api("GET", "/api/goals")));
}

// --- a goal -----------------------------------------------------------------

function checklist(journal, heading) {
  const lines = (journal || "").split("\n");
  const out = [];
  let inside = false;
  for (const line of lines) {
    const h = line.match(/^(#{1,6})\s+(.*?)\s*$/);
    if (h) {
      if (inside && h[1].length <= 2) break;
      if (h[1].length === 2 && h[2].toLowerCase() === heading) { inside = true; continue; }
      if (inside) out.push({ group: h[2] });
      continue;
    }
    const m = inside && line.match(/^\s*(?:[-*]|\d+\.)\s+\[([ xX])\]\s+(.*)$/);
    if (m) out.push({ done: m[1] !== " ", text: m[2] });
  }
  return out;
}

function taskTable(tasks) {
  return `<table class="tasks">${tasks.map((t) => {
    const tone = /failed|stopped|cut off|no report|conflict|kept/.test(t.result) ? "bad" : /done/.test(t.result) ? "ok" : "";
    return `<tr><td class="k">${t.kind}</td><td>${esc(t.name)}</td><td class="r"><span class="badge ${tone}">${esc(t.result)}</span></td></tr>`;
  }).join("")}</table>`;
}

function cardBody(c) {
  if (c.kind === "round") {
    const calls = c.lines.filter((l) => /^lead: /.test(l)).map((l) => l.replace(/^lead: /, ""));
    const said = c.lines.filter((l) => !/^lead: /.test(l));
    return `${said.length ? `<div class="said md">${md(said.join("\n\n"))}</div>` : ""}
      ${c.tasks ? taskTable(c.tasks) : c.tasks_lines ? `<pre>${esc(c.tasks_lines.join("\n"))}</pre>` : ""}
      ${calls.length ? `<div class="faint">lead: ${esc(calls.join(" · "))}</div>` : ""}`;
  }
  if (c.kind === "check" || c.kind === "you") {
    const items = c.lines.filter((l) => /^- |^Q: /.test(l)).map((l) => l.replace(/^- |^Q: /, ""));
    const rest = c.lines.filter((l) => !/^- |^Q: /.test(l));
    return `${items.length ? `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      ${rest.length ? `<div class="faint">${esc(rest.join(" · "))}</div>` : ""}`;
  }
  if (c.tasks) return taskTable(c.tasks);
  return c.lines.length ? `<pre>${esc(c.lines.join("\n"))}</pre>` : `<span class="faint">no detail</span>`;
}

function waitingHtml(g) {
  const a = g.awaiting;
  if (!a || !a.asked_at) return "";
  if (a.kind === "plan") {
    return `<div class="waiting"><h3>${a.split ? "The split" : "The plan"} waits on your review</h3>
      ${a.detail ? `<div class="md">${md(a.detail)}</div>` : ""}
      ${g.technical_plan ? `<p><a href="" data-tab="technical">Read the technical plan</a></p>` : ""}
      <textarea id="answer" placeholder="To change it, say what to change: the lead revises the plan and it comes back to you."></textarea>
      <div class="buttons"><button class="primary" id="approve">Approve</button>
      <button id="send">Ask for changes</button></div></div>`;
  }
  if (a.kind === "problem") {
    return `<div class="waiting"><h3>Stopped: ${esc(a.headline || "a problem")}</h3>
      ${a.detail ? `<pre>${esc(a.detail)}</pre>` : ""}
      <textarea id="answer" placeholder="Tell it what to do."></textarea>
      <div class="buttons"><button class="primary" id="send">Send</button></div></div>`;
  }
  const qs = a.questions || [];
  return `<div class="waiting"><h3>${qs.length} question${qs.length === 1 ? "" : "s"} for you</h3>
    ${qs.map((q, n) => `<div class="question"><div class="q">${n + 1}. ${esc(q.q)}</div>
      ${q.why ? `<div class="why">${esc(q.why)}</div>` : ""}
      ${(q.options || []).length ? `<div class="opts">${q.options.map((o) => `<button class="opt" data-n="${n + 1}" data-label="${esc(o.label)}">
        <b>${esc(o.label)}</b>${o.means ? ` <span class="means">→ ${esc(o.means)}</span>` : ""}
        ${(o.flow || []).length ? `<ol>${o.flow.map((f) => `<li>${esc(f)}</li>`).join("")}</ol>` : ""}</button>`).join("")}</div>` : ""}
      ${q.recommend ? `<div class="rec">Suggested: ${esc(q.recommend)}</div>` : ""}</div>`).join("")}
    <textarea id="answer" placeholder="Your answers. A click on an option adds it."></textarea>
    <div class="buttons"><button class="primary" id="send">Send the answers</button></div></div>`;
}

function liveHtml(g) {
  const agents = g.live || [];
  if (!agents.length) return "";
  return `<div class="panel live"><b>Running now</b>${agents.map((a) => `<div class="agent${a.depth ? " sub" : ""}">
    <div class="grow"><div>${esc(a.role)} <span class="faint">${esc(shortModel(a.model))} · ${span(a.seconds)}</span></div>
    ${a.action ? `<div class="action">${esc(a.action)}</div>` : ""}</div></div>`).join("")}</div>`;
}

function sideHtml(g) {
  const block = (title, items) => {
    const real = items.filter((x) => !x.group);
    if (!real.length) return "";
    const done = real.filter((x) => x.done).length;
    return `<div class="panel"><h4>${title}<span class="dim">${done}/${real.length}</span></h4>
      <div class="progress"><div class="fill" style="width:${Math.round((100 * done) / real.length)}%"></div></div>
      <ul class="checklist">${items.map((x) => x.group ? `<li class="group">${esc(x.group)}</li>`
        : `<li class="${x.done ? "done" : ""}"><span>${x.done ? "✓" : "○"}</span><span>${esc(x.text)}</span></li>`).join("")}</ul></div>`;
  };
  const parts = (g.parts || []).length ? `<div class="panel"><h4>Parts</h4>${g.parts.map((p) => {
    const st = state(p);
    return `<div class="row" style="margin:4px 0"><span class="dot ${st.tone}"></span>
      <a class="grow" href="#/g/${encodeURIComponent(g.repo)}/${encodeURIComponent(p.id)}">${esc(p.part || p.name)}</a>
      <span class="badge ${st.tone}">${esc(st.label)}</span></div>`;
  }).join("")}</div>` : "";
  return parts + block("Plan", checklist(g.journal, "plan")) + block("Acceptance criteria", checklist(g.journal, "acceptance criteria"));
}

function costsHtml(g) {
  const calls = g.calls || [];
  if (!calls.length) return `<div class="faint">No call has finished yet.</div>`;
  const by = {};
  for (const c of calls) {
    const k = c.label || "?";
    by[k] = by[k] || { label: k, n: 0, cost: 0, models: new Set() };
    by[k].n += 1;
    by[k].cost += c.cost || 0;
    if (c.model) by[k].models.add(shortModel(c.model));
  }
  const rows = Object.values(by).sort((a, b) => b.cost - a.cost);
  const total = rows.reduce((s, r) => s + r.cost, 0);
  return `<table class="costs"><tr><th>Agent</th><th>Models</th><th class="n">Calls</th><th class="n">Cost</th></tr>
    ${rows.map((r) => `<tr><td>${esc(r.label)}</td><td class="dim">${esc([...r.models].join(", "))}</td>
      <td class="n">${r.n}</td><td class="n">${money(r.cost)}</td></tr>`).join("")}
    <tr><td><b>Total</b></td><td></td><td class="n">${calls.length}</td><td class="n"><b>${money(total)}</b></td></tr></table>
    <p class="faint">At API prices: what the work would cost, not a bill.</p>
    ${g.usage_report ? `<details><summary>Every call</summary><pre>${esc(g.usage_report)}</pre></details>` : ""}`;
}

function filesHtml(g, base) {
  const files = g.files || [];
  const list = files.length ? `<div class="files">${files.map((f) => {
    const url = `${base}/files/${f.split("/").map(encodeURIComponent).join("/")}`;
    return /\.(png|jpe?g|gif|webp|svg)$/i.test(f) ? `<a class="img" href="${url}" target="_blank"><img src="${url}" alt="${esc(f)}"></a>`
      : `<a href="${url}" target="_blank">${esc(f)}</a>`;
  }).join("")}</div>` : "";
  return `${g.prompt ? `<h2>Prompt</h2><div class="md">${md(g.prompt)}</div>` : ""}
    ${list ? `<h2>Files</h2>${list}` : ""}
    ${g.ask ? `<details><summary>The ask, as the lead reads it</summary><div class="md">${md(g.ask)}</div></details>` : ""}`;
}

async function goalPage(repo, id) {
  view = { repo, id };
  const mine = view;
  const base = `/api/repos/${encodeURIComponent(repo)}/goals/${encodeURIComponent(id)}`;
  const ui = { open: new Set(), tab: store.get("tab", "timeline"), waitKey: null, sig: {}, log: { next: 0, text: "" }, follow: true };
  $("#main").innerHTML = `<a class="back" href="#/">← Runs</a>
    <div id="head"></div><div id="wait"></div><div id="live"></div>
    <div class="tabs" id="tabs">
      <button data-t="timeline">Timeline</button><button data-t="journal">Journal</button>
      <button data-t="technical">Technical plan</button><button data-t="ask">Ask</button>
      <button data-t="cost">Cost</button><button data-t="log">Log</button></div>
    <div class="columns"><div class="tab-body" id="body"></div><div class="side" id="side"></div></div>`;
  let g = null;

  const set = (sel, html, key) => {
    if (ui.sig[sel] === (key || html)) return false;
    ui.sig[sel] = key || html;
    $(sel).innerHTML = html;
    return true;
  };

  const showTab = () => {
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === ui.tab));
    store.set("tab", ui.tab);
    if (!g) return;
    if (ui.tab === "timeline") {
      const cs = g.timeline || [];
      if (!ui.opened) {
        ui.opened = true;
        cs.slice(-2).forEach((c) => ui.open.add(c.i));
        cs.filter((c) => c.kind === "alert").forEach((c) => ui.open.add(c.i));
      }
      let last = null;
      const html = cs.map((c) => {
        const head = c.phase !== last ? `<div class="phase">${esc(c.phase)}</div>` : "";
        last = c.phase;
        const open = ui.open.has(c.i);
        const dur = c.until ? span(c.until - c.at) : g.alive ? "now" : "";
        return `${head}<div class="tl"><div class="step ${c.kind}"><div class="panel card">
          <div class="head" data-i="${c.i}"><span class="t">${esc(c.title)}</span>
          <span class="s">${esc(c.summary)}</span>
          <span class="when">${[money(c.cost), dur, clock(c.at)].filter(Boolean).join(" · ")}</span></div>
          ${open ? `<div class="body">${cardBody(c)}</div>` : ""}</div></div></div>`;
      }).join("") || `<div class="faint">Nothing has happened yet.</div>`;
      set("#body", html, "t" + JSON.stringify([g.timeline, [...ui.open], g.alive]));
    } else if (ui.tab === "journal") {
      set("#body", g.journal ? `<div class="md">${md(g.journal)}</div>` : `<div class="faint">No journal yet.</div>`, "j" + g.journal);
    } else if (ui.tab === "technical") {
      set("#body", g.technical_plan ? `<div class="md">${md(g.technical_plan)}</div>` : `<div class="faint">No technical plan${g.small ? ": small work has none" : " yet"}.</div>`, "p" + g.technical_plan);
    } else if (ui.tab === "ask") {
      set("#body", filesHtml(g, base), "a" + g.ask + (g.files || []).join());
    } else if (ui.tab === "cost") {
      set("#body", costsHtml(g), "c" + JSON.stringify(g.calls));
    } else if (ui.tab === "log") {
      if (!$("#logbox")) { ui.sig["#body"] = "log"; $("#body").innerHTML = `<pre class="logbox" id="logbox"></pre>`; ui.log = { next: -200000, text: "" }; }
    }
  };

  $("#tabs").onclick = (e) => { if (e.target.dataset.t) { ui.tab = e.target.dataset.t; showTab(); } };
  $("#body").onclick = (e) => {
    const h = e.target.closest(".head");
    if (h) { const i = +h.dataset.i; ui.open.has(i) ? ui.open.delete(i) : ui.open.add(i); showTab(); }
  };
  $("#wait").onclick = async (e) => {
    if (e.target.dataset.tab) { e.preventDefault(); ui.tab = e.target.dataset.tab; showTab(); return; }
    const opt = e.target.closest(".opt");
    if (opt) {
      const box = $("#answer");
      box.value = (box.value ? box.value.replace(/\s*$/, "\n") : "") + `${opt.dataset.n}. ${opt.dataset.label}`;
      box.focus();
      return;
    }
    if (e.target.id === "approve") {
      if (await act(() => api("POST", base + "/approve"), "Approved — it builds now")) refresh();
    } else if (e.target.id === "send") {
      const text = $("#answer").value.trim();
      if (!text) return toast("Write the answer first", true);
      if (await act(() => api("POST", base + "/answer", { text }), "Sent — the goal carries on")) refresh();
    }
  };
  $("#head").onclick = async (e) => {
    const a = e.target.dataset.act;
    if (!a) return;
    const asks = {
      stop: "Stop this goal? Carry on starts it again where it stopped.",
      done: "Mark this goal done? It and its parts stop; its branch and PR stay.",
      clear: "Take this goal off the list? Its branch and PR stay.",
      undo: "Undo this goal? Its PR is closed, its branches deleted here and on GitHub, and its worktrees and state removed. This cannot be undone.",
    };
    if (asks[a] && !confirm(asks[a])) return;
    const r = await act(() => api("POST", `${base}/${a}`), { resume: "It carries on", stop: "Stopping", done: "Marked done", clear: "Cleared", undo: "Undone" }[a]);
    if (r && (a === "clear" || a === "undo")) location.hash = "#/";
    else refresh();
  };

  const refresh = async () => {
    if (view !== mine) return;
    g = await api("GET", base);
    g.repo = repo;
    const st = state(g);
    const can = {
      stop: g.alive, resume: !g.alive && !g.finished, done: !g.finished && !g.parent,
      clear: !g.alive, undo: !g.parent,
    };
    set("#head", `<div class="goal-head"><div class="grow">
        <div class="row"><span class="dot ${st.tone}"></span><h1>${esc(g.parent ? "Part: " + (g.part || g.name) : g.title || g.name)}</h1>
        <span class="badge ${st.tone}">${esc(st.label)}</span></div>
        <div class="facts"><span>${esc(st.text)}</span>
          ${g.round ? `<span>round ${g.round}</span>` : ""}
          ${g.cost ? `<span>${money(g.cost)}</span>` : ""}
          ${g.branch ? `<span><code>${esc(g.branch)}</code> → <code>${esc(g.base || "main")}</code></span>` : ""}
          ${g.pr_url ? `<a href="${esc(g.pr_url)}" target="_blank">PR #${esc((g.pr_url.match(/\d+$/) || [""])[0])}</a>` : ""}
          ${g.parent ? `<a href="#/g/${encodeURIComponent(repo)}/${encodeURIComponent(g.parent)}">its goal</a>` : ""}
          <span class="faint">started ${esc(ago(g.created))}</span></div></div>
      <div class="actions">
        ${can.stop ? `<button data-act="stop">Stop</button>` : ""}
        ${can.resume ? `<button data-act="resume">Carry on</button>` : ""}
        ${can.done ? `<button data-act="done">Mark done</button>` : ""}
        ${can.clear ? `<button data-act="clear">Clear</button>` : ""}
        ${can.undo ? `<button class="danger" data-act="undo">Undo</button>` : ""}
      </div></div>`);
    const waitKey = g.awaiting && g.awaiting.asked_at;
    if (waitKey !== ui.waitKey) { ui.waitKey = waitKey; $("#wait").innerHTML = waitingHtml(g); }
    set("#live", liveHtml(g));
    set("#side", sideHtml(g));
    showTab();
    if (ui.tab === "log" && $("#logbox")) {
      const chunk = await api("GET", `${base}/log?from=${ui.log.next}`);
      if (chunk.text) {
        const box = $("#logbox");
        const atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
        box.textContent += chunk.text;
        if (atEnd || ui.log.next < 0) box.scrollTop = box.scrollHeight;
      }
      ui.log.next = chunk.next;
    }
  };
  poll(refresh);
}

// --- settings ---------------------------------------------------------------

const GATES = {
  wait: "You, for the goal and each of its parts",
  top: "You for the goal; the reviewer agent for its parts",
  auto: "The reviewer agent only: goals never wait for you",
};
const CLAUDE_MODELS = [["claude-opus-5-5", "Opus 5.5"], ["claude-sonnet-5-5", "Sonnet 5.5"],
  ["claude-haiku-4-5-20251001", "Haiku 4.5"], ["claude-fable-5-1", "Fable 5.1"]];
const EFFORTS = ["low", "medium", "high", "xhigh", "max"];
const ROLES = [
  { key: "lead", effort: "lead_effort", name: "Lead",
    what: "Plans the goal, coordinates the build, fixes CI. Also answers a part's questions." },
  { key: "check", effort: "check_effort", name: "Reviewer and checker",
    what: "Reviews the plan before the build, then checks the branch against it." },
  { key: "subagent", effort: "subagent_effort", name: "Coding tasks and explorers",
    what: "Write the code and answer questions about it. Also the lead's own sub-agents." },
];

const isOpenCode = (m) => !!m && m.includes("/");

// How a model runs: {how, detail, tone}.
function runsOn(model, cfg) {
  if (!model) return { how: "not set", detail: "", tone: "bad" };
  if (!isOpenCode(model)) {
    const known = CLAUDE_MODELS.find(([id]) => id === model);
    return { how: "Claude Code (claude -p)", detail: "your Claude subscription" + (known ? "" : " · not a model this page knows"),
      tone: known ? "" : "warn", label: known ? known[1] : model };
  }
  const pid = model.split("/")[0];
  const p = (cfg.providers || []).find((x) => x.id === pid);
  const missing = !cfg.opencode ? " · OpenCode is not installed" : "";
  if (p && p.base_url) {
    return { how: "OpenCode", detail: `${p.name || p.id} at ${p.base_url} · key in $${p.key_env || "?"}${missing}`,
      tone: missing || !p.key_env ? "warn" : "", label: model };
  }
  return { how: "OpenCode", detail: `${pid}, one of OpenCode's own providers · its usual key variable${missing}`,
    tone: missing ? "warn" : "", label: model };
}

async function settingsPage() {
  view = {};
  const repos = await api("GET", "/api/repos");
  let current = store.get("repo", repos[0] && repos[0].id);
  if (!repos.find((r) => r.id === current)) current = repos[0] && repos[0].id;
  $("#main").innerHTML = `
    <div class="row" style="justify-content:space-between">
      <h2 style="margin:0">Settings for ${repos.length ? `<select id="which">${repos.map((r) =>
        `<option value="${esc(r.id)}">${esc(r.name)}</option>`).join("")}</select>` : "no repo yet"}</h2>
      <button class="primary" id="save" ${repos.length ? "" : "hidden"}>Save</button>
    </div>
    <div id="form"></div>
    <h2>Repositories</h2>
    <div class="panel settings">
      ${repos.map((r) => `<div class="row" style="margin-bottom:6px"><b>${esc(r.name)}</b><span class="dim">${esc(r.path)}</span></div>`).join("")
        || `<div class="faint">None yet: a repo is added when a goal starts in it, or here.</div>`}
      <div class="row" style="margin-top:12px"><input class="grow" id="newrepo" placeholder="/path/to/repo"><button id="addrepo">Add</button></div>
    </div>`;
  $("#addrepo").onclick = async () => {
    const path = $("#newrepo").value.trim();
    if (path && await act(() => api("POST", "/api/repos", { path }), "Added")) settingsPage();
  };
  if (!repos.length) return;
  let cfg = null;

  const modelSelect = (role) => {
    const value = cfg.models[role.key];
    const groups = [`<optgroup label="Claude subscription · claude -p">${CLAUDE_MODELS.map(([id, label]) =>
      `<option value="${id}"${id === value ? " selected" : ""}>${label}</option>`).join("")}</optgroup>`];
    for (const p of cfg.providers) {
      if (!p.id || !(p.models || []).length) continue;
      groups.push(`<optgroup label="${esc(p.name || p.id)} · OpenCode">${p.models.map((m) => {
        const id = `${p.id}/${m}`;
        return `<option value="${esc(id)}"${id === value ? " selected" : ""}>${esc(id)}</option>`;
      }).join("")}</optgroup>`);
    }
    const listed = CLAUDE_MODELS.some(([id]) => id === value) || cfg.providers.some((p) => (p.models || []).some((m) => `${p.id}/${m}` === value));
    groups.push(`<optgroup label="Other"><option value="__other"${listed ? "" : " selected"}>Another model, by name…</option></optgroup>`);
    return `<select data-model="${role.key}">${groups.join("")}</select>
      <input data-other="${role.key}" value="${listed ? "" : esc(value)}" placeholder="claude-… or provider/model" ${listed ? "hidden" : ""}>`;
  };

  const effortSelect = (role) => {
    const oc = isOpenCode(cfg.models[role.key]);
    const value = cfg.models[role.effort] || "";
    const options = (role.key === "check" ? [] : [["", "default"]]).concat(EFFORTS.map((e) => [e, e]));
    return `<select data-effort="${role.effort}" ${oc ? "disabled title=\"Effort applies to Claude models only\"" : ""}>
      ${options.map(([v, l]) => `<option value="${v}"${v === value ? " selected" : ""}>${oc ? "—" : l}</option>`).join("")}</select>`;
  };

  const summary = () => {
    const claudeRoles = ROLES.filter((r) => !isOpenCode(cfg.models[r.key]));
    const rows = ROLES.map((r) => {
      const on = runsOn(cfg.models[r.key], cfg);
      const effort = isOpenCode(cfg.models[r.key]) ? "" : (cfg.models[r.effort] || "default effort");
      return `<tr><td><b>${esc(r.name)}</b></td><td>${esc(on.label || cfg.models[r.key] || "—")}${effort ? ` <span class="dim">· ${esc(effort)}</span>` : ""}</td>
        <td><span class="badge ${on.tone}">${esc(on.how)}</span> <span class="dim">${esc(on.detail)}</span></td></tr>`;
    }).join("");
    return `<div class="panel settings wide"><h4 style="margin-top:0">What runs</h4>
      <table class="runs-table">${rows}</table>
      <p class="dim" style="margin:10px 0 0">${claudeRoles.length
        ? `Goals pause at ${cfg.usage_threshold}% of any Claude limit, because ${claudeRoles.length === ROLES.length
          ? "every role runs" : claudeRoles.map((r) => r.name.toLowerCase()).join(", ") + (claudeRoles.length === 1 ? " runs" : " run")} on your subscription.`
        : "No role runs on Claude: the usage limit does not apply."}
        A running goal keeps the lead and coding-task models it started with; efforts and the reviewer and checker apply at once.</p></div>`;
  };

  const providerUse = (p) => {
    const users = ROLES.filter((r) => (cfg.models[r.key] || "").split("/")[0] === p.id && isOpenCode(cfg.models[r.key]));
    return users.length ? `<span class="badge ok">used by ${esc(users.map((r) => r.name.toLowerCase()).join(", "))}</span>` : `<span class="badge">not used</span>`;
  };

  const providersHtml = () => cfg.providers.map((p, i) => {
    const builtin = !p.base_url && p._kind !== "endpoint";
    return `<div class="panel provider" data-i="${i}">
      <div class="row"><b class="grow">${esc(p.name || p.id || "New provider")}</b>${providerUse(p)}<button class="danger" data-rm="${i}">Remove</button></div>
      <div class="field"><label>Kind</label><select data-k="_kind">
        <option value="endpoint"${builtin ? "" : " selected"}>An OpenAI-compatible endpoint</option>
        <option value="builtin"${builtin ? " selected" : ""}>One of OpenCode's own providers (openai, openrouter, anthropic, google…)</option></select></div>
      <div class="field"><label>Id</label><div><input data-k="id" value="${esc(p.id || "")}" placeholder="${builtin ? "openrouter" : "acme"}">
        <div class="help">Models are named <code>${esc(p.id || "id")}/model</code>.${builtin ? " Use OpenCode's id for it." : ""}</div></div></div>
      ${builtin ? `<div class="help" style="margin:-4px 0 12px 182px">OpenCode reads its usual key variable, such as <code>OPENROUTER_API_KEY</code>, from <code>~/.zshrc</code>.</div>` : `
      <div class="field"><label>Base URL</label><input data-k="base_url" value="${esc(p.base_url || "")}" placeholder="https://llm.acme.example/v1"></div>
      <div class="field"><label>Key variable</label><div><input data-k="key_env" value="${esc(p.key_env || "")}" placeholder="ACME_API_KEY">
        <div class="help">The variable's name in <code>~/.zshrc</code>, never the key.</div></div></div>`}
      <div class="field"><label>Models</label><input data-k="models" value="${esc((p.models || []).join(", "))}" placeholder="qwen3-coder, kimi-k2"></div>
      ${builtin ? "" : `<div class="field"><label>Price, $ per M tokens</label><div class="row">
        <input data-k="input_price" type="number" min="0" step="0.01" value="${p.input_price ?? ""}" placeholder="input">
        <input data-k="output_price" type="number" min="0" step="0.01" value="${p.output_price ?? ""}" placeholder="output"></div></div>`}
    </div>`;
  }).join("");

  const draw = () => {
    $("#form").innerHTML = `
      <div id="summary">${summary()}</div>
      <h2>Models</h2>
      <div class="panel settings wide">
        <table class="roles"><tr><th></th><th>Model</th><th>Effort</th></tr>
        ${ROLES.map((r) => `<tr><td><b>${esc(r.name)}</b><div class="help">${esc(r.what)}</div></td>
          <td class="model">${modelSelect(r)}</td><td>${effortSelect(r)}</td></tr>`).join("")}</table>
      </div>
      <h2>Goals</h2>
      <div class="panel settings wide">
        <div class="field"><label>Goals go into</label><div><input data-k="base" value="${esc(cfg.base || "")}" placeholder="main">
          <div class="help">The branch a goal's PR goes into, unless the goal names another. Empty: main.</div></div></div>
        <div class="field"><label>Plan approval</label><div><select data-k="goal_gate">${Object.entries(GATES).map(([k, v]) =>
          `<option value="${k}"${k === cfg.goal_gate ? " selected" : ""}>${esc(v)}</option>`).join("")}</select>
          <div class="help">Who approves a goal's plan before it is built. Small work never waits.</div></div></div>
        <div class="field"><label>Claude usage limit</label><div><input data-k="usage_threshold" type="number" min="1" max="100" value="${cfg.usage_threshold}">
          <div class="help">Goals wind down and pause at this share (%) of any Claude limit, and go on when it resets. Only while a role runs on Claude.</div></div></div>
      </div>
      <h2>API providers, through OpenCode</h2>
      <div class="dim" style="margin-bottom:10px">${cfg.opencode ? `OpenCode is installed (<code>${esc(cfg.opencode)}</code>).`
        : `OpenCode is not installed: <code>npm i -g @opencode/cli</code>, then <code>cond serve restart</code>.`}
        Add a provider here to choose its models above.</div>
      <div id="providers">${providersHtml()}</div>
      <button id="addprov">+ Provider</button>`;
  };

  const refresh = () => {
    $("#summary").innerHTML = summary();
    document.querySelectorAll("[data-effort]").forEach((el) => {
      const role = ROLES.find((r) => r.effort === el.dataset.effort);
      el.outerHTML = effortSelect(role);
    });
    document.querySelectorAll(".provider").forEach((box) => {
      const badge = box.querySelector(".badge");
      if (badge) badge.outerHTML = providerUse(cfg.providers[+box.dataset.i]);
    });
  };

  const load = async () => {
    store.set("repo", current);
    const s = await api("GET", `/api/repos/${encodeURIComponent(current)}/settings`);
    cfg = { ...s, models: { ...s.models }, providers: (s.providers || []).map((p) => ({ ...p, _kind: p.base_url ? "endpoint" : "builtin" })) };
    draw();
  };

  $("#form").addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset.model) {
      const other = $(`[data-other="${t.dataset.model}"]`);
      other.hidden = t.value !== "__other";
      if (t.value === "__other") other.focus(); else cfg.models[t.dataset.model] = t.value;
      refresh();
    } else if (t.dataset.effort) {
      cfg.models[t.dataset.effort] = t.value || null;
      refresh();
    } else if (t.dataset.k === "_kind") {
      const p = cfg.providers[+t.closest(".provider").dataset.i];
      p._kind = t.value;
      if (t.value === "builtin") { delete p.base_url; delete p.key_env; delete p.input_price; delete p.output_price; }
      $("#providers").innerHTML = providersHtml();
    }
  });
  $("#form").addEventListener("input", (e) => {
    const t = e.target;
    if (t.dataset.other) { cfg.models[t.dataset.other] = t.value.trim(); refresh(); return; }
    const box = t.closest(".provider");
    const k = t.dataset.k;
    if (!k || k === "_kind") return;
    const v = t.value;
    if (box) {
      const p = cfg.providers[+box.dataset.i];
      p[k] = k === "models" ? v.split(",").map((m) => m.trim()).filter(Boolean)
        : k.endsWith("_price") ? (v === "" ? null : parseFloat(v)) : v.trim();
      refresh();
      return;
    }
    cfg[k] = k === "usage_threshold" ? parseInt(v, 10) : v;
    refresh();
  });
  $("#form").addEventListener("blur", (e) => {
    if (e.target.closest && e.target.closest(".provider")) {
      const models = document.querySelectorAll("td.model");
      ROLES.forEach((r, i) => { if (models[i]) models[i].innerHTML = modelSelect(r); });
    }
  }, true);
  $("#form").addEventListener("click", (e) => {
    if (e.target.dataset.rm) { cfg.providers.splice(+e.target.dataset.rm, 1); draw(); }
    if (e.target.id === "addprov") { cfg.providers.push({ _kind: "endpoint", models: [] }); draw(); }
  });
  $("#save").onclick = async () => {
    const providers = cfg.providers.map(({ _kind, ...p }) => (_kind === "builtin" ? { ...p, base_url: null, key_env: null } : p))
      .map((p) => Object.fromEntries(Object.entries(p).filter(([, v]) => v !== null && v !== "" && v !== undefined)));
    const r = await act(() => api("PUT", `/api/repos/${encodeURIComponent(current)}/settings`, {
      base: (cfg.base || "").trim() || null, usage_threshold: cfg.usage_threshold, goal_gate: cfg.goal_gate,
      models: { lead: cfg.models.lead, subagent: cfg.models.subagent, check: cfg.models.check,
        check_effort: cfg.models.check_effort, lead_effort: cfg.models.lead_effort || null,
        subagent_effort: cfg.models.subagent_effort || null },
      providers,
    }), "Saved");
    if (r) load();
  };
  $("#which").value = current;
  $("#which").onchange = (e) => { current = e.target.value; load(); };
  load();
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", route);
