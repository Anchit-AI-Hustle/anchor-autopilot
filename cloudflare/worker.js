// ANCHOR on Cloudflare: the same site as Vercel, served on its own (Anchit, 2026-11-09: "push and
// deploy on github and vercel and cloudflare too"; each host must be able to serve alone, no proxy
// between them). Static files come from site/ (the Worker's assets); the two functions are the
// very same files Vercel runs (site/api/*.js are plain Web-standard handlers), and the headers
// mirror site/vercel.json.
import media from "../site/api/media.js";
import suno from "../site/api/suno.js";

const SECURITY = {
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "X-Frame-Options": "SAMEORIGIN",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
};

function withHeaders(res, path) {
  const h = new Headers(res.headers);
  for (const [k, v] of Object.entries(SECURITY)) h.set(k, v);
  if (path.startsWith("/data/")) h.set("Cache-Control", "public, max-age=0, must-revalidate");
  if (path === "/ops" || path.startsWith("/ops/") || path === "/suno" || path.startsWith("/suno/")) {
    h.set("X-Robots-Tag", "noindex, nofollow, noarchive");
    h.set("Cache-Control", "public, max-age=0, must-revalidate");
  }
  if (path.startsWith("/assets/fonts/")) h.set("Cache-Control", "public, max-age=31536000, immutable");
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const path = url.pathname;
    let res;
    const m = path.match(/^\/media\/([^/]+)\/([^/]+)$/);
    if (m) {
      const u = new URL("/api/media", url);
      u.searchParams.set("tag", decodeURIComponent(m[1]));
      u.searchParams.set("file", decodeURIComponent(m[2]));
      res = await media(new Request(u, req));
    } else if (path === "/api/media") {
      res = await media(req);
    } else if (path === "/api/suno") {
      res = await suno(req);
    } else {
      res = await env.ASSETS.fetch(req);
    }
    return withHeaders(res, path);
  },
};
