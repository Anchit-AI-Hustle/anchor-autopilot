/* /ops/ - reads ledger.json (decisions, variants, uploads), catalog.json (latest status and
   links) and status.json (last run) and draws the tracker. No build step, no dependencies. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const TARGET = { youtube_full: "YouTube full", youtube_short: "YouTube Short", instagram_reel: "Instagram Reel", github_release: "GitHub release", site: "Site" };
  const GROUPS = ["record", "content", "platform", "visual"];

  const getJSON = async (url) => {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) throw new Error(`${url}: ${res.status}`);
    return res.json();
  };

  // ---------------------------------------------------------------- status words
  // one place decides what a status means, so the pills, the totals and the
  // "needs attention" filter never disagree
  const tone = (row) => {
    const s = (row.status || "").toLowerCase();
    if (row.error && !/^(live|sent|released|listed)/.test(s)) return "bad";
    if (/^(live|sent|released|listed|the short is the full)/.test(s)) return "ok";
    if (/^(scheduled|sending|buffer|pending|made|dry-run)/.test(s)) return "warn";
    if (/^(not |no full)/.test(s)) return "none";
    return "bad";
  };
  const needsAttention = (e) => e.uploads.some((u) => {
    const t = tone(u);
    return t === "bad" || (t === "warn" && u.target !== "instagram_reel") || (t === "none" && u.target === "youtube_full" && !/^no full song/.test(u.status || ""));
  }) || Boolean(e.note);

  // the catalog is refreshed by `anchor sync` more often than the ledger, so its
  // status and links win for the robot's own drops
  const merge = (ledger, catalog) => {
    const drops = new Map((catalog.drops || []).map((d) => [d.id, d]));
    for (const e of ledger.entries) {
      const d = drops.get(e.id);
      if (!d || e.source === "manual") continue;
      // v1 posted the Short through Buffer, v2 posts the full 16:9: the catalog link belongs to that row
      const ytRow = e.source === "pipeline" ? "youtube_full" : "youtube_short";
      for (const u of e.uploads) {
        if (u.target === ytRow && d.youtube_url && u.status !== "removed by YouTube (Community Guidelines)") { u.url = d.youtube_url; if (d.status) u.status = d.status === "sent" ? "live" : d.status; if (d.error) u.error = d.error; }
        if (u.target === "instagram_reel" && d.instagram_url) { u.url = d.instagram_url; u.status = "live"; }
      }
    }
    return ledger.entries;
  };

  // ---------------------------------------------------------------- header + totals
  const drawRun = (status) => {
    const r = status.last_run || {};
    const cls = r.result === "ok" ? "ok" : r.result === "failed" ? "bad" : "warn";
    const when = r.finished_at ? new Date(r.finished_at).toLocaleString("en-GB", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" }) + " IST" : "-";
    const next = status.next_post_at ? new Date(status.next_post_at).toLocaleString("en-GB", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" }) + " IST" : "-";
    $("#run").innerHTML = `Last run <b class="${cls}">${esc(r.result || "unknown")}</b>` +
      (r.drop_id ? ` · ${esc(r.drop_id)} ${esc(r.title || "")}` : "") + ` · ${esc(when)}` +
      (r.run_url ? ` · <a href="${esc(r.run_url)}" rel="noopener" target="_blank">log ↗</a>` : "") +
      ` &nbsp;·&nbsp; Next slot <b>${esc(next)}</b>` + (r.error && r.result === "failed" ? ` · <span class="bad">${esc(r.error)}</span>` : "");
  };

  const drawStats = (entries) => {
    const count = (target, ok) => entries.filter((e) => e.uploads.some((u) => u.target === target && (ok ? tone(u) === "ok" : tone(u) !== "ok" && tone(u) !== "none"))).length;
    const attention = entries.filter(needsAttention).length;
    const variants = entries.reduce((n, e) => n + e.variants.length, 0);
    const tiles = [
      ["Songs", entries.length, `${entries.filter((e) => e.source !== "manual").length} by the robot`],
      ["Full videos live", count("youtube_full", true), `${count("youtube_full", false)} pending`],
      ["Shorts live", count("youtube_short", true), "on the channel"],
      ["Reels live", count("instagram_reel", true), "Instagram"],
      ["Variants tried", variants, "attempts, siblings, redraws"],
      ["Needs attention", attention, attention ? "open the flagged rows" : "all clear", attention ? "warn" : ""],
    ];
    $("#stats").innerHTML = tiles.map(([k, v, s, cls]) => `<div class="${cls || ""}"><dt>${esc(k)}</dt><dd>${esc(v)}<small>${esc(s)}</small></dd></div>`).join("");
  };

  // ---------------------------------------------------------------- rows
  const pill = (u) => `<span class="pill ${tone(u)}" title="${esc(u.error || u.note || u.status || "")}">${esc(TARGET[u.target] || u.target)}</span>`;

  const valueCell = (v) => {
    const text = Array.isArray(v) ? v.join(", ") : v == null ? "-" : String(v);
    const long = text.length > 220 || text.split("\n").length > 5;
    return `<div class="value${long ? " clip" : ""}">${esc(text)}</div>` + (long ? `<button class="more" type="button">show all</button>` : "");
  };

  const drawDetail = (e, tr) => {
    const tpl = $("#row-detail").content.cloneNode(true);
    const det = tpl.querySelector("tr");
    const vb = det.querySelector(".variants tbody");
    vb.innerHTML = e.variants.length ? e.variants.map((v) => `<tr class="${v.chosen ? "chosen" : v.ok ? "" : "rejected"}">
        <td>${esc(v.label)}${v.url ? ` <a href="${esc(v.url)}" rel="noopener" target="_blank">↗</a>` : ""}</td>
        <td class="num">${v.score == null ? "-" : esc(v.score)}${v.kind === "audio" && v.nearest ? `<br><small>vs ${esc(v.nearest)}</small>` : ""}</td>
        <td>${v.chosen ? "released" : v.ok ? "passed, not used" : "rejected"}</td>
        <td class="rule">${esc([...(v.fail || []), ...(v.warn || []), v.note].filter(Boolean).join(" · ") || "-")}</td></tr>`).join("")
      : `<tr><td colspan="4" class="rule">Single take: nothing else was tried.</td></tr>`;
    det.querySelector(".uploads tbody").innerHTML = e.uploads.map((u) => `<tr>
        <td>${pill(u)}</td><td class="ev">${esc(u.file || "-")}${u.seconds ? ` · ${u.seconds}s` : ""}</td>
        <td>${esc(u.status || "-")}${u.due_at ? `<br><small>${esc(u.due_at)}</small>` : ""}${u.error ? `<br><small class="bad">${esc(u.error)}</small>` : u.note ? `<br><small>${esc(u.note)}</small>` : ""}</td>
        <td>${u.url ? `<a href="${esc(u.url)}" rel="noopener" target="_blank">open ↗</a>` : "-"}</td></tr>`).join("");
    const files = det.querySelector(".files");
    if (e.files && e.files.length) files.querySelector("tbody").innerHTML = e.files.map((f) => `<tr><td>${esc(f.role)}</td><td class="ev">${esc(f.file || "-")}</td><td class="rule">${esc(f.spec || "")}</td></tr>`).join("");
    else files.hidden = true;
    const db = det.querySelector(".decisions tbody");
    db.innerHTML = GROUPS.filter((g) => e.fields.some((f) => f.group === g)).map((g) => `<tr class="group"><td colspan="4">${esc(g)}</td></tr>` +
      e.fields.filter((f) => f.group === g).map((f) => `<tr><td>${esc(f.field)}</td><td class="val">${valueCell(f.value)}</td><td class="rule">${esc(f.rule)}</td><td class="ev">${esc(f.evidence || "-")}</td></tr>`).join("")).join("");
    if (e.note) det.querySelector(".detail-grid").insertAdjacentHTML("afterbegin", `<p class="note wide">⚠ ${esc(e.note)}</p>`);
    det.addEventListener("click", (ev) => {
      const b = ev.target.closest(".more");
      if (!b) return;
      b.previousElementSibling.classList.remove("clip");
      b.remove();
    });
    tr.after(det);
    return det;
  };

  const drawRows = (entries) => {
    const tb = $("#rows");
    tb.innerHTML = "";
    for (const e of entries) {
      const tr = document.createElement("tr");
      tr.className = "song";
      tr.tabIndex = 0;
      tr.setAttribute("aria-expanded", "false");
      const src = e.source === "manual" ? "by hand" : e.source === "queue" ? "your queue" : e.source === "pipeline-v1" ? "robot v1" : "robot";
      const chosen = e.variants.filter((v) => v.chosen).length;
      tr.innerHTML = `<td class="date">${esc(e.date)}</td>
        <td><span class="t"><span class="swatch" style="--sw:${esc(e.accent || "")}"></span>${esc(e.title)}<small>${esc(e.id)}${e.family ? ` · ${esc(e.family)}` : ""}${needsAttention(e) ? ' · <span class="warn">needs attention</span>' : ""}</small></span></td>
        <td>${esc(e.lane || "-")}${e.bpm ? `<br><small>${esc(e.bpm)} BPM</small>` : ""}</td>
        <td>${esc(src)}${e.engine && e.engine.name && e.engine.name !== "queue" ? `<br><small>${esc(e.engine.name)}</small>` : ""}</td>
        <td class="num">${e.variants.length ? `${e.variants.length} tried${chosen ? ` · ${chosen} used` : ""}` : "1 take"}</td>
        <td>${e.uploads.map(pill).join("")}</td>
        <td class="caret" aria-hidden="true">›</td>`;
      let det = null;
      const toggle = () => {
        det = det || drawDetail(e, tr);
        const open = tr.getAttribute("aria-expanded") !== "true";
        tr.setAttribute("aria-expanded", String(open));
        det.hidden = !open;
      };
      tr.addEventListener("click", (ev) => { if (!ev.target.closest("a")) toggle(); });
      tr.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggle(); } });
      tb.appendChild(tr);
    }
    $("#empty").hidden = entries.length > 0;
  };

  const drawRules = (entries) => {
    const rules = new Map();
    for (const e of entries) for (const f of e.fields) {
      const k = `${f.group}|${f.field}|${f.rule}`;
      rules.set(k, (rules.get(k) || { group: f.group, field: f.field, rule: f.rule, n: 0 }));
      rules.get(k).n++;
    }
    const rows = [...rules.values()].sort((a, b) => GROUPS.indexOf(a.group) - GROUPS.indexOf(b.group) || b.n - a.n || a.field.localeCompare(b.field));
    $("#rules-table tbody").innerHTML = GROUPS.filter((g) => rows.some((r) => r.group === g)).map((g) => `<tr class="group"><td colspan="3">${esc(g)}</td></tr>` +
      rows.filter((r) => r.group === g).map((r) => `<tr><td>${esc(r.field)}</td><td class="rule">${esc(r.rule)}</td><td class="num">${r.n}</td></tr>`).join("")).join("");
  };

  // ---------------------------------------------------------------- filters
  const apply = (all) => {
    const source = $("#f-source").value, attn = $("#f-attn").checked, q = $("#f-q").value.trim().toLowerCase();
    const src = (e) => e.source === "pipeline-v1" ? "pipeline" : e.source;
    drawRows(all.filter((e) => (!source || src(e) === source) && (!attn || needsAttention(e)) &&
      (!q || [e.title, e.id, e.lane, e.family, ...e.uploads.map((u) => u.url || "")].join(" ").toLowerCase().includes(q))));
  };

  const boot = async () => {
    try {
      const [ledger, catalog, status] = await Promise.all([getJSON("/data/ledger.json"), getJSON("/data/catalog.json").catch(() => ({})), getJSON("/data/status.json").catch(() => ({}))]);
      const all = merge(ledger, catalog).sort((a, b) => (b.date + b.id).localeCompare(a.date + a.id));
      drawRun(status);
      drawStats(all);
      drawRules(all);
      apply(all);
      for (const id of ["#f-source", "#f-attn", "#f-q"]) $(id).addEventListener("input", () => apply(all));
      const hash = decodeURIComponent(location.hash.slice(1));
      if (hash) { const tr = [...document.querySelectorAll("tr.song")].find((r) => r.querySelector(".t small").textContent.startsWith(hash)); if (tr) { tr.click(); tr.scrollIntoView({ block: "start" }); } }
    } catch (err) {
      $("#run").innerHTML = `<span class="bad">Could not load the ledger: ${esc(err.message)}</span>`;
    }
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
