// Sync with Suno (Anchit, 2026-11-09): every song on the channel's Suno profile as a checklist,
// each with what would be posted, and one button that sends the ticked ones to YouTube.
//
// The page holds no key. "Post to YouTube" opens a prefilled issue on the repo carrying a JSON
// block; the Queue a Suno song workflow (owner only) queues each song with the choices made here
// and, for "Post now", starts a run. Only fields changed from what the robot would post are sent.
(() => {
  "use strict";
  const REPO = "https://github.com/Anchit-AI-Hustle/anchor-autopilot";
  const FORM = "anchor-suno-sync";
  const URL_MAX = 7600;                         // GitHub's new-issue link stops working past ~8 kB
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const state = { songs: [], picks: new Map(), filter: "all", q: "", cat: null, lanes: [], youtube: new Map() };
  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window */ } },
  };

  const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
  const key = (t) => (t || "").toLowerCase().replace(/\(.*?\)|\[.*?\]/g, " ").replace(/\b(part|pt)\s*\d+\b/g, " ")
    .replace(/[^a-z0-9]+/g, " ").trim().split(" ").filter((w) => w.length > 2).sort().join(" ");
  const esc = (s) => String(s ?? "");

  function status(t) { $("#sy-status").textContent = t; }

  // ------------------------------------------------------------------ data
  async function load(live = true) {
    status("Loading songs…");
    let cat = null;
    try { cat = await (await fetch("/data/catalog.json", { cache: "no-store" })).json(); } catch { /* offline */ }
    state.cat = cat;
    const synced = (cat && cat.catalogue && cat.catalogue.songs) || [];
    state.lanes = (cat && cat.catalogue && cat.catalogue.lanes) || [];
    // every song already on YouTube: the robot's drops and the older uploads
    state.youtube = new Map();
    for (const d of [...((cat && cat.drops) || []), ...((cat && cat.legacy) || [])]) {
      const url = d.youtube_full_url || d.youtube_url;
      if (url && d.title) state.youtube.set(key(d.title), { title: d.title, url, date: d.date });
    }
    const byId = new Map(synced.map((s) => [s.id, { ...s, synced: true }]));
    let liveNote = "";
    if (live) {
      try {
        const r = await fetch("/api/suno", { cache: "no-store" });
        const j = await r.json();
        if (!r.ok) throw new Error(j.error || r.status);
        for (const s of j.songs) byId.set(s.id, { ...(byId.get(s.id) || {}), ...s, live: true });
        liveNote = `live from Suno just now (${j.total} songs)`;
      } catch (e) {
        liveNote = "Suno did not answer, showing the last sync";
      }
    }
    for (const id of store.get("sy-extra") || []) if (!byId.has(id)) await addById(id, byId, true);
    state.songs = [...byId.values()].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    const when = cat && cat.catalogue && cat.catalogue.checked_at ? new Date(cat.catalogue.checked_at).toLocaleString() : "never";
    status(`${state.songs.length} songs · ${liveNote} · ratings from the last sync ${when}`);
    render();
  }

  async function addById(id, byId, quiet) {
    try {
      const r = await fetch(`/api/suno?song=${encodeURIComponent(id)}`, { cache: "no-store" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.status);
      byId.set(j.song.id, { ...(byId.get(j.song.id) || {}), ...j.song, live: true, added: true });
      const extra = new Set(store.get("sy-extra") || []); extra.add(j.song.id); store.set("sy-extra", [...extra]);
      return j.song;
    } catch (e) {
      if (!quiet) status(`Could not add that song: ${e.message}`);
      return null;
    }
  }

  // what the robot would post, for a song the last sync has not seen yet: the synced template
  // with this song's title in it
  function defaults(s) {
    if (s.post) return s.post;
    const t = (state.cat && state.cat.catalogue && state.cat.catalogue.songs || []).find((x) => x.post);
    if (!t) return { youtube_title: `${s.title} | Hard Techno | ANCHOR`, description: "", hashtags: "#hardtechno #acidtechno #techno", lane: "", style: "motion" };
    const swap = (txt) => txt.split(t.title).join(s.title);
    return { ...t.post, youtube_title: swap(t.post.youtube_title), description: swap(t.post.description) };
  }

  // already on YouTube, another take of something on YouTube, or the same song twice on Suno
  function dup(s) {
    const k = key(s.title);
    const yt = state.youtube.get(k) || (s.released_at ? { title: s.title, url: "", date: s.released_at.slice(0, 10) } : null);
    if (yt) return { kind: "out", text: `On YouTube already: ${yt.title}${yt.date ? ` (${yt.date})` : ""}`, url: yt.url };
    if (s.queue_pos) return { kind: "dup", text: `In the release queue at #${s.queue_pos}` };
    if (s.idea_posted) return { kind: "dup", text: "Another take of a song already posted" };
    const twins = state.songs.filter((x) => x !== s && key(x.title) === k);
    if (twins.length) return { kind: "dup", text: `${twins.length + 1} takes on Suno with this title: tick only the best one` };
    if ((s.similar || []).length) return { kind: "dup", text: `Close to ${s.similar.map((x) => x.title || x).slice(0, 2).join(", ")}` };
    return { kind: "new", text: "Not on YouTube yet" };
  }

  // ------------------------------------------------------------------ render
  function visible(s) {
    const d = dup(s);
    if (state.filter === "new" && d.kind !== "new") return false;
    if (state.filter === "dup" && d.kind !== "dup") return false;
    if (state.filter === "out" && d.kind !== "out") return false;
    const q = state.q.trim().toLowerCase();
    return !q || `${s.title} ${s.tags} ${s.lyrics}`.toLowerCase().includes(q);
  }

  function render() {
    const list = $("#sy-list");
    list.textContent = "";
    const counts = { all: 0, new: 0, dup: 0, out: 0 };
    for (const s of state.songs) { counts.all++; counts[dup(s).kind]++; }
    for (const k in counts) $(`#n-${k}`).textContent = counts[k];
    const shown = state.songs.filter(visible);
    for (const s of shown) list.append(card(s));
    if (!shown.length) {
      const li = document.createElement("li");
      li.className = "sy-empty";
      li.textContent = "Nothing here with these filters.";
      list.append(li);
    }
    bar();
  }

  function card(s) {
    const el = $("#sy-card").content.firstElementChild.cloneNode(true);
    const d = dup(s);
    const def = defaults(s);
    const pick = state.picks.get(s.id);
    el.dataset.id = s.id;
    el.classList.toggle("is-on", !!pick);
    el.classList.add(`k-${d.kind}`);
    $(".sy-title", el).textContent = s.title;
    if (s.image) $(".sy-cover", el).src = s.image; else $(".sy-cover", el).remove();
    const meta = [mmss(s.duration_s || 0), s.model, s.created_at && s.created_at.slice(0, 10),
      `${s.plays || 0} plays`, def.lane_name, def.bpm && `${def.bpm} BPM`, s.added && "added by link"].filter(Boolean);
    $(".sy-meta", el).append(...meta.map((m) => Object.assign(document.createElement("li"), { textContent: m })));
    const dp = $(".sy-dup", el);
    dp.textContent = d.text;
    dp.className = `sy-dup ${d.kind}`;
    if (d.url) { const a = document.createElement("a"); a.href = d.url; a.target = "_blank"; a.rel = "noopener"; a.textContent = " Watch ↗"; dp.append(a); }
    $(".sy-rating", el).textContent = s.rating != null ? `${s.rating}/10` : "new";
    $(".sy-rating", el).classList.toggle("bad", s.postable === false);
    // Suno's m4a is Opus, which Safari may not play: the song's mp4 is the fallback source
    const au = $(".sy-audio", el);
    const srcs = [[s.audio_url, "audio/mp4; codecs=opus"], [s.video_url, "video/mp4"]].filter((x) => x[0]);
    for (const [u, t] of srcs) au.append(Object.assign(document.createElement("source"), { src: u, type: t }));
    if (!srcs.length) au.remove();
    const vbtn = $(".f-video", el), vid = $(".sy-video", el);
    if (s.video_url) {
      vbtn.addEventListener("click", () => { vid.hidden = !vid.hidden; if (!vid.src) vid.src = s.video_url; if (!vid.hidden) vid.play().catch(() => {}); vbtn.textContent = vid.hidden ? "Watch the Suno video" : "Hide the video"; });
    } else vbtn.remove();
    $(".sy-link", el).href = s.url;
    $(".sy-lyrics", el).textContent = s.lyrics || "No lyrics on Suno (an instrumental, or the lyrics are hidden).";
    $(".sy-tags", el).textContent = s.tags || "No style prompt.";
    const checks = $(".sy-checks", el);
    for (const c of [...(s.checks || []), ...(s.factors || []).map((f) => ({ ok: f.score >= f.max * 0.6, label: `${f.name} ${f.score}/${f.max}`, detail: f.note }))]) {
      const li = document.createElement("li");
      li.className = c.ok ? "ok" : "no";
      li.textContent = `${c.label}: ${c.detail}`;
      checks.append(li);
    }
    if (!checks.children.length) $(".sy-checks-wrap", el).remove();
    if (s.decision && s.decision.reason) {
      const li = document.createElement("li"); li.textContent = `Robot: ${s.decision.verdict}, ${s.decision.reason}`; checks.append(li);
    }

    // the editable post, starting from the robot's own
    const v = { ...def, title: s.title, ...(pick || {}) };
    const f = (c) => $(c, el);
    for (const r of $$(".f-style", el)) { r.name = `style-${s.id}`; r.checked = r.value === (v.style || "motion"); }
    f(".f-title").value = v.title;
    f(".f-yt").value = v.youtube_title || "";
    f(".f-desc").value = v.description || "";
    f(".f-tags").value = v.hashtags || "";
    const lane = f(".f-lane");
    lane.append(new Option("Guess from the Suno style prompt", ""));
    for (const l of state.lanes) lane.append(new Option(l.name, l.id));
    lane.value = (pick && pick.lane) || def.lane || "";
    f(".f-force").checked = !!(pick && pick.force);
    $(".sy-force", el).hidden = d.kind === "new";
    const counters = () => { f(".f-yt-n").textContent = `${f(".f-yt").value.length}/100`; f(".f-desc-n").textContent = `${f(".f-desc").value.length}/4900`; };
    counters();
    const tick = f(".f-tick");
    tick.checked = !!pick;
    tick.setAttribute("aria-label", `Post ${s.title}`);
    const save = () => {
      counters();
      if (!tick.checked) { state.picks.delete(s.id); el.classList.remove("is-on"); bar(); return; }
      state.picks.set(s.id, {
        style: ($$(".f-style", el).find((r) => r.checked) || {}).value || "motion",
        title: f(".f-title").value.trim(), youtube_title: f(".f-yt").value.trim(),
        description: f(".f-desc").value.trim(), hashtags: f(".f-tags").value.trim(),
        lane: lane.value, force: f(".f-force").checked,
      });
      el.classList.add("is-on");
      bar();
    };
    el.addEventListener("input", (e) => { if (e.target !== tick && !tick.checked && e.target.closest(".sy-edit")) tick.checked = true; save(); });
    el.addEventListener("change", save);
    f(".f-reset").addEventListener("click", () => {
      f(".f-title").value = s.title; f(".f-yt").value = def.youtube_title || ""; f(".f-desc").value = def.description || "";
      f(".f-tags").value = def.hashtags || ""; lane.value = def.lane || "";
      for (const r of $$(".f-style", el)) r.checked = r.value === "motion";
      save();
    });
    return el;
  }

  // ------------------------------------------------------------------ the request
  function request() {
    const all = $("#sy-style-all").value;
    const songs = [];
    for (const [id, p] of state.picks) {
      const s = state.songs.find((x) => x.id === id);
      if (!s) continue;
      const def = defaults(s);
      const out = { id, style: all || p.style || "motion" };
      if (p.title && p.title !== s.title) out.title = p.title;
      if (p.youtube_title && p.youtube_title !== def.youtube_title) out.youtube_title = p.youtube_title;
      if (p.description && p.description !== def.description) out.description = p.description;
      if (p.hashtags && p.hashtags !== def.hashtags) out.hashtags = p.hashtags;
      if (p.lane && p.lane !== def.lane) out.lane = p.lane;
      if (p.force) out.force = true;
      songs.push({ ...out, _t: p.title || s.title });
    }
    const body = { form: FORM, release: $("#sy-when").value, songs: songs.map(({ _t, ...x }) => x) };
    const names = songs.map((x) => x._t);
    const text = `Post to YouTube from the Sync with Suno page:\n\n${names.map((n) => `- ${n}`).join("\n")}\n\n` +
      "```json\n" + JSON.stringify(body, null, 1) + "\n```\n";
    const title = `Post to YouTube: ${names.length === 1 ? names[0] : `${names.length} songs`}`;
    return { title, text, n: names.length };
  }

  function bar() {
    const n = state.picks.size;
    $("#sy-count").textContent = n;
    $("#sy-post").disabled = $("#sy-copy").disabled = !n;
    const dups = [...state.picks.keys()].map((id) => state.songs.find((s) => s.id === id)).filter((s) => s && dup(s).kind !== "new" && !state.picks.get(s.id).force);
    const r = n ? request() : null;
    const url = r ? issueUrl(r) : "";
    $("#sy-warn").textContent = dups.length ? `· ${dups.length} look like duplicates and will be skipped unless you allow them`
      : url.length > URL_MAX ? "· too long for one link: use Copy request" : "";
    document.body.classList.toggle("has-picks", n > 0);
  }

  function issueUrl(r) {
    return `${REPO}/issues/new?labels=youtube-queue&title=${encodeURIComponent(r.title)}&body=${encodeURIComponent(r.text)}`;
  }

  async function copy() {
    const r = request();
    try { await navigator.clipboard.writeText(r.text); status("Request copied: paste it into a new issue on the repo with the youtube-queue label."); }
    catch { status("Could not copy here; select the request from the issue instead."); }
  }

  function post() {
    const r = request();
    const url = issueUrl(r);
    if (url.length > URL_MAX) {
      copy();
      window.open(`${REPO}/issues/new?labels=youtube-queue&title=${encodeURIComponent(r.title)}`, "_blank", "noopener");
      return;
    }
    window.open(url, "_blank", "noopener");
    status(`Opened the request for ${r.n} song(s): press "Create" on GitHub and the robot takes it from there.`);
  }

  // ------------------------------------------------------------------ wire up
  function init() {
    $$(".chip-btn[data-f]").forEach((b) => b.addEventListener("click", () => {
      state.filter = b.dataset.f;
      $$(".chip-btn[data-f]").forEach((x) => x.classList.toggle("on", x === b));
      render();
    }));
    let t;
    $("#sy-q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value; render(); }, 150); });
    $("#sy-add").addEventListener("submit", async (e) => {
      e.preventDefault();
      const m = ($("#sy-link").value || "").match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
      if (!m) { status("That is not a Suno song link."); return; }
      const byId = new Map(state.songs.map((s) => [s.id, s]));
      const s = await addById(m[0].toLowerCase(), byId, false);
      if (s) { state.songs = [...byId.values()]; $("#sy-link").value = ""; status(`Added ${s.title}.`); render(); }
    });
    $("#sy-pick-new").addEventListener("click", () => {
      for (const s of state.songs) if (dup(s).kind === "new" && s.postable !== false && !state.picks.has(s.id)) {
        const d = defaults(s);
        state.picks.set(s.id, { style: "motion", title: s.title, youtube_title: d.youtube_title, description: d.description, hashtags: d.hashtags, lane: d.lane, force: false });
      }
      render();
    });
    $("#sy-clear").addEventListener("click", () => { state.picks.clear(); render(); });
    $("#sy-refresh").addEventListener("click", () => load(true));
    $("#sy-style-all").addEventListener("change", bar);
    $("#sy-when").addEventListener("change", bar);
    $("#sy-post").addEventListener("click", post);
    $("#sy-copy").addEventListener("click", copy);
    load(true);
  }
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", init) : init();
})();
