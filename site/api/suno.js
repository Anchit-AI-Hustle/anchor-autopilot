// The Sync with Suno page's live view of the channel's Suno songs.
//
// GET /api/suno            every public song on suno.com/@anchor_at, newest first
// GET /api/suno?song=<id>  one song by id (an unlisted song opens for anyone with its link)
//
// It reads Suno's public profile API, the same one suno.com/@anchor_at reads, with no login
// and no key. The handle is fixed and the song id must be a UUID, so this cannot be pointed
// at anything else, and a song from another account is refused.

export const config = { runtime: "edge" };

const HANDLE = "anchor_at";
const API = "https://studio-api.prod.suno.com/api";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function clip(o) {
  if (!o || !o.id || o.status !== "complete") return null;
  const m = o.metadata || {};
  const media = o.media_urls || [];
  const m4a = media.find((u) => (u.url || "").endsWith(".m4a"));
  return {
    id: o.id,
    title: (o.title || "Untitled").trim(),
    duration_s: Math.round(Number(m.duration || o.duration || 0) * 10) / 10,
    tags: (m.tags || "").trim(),
    lyrics: (m.prompt || "").trim(),
    model: o.major_model_version || o.model_name || "",
    plays: Number(o.play_count || 0),
    upvotes: Number(o.upvote_count || 0),
    created_at: o.created_at || "",
    image: o.image_large_url || o.image_url || "",
    // the API's own audio_url is ".../api/forbidden" without a login; the m4a in media_urls plays
    audio_url: (m4a && m4a.url) || (/forbidden/.test(o.audio_url || "forbidden") ? "" : o.audio_url),
    video_url: o.video_url || "",
    url: `https://suno.com/song/${o.id}`,
    is_public: o.is_public !== false,
  };
}

async function get(url) {
  const r = await fetch(url, { headers: { Accept: "application/json", "User-Agent": "anchor-autopilot/1.0" } });
  if (!r.ok) throw new Error(`suno ${r.status}`);
  return r.json();
}

function reply(body, status = 200, cache = "public, max-age=60") {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": cache, "X-Content-Type-Options": "nosniff" },
  });
}

export default async function handler(req) {
  const song = (new URL(req.url).searchParams.get("song") || "").toLowerCase();
  try {
    if (song) {
      if (!UUID.test(song)) return reply({ error: "not a Suno song id" }, 400, "no-store");
      const o = await get(`${API}/clip/${song}`);
      if ((o.handle || "").toLowerCase() !== HANDLE) return reply({ error: `not a song of @${HANDLE}` }, 403, "no-store");
      const c = clip(o);
      return c ? reply({ song: c }) : reply({ error: "that song is not finished on Suno" }, 404, "no-store");
    }
    const songs = [];
    const seen = new Set();
    for (let page = 1; page <= 40; page++) {
      const d = await get(`${API}/profiles/${HANDLE}?page=${page}&clips_sort_by=created_at&playlists_sort_by=created_at`);
      const list = d.clips || [];
      for (const o of list) {
        const c = clip(o);
        if (c && !seen.has(c.id)) { seen.add(c.id); songs.push(c); }
      }
      if (!list.length || seen.size >= Number(d.num_total_clips || 0)) break;
    }
    return reply({ handle: HANDLE, checked_at: new Date().toISOString(), total: songs.length, songs });
  } catch (e) {
    return reply({ error: "Suno did not answer, showing the last sync" }, 502, "no-store");
  }
}
