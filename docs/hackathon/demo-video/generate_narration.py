#!/usr/bin/env python3
"""Generate scene narration with local Qwen3-TTS voice clone and build a full timeline."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

HACKATHON = Path(__file__).resolve().parent.parent
ROOT = Path(__file__).resolve().parent
SRT = ROOT / "captions.srt"
VOICE_SAMPLE = Path(
    "/Users/valikalasudeshchandra/Documents/Personal_exp/switch/voice_sample/20261109 145722.m4a"
)
FFMPEG = Path(
    "/Users/valikalasudeshchandra/Library/Caches/goip-demo-tools/venv/lib/python3.12/"
    "site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v9.0"
)
PY = Path("/Users/valikalasudeshchandra/Library/Caches/goip-demo-tools/voice-venv/bin/python")
WORK = HACKATHON.parent / "final_submission/video/voiceover"
CACHE = Path("/Users/valikalasudeshchandra/Library/Caches/goip-demo-tools/voice-work")
REF_WAV = CACHE / "reference.wav"
REF_TEXT = CACHE / "ref_text.txt"
MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit"
STT_MODEL = "mlx-community/whisper-large-v3-turbo"
TARGET_SR = 48000


@dataclass
class Scene:
    index: int
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def parse_srt(path: Path) -> list[Scene]:
    raw = path.read_text(encoding="utf-8").strip().split("\n\n")
    scenes: list[Scene] = []

    def ts(value: str) -> float:
        hh, mm, rest = value.split(":")
        ss, ms = rest.split(",")
        return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000.0

    for block in raw:
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        index = int(lines[0])
        start_s, end_s = lines[1].split(" --> ")
        text = " ".join(line.strip() for line in lines[2:] if line.strip())
        scenes.append(Scene(index, ts(start_s), ts(end_s), text))
    return scenes


def ensure_reference() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "source").mkdir(exist_ok=True)
    if not REF_WAV.exists():
        run(
            [
                str(FFMPEG),
                "-y",
                "-i",
                str(VOICE_SAMPLE),
                "-ac",
                "1",
                "-ar",
                "24000",
                "-af",
                "highpass=f=80,loudnorm=I=-18:TP=-2:LRA=11",
                str(REF_WAV),
            ]
        )


def ensure_ref_text() -> str:
    if REF_TEXT.exists() and REF_TEXT.read_text(encoding="utf-8").strip():
        return REF_TEXT.read_text(encoding="utf-8").strip()
    out_stem = CACHE / "stt_reference"
    run(
        [
            str(PY),
            "-m",
            "mlx_audio.stt.generate",
            "--model",
            STT_MODEL,
            "--audio",
            str(REF_WAV),
            "--output-path",
            str(out_stem),
            "--format",
            "txt",
            "--language",
            "en",
        ]
    )
    produced = Path(f"{out_stem}.txt")
    if not produced.exists():
        produced = Path(f"{out_stem}.txt.txt")
    text = produced.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit("Reference transcript is empty; provide ref_text.txt manually.")
    REF_TEXT.write_text(text + "\n", encoding="utf-8")
    return text


def speak_text(text: str) -> str:
    spoken = text
    spoken = spoken.replace("GOIP-TASK", "G O I P task")
    spoken = spoken.replace("GOIP", "G O I P")
    spoken = spoken.replace("FastAPI", "Fast A P I")
    spoken = spoken.replace("Stitch.ai", "Stitch dot A I")
    spoken = spoken.replace("LLM", "L L M")
    spoken = spoken.replace("RAG", "R A G")
    return spoken


def tts_for_scene(model, text: str, ref_text: str, dest: Path) -> None:
    from mlx_audio.tts.generate import generate_audio

    dest.parent.mkdir(parents=True, exist_ok=True)
    generate_audio(
        text=speak_text(text),
        model=model,
        ref_audio=str(REF_WAV),
        ref_text=ref_text,
        lang_code="English",
        output_path=str(dest.parent),
        file_prefix=dest.stem,
        audio_format="wav",
        join_audio=True,
        temperature=0.55,
        top_p=0.82,
        top_k=40,
        repetition_penalty=1.7,
        verbose=False,
    )
    produced = dest.parent / f"{dest.stem}.wav"
    if produced != dest and produced.exists():
        produced.rename(dest)


def load_mono(path: Path, sr: int = TARGET_SR) -> np.ndarray:
    data, file_sr = sf.read(path, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if file_sr != sr:
        tmp_in = CACHE / "resample_in.wav"
        tmp_out = CACHE / "resample_out.wav"
        sf.write(tmp_in, data, file_sr)
        run(
            [
                str(FFMPEG),
                "-y",
                "-i",
                str(tmp_in),
                "-ar",
                str(sr),
                "-ac",
                "1",
                str(tmp_out),
            ]
        )
        data, _ = sf.read(tmp_out, dtype="float32")
    return np.asarray(data, dtype=np.float32)


def fit_segment(audio: np.ndarray, target_seconds: float) -> np.ndarray:
    target_samples = int(round(target_seconds * TARGET_SR))
    if len(audio) == 0:
        return np.zeros(target_samples, dtype=np.float32)
    if len(audio) == target_samples:
        return audio
    if len(audio) < target_samples:
        pad = np.zeros(target_samples - len(audio), dtype=np.float32)
        return np.concatenate([audio, pad])
    ratio = len(audio) / target_samples
    tmp_in = CACHE / "fit_in.wav"
    tmp_out = CACHE / "fit_out.wav"
    sf.write(tmp_in, audio, TARGET_SR)
    filters: list[str] = []
    remaining = ratio
    while remaining > 1.001:
        step = min(remaining, 2.0)
        filters.append(f"atempo={step:.6f}")
        remaining /= step
    if remaining < 0.999:
        filters.append(f"atempo={remaining:.6f}")
    af = ",".join(filters) if filters else "anull"
    run([str(FFMPEG), "-y", "-i", str(tmp_in), "-af", af, str(tmp_out)])
    fitted, _ = sf.read(tmp_out, dtype="float32")
    fitted = np.asarray(fitted, dtype=np.float32)
    if len(fitted) > target_samples:
        fitted = fitted[:target_samples]
    elif len(fitted) < target_samples:
        fitted = np.pad(fitted, (0, target_samples - len(fitted)))
    return fitted


def normalize_loudness(timeline: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(timeline))) or 1.0
    target_peak = 0.89
    return timeline * (target_peak / peak)


def main() -> None:
    ensure_reference()
    ref_text = ensure_ref_text()
    scenes = parse_srt(SRT)
    total = scenes[-1].end if scenes else 0.0
    timeline = np.zeros(int(round(total * TARGET_SR)), dtype=np.float32)

    from mlx_audio.tts.utils import load_model

    model = load_model(MODEL)

    for scene in scenes:
        raw = WORK / "segments" / f"{scene.index:02d}_raw.wav"
        if not raw.exists():
            print(f"Generating scene {scene.index} …", flush=True)
            tts_for_scene(model, scene.text, ref_text, raw)
        segment = fit_segment(load_mono(raw), scene.duration)
        start = int(round(scene.start * TARGET_SR))
        timeline[start : start + len(segment)] += segment

    timeline = normalize_loudness(timeline)
    master = WORK / "narration_full.wav"
    sf.write(master, timeline, TARGET_SR, subtype="PCM_16")
    print(f"Wrote {master} ({total:.2f}s)", flush=True)


if __name__ == "__main__":
    main()
