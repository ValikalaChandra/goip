#!/usr/bin/env python3
"""Mux local narration onto the captioned demo video."""

from __future__ import annotations

import subprocess
from pathlib import Path

FFMPEG = "/Users/valikalasudeshchandra/Library/Caches/goip-demo-tools/venv/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v9.0"
ROOT = Path(__file__).resolve().parent
HACKATHON = ROOT.parent
VIDEO = ROOT / "FINAL_DEMO.mp4"
NARRATION = HACKATHON.parent / "final_submission/video/voiceover/narration_full.wav"
OUT_DEMO = ROOT / "FINAL_DEMO.mp4"
OUT_SUBMISSION = HACKATHON.parent / "final_submission/video/GOIP_FINAL_DEMO.mp4"


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> None:
    if not NARRATION.exists():
        raise SystemExit(f"Missing narration: {NARRATION}")
    if not VIDEO.exists():
        raise SystemExit(f"Missing captioned video: {VIDEO}")
    source_video = VIDEO
    temp = ROOT / "rendered/final/with_voice.mp4"
    temp.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(source_video),
            "-i",
            str(NARRATION),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(temp),
        ]
    )
    run(["cp", str(temp), str(OUT_DEMO)])
    run(["cp", str(temp), str(OUT_SUBMISSION)])
    print(f"Updated {OUT_DEMO}")


if __name__ == "__main__":
    main()
