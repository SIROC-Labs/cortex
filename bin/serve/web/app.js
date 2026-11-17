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

// Draw the mermaid blocks under `root` as diagrams. A block mermaid cannot parse
// stays as its source, with the error under it.
let mermaidReady = false;
async function diagrams(root) {
  if (!window.mermaid || !root) return;
  if (!mermaidReady) {
    const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "neutral" });
    mermaidReady = true;
  }
  const blocks = root.querySelectorAll("pre > code.language-mermaid");
  for (const code of blocks) {
    const source = code.textContent;
    const box = document.createElement("div");
    box.className = "diagram";
    code.parentElement.replaceWith(box);
    try {
      const { svg } = await mermaid.render("m" + Math.random().toString(36).slice(2), source);
      box.innerHTML = svg;
    } catch (e) {
      box.innerHTML = `<pre>${esc(source)}</pre><div class="faint">The diagram does not draw: ${esc(e.message || e)}</div>`;
    }
  }
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
      <textarea id="prompt" placeholder="What should be built? Write it, paste links, or drop images and files. ⌘⏎ starts it."></textarea>
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
    <div class="row" id="goals-head" style="justify-content:space-between"><h2>Goals</h2>
      <button id="toggle-finished" hidden></button></div>
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
  let showFinished = store.get("finished", false);
  let last = [];
  $("#goals-head").onclick = (e) => {
    if (e.target.id !== "toggle-finished") return;
    showFinished = !showFinished;
    store.set("finished", showFinished);
    render(last);
  };
  const render = (goals) => {
    last = goals;
    const tops = goals.filter((g) => !g.parent);
    const partsOf = (g) => goals.filter((p) => p.parent === g.id);
    const rank = (g) => (g.waiting ? 0 : !g.finished ? 1 : 2);
    tops.sort((a, b) => rank(a) - rank(b) || (b.created || 0) - (a.created || 0));
    const finishedCount = tops.filter((g) => g.finished).length;
    const shown = tops.filter((g) => showFinished || !g.finished || partsOf(g).some((p) => !p.finished));
    $("#toggle-finished").textContent = `${showFinished ? "Hide" : "Show"} finished (${finishedCount})`;
    $("#toggle-finished").hidden = !finishedCount;
    if (!shown.length) {
      $("#list").innerHTML = `<div class="panel empty">${tops.length ? "No goal is running." : "No goals yet."} Write a prompt above to start one.</div>`;
      return;
    }
    const folded = store.get("folded", {});
    const isFolded = (g) => (g.id in folded ? folded[g.id] : !!g.finished && partsOf(g).every((p) => p.finished));
    const row = (g) => {
      const st = state(g);
      const parts = g.parent ? [] : partsOf(g);
      const waits = parts.some((p) => p.waiting);
      const fold = parts.length ? `<button class="fold${waits ? " warn" : ""}" data-fold="${esc(g.id)}"><svg class="chev${isFolded(g) ? "" : " open"}" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M4.5 2.5 8 6l-3.5 3.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>${parts.length} parts${waits && isFolded(g) ? " · one waits on you" : ""}</button>` : "";
      return `<div class="goal-row${g.parent ? " part" : ""}" data-repo="${esc(g.repo)}" data-id="${esc(g.id)}">
        <span class="dot ${st.tone}"></span>
        <div class="grow">
          <div class="title"><span class="name">${esc(g.parent ? g.part || g.name : g.title || g.name)}</span>${fold}
            ${many && !g.parent ? `<span class="badge">${esc(g.repo)}</span>` : ""}</div>
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
    $("#list").innerHTML = `<div class="panel goals">${shown.map((g) => row(g) + (isFolded(g) ? "" : partsOf(g).map(row).join(""))).join("")}</div>`;
    document.querySelectorAll("[data-fold]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        const g = goals.find((x) => x.id === b.dataset.fold);
        folded[g.id] = !isFolded(g);
        store.set("folded", folded);
        render(goals);
      };
    });
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
      ${g.technical_plan ? `<p><a href="" data-tab="plan">Read the technical plan ↓</a></p>` : ""}
      <div class="row"><button class="link" data-discuss="plan">Discuss the plan</button></div>
      <div class="disc" id="disc-plan" hidden></div>
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
    ${qs.map((q, n) => `<div class="question" data-q="${n + 1}"><div class="q">${n + 1}. ${esc(q.q)}</div>
      <div class="q-summary" hidden><span class="answered">✓</span> <span class="q-answer"></span>
        <button class="link" data-change="${n + 1}">Change</button></div>
      <div class="q-body">
      ${q.why ? `<div class="why">${esc(q.why)}</div>` : ""}
      ${(q.options || []).length ? `<div class="opts">${q.options.map((o) => `<button class="opt" data-n="${n + 1}" data-label="${esc(o.label)}">
        <b>${esc(o.label)}</b>${o.means ? ` <span class="means">→ ${esc(o.means)}</span>` : ""}
        ${(o.flow || []).length ? `<ol>${o.flow.map((f) => `<li>${esc(f)}</li>`).join("")}</ol>` : ""}</button>`).join("")}</div>` : ""}
      ${q.recommend ? `<div class="rec">Suggested: ${esc(q.recommend)}</div>` : ""}
      <textarea class="own" data-n="${n + 1}" rows="1" placeholder="${(q.options || []).length ? "Or answer in your own words" : "Your answer"}"></textarea>
      <div class="row"><button class="link" data-discuss="q${n + 1}">Discuss this question</button></div>
      <div class="disc" id="disc-q${n + 1}" hidden></div></div></div>`).join("")}
    <textarea id="answer" rows="2" placeholder="Anything else to tell it (optional)"></textarea>
    <div class="buttons"><button class="primary" id="send">Send the answers</button></div></div>`;
}

// A question's answer: the option picked, or the words written; "" when none.
function answerOf(n) {
  const own = $(`.own[data-n="${n}"]`);
  const pick = $(`.opt.on[data-n="${n}"]`);
  return (own && own.value.trim()) || (pick ? pick.dataset.label : "");
}

// An answered question folds to one line with its answer; Change opens it again.
function fold(n, folded) {
  const box = $(`.question[data-q="${n}"]`);
  if (!box) return;
  const answer = answerOf(n);
  const shut = folded && !!answer;
  box.classList.toggle("folded", shut);
  box.querySelector(".q-body").hidden = shut;
  box.querySelector(".q-summary").hidden = !shut;
  box.querySelector(".q-answer").textContent = answer;
}

// A talk about one question or the plan: its own session, apart from the goal's.
function discussion(box, base, topic, onUse) {
  const url = `${base}/discussions/${topic}`;
  box.innerHTML = `<div class="msgs"></div><div class="row composer-row"><textarea rows="2" class="grow"
    placeholder="Ask about it. This talk is its own: the goal does not see it."></textarea><button class="primary">Send</button></div>`;
  const msgs = box.querySelector(".msgs");
  const input = box.querySelector("textarea");
  const send = box.querySelector("button");
  let timer = null;
  const render = (t) => {
    msgs.innerHTML = t.messages.map((m, i) => `<div class="msg ${m.role}"><div class="who">${m.role === "person" ? "You" : "Agent"}</div>
      <div class="md">${md(m.text)}</div>${m.role === "agent" && onUse ? `<button class="link" data-use="${i}">Use as my answer</button>` : ""}</div>`).join("")
      + (t.pending ? `<div class="msg agent"><div class="who">Agent</div><div class="faint">thinking… it reads what it needs first</div></div>` : "")
      + (t.error ? `<div class="msg"><span class="badge bad">${esc(t.error)}</span></div>` : "");
    diagrams(msgs);
    send.disabled = t.pending;
    msgs.querySelectorAll("[data-use]").forEach((b) => { b.onclick = () => onUse(t.messages[+b.dataset.use].text); });
    clearTimeout(timer);
    if (t.pending && box.isConnected) timer = setTimeout(load, 2500);
  };
  const load = async () => { try { render(await api("GET", url)); } catch (e) { toast(e.message, true); } };
  send.onclick = async () => {
    const text = input.value.trim();
    if (!text) return;
    const t = await act(() => api("POST", url, { text }));
    if (t) { input.value = ""; render(t); }
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send.onclick(); });
  load();
}

