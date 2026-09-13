(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const el = (tag, props = {}, ...kids) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (v === undefined || v === null) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("data-") || k.startsWith("aria-") || k === "href" || k === "src" || k === "alt" ||
               k === "rel" || k === "target" || k === "type" || k === "loading" || k === "width" ||
               k === "height" || k === "style" || k === "colspan" || k === "title") {
        node.setAttribute(k, v);
      } else node[k] = v;
    }
    for (const kid of kids) if (kid) node.append(kid);
    return node;
  };

  const CHANNEL = "https://www.youtube.com/@AT_ANCHOR";
  const REPO = "https://github.com/Anchit-AI-Hustle/anchor-autopilot";
  const state = { catalog: { drops: [] }, status: {}, current: null };

  const fmtDate = (iso) => new Date(iso + (iso.length === 10 ? "T00:00:00Z" : ""))
    .toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const fmtWhen = (iso) => new Date(iso).toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
  const fmtTime = (s) => {
    if (!isFinite(s)) return "0:00";
    const m = Math.floor(s / 60), r = Math.floor(s % 60);
    return `${m}:${String(r).padStart(2, "0")}`;
  };
  const ago = (iso) => {
    const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 90) return "just now";
    if (s < 3600 * 1.5) return `${Math.round(s / 60)} min ago`;
    if (s < 86400 * 1.5) return `${Math.round(s / 3600)} h ago`;
    return `${Math.round(s / 86400)} days ago`;
  };

  async function getJSON(url) {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) throw new Error(`${url} ${res.status}`);
    return res.json();
  }

  function setAccent(color) {
    if (/^#[0-9a-f]{6}$/i.test(color || "")) document.documentElement.style.setProperty("--accent", color);
  }

  // ------------------------------------------------------------------ hero
  function statusNote(d) {
    switch (d.status) {
      case "sent": return "Live on YouTube Shorts.";
      case "scheduled": case "sending": return `Premieres on YouTube ${fmtWhen(d.post_at)}.`;
      case "error": return "Out on this site. The YouTube upload failed and is flagged for review.";
      case "released": return "Out now on this site.";
      case "dry-run": return "Rehearsal render. Not published.";
      default: return "Rendered and queued.";
    }
  }

  function showDrop(d, { autoplay = false } = {}) {
    state.current = d;
    setAccent(d.accent);
    $("drop-cover").src = "/" + d.cover;
    $("drop-cover").alt = `Cover art for ${d.title} by ANCHOR`;
    const latest = state.catalog.drops[0] && state.catalog.drops[0].id === d.id;
    $("drop-eyebrow").textContent = latest ? "Latest drop" : `Drop · ${fmtDate(d.date)}`;
    $("drop-title").textContent = d.title;
    const chips = $("drop-chips");
    chips.replaceChildren(
      el("li", {}, el("strong", { text: d.lane_name })),
      el("li", { text: `${d.bpm} BPM` }),
      el("li", { text: d.key }),
      el("li", { text: fmtDate(d.date) }),
    );
    $("drop-note").textContent = statusNote(d);
    const actions = $("drop-actions");
    actions.replaceChildren();
    const videoSrc = d.video_url || d.short_url;
    if (videoSrc) {
      const watch = el("button", { class: "btn primary", type: "button", text: "▶  Watch the Short" });
      watch.addEventListener("click", () => openVideo(d));
      actions.append(watch);
    }
    actions.append(el("a", { class: videoSrc ? "btn" : "btn primary", href: d.youtube_url || CHANNEL, rel: "noopener",
      target: "_blank", text: d.youtube_url ? "On YouTube ↗" : "YouTube channel ↗" }));
    if (d.audio_url) actions.append(el("a", { class: "btn", href: d.audio_url, text: "Download MP3" }));
    if (d.release_url) actions.append(el("a", { class: "btn", href: d.release_url, rel: "noopener", target: "_blank", text: "Release files ↗" }));

    renderSpecs(d);

    const player = $("player"), audio = $("audio");
    if (d.audio_url) {
      player.hidden = false;
      if (audio.getAttribute("src") !== d.audio_url) {
        audio.pause();
        audio.setAttribute("src", d.audio_url);
        $("seek").value = 0;
        $("t-now").textContent = "0:00";
        $("t-total").textContent = fmtTime(d.duration_s);
        setPlaying(false);
      }
      if (autoplay) audio.play().then(() => setPlaying(true)).catch(() => {});
    } else {
      player.hidden = true;
      audio.pause();
    }
    document.querySelectorAll(".card[data-id]").forEach((c) =>
      c.setAttribute("aria-current", c.dataset.id === d.id ? "true" : "false"));
  }

  function setBusy(on) {
    const b = $("play");
    b.classList.toggle("is-loading", on);
    b.setAttribute("aria-busy", on ? "true" : "false");
  }

  function setPlaying(on) {
    const b = $("play");
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.setAttribute("aria-label", on ? "Pause track" : "Play track");
    if (on) setBusy(false);
  }

  function wirePlayer() {
    const audio = $("audio"), seek = $("seek");
    $("play").addEventListener("click", () => {
      if (!audio.getAttribute("src")) return;
      if (audio.paused) {
        setBusy(true);                       // the file streams from the release: say so while it loads
        audio.play().then(() => setPlaying(true)).catch((err) => {
          setBusy(false);
          setPlaying(false);
          $("drop-note").textContent = `Could not start playback (${err.name}). Use Download MP3.`;
        });
      } else { audio.pause(); setPlaying(false); }
    });
    audio.addEventListener("waiting", () => setBusy(true));
    audio.addEventListener("playing", () => { setBusy(false); setPlaying(true); });
    audio.addEventListener("canplay", () => setBusy(false));
    audio.addEventListener("error", () => {
      setBusy(false);
      setPlaying(false);
      $("drop-note").textContent = "That track would not load. Use Download MP3 or Release files.";
    });
    audio.addEventListener("timeupdate", () => {
      if (audio.duration) seek.value = Math.round((audio.currentTime / audio.duration) * 1000);
      $("t-now").textContent = fmtTime(audio.currentTime);
    });
    audio.addEventListener("loadedmetadata", () => { $("t-total").textContent = fmtTime(audio.duration); });
    audio.addEventListener("ended", () => { setPlaying(false); seek.value = 0; });
    audio.addEventListener("pause", () => setPlaying(false));
    seek.addEventListener("input", () => {
      if (audio.duration) audio.currentTime = (seek.value / 1000) * audio.duration;
    });
  }

  // ---------------------------------------------------------------- grids
  function renderGrid() {
    const drops = state.catalog.drops || [];
    const grid = $("grid");
    grid.replaceChildren(...drops.map((d) => {
      const btn = el("button", { class: "card", type: "button", "data-id": d.id,
        "aria-label": `Play ${d.title}, ${d.bpm} BPM, ${fmtDate(d.date)}` },
        el("img", { src: "/" + d.cover, alt: "", loading: "lazy", width: "600", height: "600" }),
        el("span", { class: "t", text: d.title }),
        el("span", { class: "m", text: `${fmtDate(d.date)} · ${d.bpm} BPM · ${d.key}` }),
        d.status === "sent" ? el("span", { class: "badge", text: "On YouTube" }) :
          d.status === "scheduled" ? el("span", { class: "badge", text: "Premieres soon" }) : null,
      );
      if (/^#[0-9a-f]{6}$/i.test(d.accent || "")) btn.style.setProperty("--card-accent", d.accent);
      btn.addEventListener("click", () => {
        history.replaceState(null, "", "#" + d.id);
        showDrop(d, { autoplay: true });
        window.scrollTo({ top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      });
      return el("li", {}, btn);
    }));
    $("release-count").textContent = drops.length ? `${drops.length} automated release${drops.length > 1 ? "s" : ""} · newest first` : "";
    $("grid-empty").hidden = drops.length > 0;

    const legacy = state.catalog.legacy || [];
    $("legacy-h").hidden = legacy.length === 0;
    $("legacy").replaceChildren(...legacy.map((l) => el("li", {},
      el("a", { class: "card", href: l.youtube_url, rel: "noopener", target: "_blank",
        "aria-label": `${l.title} on YouTube` },
        legacyThumb(l.thumb),
        el("span", { class: "t", text: l.title }),
        el("span", { class: "m", text: `${fmtDate(l.date)} · YouTube` }),
      ))));
  }

  function legacyThumb(src) {
    const img = el("img", { src, alt: "", loading: "lazy", width: "600", height: "600" });
    img.addEventListener("error", () => {
      if (img.src.includes("/oar2.jpg")) img.src = img.src.replace("/oar2.jpg", "/hqdefault.jpg");
      else if (!img.src.endsWith("/assets/hero-default.jpg")) img.src = "/assets/hero-default.jpg";
    });
    return img;
  }



  // -------------------------------------------------------------- the specs
  function renderSpecs(d) {
    const box = $("drop-specs"), grid = $("spec-grid");
    if (!d || d.legacy) { box.hidden = true; return; }
    const q = d.qc || {}, eng = d.engine || {};
    const cap = (d.caption || "").split(",").map((s) => s.trim()).filter(Boolean);
    $("spec-summary").textContent = cap.length
      ? `${cap[0].replace(/^./, (c) => c.toUpperCase())} — ${cap.slice(1, 5).join(", ")}.`
      : `${d.lane_name} at ${d.bpm} BPM in ${d.key}.`;
    const rows = [
      ["Genre", d.genre_line],
      ["Style", d.style_line],
      ["Tempo", q.bpm_est ? `${q.bpm_est} BPM (measured)` : (d.bpm ? `${d.bpm} BPM` : null)],
      ["Key", d.key],
      ["Length", d.duration_s ? `${fmtTime(d.duration_s)} · Short ${d.short_s}s` : null],
      ["Master", q.lufs != null ? `${q.lufs} LUFS` : null],
      ["Cover", d.art_source === "cloudflare-flux" ? "AI (FLUX.1 schnell)" : "Procedural"],
      ["Made by", eng.name === "queue"
        ? `Your own track${eng.source_file ? ` · ${eng.source_file}` : ""}`
        : eng.name === "acestep_cpp"
        ? `ACE-Step 1.5 ${(eng.model || "").includes("sft") ? "sft" : (eng.model || "").includes("turbo") ? "turbo" : "DiT"}`
          + ` · ${eng.steps || 8} steps`
          + (eng.guidance > 1 ? ` · CFG ${eng.guidance}` : " · no CFG")
          + (eng.render_s ? ` · ${Math.round(eng.render_s / 60)} min CPU` : "")
        : (eng.name || "—")],
      ["Seed", d.seed != null ? String(d.seed) : null],
      ["Checks", (q.warnings && q.warnings.length) ? q.warnings.join("; ") : "No warnings"],
    ].filter(([, v]) => v);
    grid.replaceChildren();
    for (const [k, v] of rows) {
      const cell = el("div", { class: "spec" });
      cell.append(el("dt", { text: k }), el("dd", { text: v }));
      grid.append(cell);
    }
    box.hidden = false;
  }


  // ------------------------------------------------------------- catalogue
  // Clicking "Add to YouTube" opens a prefilled issue on the repo. A workflow picks it
  // up and records the song in queue/queue.json, best rating first; the next daily run
  // fetches the audio from Suno and releases it — the robot always prefers the queue.
  function queueUrl(s) {
    const body = [
      `Queue this song for the next ANCHOR drop.`,
      ``,
      `- Song: ${s.title}`,
      `- Suno: ${s.url}`,
      `- Id: \`${s.id}\``,
      `- Rated ${Number(s.rating).toFixed(1)} — ${s.verdict}`,
      s.group_size > 1 ? `- Note: ${s.group_size} near-identical versions exist; ${s.group_pick ? "this is the best of them" : "a higher rated version exists"}` : null,
      ``,
      `_Sent from the catalogue on anchor.anchit-tandon.com._`,
    ].filter((l) => l !== null).join("\n");
    return `${REPO}/issues/new?labels=youtube-queue`
      + `&title=${encodeURIComponent("Queue: " + s.title)}`
      + `&body=${encodeURIComponent(body)}`;
  }

  function ctaCell(s, isAlternate) {
    const cell = el("td", { class: "c-cta" });
    if (s.released_at) {
      cell.append(el("span", { class: "cta-state is-out", text: "Released" }),
                  el("span", { class: "chip chip-done", text: fmtDate(s.released_at) }));
      return cell;
    }
    if (s.queue_pos) {
      const first = s.queue_pos === 1;
      cell.append(el("span", { class: "cta-state" + (first ? " is-next" : ""),
                               text: first ? "Next out" : "In the queue" }),
                  el("span", { class: "chip " + (first ? "chip-next" : "chip-queued"),
                               text: first ? "goes out next run" : `#${s.queue_pos} in line` }));
      return cell;
    }
    cell.append(el("a", {
      class: "queue-btn" + (s.postable && !isAlternate ? "" : " ghost"),
      href: queueUrl(s), rel: "noopener", target: "_blank",
      title: s.postable
        ? `Queue "${s.title}" for the next drop`
        : `Not on format (${s.verdict}) — queue it anyway`,
    }, el("span", { class: "queue-ico", "aria-hidden": "true", text: "▶" }),
       el("span", { text: !s.postable ? "Queue anyway" : isAlternate ? "Post this instead" : "Add to YouTube" })));
    cell.append(el("span", { class: "chip " + (s.postable ? "chip-yes" : "chip-no"),
                             text: s.postable ? "Postable" : "Not yet" }));
    return cell;
  }

  // The whole working behind the rating and the yes/no, so a No can be argued with.
  function whyPanel(s) {
    const box = el("details", { class: "why" });
    const passed = (s.checks || []).filter((c) => c.ok).length;
    const total = (s.checks || []).length;
    box.append(el("summary", {},
      el("span", { class: "c-why", text: s.verdict }),
      el("span", { class: "why-more", text: total ? `why — ${passed}/${total} checks` : "why" })));

    const body = el("div", { class: "why-body" });
    if (s.factors && s.factors.length) {
      const bars = el("div", { class: "why-bars" });
      for (const f of s.factors) {
        const pct = Math.max(0, Math.min(100, (f.score / f.max) * 100));
        bars.append(el("div", { class: "why-bar" },
          el("span", { class: "wb-name", text: f.name }),
          el("span", { class: "wb-track" }, el("span", { class: "wb-fill", style: `width:${pct}%` })),
          el("span", { class: "wb-num", text: `${Number(f.score).toFixed(1)} / ${Number(f.max).toFixed(1)}` }),
          el("span", { class: "wb-note", text: f.note })));
      }
      body.append(bars);
    }
    if (total) {
      const list = el("ul", { class: "why-checks" });
      for (const c of s.checks) {
        list.append(el("li", { class: c.ok ? "ok" : "no" },
          el("span", { class: "wc-mark", "aria-hidden": "true", text: c.ok ? "✓" : "✕" }),
          el("span", {}, el("strong", { text: c.label }), el("span", { text: " — " + c.detail }))));
      }
      body.append(list);
      body.append(el("p", { class: "why-call",
        text: s.postable
          ? `All ${total} checks pass, so this one can go to YouTube.`
          : `${total - passed} check${total - passed > 1 ? "s" : ""} failed, so the robot will not post it on its own — the button queues it anyway if you disagree.` }));
    }
    box.append(body);
    return box;
  }

  // Takes of one idea are shown together, not scattered down a rating-sorted list, because
  // the only decision that matters here is "which one of these do I post".
  function families(songs) {
    const by = new Map();
    for (const s of songs) {
      const k = s.group || ("solo:" + s.id);
      if (!by.has(k)) by.set(k, []);
      by.get(k).push(s);
    }
    const out = [...by.values()].map((takes) => {
      takes.sort((a, b) => (b.group_pick === true) - (a.group_pick === true) || b.rating - a.rating);
      return { takes, pick: takes.find((t) => t.group_pick !== false) || takes[0] };
    });
    out.sort((a, b) => b.pick.rating - a.pick.rating);
    return out;
  }

  function famHeader(fam) {
    const n = fam.takes.length;
    const td = el("td", { class: "fam-head", colspan: "6" });
    const p = fam.pick, r = Number(p.rating).toFixed(1);
    const verdict = p.released_at ? `${p.title} (${r}) is already out — skip the other ${n - 1}`
      : p.queue_pos === 1 ? `${p.title} (${r}) is next out — skip the other ${n - 1}`
      : p.queue_pos ? `${p.title} (${r}) is queued #${p.queue_pos} — skip the other ${n - 1}`
      : `post ${p.title} (${r}) — skip the other ${n - 1}`;
    td.append(el("span", { class: "fam-title", text: p.title }),
              el("span", { class: "fam-count", text: `${n} takes of this idea` }),
              el("span", { class: "fam-verdict", text: verdict }));
    return el("tr", { class: "fam-row" }, td);
  }

  function takeRow(s, fam) {
    const multi = fam.takes.length > 1;
    const isPick = s === fam.pick;
    const tr = el("tr", { "data-song": s.id,
                          class: multi ? (isPick ? "in-fam is-pick" : "in-fam is-alt") : "" });
    const name = el("td", { class: "c-name" },
      el("a", { href: s.url, rel: "noopener", target: "_blank", text: s.title }));
    if (multi) {
      name.append(el("span", { class: "take-tag " + (isPick ? "tag-use" : "tag-alt"),
        text: isPick ? (s.released_at ? "POSTED" : s.queue_pos ? "QUEUED — POST THIS ONE" : "POST THIS ONE")
                     : "alternate — " + whySameIdea(s, fam.pick) }));
    }
    name.append(s.checks || s.factors ? whyPanel(s) : el("span", { class: "c-why", text: s.verdict }));
    tr.append(
      name,
      el("td", { class: "hide-sm c-tags", text: (s.tags || "—").slice(0, 90) }),
      el("td", { class: "c-num", text: fmtTime(s.duration_s) }),
      el("td", { class: "hide-sm c-num", text: String(s.plays ?? 0) }),
      el("td", { class: "c-rate", text: Number(s.rating).toFixed(1) }),
      ctaCell(s, multi && !isPick),
    );
    return tr;
  }

  // Say why this is an alternate in the terms it was actually grouped on. A take that
  // shares the title but was prompted differently is not "50% the same" - that number
  // would argue against the grouping the reader is looking at.
  function whySameIdea(s, pick) {
    const hit = (s.similar || []).find((x) => x.id === pick.id);
    if (hit && hit.score >= 0.55) return `${Math.round(hit.score * 100)}% the same, scores lower`;
    return "another take of the same title, scores lower";
  }

  // The channel posts one track a day, so the page owes the reader one answer before any
  // table: which single song is next. Everything below this card is how it was chosen.
  function renderNextUp(cat) {
    const box = $("next-up");
    if (!box) return;
    const up = cat.next_up;
    if (!up) { box.hidden = true; box.replaceChildren(); return; }
    box.hidden = false;
    const queued = up.source === "queue";
    const song = (cat.songs || []).find((s) => s.id === up.id);

    const head = el("p", { class: "nu-eyebrow" },
      el("span", { class: "nu-dot", "aria-hidden": "true" }),
      el("span", { text: queued ? "Next out" : "Nothing queued — post this next" }));

    const title = el("p", { class: "nu-title" },
      el("span", { class: "nu-name", text: up.title }),
      up.rating != null ? el("span", { class: "nu-rate", text: Number(up.rating).toFixed(1) }) : null);

    const why = el("p", { class: "nu-why", text:
      up.why + (up.waiting ? ` · ${up.waiting} more waiting behind it.` : "") });

    const acts = el("p", { class: "nu-acts" });
    if (!queued && song) {
      acts.append(el("a", { class: "queue-btn nu-btn", href: queueUrl(song), rel: "noopener",
                            target: "_blank" },
        el("span", { class: "queue-ico", "aria-hidden": "true", text: "\u25B6" }),
        el("span", { text: "Add to YouTube" })));
    }
    if (song) {
      acts.append(el("a", { class: "nu-link", href: song.url, rel: "noopener", target: "_blank",
                            text: "Hear it on Suno \u2197" }));
      acts.append(el("button", { type: "button", class: "nu-link nu-jump",
                                 text: "Show me the row" }));
    }
    box.replaceChildren(head, title, why, acts);
    const jump = box.querySelector(".nu-jump");
    if (jump) jump.addEventListener("click", () => jumpTo(up.id));
  }

  function jumpTo(id) {
    const row = document.querySelector(`tr[data-song="${id}"]`);
    if (!row) return;
    row.scrollIntoView({ block: "center", behavior: "smooth" });
    row.classList.remove("flash");
    void row.offsetWidth;                       // restart the animation on a repeat click
    row.classList.add("flash");
  }

  function renderCatalogue(filter) {
    const cat = state.catalog.catalogue;
    const box = $("catalogue");
    if (!cat || !(cat.songs || []).length) { box.hidden = true; return; }
    box.hidden = false;
    const fams = families(cat.songs);
    const distinct = fams.length;
    const dupes = fams.filter((f) => f.takes.length > 1);
    renderNextUp(cat);
    $("cat-count").textContent =
      `${cat.postable} of ${cat.total} postable · ${distinct} distinct`
      + (cat.queued ? ` · ${cat.queued} queued` : "");
    const when = cat.checked_at ? ago(cat.checked_at) : "just now";
    $("cat-sub").textContent =
      `Synced from suno.com/@${cat.handle} ${when} — every song rated against the channel's format`
      + (dupes.length
          ? `. ${dupes.length} idea${dupes.length > 1 ? "s have" : " has"} more than one take, grouped below: post the one marked POST THIS ONE and skip its alternates.`
          : ".");

    const rows = $("cat-rows");
    rows.replaceChildren();
    let shown = 0;
    for (const fam of fams) {
      const keep = fam.takes.filter((s) => {
        if (filter === "yes" && !s.postable) return false;
        if (filter === "no" && s.postable) return false;
        if (filter === "pick" && !(s.postable && s === fam.pick)) return false;
        if (filter === "twin" && fam.takes.length < 2) return false;
        return true;
      });
      if (!keep.length) continue;
      if (fam.takes.length > 1 && filter !== "pick") rows.append(famHeader(fam));
      for (const s of keep) { rows.append(takeRow(s, fam)); shown++; }
    }
    if (!shown) {
      rows.append(el("tr", {}, el("td", { class: "c-empty", colspan: "6",
        text: "Nothing in the catalogue matches that filter." })));
    }
  }

  function wireCatalogue() {
    const bar = $("cat-filters");
    if (!bar) return;
    bar.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      bar.querySelectorAll("button").forEach((o) => o.setAttribute("aria-pressed", o === b ? "true" : "false"));
      renderCatalogue(b.dataset.f);
    });
  }

  // ------------------------------------------------------------ the Short
  let lastFocus = null;

  function openVideo(d) {
    const src = d.video_url || d.short_url;
    if (!src) return;
    const box = $("video-box"), video = $("video"), audio = $("audio");
    audio.pause();
    setPlaying(false);
    video.poster = d.cover ? d.cover : "/assets/hero-default.jpg";
    if (video.getAttribute("src") !== src) video.setAttribute("src", src);
    $("video-cap").textContent = `${d.title} · ${d.bpm} BPM · ${d.key}`;
    lastFocus = document.activeElement;
    box.hidden = false;
    document.body.classList.add("locked");
    $("video-close").focus();
    video.play().catch(() => {});
  }

  function closeVideo() {
    const box = $("video-box"), video = $("video");
    if (box.hidden) return;
    video.pause();
    box.hidden = true;
    document.body.classList.remove("locked");
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  function wireVideo() {
    $("video-close").addEventListener("click", closeVideo);
    $("video-scrim").addEventListener("click", closeVideo);
    $("video").addEventListener("ended", closeVideo);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeVideo(); });
  }

  // ------------------------------------------------------------ countdown
  function nextSlot() {
    const s = state.status;
    const t = s.next_post_at ? new Date(s.next_post_at) : null;
    if (t && t.getTime() > Date.now()) return t;
    const [hh, mm] = ((s.schedule && s.schedule.post_time_utc) || "17:30").split(":").map(Number);
    const now = new Date();
    const slot = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), hh, mm));
    if (slot.getTime() <= now.getTime()) slot.setUTCDate(slot.getUTCDate() + 1);
    return slot;
  }

  function tick() {
    const target = nextSlot();
    const s = Math.max(0, Math.floor((target.getTime() - Date.now()) / 1000));
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    const clock = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
    $("countdown").textContent = d > 0 ? `${d}d ${clock}` : clock;
    $("next-when").textContent = fmtWhen(target.toISOString());
  }

  // --------------------------------------------------------- machine room
  function renderStatus() {
    const s = state.status || {}, last = s.last_run || {};
    const health = $("health");
    let cls = "", text = "Waiting for the first run";
    if (last.result === "ok" || last.result === "dry-run") {
      const fresh = last.finished_at && Date.now() - new Date(last.finished_at).getTime() < 30 * 3600 * 1000;
      cls = fresh ? "ok" : "bad";
      text = fresh ? "All systems running" : "Overdue: no run in the last 30 h";
    } else if (last.result === "failed") {
      cls = "bad";
      text = `Last run failed at ${last.stage || "unknown stage"}`;
    }
    health.className = "health " + cls;
    $("health-text").textContent = text;
    $("s-last").textContent = last.finished_at ? `${last.result === "failed" ? "Failed" : "OK"} · ${ago(last.finished_at)}` : "—";
    $("s-streak").textContent = s.streak ? `${s.streak} day${s.streak > 1 ? "s" : ""}` : "—";
    $("s-total").textContent = s.totals ? String(s.totals.drops) : String((state.catalog.drops || []).length);
    const eng = s.engine || {};
    $("s-render").textContent = eng.total_s ? `${Math.round(eng.total_s / 60)} min · free CPU` : "—";
  }

  async function init() {
    $("year").textContent = String(new Date().getFullYear());
    wirePlayer();
    try {
      const [catalog, status] = await Promise.all([
        getJSON("/data/catalog.json"),
        getJSON("/data/status.json").catch(() => ({})),
      ]);
      state.catalog = catalog || { drops: [] };
      state.status = status || {};
    } catch (err) {
      $("drop-note").textContent = "Couldn't load the release data. Refresh to try again.";
    }
    const artist = state.catalog.artist || {};
    if (artist.bio) $("bio").textContent = artist.bio;
    renderGrid();
    renderStatus();
    const drops = state.catalog.drops || [];
    const wanted = decodeURIComponent(location.hash.slice(1));
    const pick = drops.find((d) => d.id === wanted) || drops[0];
    if (pick) showDrop(pick);
    else {
      $("drop-title").textContent = "ANCHOR";
      $("drop-eyebrow").textContent = "Industrial hard techno";
      $("drop-note").textContent = "Daily drops start at the next slot.";
      $("drop-actions").replaceChildren(el("a", { class: "btn primary", href: CHANNEL, rel: "noopener", target: "_blank", text: "YouTube channel ↗" }));
    }
    wireVideo();
    wireCatalogue();
    renderCatalogue('all');
    tick();
    setInterval(tick, 1000);
    setInterval(renderStatus, 60 * 1000);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
