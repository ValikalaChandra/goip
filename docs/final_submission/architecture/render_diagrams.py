#!/usr/bin/env python3
"""Draw the three GOIP architecture plates on a 1920x1080 grid.

Connectors are painted first and only travel through the gaps between boxes.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
W, H = 1920, 1080
PAPER = (244, 241, 234)
INK = (20, 32, 43)
TEAL = (12, 95, 89)
BROWN = (92, 74, 58)
SAND = (231, 220, 200)
WHITE = (255, 255, 255)
MUTED = (82, 97, 112)
LINE = (90, 104, 112)

FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(BOLD if bold else FONT, size)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (W, H), PAPER)
    return image, ImageDraw.Draw(image)


def text_size(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=face)
    return box[2] - box[0], box[3] - box[1]


def wrap(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if text_size(draw, trial, face)[0] <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: tuple[int, int, int], outline: tuple[int, int, int]) -> None:
    draw.rounded_rectangle(box, radius=16, fill=fill, outline=outline, width=3)


def label_block(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    body: str,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int],
    title_fill: tuple[int, int, int],
    body_fill: tuple[int, int, int],
) -> None:
    rounded(draw, box, fill, outline)
    x0, y0, x1, y1 = box
    inner = x1 - x0 - 36
    title_face = font(28, bold=True)
    body_face = font(20)
    lines = wrap(draw, body, body_face, inner) if body else []
    title_w, title_h = text_size(draw, title, title_face)
    body_h = sum(text_size(draw, line, body_face)[1] + 4 for line in lines)
    block_h = title_h + (12 + body_h if lines else 0)
    top = y0 + max(16, (y1 - y0 - block_h) // 2)
    draw.text((x0 + (x1 - x0 - title_w) // 2, top), title, font=title_face, fill=title_fill)
    cursor = top + title_h + 12
    for line in lines:
        line_w, line_h = text_size(draw, line, body_face)
        draw.text((x0 + (x1 - x0 - line_w) // 2, cursor), line, font=body_face, fill=body_fill)
        cursor += line_h + 4


def arrow(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]], color: tuple[int, int, int], width: int = 4) -> None:
    draw.line(points, fill=color, width=width, joint="curve")
    x1, y1 = points[-2]
    x2, y2 = points[-1]
    size = 14
    if x2 == x1 and y2 > y1:
        head = [(x2, y2), (x2 - size, y2 - size), (x2 + size, y2 - size)]
    elif x2 == x1 and y2 < y1:
        head = [(x2, y2), (x2 - size, y2 + size), (x2 + size, y2 + size)]
    elif y2 == y1 and x2 > x1:
        head = [(x2, y2), (x2 - size, y2 - size), (x2 - size, y2 + size)]
    else:
        head = [(x2, y2), (x2 + size, y2 - size), (x2 + size, y2 + size)]
    draw.polygon(head, fill=color)


def footer(draw: ImageDraw.ImageDraw, text: str) -> None:
    face = font(22)
    width, _ = text_size(draw, text, face)
    draw.text(((W - width) // 2, 1024), text, font=face, fill=MUTED)


def heading(draw: ImageDraw.ImageDraw, title: str, note: str) -> None:
    draw.text((56, 28), title, font=font(40, bold=True), fill=INK)
    note_w, _ = text_size(draw, note, font(22))
    draw.text((W - 56 - note_w, 42), note, font=font(22), fill=MUTED)


def system() -> Image.Image:
    image, draw = canvas()
    heading(draw, "GOIP system architecture", "Paths that exist in this repository")

    sources = (56, 110, 336, 250)
    human = (392, 110, 952, 250)
    browser = (1008, 110, 1528, 250)
    model = (1584, 110, 1864, 250)
    api = (392, 330, 1528, 470)
    frame = (56, 520, 1864, 800)
    cards = []
    gap = 16
    card_w = 236
    left = 80
    for index in range(7):
        x = left + index * (card_w + gap)
        cards.append((x, 590, x + card_w, 700))
    orchestrator = (80, 712, 1840, 784)
    switch = (80, 860, 560, 990)
    mattermost = (720, 860, 1200, 990)
    postgres = (1360, 860, 1840, 990)

    # Connectors stay in the gaps. They stop at a box edge.
    arrow(draw, [(196, 250), (196, 290), (392, 290), (392, 330)], INK)
    arrow(draw, [(672, 250), (672, 330)], INK)
    arrow(draw, [(1268, 250), (1268, 330)], INK)
    arrow(draw, [(1724, 250), (1724, 290), (1528, 290), (1528, 330)], LINE)
    arrow(draw, [(960, 470), (960, 520)], TEAL)
    arrow(draw, [(320, 800), (320, 860)], TEAL)
    arrow(draw, [(1600, 800), (1600, 860)], BROWN)
    arrow(draw, [(720, 925), (560, 925)], TEAL)

    label_block(draw, sources, "Public sources", "HN, TechCrunch, GitHub, Crawl4AI", WHITE, INK, INK, MUTED)
    label_block(draw, human, "Human operator", "Reads the desk. Does not send outreach.", INK, INK, WHITE, (220, 226, 230))
    label_block(draw, browser, "GOIP web application", "Static page. Overview, leads, Switch, Settings.", WHITE, INK, INK, MUTED)
    label_block(draw, model, "OpenRouter", "Research and qualification only.", WHITE, INK, INK, MUTED)
    label_block(draw, api, "FastAPI  ·  127.0.0.1:8001", "Serves the page and the API. Runs each stage. Writes PostgreSQL.", TEAL, TEAL, WHITE, (220, 236, 234))
    rounded(draw, frame, WHITE, TEAL)
    draw.text((80, 532), "SEVEN AGENTS IN ONE SWITCH ROOM", font=font(22, bold=True), fill=TEAL)
    names = [
        ("Discovery", "Public signals and URLs"),
        ("Company research", "Fact, then inference"),
        ("Technical", "A stated need"),
        ("Qualification", "Three separate scores"),
        ("Strategy", "A note. No contact."),
        ("Quality assurance", "Rejects the service"),
        ("Orchestrator", "The one you address"),
    ]
    for box, (title, body) in zip(cards, names):
        label_block(draw, box, title, body, WHITE, INK, INK, MUTED)
    label_block(draw, orchestrator, "One room, one stage at a time", "The specialists do not call each other.", SAND, BROWN, INK, MUTED)
    label_block(draw, switch, "Switch Core", "Room and agent API on port 50990.", TEAL, TEAL, WHITE, (220, 236, 234))
    label_block(draw, mattermost, "Mattermost", "Human composer. Switch bridges it. GOIP does not call it.", WHITE, INK, INK, MUTED)
    label_block(draw, postgres, "PostgreSQL", "Companies, signals, versions, stored messages.", BROWN, BROWN, WHITE, (236, 228, 220))
    footer(draw, "Solid HTTP    ·    teal room message    ·    gray OpenRouter    ·    brown database write")
    return image


def collaboration() -> Image.Image:
    image, draw = canvas()
    heading(draw, "How one stage moves", "Switch carries the message. GOIP runs the work.")
    steps = [
        (56, 150, 456, 290, "1  Browser", "HTTP to FastAPI"),
        (504, 150, 904, 290, "2  FastAPI", "Starts a run when Switch is connected"),
        (952, 150, 1352, 290, "3  Orchestrator", "Posts GOIP-TASK into the room"),
        (1400, 150, 1864, 290, "4  Switch", "Delivers it on that agent's websocket"),
        (1400, 390, 1864, 530, "5  Specialist", "Runs the stage in GOIP code"),
        (952, 390, 1352, 530, "6  Model, sometimes", "Research and qualification call OpenRouter"),
        (504, 390, 904, 530, "7  PostgreSQL", "GOIP writes the rows, including the message"),
        (56, 390, 456, 530, "8  GOIP-RESULT", "The specialist posts the result back to the room"),
    ]
    # Gaps only: rightward on the top row, down the right gutter, leftward on the bottom row.
    arrow(draw, [(456, 220), (504, 220)], TEAL)
    arrow(draw, [(904, 220), (952, 220)], TEAL)
    arrow(draw, [(1352, 220), (1400, 220)], TEAL)
    arrow(draw, [(1632, 290), (1632, 390)], TEAL)
    arrow(draw, [(1400, 460), (1352, 460)], BROWN)
    arrow(draw, [(952, 460), (904, 460)], BROWN)
    arrow(draw, [(504, 460), (456, 460)], BROWN)

    for box_x0, box_y0, box_x1, box_y1, title, body in steps:
        fill, title_fill, body_fill, outline = WHITE, INK, MUTED, INK
        if title.startswith("4"):
            fill, title_fill, body_fill, outline = TEAL, WHITE, (220, 236, 234), TEAL
        if title.startswith("7"):
            fill, title_fill, body_fill, outline = BROWN, WHITE, (236, 228, 220), BROWN
        label_block(draw, (box_x0, box_y0, box_x1, box_y1), title, body, fill, outline, title_fill, body_fill)

    note = (56, 620, 1864, 760)
    gate = (56, 810, 1864, 960)
    label_block(
        draw, note, "Human sentence",
        "It enters through the Mattermost composer, crosses Switch's bridge, and arrives on the same websocket.",
        WHITE, TEAL, INK, MUTED,
    )
    label_block(
        draw, gate, "If Switch is down",
        "POST /api/runs can take a local path. That path does not write the room transcript.",
        WHITE, BROWN, INK, MUTED,
    )
    footer(draw, "Stages run one at a time. The seven agents are not seven simultaneous models.")
    return image


def evidence() -> Image.Image:
    image, draw = canvas()
    heading(draw, "Evidence, scores, and the refusal", "Stitch.ai, as stored")
    scores = [
        (56, 140, 616, 320, "Business signal  70", "How notable the stored event is. A launch can score here."),
        (652, 140, 1212, 320, "Technical evidence  25", "An assistant is mentioned. No requirement is written down."),
        (1248, 140, 1864, 320, "Freelance fit  0", "An outsider is not a fair reading of the text."),
    ]
    for box in scores:
        label_block(draw, box[:4], box[4], box[5], WHITE, INK, INK, MUTED)
    arrow(draw, [(336, 320), (336, 390)], INK)
    arrow(draw, [(932, 320), (932, 390)], INK)

    classes = (56, 390, 1212, 560)
    intent = (1248, 390, 1864, 560)
    label_block(
        draw, classes, "Evidence class",
        "Observed fact, derived fact, inference, hypothesis, or unknown. A quote counts only in the stored text.",
        WHITE, INK, INK, MUTED,
    )
    label_block(
        draw, intent, "Commercial intent",
        "Tracked beside the scores. Not added into 70, 25, or 0.",
        SAND, BROWN, INK, MUTED,
    )
    arrow(draw, [(634, 560), (634, 640)], TEAL)
    qa = (56, 640, 936, 820)
    human = (984, 640, 1864, 820)
    label_block(
        draw, qa, "Quality assurance  ·  reject",
        "The service line LLM integration and RAG has no support. The company stays.",
        TEAL, TEAL, WHITE, (220, 236, 234),
    )
    arrow(draw, [(936, 730), (984, 730)], TEAL)
    label_block(
        draw, human, "Human review",
        "Needs review. No approval, no draft, no outreach.",
        INK, INK, WHITE, (220, 226, 230),
    )
    footer(draw, "Historical composite 76 is kept on version 1. Version 2 does not overwrite it.")
    return image


def main() -> None:
    plates = {
        "GOIP_SYSTEM_ARCHITECTURE.png": system(),
        "GOIP_AGENT_COLLABORATION.png": collaboration(),
        "GOIP_EVIDENCE_QUALIFICATION.png": evidence(),
    }
    for name, image in plates.items():
        image.save(OUT / name, "PNG")
        print(name, image.size)


if __name__ == "__main__":
    main()