// What the running call is doing now, under its step.
function nowHtml(now) {
  if (!now) return "";
  return `<div class="now">${now.said ? `<div class="md said">${md(now.said)}</div>` : ""}
    ${(now.actions || []).length ? `<ul class="actions">${now.actions.map((x) => `<li><code>${esc(x)}</code></li>`).join("")}</ul>` : ""}
    ${(now.agents || []).length ? `<div class="faint">Sub-agents at work:</div><ul>${now.agents.map((x) =>
      `<li>${esc(x.description || "a sub-agent")}${x.action ? ` <span class="faint">· ${esc(x.action)}</span>` : ""}</li>`).join("")}</ul>` : ""}</div>`;
}

function liveHtml(g) {
  const agents = g.live || [];
  if (!agents.length) return "";
  return `<div class="panel live"><b>Running now</b>${agents.map((a) => `<div class="agent${a.depth ? " sub" : ""}">
    <div class="grow"><div>${esc(a.role)} <span class="faint">${esc(shortModel(a.model))} · ${span(a.seconds)}</span></div>
    ${a.action ? `<div class="action">${esc(a.action)}</div>` : ""}</div></div>`).join("")}</div>`;
}

// A count in the status line whose list shows on hover.
function hoverList(label, items) {
  const real = items.filter((x) => !x.group);
  if (!real.length) return "";
  const done = real.filter((x) => x.done).length;
  return `<span class="hover">${label} ${done}/${real.length}<div class="pop panel"><ul class="checklist">${items.map((x) =>
    x.group ? `<li class="group">${esc(x.group)}</li>`
      : `<li class="${x.done ? "done" : ""}"><span>${x.done ? "✓" : "○"}</span><span>${esc(x.text)}</span></li>`).join("")}</ul></div></span>`;
}

