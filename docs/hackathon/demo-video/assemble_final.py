#!/usr/bin/env python3
"""Build the architecture-led silent film from existing footage and the new diagrams."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

FFMPEG = "/Users/valikalasudeshchandra/Library/Caches/goip-demo-tools/venv/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v9.0"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
ROOT = Path("/Users/valikalasudeshchandra/Documents/Personal_exp/switch/goip/docs/hackathon")
REC = ROOT / "demo-video/recordings/goip-browser.webm"
CONSOLE = ROOT / "demo-video/recordings/switch-console.mov"
CUES = json.loads((ROOT / "demo-video/recordings/cues.json").read_text(encoding="utf-8"))
CUE = {item["name"]: item["t"] for item in CUES}
ARCH = ROOT.parent / "final_submission/architecture"
STILL = Path("/Users/valikalasudeshchandra/Documents/Personal_exp/switch/goip/docs/final-sprint/gui-roundtrip.png")
WORK = ROOT / "demo-video/rendered/final"
WORK.mkdir(parents=True, exist_ok=True)

PAD = "scale=1920:900:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:24:color=0xF4F1EA,fps=30"
APP = "scale=1920:1080,fps=30"


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def ass_ts(seconds: float) -> str:
    centiseconds = int(round(max(0.0, seconds) * 100))
    whole, cs = divmod(centiseconds, 100)
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def srt_ts(seconds: float) -> str:
    millis = int(round(max(0.0, seconds) * 1000))
    whole, ms = divmod(millis, 1000)
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def silent_video(args_in: list[str], dest: Path, duration: float, vf: str) -> None:
    run([
        FFMPEG, "-y", *args_in,
        "-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16",
        "-c:a", "aac", "-shortest",
        str(dest),
    ])


def card(dest: Path, duration: float, lines: list[tuple[str, int, str]]) -> None:
    draws = []
    for text, size, y in lines:
        safe = text.replace(":", r"\:").replace("'", r"\'")
        draws.append(
            f"drawtext=fontfile={FONT}:text='{safe}':fontsize={size}:fontcolor=white:x=(w-text_w)/2:y={y}"
        )
    silent_video(
        ["-f", "lavfi", "-t", str(duration), "-i", f"color=c=0x14202b:s=1920x1080:r=30:d={duration}"],
        dest, duration, ",".join(draws),
    )


def hold(image: Path, dest: Path, duration: float) -> None:
    silent_video(
        ["-loop", "1", "-t", str(duration), "-i", str(image)],
        dest, duration, PAD,
    )


def hold_full(image: Path, dest: Path, duration: float) -> None:
    silent_video(
        ["-loop", "1", "-t", str(duration), "-i", str(image)],
        dest, duration, "scale=1920:960:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:0:color=0xF4F1EA,fps=30",
    )


def cut(start: float, duration: float, dest: Path) -> None:
    silent_video(
        ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(REC)],
        dest, duration, APP,
    )


def main() -> None:
    pieces: list[tuple[Path, float, str]] = []

    def add(path: Path, duration: float, caption: str) -> None:
        pieces.append((path, duration, caption))

    title = WORK / "01-title.mp4"
    card(title, 12, [
        ("Building Global Opportunity Intelligence", 52, "400"),
        ("with Switch", 48, "480"),
        ("Seven specialized agents. One shared room. Evidence before opportunity.", 26, "580"),
    ])
    add(title, 12, "I built GOIP to turn scattered public signals into a lead I can refuse.\nThe decision stays with a person.")

    overview_len = 28.0
    overview = WORK / "02-overview.mp4"
    cut(CUE["overview"], overview_len, overview)
    add(overview, overview_len, "These cards are stored rows, read on 9 November 2026.\nTwenty-seven companies. Sixty-five signals are not linked to a company.")

    list_len = CUE["needs_review"] - CUE["list"]
    listing = WORK / "03-list.mp4"
    cut(CUE["list"], list_len, listing)
    add(listing, list_len, "Historical score, business signal, technical evidence, and freelance fit\nstay in separate columns.")

    filter_len = CUE["stitch"] - CUE["needs_review"]
    filtered = WORK / "04-filter.mp4"
    cut(CUE["needs_review"], filter_len, filtered)
    add(filtered, filter_len, "Six leads are in review. The search is narrowed to Stitch.ai.\nOpening the row does not change it.")

    top_len = CUE["scores"] - CUE["stitch"]
    stitch = WORK / "05-stitch.mp4"
    cut(CUE["stitch"], top_len, stitch)
    add(stitch, top_len, "The historical score is still 76. That is the old composite.\nIt is not the result of the three later scores.")

    score_len = CUE["qa"] - CUE["scores"]
    scores = WORK / "06-scores.mp4"
    cut(CUE["scores"], score_len, scores)
    add(scores, score_len, "Business signal is 70. Technical evidence is 25. Freelance fit is 0.\nA launch can be notable and still not be a freelance job.")

    qa_len = CUE["switch_screen"] - CUE["qa"]
    qa = WORK / "07-qa.mp4"
    cut(CUE["qa"], qa_len, qa)
    add(qa, qa_len, "Quality assurance rejected the old service line, LLM integration and RAG.\nThe company stays in review. The company was not rejected.")

    diagrams = [
        (22, ARCH / "GOIP_SYSTEM_ARCHITECTURE.png", "FastAPI receives the page and the API calls.\nSwitch carries the room. It does not run the stage, and it is not the model."),
        (22, ARCH / "GOIP_AGENT_COLLABORATION.png", "A stage is one GOIP-TASK, work inside GOIP, then one GOIP-RESULT.\nThe seven agents are not seven models running at once."),
        (20, ARCH / "GOIP_EVIDENCE_QUALIFICATION.png", "Business 70, technical 25, and freelance fit 0 are separate.\nQuality assurance rejects the service line. The company stays in review."),
    ]
    for index, (duration, image, caption) in enumerate(diagrams, start=5):
        path = WORK / f"{index:02d}-diagram.mp4"
        hold_full(image, path, duration)
        add(path, duration, caption)

    console = WORK / "12-console.mp4"
    silent_video(
        ["-ss", "1", "-t", "18", "-i", str(CONSOLE)],
        console, 18, PAD,
    )
    add(console, 18, "This is the existing Switch room, recorded without typing.\nThe rows are stored stage messages. Nothing was sent for this film.")

    still = WORK / "13-roundtrip.mp4"
    hold(STILL, still, 12)
    add(still, 12, "An earlier console recording, not this take.\nA person addressed the orchestrator. Strategy replied that no outreach was sent.")

    switch_len = 22.0
    switch = WORK / "14-switch.mp4"
    cut(CUE["switch_screen"], switch_len, switch)
    add(switch, switch_len, "GOIP stores the same room activity. Seven agents are members.\nThe screen shows the latest stored rows. It is not a claim that every agent finished a new run.")

    settings = WORK / "15-settings.mp4"
    cut(CUE["settings"], 12, settings)
    add(settings, 12, "Settings shows which integrations are configured.\nThe secret values are not on this page.")

    limits = WORK / "16-limits.mp4"
    card(limits, 16, [
        ("What is still unfinished", 42, "300"),
        ("65 signals are not linked to a company.", 32, "430"),
        ("14 high-priority and 7 qualified labels are the first scorer.", 32, "500"),
        ("34 backend tests passed on the last recorded run.", 32, "570"),
        ("This card is a statement, not a live terminal.", 26, "660"),
    ])
    add(limits, 16, "The older labels have not been rewritten with the three scores.\nDiscovery coverage is incomplete. That is the current limit, not a roadmap disguised as a feature.")

    ending = WORK / "17-end.mp4"
    card(ending, 14, [
        ("GLOBAL OPPORTUNITY INTELLIGENCE", 46, "390"),
        ("Built with Switch", 34, "490"),
        ("#HowISwitch", 30, "570"),
    ])
    add(ending, 14, "The desk can research a company and still refuse to pitch it.\nSwitch is the room where that argument is visible.")

    concat = WORK / "concat.txt"
    concat.write_text("".join(f"file '{path}'\n" for path, _, _ in pieces), encoding="utf-8")
    silent = WORK / "silent.mp4"
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(silent)])

    cursor = 0.0
    spans = []
    for _, duration, caption in pieces:
        spans.append((cursor, cursor + duration, caption))
        cursor += duration

    srt_blocks = []
    dialogues = []
    for number, (start, finish, text) in enumerate(spans, start=1):
        srt_blocks.append(f"{number}\n{srt_ts(start)} --> {srt_ts(finish)}\n{text}\n")
        safe = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")
        dialogues.append(f"Dialogue: 0,{ass_ts(start)},{ass_ts(finish)},Caption,,0,0,0,,{safe}")
    srt = ROOT / "demo-video/captions.srt"
    srt.write_text("\n".join(srt_blocks) + "\n", encoding="utf-8")
    ass = ROOT / "demo-video/captions.ass"
    ass.write_text(
        "\n".join([
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1920",
            "PlayResY: 1080",
            "WrapStyle: 2",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Caption,Arial,30,&H00FFFFFF,&H000000FF,&H00000000,&HCC2B2014,0,0,0,0,100,100,0,0,4,10,0,2,80,80,22,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *dialogues,
            "",
        ]),
        encoding="utf-8",
    )
    final = ROOT / "demo-video/FINAL_DEMO.mp4"
    run([
        FFMPEG, "-y", "-i", str(silent),
        "-vf", f"ass={ass}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-crf", "16",
        "-c:a", "copy",
        str(final),
    ])
    print(f"{final} {cursor:.2f}s")


if __name__ == "__main__":
    main()
