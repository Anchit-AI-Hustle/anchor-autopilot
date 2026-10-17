"""One motion-graphics video per song, built from scenes that follow the music.

``render_scene_video`` takes the song's sections (``structure.sections``: intro, build, groove,
drop, breakdown, outro, every cut on a bar line) and gives each its own look, all driven by the
same beat grid so the picture hits on the kick:

* card: the artwork as a card pulsing over its own blurred glow (intros, outros)
* mirror: the artwork rotating in a four-way mirror (builds speed up and strobe, some drops)
* corridor: a 3D fly-through, floor and ceiling of artwork scrolling to the horizon (drops, grooves)
* glitch: zoom punch with the colour channels splitting on every beat (drops, grooves)
* spectrum: a slow blurred glow, a turning disc and a big spectrum (breakdowns)

Every scene starts with a white flash on the bar line and carries a section tag; the song title
opens the video. Where timed lyrics exist they run as a caption over every scene. It is one
ffmpeg graph and one encode: scenes are trimmed to whole frames and joined, so cuts and beat
pulses cannot drift against the audio however many scenes there are.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import fx, lyrics as lyr, viz
from .audio import decode
from .util import log
from .video import AAC_CLEAN, _ff, beat_pulse_expr, beat_step_expr, media_summary, scanlines

FPS = 30
LINGER = 1.2              # seconds a sung line stays up after its last word
# which looks each kind of section may take, in order of preference
LOOKS = {
    "intro": ["card", "glitch"],
    "outro": ["card", "glitch"],
    "build": ["mirror", "glitch"],
    "groove": ["glitch", "corridor", "mirror"],
    "drop": ["corridor", "glitch", "mirror"],
    "breakdown": ["spectrum"],
}


def assign_looks(secs: list[dict]) -> list[str]:
    """A look for every scene: the least-used one its kind allows that differs from the scene before,
    so neighbouring scenes never repeat and a long drop cycles through everything it can."""
    used: dict[str, int] = {}
    out: list[str] = []
    for sc in secs:
        cands = LOOKS.get(sc["kind"]) or ["glitch"]
        order = sorted(range(len(cands)), key=lambda j: (used.get(cands[j], 0), j))
        pick = next((cands[j] for j in order if not out or cands[j] != out[-1]), cands[order[0]])
        out.append(pick)
        used[pick] = used.get(pick, 0) + 1
    return out


def square(src: Path, dst: Path, size: int = 1080) -> Path:
    """The artwork as a square texture for the scenes: centre crop, resized."""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    side = min(im.size)
    left, top = (im.width - side) // 2, (im.height - side) // 2
    im.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS).save(dst, quality=93)
    return dst


def song_sections(audio: Path, bpm: float, offset: float) -> list[dict]:
    from . import structure
    return structure.sections(decode(audio), bpm, offset)


def frames(sections: list[dict], duration: float) -> list[tuple[int, int]]:
    """(first, last+1) frame of every scene, contiguous and covering the whole song."""
    total = round(duration * FPS)
    cuts = [round(s["start"] * FPS) for s in sections] + [total]
    cuts[0] = 0
    out = []
    for a, b in zip(cuts, cuts[1:]):
        out.append((a, max(b, a + 1)))
    out[-1] = (out[-1][0], total)
    return out


def _scene(look: str, i: int, W: int, H: int, sc: dict, n0: int, n1: int, bpm: float, off: float,
           first: bool) -> list[str]:
    """Filter lines from the trimmed artwork ``[t{i}]`` to ``[o{i}]`` for one scene."""
    t0 = n0 / FPS
    dur = (n1 - n0) / FPS
    P = beat_pulse_expr(bpm, off, 1.0, t0)
    Q = max(W, H)
    var = i
    beat = 60.0 / bpm
    S = beat_step_expr(bpm, off, t0)          # beats so far, each one a surge that lands on the kick
    hue = ((var * 37) % 24) - 12             # a small swing: the scenes stay in the cover's own colours
    sign = 1 if var % 2 == 0 else -1
    s = f"[t{i}]"
    L: list[str] = []
    if look == "card":
        C = int((min(W, H * 0.9)) * (0.62 if W > H else 0.8))
        L += [f"{s}split=2[ba{i}][ca{i}]",
              f"[ba{i}]scale={Q}:{Q},crop={W}:{H},gblur=sigma=40,"
              f"eq=brightness='-0.2+0.12*({P})':saturation=1.3:eval=frame[bg{i}]",
              f"[ca{i}]scale=w='{C}*(1+0.09*({P}))':h=-2:eval=frame[cd{i}]",
              f"[bg{i}][cd{i}]overlay=x='({W}-w)/2':y='({H}-h)/2-{int(H * 0.07)}':format=auto:shortest=1[x{i}]"]
    elif look == "mirror":
        build = sc["kind"] == "build"
        ang = (f"{sign}*({0.28 * beat:.5f}*({S})+0.06*({P}))" if not build
               else f"{sign}*(t*0.3+2.2*t*t/{dur:.3f}+0.2*({P}))")
        strobe = (f",eq=brightness='0.28*gt(mod(t/{beat:.5f}*(1+3*t/{dur:.3f}),1),0.82)':eval=frame" if build else "")
        L += [f"{s}scale=1620:1620,rotate=a='{ang}':ow=1620:oh=1620:c=black,crop=1080:1080,"
              f"scale={W // 2}:{H // 2}:force_original_aspect_ratio=increase,crop={W // 2}:{H // 2},split=2[qa{i}][qb{i}]",
              f"[qb{i}]hflip[qc{i}]", f"[qa{i}][qc{i}]hstack[tp{i}]",
              f"[tp{i}]split=2[ta{i}][tb{i}]", f"[tb{i}]vflip[bt{i}]",
              f"[ta{i}][bt{i}]vstack,scale=w='{W}*(1+0.08*({P}))':h=-2:eval=frame,crop={W}:{H},"
              f"hue=h='{hue}+10*sin((t+{t0:.3f})*0.9)':s=1.3,eq=brightness='0.10*({P})':eval=frame{strobe}[x{i}]"]
    elif look == "corridor":
        spd = 420 * (1 if var % 4 != 3 else -1)
        L += [f"{s}scale=1080:1080,split=4[ca{i}][cb{i}][cc{i}][cd{i}]",
              f"[cb{i}]vflip[cf{i}]",
              f"[ca{i}][cf{i}][cc{i}]vstack=inputs=3[st{i}]",
              f"[st{i}]crop=1080:1080:0:'mod({spd * beat:.3f}*({S})+1080*10,2160)',scale={W}:{H},"
              f"perspective=x0={W * 0.43:.0f}:y0={H * 0.5:.0f}:x1={W * 0.57:.0f}:y1={H * 0.5:.0f}:"
              f"x2=-{W * 1.0:.0f}:y2={H}:x3={W * 2.0:.0f}:y3={H}:sense=destination:eval=init,format=gbrp,split=2[fa{i}][fb{i}]",
              f"[fb{i}]vflip[fc{i}]", f"[fa{i}][fc{i}]blend=all_mode=lighten[fl{i}]",
              f"[cd{i}]scale={Q}:{Q},crop={W}:{H},gblur=sigma=30,eq=brightness=-0.35,format=gbrp[sk{i}]",
              f"[sk{i}][fl{i}]blend=all_mode=lighten,format=yuv420p,"
              f"eq=brightness='0.16*({P})':contrast=1.12:saturation=1.25:eval=frame,hue=h={hue}[x{i}]"]
    elif look == "glitch":
        L += [f"{s}scale=w='{Q}*(1.0+0.14*({P}))':h=-2:eval=frame,crop={W}:{H},"
              f"hue=h={hue}:s=1.05,split=3[ga{i}][gb{i}][gc{i}]",
              f"[ga{i}]colorchannelmixer=rr=1:gg=0:bb=0[gr{i}]",
              f"[gb{i}]colorchannelmixer=rr=0:gg=1:bb=0[gg{i}]",
              f"[gc{i}]colorchannelmixer=rr=0:gg=0:bb=1[gbl{i}]",
              f"color=c=black:s={W}x{H}:r={FPS}[k1{i}]", f"color=c=black:s={W}x{H}:r={FPS}[k2{i}]",
              f"color=c=black:s={W}x{H}:r={FPS}[k3{i}]",
              f"[k1{i}][gr{i}]overlay=x='{sign * 18}*({P})':y=0:shortest=1[r2{i}]",
              f"[k2{i}][gg{i}]overlay=x=0:y=0:shortest=1[g2{i}]",
              f"[k3{i}][gbl{i}]overlay=x='{-sign * 18}*({P})':y=0:shortest=1[b2{i}]",
              f"[r2{i}]format=gbrp[r3{i}]", f"[g2{i}]format=gbrp[g3{i}]", f"[b2{i}]format=gbrp[b3{i}]",
              f"[r3{i}][g3{i}]blend=all_mode=addition[rg{i}]",
              f"[rg{i}][b3{i}]blend=all_mode=addition,format=yuv420p,noise=alls=10:allf=t,"
              f"eq=brightness='0.08*({P})':eval=frame[x{i}]"]
    else:                                                     # spectrum (breakdown)
        C = int(min(W, H) * (0.5 if W > H else 0.62))
        L += [f"{s}split=2[ba{i}][ca{i}]",
              f"[ba{i}]scale=w='{Q}*(1.05+0.004*t)':h=-2:eval=frame,crop={W}:{H},gblur=sigma=28,"
              f"eq=brightness=-0.28:saturation=1.2,hue=h={hue}[bg{i}]",
              f"[ca{i}]scale={C}:{C},format=rgba,rotate=a='{0.35 * beat:.5f}*({S})*{sign}':ow={int(C * 1.42)}:oh={int(C * 1.42)}:"
              f"c=0x00000000[dk{i}]",
              f"[bg{i}][dk{i}]overlay=x='({W}-w)/2':y='({H}-h)/2-{int(H * 0.04)}':format=auto:shortest=1[x{i}]"]
    flash = "" if first else f",eq=brightness='0.7*exp(-14*t)':eval=frame"
    L[-1] = L[-1].rsplit("[x", 1)[0] + f"{flash}[y{i}]"
    count = n1 - n0
    L.append(f"[y{i}]setsar=1,format=yuv420p,fps={FPS},tpad=stop_mode=clone:stop=3,trim=end_frame={count},"
             f"setpts=PTS-STARTPTS[o{i}]")
    return L


def write_ass(path: Path, accent: str, W: int, H: int, secs: list[dict], lines: list[dict],
              title: str, sub: str, handle: str = "") -> Path:
    vert = H > W
    size = 74 if vert else 86
    mv = int(H * (0.20 if vert else 0.17))
    head = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0",
            "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
            "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,"
            "MarginV,Encoding",
            # the caption sits on a dark see-through box: the words stay readable over any scene, even one
            # in the song's own accent colour
            f"Style: Cap,Anton,{size},{lyr._bgr(accent)},&H00FFFFFF,&H48000000,&H48000000,0,0,0,0,100,100,1,0,3,12,0,2,"
            f"70,70,{mv},1",
            f"Style: Title,Anton,{int(W * ((0.115 if not vert else 0.15) * 0.42))},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,"
            "0,100,100,3,0,1,4,3,5,60,60,0,1",
            f"Style: Sub,Anton,{int(W * (0.03 if not vert else 0.05))},{lyr._bgr(accent)},{lyr._bgr(accent)},&H00000000,"
            "&H90000000,0,0,0,0,100,100,6,0,1,2,2,5,60,60,0,1",
            f"Style: Tag,Anton,{int(W * (0.022 if not vert else 0.04))},{lyr._bgr(accent)},{lyr._bgr(accent)},"
            "&H00000000,&H90000000,0,0,0,0,100,100,5,0,1,2,2,7,60,60,50,1",
            "", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
    ev = []
    t0 = secs[0]["end"] if secs[0]["kind"] == "intro" else 6.0
    show = min(t0, 9.0)
    ty, sy = (0.72, 0.82) if not vert else (0.70, 0.78)
    ty, sy = (0.075, 0.125) if not vert else (0.085, 0.125)      # the title sits at the top, clear of the artwork and the caption
    ev.append(f"Dialogue: 3,{lyr._t(0.2)},{lyr._t(show)},Title,,0,0,0,,"
              f"{{\\pos({W // 2},{int(H * ty)})\\fad(500,500)}}{lyr._esc(title).upper()}")
    ev.append(f"Dialogue: 3,{lyr._t(0.5)},{lyr._t(show)},Sub,,0,0,0,,"
              f"{{\\pos({W // 2},{int(H * sy)})\\fad(500,500)}}{lyr._esc(sub).upper()}")
    seen: dict[str, int] = {}
    for sc in secs:
        k = sc["kind"]
        seen[k] = seen.get(k, 0) + 1
        label = {"intro": "INTRO", "outro": "OUTRO", "build": "BUILD", "drop": "DROP", "groove": "GROOVE",
                 "breakdown": "BREAKDOWN"}[k]
        n = f" {seen[k]:02d}" if k in ("drop", "build", "groove", "breakdown") else ""
        if k == "intro":
            continue
        ev.append(f"Dialogue: 3,{lyr._t(sc['start'] + 0.05)},{lyr._t(min(sc['end'], sc['start'] + 2.6))},Tag,,0,0,0,,"
                  f"{{\\fad(120,300)}}// {label}{n}")
    for i, ln in enumerate(lines):
        t0_ = ln["start"] - 0.2
        last = max(e for _w, _s, e in ln["words"])
        # off the screen once it has been sung: through an instrumental stretch the frame stays clear
        t1_ = min((lines[i + 1]["start"] - 0.2) if i + 1 < len(lines) else 1e9, last + LINGER)
        t1_ = max(t1_, t0_ + 0.4)
        parts, cursor = [], t0_                 # karaoke time counts from the event start, not the first word
        for wd, s, e in ln["words"]:
            lead = max(0, round((s - cursor) * 100))
            if lead:
                parts.append(f"{{\\k{lead}}}")
            parts.append(f"{{\\kf{max(1, round((e - s) * 100))}}}{lyr._esc(wd).upper()} ")
            cursor = e
        ev.append(f"Dialogue: 4,{lyr._t(t0_)},{lyr._t(t1_)},Cap,,0,0,0,,{{\\fad(150,100)}}{''.join(parts)}")
    path.write_text("\n".join(head + ev) + "\n", encoding="utf-8")
    return path


def render_scene_video(tex: Path, audio: Path, out: Path, accent: str, secs: list[dict], title: str, sub: str,
                       work: Path, *, bpm: float, beat_offset: float, lines: list[dict] | None = None,
                       vertical: bool = False, crf: int = 23, timeout: int = 5400) -> dict:
    """The song's scene video, verified against the audio length. ``tex`` is the square artwork."""
    duration = media_summary(audio)["duration"]
    W, H = (1080, 1920) if vertical else (1920, 1080)
    work.mkdir(parents=True, exist_ok=True)
    fr = frames(secs, duration)
    scan = scanlines(W, H, work / f"scan-{W}.png")
    a = _ff(accent)
    ass = write_ass(work / "scenes.ass", accent, W, H, secs, lines or [], title, sub)
    n = len(secs)
    looks = assign_looks(secs)
    parts = [f"[0:v]format=yuv420p,split={n}" + "".join(f"[s{i}]" for i in range(n))]
    for i, (sc, (n0, n1)) in enumerate(zip(secs, fr)):
        parts.append(f"[s{i}]trim=start_frame={n0}:end_frame={n1},setpts=PTS-STARTPTS[t{i}]")
        parts += _scene(looks[i], i, W, H, sc, n0, n1, bpm, beat_offset, i == 0)
    parts.append("".join(f"[o{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[body]")
    bd = [(s["start"], s["end"]) for s in secs if s["kind"] == "breakdown"]
    parts += [f"[3:v]scale={W}:{H}:flags=bilinear,format=rgba[fxl]", "[body][fxl]overlay=x=0:y=0:format=auto:shortest=1[v2]"]
    last = "v2"
    graph = parts
    graph.append(f"[{last}][2:v]overlay=x=0:y='-mod(t*24,8)':shortest=1[v3]")
    graph.append(f"color=c={a}:s={W}x8:r={FPS}[fill]")
    graph.append(f"color=c=0x0a1622:s={W}x8:r={FPS}[track]")
    graph.append(f"[track][fill]overlay=x='-{W}+{W}*t/{duration:.3f}':y=0:shortest=1[bar]")
    graph.append(f"[v3][bar]overlay=x=0:y={H - 8}:shortest=1,vignette=PI/5,"
                 f"subtitles=scenes.ass:fontsdir={_fonts()},format=yuv420p[vout]")
    rgb = (int(a[2:4], 16), int(a[4:6], 16), int(a[6:8], 16))
    mono = decode(audio).mean(axis=1)
    n_total = round(duration * FPS)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-i",
           str(Path(tex).resolve()), "-i", str(Path(audio).resolve()), "-loop", "1", "-framerate", str(FPS), "-i",
           str(scan.resolve()), "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W // 2}x{H // 2}", "-framerate",
           str(FPS), "-i", "pipe:0", "-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "1:a",
           "-t", f"{duration:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
           "-maxrate", "4M", "-bufsize", "8M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", *AAC_CLEAN,
           "-ar", "48000", "-movflags", "+faststart", str(Path(out).resolve())]
    log("$ " + " ".join(cmd[:6]) + " ...")
    errf = work / "ffmpeg.err"
    with open(errf, "wb") as ef:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=ef, cwd=str(work))
        try:
            for raw in fx.frames(mono, FPS, n_total + 2, W, H, rgb, secs, bpm, beat_offset, base=int(H * 0.11)):
                proc.stdin.write(raw)
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass
        code = proc.wait(timeout=timeout)
    if code != 0:
        raise RuntimeError(f"scene render failed ({code}): " + errf.read_text(errors="replace")[-1500:])
    scan.unlink(missing_ok=True)
    info = media_summary(out)
    if abs(info["duration"] - duration) > 1.5:
        raise RuntimeError(f"scene render truncated: {info['duration']:.1f}s vs audio {duration:.1f}s")
    return {**info, "scenes": n}


def _fonts() -> str:
    from .config import FONTS
    return str(FONTS)