function planHtml(g) {
  const parts = (g.parts || []).length ? `<h2>Parts</h2>${g.parts.map((p) => {
    const st = state(p);
    return `<a class="goal-row part-row" href="#/g/${encodeURIComponent(g.repo)}/${encodeURIComponent(p.id)}">
      <span class="dot ${st.tone}"></span>
      <div class="grow"><div class="title">${esc(p.part || p.name)}</div><div class="doing">${esc(st.text)}</div></div>
      <div class="meta">${p.round ? `<span>round ${p.round}</span>` : ""}${p.cost ? `<span>${money(p.cost)}</span>` : ""}
        <span class="badge ${st.tone}">${esc(st.label)}</span></div></a>`;
  }).join("")}` : "";
  const body = (parts ? `<h2>Parts</h2><div class="panel goals">${parts.replace("<h2>Parts</h2>", "")}</div>` : "") + (g.technical_plan ? `<div class="md">${md(g.technical_plan)}</div>` : "");
  return body || `<div class="faint">No technical plan${g.small ? ": small work has none" : " yet"}.</div>`;
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
    if (f.endsWith("/")) return `<span class="chip">${esc(f)} (folder)</span>`;
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
  const ui = { open: new Set(), tab: ["timeline", "plan", "ask", "journal", "cost", "log"].includes(store.get("tab")) ? store.get("tab") : "timeline", waitKey: null, sig: {}, log: { next: 0, text: "" }, follow: true };
  $("#main").innerHTML = `<a class="back" href="#/">← Runs</a>
    <div id="head"></div><div id="wait"></div><div id="live"></div>
    <div class="tabs" id="tabs">
      <button data-t="timeline">Timeline</button><button data-t="plan">Plan</button>
      <button data-t="ask">Ask</button><button data-t="journal">Journal</button>
      <button data-t="cost">Cost</button><button data-t="log">Log</button></div>
    <div id="plan-disc" hidden><button class="link" id="plan-disc-open">Discuss the plan</button><div class="disc" id="plan-disc-box" hidden></div></div>
    <div class="tab-body" id="body"></div>`;
  let g = null;

  const set = (sel, html, key) => {
    if (ui.sig[sel] === (key || html)) return false;
    ui.sig[sel] = key || html;
    $(sel).innerHTML = html;
    diagrams($(sel));
    return true;
  };

  const showTab = () => {
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === ui.tab));
    store.set("tab", ui.tab);
    $("#plan-disc").hidden = ui.tab !== "plan" || !g || (!g.technical_plan && !g.journal);
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
        const live = g.alive && g.now && c === cs[cs.length - 1];
        const open = ui.open.has(c.i) || live;
        const dur = c.until ? span(c.until - c.at) : g.alive ? "now" : "";
        return `${head}<div class="tl"><div class="step ${c.kind}"><div class="panel card">
          <div class="head" data-i="${c.i}"><span class="t">${esc(c.title)}</span>
          <span class="s">${esc(live ? g.now.said || (g.now.actions || []).slice(-1)[0] || c.summary : c.summary)}</span>
          <span class="when">${[money(c.cost), dur, clock(c.at)].filter(Boolean).join(" · ")}</span></div>
          ${open ? `<div class="body">${live ? nowHtml(g.now) : ""}${cardBody(c)}</div>` : ""}</div></div></div>`;
      }).join("") || `<div class="faint">Nothing has happened yet.</div>`;
      set("#body", html, "t" + JSON.stringify([g.timeline, [...ui.open], g.alive, g.now]));
    } else if (ui.tab === "journal") {
      set("#body", g.journal ? `<div class="md">${md(g.journal)}</div>` : `<div class="faint">No journal yet.</div>`, "j" + g.journal);
    } else if (ui.tab === "plan") {
      set("#body", planHtml(g), "p" + g.journal + g.technical_plan + JSON.stringify(g.parts || []));
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
  $("#wait").addEventListener("input", (e) => {
    if (e.target.classList.contains("own") && e.target.value.trim()) {
      document.querySelectorAll(`.opt[data-n="${e.target.dataset.n}"]`).forEach((o) => o.classList.remove("on"));
    }
  });
  $("#wait").addEventListener("focusout", (e) => {
    if (e.target.classList.contains("own") && e.target.value.trim()) fold(e.target.dataset.n, true);
  });
  $("#wait").addEventListener("keydown", (e) => {
    if (e.target.classList.contains("own") && e.key === "Enter" && !e.shiftKey && e.target.value.trim()) {
      e.preventDefault();
      e.target.blur();
    }
  });
  $("#plan-disc-open").onclick = () => {
    const box = $("#plan-disc-box");
    box.hidden = !box.hidden;
    if (!box.hidden && !box.dataset.on) { box.dataset.on = "1"; discussion(box, base, "plan"); }
  };
  $("#wait").onclick = async (e) => {
    if (e.target.dataset.tab) {
      e.preventDefault();
      ui.tab = e.target.dataset.tab;
      showTab();
      $("#tabs").scrollIntoView({ behavior: "smooth" });
      return;
    }
    const opt = e.target.closest(".opt");
    if (opt) {
      const on = !opt.classList.contains("on");
      document.querySelectorAll(`.opt[data-n="${opt.dataset.n}"]`).forEach((o) => o.classList.remove("on"));
      opt.classList.toggle("on", on);
      if (on) {
        $(`.own[data-n="${opt.dataset.n}"]`).value = "";
        fold(opt.dataset.n, true);
      }
      return;
    }
    if (e.target.dataset.change) { fold(e.target.dataset.change, false); return; }
    const talk = e.target.dataset.discuss;
    if (talk) {
      const box = $(`#disc-${talk}`);
      box.hidden = !box.hidden;
      if (!box.hidden && !box.dataset.on) {
        box.dataset.on = "1";
        discussion(box, base, talk, talk === "plan" ? (text) => { $("#answer").value = text; }
          : (text) => {
            const own = $(`.own[data-n="${talk.slice(1)}"]`);
            own.value = text;
            own.dispatchEvent(new Event("input", { bubbles: true }));
            fold(talk.slice(1), true);
          });
      }
      return;
    }
    if (e.target.id === "approve") {
      if (await act(() => api("POST", base + "/approve"), "Approved — it builds now")) refresh();
    } else if (e.target.id === "send") {
      const own = [...document.querySelectorAll("#wait .own")];
      const lines = own.map((box) => {
        const value = answerOf(box.dataset.n);
        return value ? `${box.dataset.n}. ${value}` : null;
      });
      const missing = lines.map((l, i) => (l ? null : i + 1)).filter(Boolean);
      if (missing.length) return toast(`Answer question ${missing.join(", ")} first: pick an option or write your own`, true);
      const extra = $("#answer").value.trim();
      const text = [lines.join("\n"), extra].filter(Boolean).join("\n\n");
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
          ${hoverList("steps", checklist(g.journal, "plan"))}
          ${hoverList("criteria", checklist(g.journal, "acceptance criteria"))}
          ${g.cost ? `<span title="${g.own_cost != null ? "its own " + money(g.own_cost) + ", the rest its parts'" : ""}">${money(g.cost)}${g.own_cost != null ? " with its parts" : ""}</span>` : ""}
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
    if (waitKey !== ui.waitKey) {
      ui.waitKey = waitKey;
      $("#wait").innerHTML = waitingHtml(g);
      diagrams($("#wait"));
      if (waitKey && g.awaiting.kind === "plan") ui.tab = "plan";
    }
    set("#live", liveHtml(g));
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
  auto: "The reviewer agent only",
};
const CLAUDE_MODELS = [["claude-opus-5-5", "Opus 5.5"], ["claude-sonnet-5-5", "Sonnet 5.5"],
  ["claude-haiku-4-5-20251001", "Haiku 4.5"], ["claude-fable-5-1", "Fable 5.1"]];
const EFFORTS = ["low", "medium", "high", "xhigh", "max"];
const ROLES = [["lead", "Lead"], ["check", "Reviewer and checker"], ["subagent", "Coding tasks"]];

const options = (list, value, empty) => (empty ? `<option value="">${esc(empty)}</option>` : "") +
  list.map(([v, l]) => `<option value="${esc(v)}"${v === value ? " selected" : ""}>${esc(l)}</option>`).join("");

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
    <div class="panel settings wide">
      ${repos.map((r) => `<div class="row" style="margin-bottom:6px"><b>${esc(r.name)}</b><span class="dim">${esc(r.path)}</span></div>`).join("")}
      <div class="row" style="margin-top:12px"><input class="grow" id="newrepo" placeholder="/path/to/repo"><button id="addrepo">Add</button></div>
    </div>`;
  $("#addrepo").onclick = async () => {
    const path = $("#newrepo").value.trim();
    if (path && await act(() => api("POST", "/api/repos", { path }), "Added")) settingsPage();
  };
  if (!repos.length) return;
  let cfg = null;

  const ocModels = () => cfg.providers.flatMap((p) => (p.id ? (p.models || []).map((m) => [`${p.id}/${m}`, `${p.id}/${m}`]) : []));

  const claudeHtml = () => `<div class="panel settings wide"><table class="roles">
      <tr><th></th><th>Model</th><th>Effort</th></tr>
      ${ROLES.map(([k, name]) => `<tr><td><b>${name}</b></td>
        <td><select data-claude="${k}">${options(CLAUDE_MODELS, cfg.models[k])}</select></td>
        <td><select data-effort="${k}_effort">${options(EFFORTS.map((e) => [e, e]), cfg.models[k + "_effort"] || "",
          k === "check" ? null : "default")}</select></td></tr>`).join("")}
      <tr><td><b>Usage limit</b></td><td><div class="row"><input data-k="usage_threshold" type="number" min="1" max="100"
        value="${cfg.usage_threshold}" style="width:90px"> <span class="dim">% of any Claude limit, then goals pause</span></div></td><td></td></tr>
    </table></div>`;

  const providerRows = () => cfg.providers.map((p, i) => `<tr data-i="${i}">
      <td><input data-p="id" value="${esc(p.id || "")}" placeholder="openrouter"></td>
      <td><input data-p="base_url" value="${esc(p.base_url || "")}" placeholder="OpenCode's own"></td>
      <td><input data-p="key_env" value="${esc(p.key_env || "")}" placeholder="${p.base_url ? "ACME_API_KEY" : "its usual"}"></td>
      <td><input data-p="models" value="${esc((p.models || []).join(", "))}" placeholder="model, model"></td>
      <td><input data-p="input_price" type="number" min="0" step="0.01" value="${p.input_price ?? ""}" placeholder="$ in"></td>
      <td><input data-p="output_price" type="number" min="0" step="0.01" value="${p.output_price ?? ""}" placeholder="$ out"></td>
      <td><button class="danger" data-rm="${i}" title="Remove">×</button></td></tr>`).join("");

  const ocRoles = () => ROLES.map(([k, name]) => `<tr><td><b>${name}</b></td>
      <td><select data-oc="${k}">${options(ocModels(), cfg.opencode_models[k] || "", ocModels().length ? "pick a model" : "add a provider below")}</select></td></tr>`).join("");

  const opencodeHtml = () => `<div class="panel settings wide">
      ${cfg.opencode ? "" : `<div class="badge warn" style="margin-bottom:10px">OpenCode is not installed: npm i -g @opencode/cli, then cond serve restart</div>`}
      <table class="roles"><tr><th></th><th>Model</th></tr><tbody id="ocroles">${ocRoles()}</tbody></table>
      <h4>Providers</h4>
      <table class="providers"><tr><th>Id</th><th>Base URL</th><th>Key variable</th><th>Models</th><th>$/M in</th><th>$/M out</th><th></th></tr>
        <tbody id="provrows">${providerRows()}</tbody></table>
      <button id="addprov">+ Provider</button></div>`;

  const draw = () => {
    const claude = cfg.runner !== "opencode";
    $("#form").innerHTML = `
      <div class="runs-on"><span>Runs on</span>
        <button data-runner="claude" class="${claude ? "on" : ""}">Claude Code <code>claude -p</code></button>
        <button data-runner="opencode" class="${claude ? "" : "on"}">OpenCode</button></div>
      ${claude ? claudeHtml() : opencodeHtml()}
      <h2>Goals</h2>
      <div class="panel settings wide"><table class="roles">
        <tr><td><b>Goals go into</b></td><td><input data-k="base" value="${esc(cfg.base || "")}" placeholder="main"></td></tr>
        <tr><td><b>Plan approval</b></td><td><select data-k="goal_gate">${options(Object.entries(GATES), cfg.goal_gate)}</select></td></tr>
      </table></div>`;
  };

  const load = async () => {
    store.set("repo", current);
    const s = await api("GET", `/api/repos/${encodeURIComponent(current)}/settings`);
    cfg = { ...s, models: { ...s.models }, opencode_models: { ...s.opencode_models }, providers: (s.providers || []).map((p) => ({ ...p })) };
    draw();
  };

  const form = $("#form");
  form.addEventListener("click", (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    if (t.dataset.runner) { cfg.runner = t.dataset.runner; draw(); }
    if (t.dataset.rm) { cfg.providers.splice(+t.dataset.rm, 1); draw(); }
    if (t.id === "addprov") { cfg.providers.push({ models: [] }); draw(); }
  });
  form.addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset.claude) cfg.models[t.dataset.claude] = t.value;
    if (t.dataset.effort) cfg.models[t.dataset.effort] = t.value || null;
    if (t.dataset.oc) cfg.opencode_models[t.dataset.oc] = t.value || null;
    if (t.dataset.p) $("#ocroles").innerHTML = ocRoles();
  });
  form.addEventListener("input", (e) => {
    const t = e.target;
    if (t.dataset.k) cfg[t.dataset.k] = t.dataset.k === "usage_threshold" ? parseInt(t.value, 10) : t.value;
    if (t.dataset.p) {
      const p = cfg.providers[+t.closest("tr").dataset.i];
      const k = t.dataset.p;
      p[k] = k === "models" ? t.value.split(",").map((m) => m.trim()).filter(Boolean)
        : k.endsWith("_price") ? (t.value === "" ? null : parseFloat(t.value)) : t.value.trim();
    }
  });
  $("#save").onclick = async () => {
    const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== null && v !== "" && v !== undefined));
    const r = await act(() => api("PUT", `/api/repos/${encodeURIComponent(current)}/settings`, {
      runner: cfg.runner, base: (cfg.base || "").trim() || null, usage_threshold: cfg.usage_threshold, goal_gate: cfg.goal_gate,
      models: { lead: cfg.models.lead, subagent: cfg.models.subagent, check: cfg.models.check,
        check_effort: cfg.models.check_effort, lead_effort: cfg.models.lead_effort || null,
        subagent_effort: cfg.models.subagent_effort || null },
      opencode_models: clean(cfg.opencode_models),
      providers: cfg.providers.map(clean),
    }), "Saved");
    if (r) load();
  };
  $("#which").value = current;
  $("#which").onchange = (e) => { current = e.target.value; load(); };
  load();
}

async function waitingCount() {
  try {
    const goals = await api("GET", "/api/goals");
    const n = goals.filter((g) => g.waiting).length;
    const el = $("#waiting-count");
    el.textContent = n;
    el.hidden = !n;
    el.title = n + " goal" + (n === 1 ? "" : "s") + " waiting on you";
  } catch (e) { /* the page says so where it matters */ }
  setTimeout(waitingCount, document.hidden ? 60000 : 10000);
}

window.addEventListener("DOMContentLoaded", waitingCount);
window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", route);
