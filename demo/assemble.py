"""Assemble the demo video: recorded clips + ElevenLabs narration + burned-in captions -> one MP4.

App clips are real recordings, often longer than their narration (the agent is thinking). We keep the
last few seconds (the answer landing) at 1x and fast-forward the wait before it, so nothing is faked.

usage: python demo/assemble.py [--no-captions]
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIPS, AUDIO, BUILD = ROOT / "out" / "clips", ROOT / "out" / "audio", ROOT / "out" / "build"
FINAL = ROOT / "out" / "capy-pals-demo.mp4"
TIMELINE = [  # clip, narrations played over it
    ("s01_title", ["s01_title"]), ("s02_problem", ["s02_problem"]), ("s03_ask", ["s03_ask", "s04_path"]),
    ("s04b_plan", ["s04b_plan"]), ("s05_data", ["s05_data"]), ("s06_lookup", ["s06_lookup"]), ("s07_memory", ["s07_memory"]),
    ("s08_approve", ["s08_approve"]), ("s09_hood", ["s09_hood"]), ("s10_outro", ["s10_outro"]),
]
GAP, LEAD, TAIL = 0.45, 0.35, 0.7
HOLD = {"s08_approve": 12.0}  # seconds kept at 1x at the end of a clip (the approval must be seen)
APP = {"s03_ask", "s04b_plan", "s06_lookup", "s07_memory", "s08_approve"}
START_TRIM = 1.5  # app clips open on half-loaded pages
END_TRIM = {"s08_approve": 3.0}  # nothing happens after the sent toast
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SPED_UP = (f"drawtext=fontfile={FONT}:text='▶▶ sped up':x=96:y=788:fontsize=18:fontcolor=white:"
           "box=1:boxcolor=0x201A14@0.65:boxborderw=8")
LOUDNESS = "loudnorm=I=-14:TP=-1.5:LRA=11"  # YouTube's reference level


def run(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def dur(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout.strip())


def srt_time(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def cues(text: str, start: float, length: float) -> list[tuple[float, float, str]]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    chunks = []
    for p in parts:  # keep captions short: split long sentences at commas
        if len(p) > 95 and "," in p:
            mid = p.rfind(",", 0, len(p) // 2 + 20)
            chunks += [p[: mid + 1], p[mid + 1:].strip()]
        else:
            chunks.append(p)
    total = sum(len(c) for c in chunks)
    out, t = [], start
    for c in chunks:
        d = length * len(c) / total
        out.append((t, t + d, c))
        t += d
    return out


def build_scene(i: int, clip: str, narr: list[str], script: dict) -> tuple[Path, list]:
    src = CLIPS / f"{clip}.mp4"
    a_durs = [dur(AUDIO / f"{n}.mp3") for n in narr]
    a_total = LEAD + sum(a_durs) + GAP * (len(narr) - 1)
    target = a_total + TAIL
    if clip in HOLD:  # this scene's ending must play at 1x even if it outlasts the narration
        target = max(target, HOLD[clip] + 1.5)
    t0 = START_TRIM if clip in APP else 0.0
    v = dur(src) - t0 - END_TRIM.get(clip, 0.0)
    seg = BUILD / f"{i:02d}_{clip}_v.mp4"
    if v > target + 0.5:  # fast-forward the wait, keep the landing at 1x
        hold = HOLD.get(clip) or min(7.0, v * 0.35, target * 0.6)
        hold = min(hold, target - 0.5, v - 0.5)
        fast_in, fast_out = v - hold, target - hold
        f = max(1.0, fast_in / fast_out)
        badge = f",{SPED_UP}" if f >= 1.5 else ""  # say so whenever we fast-forward a wait
        run("-i", str(src), "-filter_complex",
            f"[0:v]trim={t0:.3f}:{t0 + fast_in:.3f},setpts=(PTS-STARTPTS)/{f:.4f}{badge}[a];"
            f"[0:v]trim={t0 + fast_in:.3f}:{t0 + v:.3f},setpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=1[v]",
            "-map", "[v]", "-r", "30", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(seg))
    else:  # hold the last frame until the narration ends
        pad = max(0.0, target - v)
        run("-i", str(src), "-vf", f"trim={t0:.3f}:{t0 + v:.3f},setpts=PTS-STARTPTS,"
            f"tpad=stop_mode=clone:stop_duration={pad:.3f}", "-r", "30",
            "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(seg))
    length = dur(seg)
    # narration track for this scene
    inputs, filt, t = [], [], LEAD
    for k, (n, d) in enumerate(zip(narr, a_durs)):
        inputs += ["-i", str(AUDIO / f"{n}.mp3")]
        filt.append(f"[{k + 1}:a]adelay={int(t * 1000)}|{int(t * 1000)}[a{k}]")
        t += d + GAP
    mix = "".join(f"[a{k}]" for k in range(len(narr)))
    out = BUILD / f"{i:02d}_{clip}.mp4"
    run("-i", str(seg), *inputs, "-filter_complex",
        ";".join(filt) + f";{mix}amix=inputs={len(narr)}:normalize=0,apad[aud]",
        "-map", "0:v", "-map", "[aud]", "-t", f"{length:.3f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", str(out))
    # caption cues (relative to scene start)
    caps, t = [], LEAD
    for n, d in zip(narr, a_durs):
        caps += cues(script[n], t, d)
        t += d + GAP
    return out, caps, length


def main():
    captions = "--no-captions" not in sys.argv
    BUILD.mkdir(parents=True, exist_ok=True)
    script = {s["id"]: s["text"] for s in json.loads((ROOT / "script.json").read_text())}
    parts, all_caps, offset = [], [], 0.0
    for i, (clip, narr) in enumerate(TIMELINE):
        out, caps, length = build_scene(i, clip, narr, script)
        parts.append(out)
        all_caps += [(a + offset, b + offset, c) for a, b, c in caps]
        offset += length
        print(f"{clip:12} {length:5.1f}s")
    listing = BUILD / "concat.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    joined = BUILD / "joined.mp4"
    run("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined))
    if captions:
        srt = BUILD / "captions.srt"
        srt.write_text("".join(f"{k + 1}\n{srt_time(a)} --> {srt_time(b)}\n{c}\n\n" for k, (a, b, c) in enumerate(all_caps)))
        style = ("FontName=DejaVu Sans,FontSize=12,PrimaryColour=&H00FFFFFF,OutlineColour=&H00201A14,BackColour=&H99201A14,"
                 "BorderStyle=4,Outline=1,Shadow=0,MarginV=10,Alignment=2")
        run("-i", str(joined), "-vf", f"subtitles={srt}:force_style='{style}'", "-c:v", "libx264", "-crf", "20",
            "-preset", "medium", "-pix_fmt", "yuv420p", "-af", LOUDNESS, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", str(FINAL))
    else:
        run("-i", str(joined), "-c:v", "copy", "-af", LOUDNESS, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", str(FINAL))
    print(f"final: {FINAL} ({dur(FINAL):.1f}s)")


if __name__ == "__main__":
    main()
