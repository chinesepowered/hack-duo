"""Generate per-scene narration with ElevenLabs (young, bright female voice) and report durations.

usage: python demo/narrate.py [scene_id ...] [--force]
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")
OUT = ROOT / "out" / "audio"
VOICE = os.getenv("ELEVENLABS_VOICE_ID", "cgSgspJ2msm6clMCkdW9")  # Jessica: young, playful, bright, warm
MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_v4")


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


def tts(text: str, path: Path):
    r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}", params={"output_format": "mp3_44100_128"},
                   headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}, timeout=120,
                   json={"text": text, "model_id": MODEL,
                         "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35,
                                            "use_speaker_boost": True, "speed": 1.0}})
    r.raise_for_status()
    path.write_bytes(r.content)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    scenes = json.loads((ROOT / "script.json").read_text())
    total = 0.0
    for s in scenes:
        if args and s["id"] not in args:
            continue
        path = OUT / f"{s['id']}.mp3"
        if force or not path.exists():
            tts(s["text"], path)
        d = duration(path)
        total += d
        print(f"{s['id']:12} {d:5.1f}s  {s['text'][:70]}")
    print(f"total narration: {total:.1f}s")


if __name__ == "__main__":
    main()
