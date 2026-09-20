"""YouTube Short renderer (1080x1920, 30 fps, H.264 + AAC) built from one ffmpeg graph.

Each visual family gets its own audio-reactive layer (spectrum bars, waveform,
spectrogram or vectorscope), its own colours and a tempo-locked cover pulse, so
consecutive drops never share one template.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from .config import FONTS, Family
from .util import media_summary, run

W, H, FPS = 1080, 1920, 30
COVER = 900
COVER_Y = 330
VIZ_W, VIZ_H, VIZ_Y = 1080, 250, 1525   # between the meta line (1450) and the progress bar (1812)
SCOPE = 1180


def _ff(c: str) -> str:
    return "0x" + c.lstrip("#")


def _viz(fam: Family) -> tuple[str, int, int]:
    """Audio-reactive layer: (filter, width, height). Black is keyed out afterwards."""
    a, b = _ff(fam.accent), _ff(fam.accent2)
    if fam.viz == "bars":
        return (f"showfreqs=s={VIZ_W}x{VIZ_H}:mode=bar:ascale=log:fscale=log:win_size=2048:"
                f"averaging=2:colors={a}|{b}", VIZ_W, VIZ_H)
    if fam.viz == "line":
        return (f"showfreqs=s={VIZ_W}x{VIZ_H}:mode=line:ascale=log:fscale=log:win_size=2048:"
                f"averaging=3:colors={a}|{b}", VIZ_W, VIZ_H)
    if fam.viz == "wave":
        return f"showwaves=s={VIZ_W}x{VIZ_H}:mode=cline:rate={FPS}:scale=sqrt:draw=full:colors={a}", VIZ_W, VIZ_H
    # scope: a Lissajous halo drawn behind the cover
    r, g, bl = (int(fam.accent[i:i + 2], 16) for i in (1, 3, 5))
    return (f"avectorscope=s={SCOPE}x{SCOPE}:mode=lissajous_xy:draw=line:scale=sqrt:zoom=1.25:rate={FPS}:"
            f"rc={r}:gc={g}:bc={bl}:ac=255:rf=18:gf=18:bf=18:af=18", SCOPE, SCOPE)


def background(cover: Path, out: Path) -> None:
    """Static blurred, darkened, vignetted backdrop (computed once, not per frame)."""
    img = Image.open(cover).convert("RGB").resize((H, H), Image.LANCZOS)
    left = (H - W) // 2
    img = img.crop((left, 0, left + W, H)).filter(ImageFilter.GaussianBlur(38))
    img = ImageEnhance.Brightness(img).enhance(0.62)
    img = ImageEnhance.Color(img).enhance(1.3)
    img = ImageEnhance.Contrast(img).enhance(1.08)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    mask = np.clip(1.15 - 0.55 * d ** 2, 0.25, 1.0)[..., None]
    arr = np.asarray(img, dtype=np.float32) * mask
    Image.fromarray(arr.clip(0, 255).astype(np.uint8)).save(out, quality=92)


PULSE_AMP = 30      # px the cover grows on each beat
PULSE_DECAY = 3.2   # decay per beat: visible for ~3 frames at 30 fps, gone before the next beat


def pulse_curve(t: float, bpm: float, beat_offset: float = 0.0) -> float:
    """0..1 cover pulse: 1 exactly on the beat, decaying to ~0 before the next one."""
    beat = 60.0 / float(bpm)
    return math.exp(-PULSE_DECAY * ((t - beat_offset) % beat) / beat)


def pulse_expr(bpm: float, beat_offset: float = 0.0) -> str:
    """The same curve as an ffmpeg expression (t + beat keeps the modulo positive)."""
    beat = 60.0 / float(bpm)
    return (f"{COVER}+{PULSE_AMP}*exp(-{PULSE_DECAY}*"
            f"mod(t+{beat:.5f}-{beat_offset:.4f},{beat:.5f})/{beat:.5f})")


def build_graph(fam: Family, bpm: int, duration: float, texts: dict[str, Path],
                beat_offset: float = 0.0) -> str:
    anton = FONTS / "Anton.ttf"
    mono = FONTS / "JetBrainsMono-Bold.ttf"
    viz, vw, vh = _viz(fam)
    beat = 60.0 / bpm
    pulse = pulse_expr(bpm, beat_offset)
    title_y = COVER_Y + COVER + 50
    cover_mid = COVER_Y + COVER // 2
    if fam.viz == "scope":   # halo behind the cover
        layers = [f"[bg][viz]overlay=x={(W - vw) // 2}:y={cover_mid - vh // 2}:shortest=1[s0]",
                  f"[s0][cov]overlay=x='(W-w)/2':y='{COVER_Y}-(h-{COVER})/2':eval=frame[s2]"]
    else:                    # spectrum/wave band under the title
        layers = [f"[bg][cov]overlay=x='(W-w)/2':y='{COVER_Y}-(h-{COVER})/2':eval=frame[s1]",
                  f"[s1][viz]overlay=x={(W - vw) // 2}:y={VIZ_Y}:shortest=1[s2]"]
    return ";".join([
        "[0:v]format=yuv420p[bg]",
        # format must come BEFORE scale: a trailing format filter pins the link size and
        # freezes the per-frame resize, which is what killed the pulse
        f"[1:v]format=rgba,scale=w='{pulse}':h='{pulse}':eval=frame,setsar=1[cov]",
        "[2:a]asplit=2[aout][aviz]",
        f"[aviz]{viz},format=rgba,colorkey=0x000000:0.22:0.15[viz]",
        *layers,
        f"color=c={_ff(fam.accent)}:s=900x6:r={FPS}[barfill]",
        f"color=c=0x2a2a2a:s=900x6:r={FPS}[bartrack]",
        f"[bartrack][barfill]overlay=x='-900+900*t/{duration:.3f}':y=0:shortest=1[bar]",
        "[s2][bar]overlay=x=90:y=1812:shortest=1[s3]",
        "[s3]"
        f"drawtext=fontfile='{mono}':textfile='{texts['artist']}':fontsize=44:fontcolor=0xF2F2F2:"
        f"x=(w-text_w)/2:y=150,"
        f"drawtext=fontfile='{anton}':textfile='{texts['title']}':fontsize=118:fontcolor={_ff(fam.accent)}:"
        f"shadowcolor=0x000000@0.7:shadowx=4:shadowy=6:x=(w-text_w)/2:y={title_y},"
        f"drawtext=fontfile='{mono}':textfile='{texts['meta']}':fontsize=34:fontcolor=0xE6E6E6:"
        f"x=(w-text_w)/2:y={title_y + 170},"
        f"drawtext=fontfile='{mono}':textfile='{texts['footer']}':fontsize=28:fontcolor=0xBDBDBD:"
        f"x=(w-text_w)/2:y=1848,"
        "format=yuv420p[vout]",
    ])


def render_short(cover_1080: Path, audio: Path, out: Path, fam: Family, brief: dict,
                 artist: str, handle: str, workdir: Path, beat_offset: float = 0.0) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    duration = media_summary(audio)["duration"]
    texts = {
        "artist": "  ".join(artist.upper()),
        "title": brief["title"].upper(),
        # No musical key on screen: it tells a listener nothing and eats the meta line.
        "meta": f"{brief['lane_name'].upper()}  ·  {brief['bpm']} BPM",
        "footer": f"{handle}  ·  NEW TRACK EVERY DAY",
    }
    paths = {}
    for key, value in texts.items():
        p = workdir / f"text_{key}.txt"
        p.write_text(value, encoding="utf-8")
        paths[key] = p
    graph = build_graph(fam, int(brief["bpm"]), duration, paths, beat_offset)
    bg = workdir / "background.jpg"
    background(cover_1080, bg)
    run(["ffmpeg", "-y", "-hide_banner", "-v", "error",
         "-loop", "1", "-framerate", str(FPS), "-i", bg,
         "-loop", "1", "-framerate", str(FPS), "-i", cover_1080,
         "-i", audio,
         "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
         "-t", f"{duration:.3f}", "-r", str(FPS),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-maxrate", "8M", "-bufsize", "16M",
         "-profile:v", "high",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", out], timeout=1800)
    info = media_summary(out)
    problems = []
    if (info.get("width"), info.get("height")) != (W, H):
        problems.append(f"size {info.get('width')}x{info.get('height')}")
    if abs(info["duration"] - duration) > 0.5:
        problems.append(f"duration {info['duration']:.2f}s vs audio {duration:.2f}s")
    if info.get("vcodec") != "h264" or info.get("acodec") != "aac":
        problems.append(f"codecs {info.get('vcodec')}/{info.get('acodec')}")
    if problems:
        raise RuntimeError("rendered Short failed checks: " + "; ".join(problems))
    return info


def poster_frame(video: Path, out: Path, at: float = 3.0) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", video, "-frames:v", "1", "-q:v", "3", out],
        quiet=True)


# ------------------------------------------------------------- full-length videos
# The full track is a still frame over the audio, encoded at 2 fps: a 3-minute video comes
# out at 4-5 MB and renders in seconds, and because every frame is the same, YouTube's own
# thumbnail IS the composed frame - so the frame is designed as a thumbnail first.
#
# The 16:9 frame fills itself: the art bleeds edge to edge with the title and genre phrase set
# over it. The catalogue's earlier full-length frames put a small square cover in the middle
# of a blurred field; vidIQ scored one at 27/100, and "too much empty space" alone cost 40
# points of that. Nothing here leaves the frame empty.

def frame_169(cover: Path, brief: dict, lane_phrase: str, artist: str, out: Path) -> Path:
    """The 16:9 frame and the thumbnail. Set for a phone: YouTube shows it at about 170 px
    tall, so the title fills two thirds of the width in one or two lines and the genre line is
    big enough to read at that size. Nothing smaller than 90 px goes on it."""
    W2, H2 = 1920, 1080
    cov = Image.open(cover).convert("RGB")
    s = max(W2 / cov.width, H2 / cov.height)
    bg = cov.resize((int(cov.width * s) + 1, int(cov.height * s) + 1), Image.LANCZOS)
    x, y = (bg.width - W2) // 2, (bg.height - H2) // 2
    bg = bg.crop((x, y, x + W2, y + H2))
    from PIL import ImageDraw, ImageFont
    scrim = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    for i in range(1300):                                          # left-to-right fade: solid under the type, the art clear on the right
        a = int(190 * max(0.0, 1 - i / 1300) ** 1.4)
        sd.line([(i, 0), (i, H2)], fill=(9, 8, 8, a))
    bg = Image.alpha_composite(bg.convert("RGBA"), scrim).convert("RGB")
    d = ImageDraw.Draw(bg, "RGBA")

    def font(size):
        return ImageFont.truetype(str(FONTS / "Anton.ttf"), size)

    # title: one line if it fits at 300, otherwise two lines split at the widest gap
    title = brief["title"].upper()
    words = title.split()
    lines, size = [title], 300
    while d.textlength(lines[0], font=font(size)) > 1240 and size > 200:
        size -= 10
    if d.textlength(title, font=font(size)) > 1240 and len(words) > 1:
        best = min(range(1, len(words)), key=lambda k: abs(len(" ".join(words[:k])) - len(" ".join(words[k:]))))
        lines, size = [" ".join(words[:best]), " ".join(words[best:])], 250
        while max(d.textlength(l, font=font(size)) for l in lines) > 1240 and size > 150:
            size -= 10
    f = font(size)
    line_h = int(size * 0.98)
    block = len(lines) * line_h + 40 + int(size * 0.38)
    top = (H2 - block) // 2 - 20
    for i, line in enumerate(lines):
        yy = top + i * line_h
        d.text((104, yy + 8), line, font=f, fill=(0, 0, 0, 170))     # hard shadow: reads on any art
        d.text((96, yy), line, font=f, fill=(246, 246, 244))
    sub = f"{lane_phrase.upper()}  ·  {int(brief['bpm'])} BPM" if brief.get("bpm") else lane_phrase.upper()
    fs = font(max(90, int(size * 0.38)))
    while d.textlength(sub, font=fs) > 1240 and fs.size > 80:
        fs = font(fs.size - 6)
    yy = top + len(lines) * line_h + 40
    d.text((104, yy + 6), sub, font=fs, fill=(0, 0, 0, 170))
    d.text((96, yy), sub, font=fs, fill=(226, 84, 40))
    bg.save(out, quality=93)
    return out


def frame_916(cover: Path, out: Path) -> Path:
    W2, H2 = 1080, 1920
    cov = Image.open(cover).convert("RGB")
    s = max(W2 / cov.width, H2 / cov.height)
    bg = cov.resize((int(cov.width * s) + 1, int(cov.height * s) + 1), Image.LANCZOS)
    x, y = (bg.width - W2) // 2, (bg.height - H2) // 2
    bg = bg.crop((x, y, x + W2, y + H2)).filter(ImageFilter.GaussianBlur(30))
    bg = ImageEnhance.Brightness(bg).enhance(0.45)
    fg = cov.resize((1000, 1000), Image.LANCZOS)
    bg.paste(fg, (40, (H2 - 1000) // 2))
    bg.save(out, quality=93)
    return out


def render_still(frame: Path, audio: Path, out: Path, crf: int = 23) -> dict:
    duration = media_summary(audio)["duration"]
    run(["ffmpeg", "-y", "-hide_banner", "-v", "error", "-loop", "1", "-framerate", "2", "-i", frame,
         "-i", audio, "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage", "-crf", str(crf),
         "-r", "2", "-g", "60", "-pix_fmt", "yuv420p", "-shortest",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out], timeout=900)
    info = media_summary(out)
    if abs(info["duration"] - duration) > 1.5:
        raise RuntimeError(f"full render truncated: {info['duration']:.1f}s vs audio {duration:.1f}s")
    return info


def render_motion(frame: Path, audio: Path, out: Path, accent: str, crf: int = 23) -> dict:
    """The 16:9 frame with the record moving on it: a waveform in the family accent along the
    bottom and a thin progress bar. A still frame lost most viewers inside thirty seconds
    (channel analytics, Sept 2026: 0:30 average view from impressions); something on screen
    that follows the kick keeps the listener with the track."""
    duration = media_summary(audio)["duration"]
    r, g, b = (int(accent.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    graph = ";".join([
        "[0:v]format=yuv420p[bg]",
        "[1:a]asplit=2[aout][aviz]",
        # drawn white and tinted afterwards: showwaves' cline mode mangles a coloured line
        "[aviz]showwaves=s=1920x220:mode=cline:rate=30:colors=white|white:scale=sqrt,format=rgba,"
        f"colorkey=0x000000:0.2:0.1,colorchannelmixer=rr={r:.3f}:gg={g:.3f}:bb={b:.3f}:aa=0.8[wave]",
        "[bg][wave]overlay=x=0:y=852:shortest=1[s1]",
        f"color=c={_ff(accent)}:s=1920x8:r=30[fill]",
        "color=c=0x1a1a1a:s=1920x8:r=30[track]",
        f"[track][fill]overlay=x='-1920+1920*t/{duration:.3f}':y=0:shortest=1[bar]",
        "[s1][bar]overlay=x=0:y=1072:shortest=1,format=yuv420p[vout]",
    ])
    run(["ffmpeg", "-y", "-hide_banner", "-v", "error", "-loop", "1", "-framerate", "30", "-i", frame,
         "-i", audio, "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
         "-t", f"{duration:.3f}", "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
         "-maxrate", "4M", "-bufsize", "8M", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out], timeout=1800)
    info = media_summary(out)
    if abs(info["duration"] - duration) > 1.5:
        raise RuntimeError(f"full render truncated: {info['duration']:.1f}s vs audio {duration:.1f}s")
    return info


def render_full(art_raw: Path, cover: Path, audio: Path, out_dir: Path, base: str, brief: dict,
                lane_phrase: str, artist: str, accent: str | None = None) -> dict:
    """The 16:9 YouTube video and the 9:16 Reel, both verified against the audio length.

    ``art_raw`` is the artwork before the cover typography: the 16:9 frame sets its own title
    so nothing half-cropped shows through. ``cover`` is the finished square for the Reel.
    With ``accent`` the 16:9 moves (waveform + progress); without it, a still at 2 fps.
    """
    f169 = frame_169(art_raw if art_raw.exists() else cover, brief, lane_phrase, artist, out_dir / "frame-169.jpg")
    f916 = frame_916(cover, out_dir / "frame-916.jpg")
    v169 = out_dir / f"{base}-full-169.mp4"
    v916 = out_dir / f"{base}-full-916.mp4"
    i169 = render_motion(f169, audio, v169, accent, crf=23) if accent else render_still(f169, audio, v169, crf=23)
    i916 = render_still(f916, audio, v916, crf=24)
    return {"full_169": {"file": v169.name, **i169}, "full_916": {"file": v916.name, **i916},
            "thumbnail": f169.name}
