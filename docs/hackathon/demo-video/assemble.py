#!/usr/bin/env python3
"""Assemble the silent demo from the browser recording, the diagram, and captions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

FFMPEG = "/Users/valikalasudeshchandra/Library/Caches/goip-demo-tools/venv/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v9.0"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
ROOT = Path("/Users/valikalasudeshchandra/Documents/Personal_exp/switch/goip/docs/hackathon")
REC = ROOT / "demo-video/recordings/goip-browser.webm"
CONSOLE_SRC = ROOT / "demo-video/recordings/switch-console.mov"
CUES = ROOT / "demo-video/recordings/cues.json"
DIAGRAM = ROOT / "architecture/architecture.png"
WORK = ROOT / "demo-video/rendered"
WORK.mkdir(parents=True, exist_ok=True)

TITLE = 12.0
ARCH = 62.0
END = 16.0
CONSOLE = 20.0


def ass_ts(seconds: float) -> str:
    centiseconds = int(round(max(0.0, seconds) * 100))
    whole, cs = divmod(centiseconds, 100)
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    whole = int(seconds)
    millis = int(round((seconds - whole) * 1000))
    if millis == 1000:
        whole += 1
        millis = 0
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def card(path: Path, duration: float, lines: list[tuple[str, int, str]]) -> None:
    draws = []
    for text, size, y in lines:
        safe = text.replace(":", r"\:").replace("'", r"\'")
        draws.append(
            "drawtext="
            f"fontfile={FONT}:text='{safe}':fontsize={size}:fontcolor=white:"
            f"x=(w-text_w)/2:y={y}"
        )
    run([
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"color=c=0x14202b:s=1920x1080:r=30:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(duration),
        "-vf", ",".join(draws),
        "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(path),
    ])


def main() -> None:
    cues = {item["name"]: item["t"] for item in json.loads(CUES.read_text(encoding="utf-8"))}
    trim = cues["overview"]
    app_dur = cues["app_end"] - trim

    def rel(name: str) -> float:
        return cues[name] - trim

    app = WORK / "app.mp4"
    run([
        FFMPEG, "-y",
        "-ss", f"{trim:.3f}", "-i", str(REC),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", f"{app_dur:.3f}",
        "-vf", "scale=1920:1080,fps=30",
        "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(app),
    ])
    before_dur = rel("switch_screen")
    after_dur = app_dur - before_dur
    before = WORK / "app-before.mp4"
    after = WORK / "app-after.mp4"
    run([
        FFMPEG, "-y", "-i", str(app),
        "-t", f"{before_dur:.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac",
        str(before),
    ])
    run([
        FFMPEG, "-y", "-ss", f"{before_dur:.3f}", "-i", str(app),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac",
        str(after),
    ])
    console = WORK / "console.mp4"
    run([
        FFMPEG, "-y",
        "-ss", "1", "-i", str(CONSOLE_SRC),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(CONSOLE),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0xE7EDF1,fps=30",
        "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(console),
    ])

    title = WORK / "title.mp4"
    card(title, TITLE, [
        ("GLOBAL OPPORTUNITY INTELLIGENCE", 58, "430"),
        ("A read-only walkthrough of the running desk", 30, "520"),
    ])
    ending = WORK / "end.mp4"
    card(ending, END, [
        ("GLOBAL OPPORTUNITY INTELLIGENCE", 52, "390"),
        ("Built with Switch", 34, "480"),
        ("#HowISwitch", 30, "560"),
    ])

    arch = WORK / "architecture.mp4"
    run([
        FFMPEG, "-y",
        "-loop", "1", "-i", str(DIAGRAM),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(ARCH),
        "-vf", "scale=1920:900:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:24:color=0xF4F1EA,fps=30",
        "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(arch),
    ])

    concat = WORK / "concat.txt"
    concat.write_text(
        "\n".join(f"file '{path}'" for path in (title, before, console, after, arch, ending)) + "\n",
        encoding="utf-8",
    )
    silent = WORK / "silent.mp4"
    run([
        FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-c", "copy", str(silent),
    ])

    off = TITLE
    spans = [
        (0, TITLE, "Global Opportunity Intelligence.\nA local desk that keeps the public source next to the claim."),
        (off + rel("overview"), off + rel("overview_counts"), "The overview is stored data.\nCounts come from the database, not from a target."),
        (off + rel("overview_counts"), off + rel("list"), "Twenty-seven companies are stored. Ninety-two signals were collected.\nSixty-five of those signals are not linked to a company."),
        (off + rel("list"), off + rel("needs_review"), "Historical score, business signal, technical evidence, and freelance fit\nstay in separate columns."),
        (off + rel("needs_review"), off + rel("stitch"), "Six leads are in review. The search is narrowed to Stitch.ai.\nOpening the row does not change it."),
        (off + rel("stitch"), off + rel("scores"), "The historical score is still 76.\nThat is the old composite, not the three-score result."),
        (off + rel("scores"), off + rel("qa"), "Business signal is 70. Technical evidence is 25. Freelance fit is 0.\nA launch is not yet a freelance job."),
        (off + rel("qa"), off + before_dur, "Quality assurance rejected the old service line.\nThe company stays in review. Nothing was sent."),
    ]
    console_at = off + before_dur
    spans.extend([
        (console_at, console_at + 10, "This is the existing Switch room.\nThese messages were already stored. Nothing was typed or sent."),
        (console_at + 10, console_at + CONSOLE, "The orchestrator and the specialist agents share one thread.\nSwitch is the collaboration layer."),
    ])
    after_at = console_at + CONSOLE
    spans.extend([
        (after_at, after_at + (rel("settings") - rel("switch_screen")), "GOIP stores the same room activity. The seven agents are members.\nThese rows were already stored."),
        (after_at + (rel("settings") - rel("switch_screen")), after_at + (rel("return") - rel("switch_screen")), "Settings shows which integrations are configured.\nThe secret values are not on this page."),
        (after_at + (rel("return") - rel("switch_screen")), after_at + after_dur, "The older high-priority labels are still the first scorer.\nThey have not been rewritten."),
    ])
    arch_at = after_at + after_dur
    beats = [
        "The operator uses the web application.\nFastAPI serves that page and the API.",
        "Discovery code fetches Hacker News, TechCrunch, GitHub,\nand one Crawl4AI query.",
        "Research and qualification call OpenRouter.\nSwitch is not the model provider.",
        "Seven agents are members of one room.\nThe orchestrator is the one a person addresses.",
        "The runtime posts stage messages into Switch\nand reads the replies.",
        "PostgreSQL stores companies, signals, evaluations,\nreviews, and those messages.",
        "Mattermost is attached by Switch as the human composer.\nGOIP does not call it.",
        "A solid arrow is HTTP. A dashed arrow is a room message.\nThe brown arrow is a database write.",
    ]
    step = ARCH / len(beats)
    for index, text in enumerate(beats):
        spans.append((arch_at + index * step, arch_at + (index + 1) * step, text))
    end_at = arch_at + ARCH
    spans.append((end_at, end_at + END, "GOIP keeps the source next to the claim.\nSwitch is the room where that work is visible. No outreach was sent."))

    srt = ROOT / "demo-video/captions.srt"
    blocks = []
    dialogues = []
    for number, (start, finish, text) in enumerate(spans, start=1):
        blocks.append(f"{number}\n{ts(start)} --> {ts(finish)}\n{text}\n")
        safe = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")
        dialogues.append(f"Dialogue: 0,{ass_ts(start)},{ass_ts(finish)},Caption,,0,0,0,,{safe}")
    srt.write_text("\n".join(blocks) + "\n", encoding="utf-8")
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
            "Style: Caption,Arial,32,&H00FFFFFF,&H000000FF,&H00000000,&HCC2B2014,0,0,0,0,100,100,0,0,4,12,0,2,90,90,28,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *dialogues,
            "",
        ]),
        encoding="utf-8",
    )

    final = ROOT / "demo-video/final-demo.mp4"
    run([
        FFMPEG, "-y", "-i", str(silent),
        "-vf", f"ass={ass}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-crf", "18",
        "-c:a", "copy",
        str(final),
    ])
    print(final)


if __name__ == "__main__":
    main()
