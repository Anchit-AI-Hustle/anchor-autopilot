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
               k === "rel" || k === "target" || k === "type" || k === "loading" || k === "width" || k === "height") {
        node.setAttribute(k, v);
      } else node[k] = v;
    }
    for (const kid of kids) if (kid) node.append(kid);
    return node;
  };

  const CHANNEL = "https://www.youtube.com/@AT_ANCHOR";
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
    actions.append(el("a", { class: "btn primary", href: d.youtube_url || CHANNEL, rel: "noopener", target: "_blank",
      text: d.youtube_url ? "Watch the Short ↗" : "YouTube channel ↗" }));
    if (d.audio_url) actions.append(el("a", { class: "btn", href: d.audio_url, text: "Download MP3" }));
    if (d.release_url) actions.append(el("a", { class: "btn", href: d.release_url, rel: "noopener", target: "_blank", text: "Release files ↗" }));

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

  function setPlaying(on) {
    const b = $("play");
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.setAttribute("aria-label", on ? "Pause track" : "Play track");
  }

  function wirePlayer() {
    const audio = $("audio"), seek = $("seek");
    $("play").addEventListener("click", () => {
      if (audio.paused) audio.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
      else { audio.pause(); setPlaying(false); }
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
    tick();
    setInterval(tick, 1000);
    setInterval(renderStatus, 60 * 1000);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
