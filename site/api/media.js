// Serve a drop's release asset from our own origin, with a media content type.
//
// GitHub answers release downloads with `application/octet-stream` and
// `Content-Disposition: attachment`. Chrome sniffs the container and plays them anyway;
// Safari and iOS refuse outright - that is the NotSupportedError on the <audio> element
// and the dead play button on the Short. A plain Vercel rewrite does not help: GitHub
// replies 302 to a signed release-assets URL, so the browser follows it and lands back on
// octet-stream. This follows that redirect server side and streams the bytes back under a
// real audio/mpeg or video/mp4, which every browser will play.
//
// Range requests are passed through so seeking and scrubbing still work.

export const config = { runtime: "edge" };

const REPO = "https://github.com/Anchit-AI-Hustle/anchor-autopilot/releases/download";
const TAG = /^drop-\d{4}-\d{2}-\d{2}$/;
const FILE = /^[A-Za-z0-9][A-Za-z0-9._'-]*\.(mp3|mp4)$/;
const TYPES = { mp3: "audio/mpeg", mp4: "video/mp4" };

export default async function handler(req) {
  const { searchParams } = new URL(req.url);
  const tag = searchParams.get("tag") || "";
  const file = searchParams.get("file") || "";

  // Only ever a drop release asset from this repo: the destination is built from two
  // matched patterns, never from caller-supplied text, so this cannot be pointed elsewhere.
  if (!TAG.test(tag) || !FILE.test(file)) {
    return new Response("Not found", { status: 404 });
  }

  const range = req.headers.get("range");
  let upstream;
  try {
    upstream = await fetch(`${REPO}/${tag}/${encodeURIComponent(file)}`, {
      headers: range ? { Range: range } : {},
      redirect: "follow",
    });
  } catch {
    return new Response("Upstream unavailable", { status: 502 });
  }
  if (!upstream.ok && upstream.status !== 206) {
    return new Response("Not found", { status: upstream.status === 404 ? 404 : 502 });
  }

  const headers = new Headers({
    "Content-Type": TYPES[file.split(".").pop()],
    "Content-Disposition": "inline",
    "Accept-Ranges": "bytes",
    "Cache-Control": "public, max-age=86400",
    "X-Content-Type-Options": "nosniff",
  });
  for (const k of ["content-length", "content-range"]) {
    const v = upstream.headers.get(k);
    if (v) headers.set(k, v);
  }

  return new Response(req.method === "HEAD" ? null : upstream.body, {
    status: upstream.status,
    headers,
  });
}
