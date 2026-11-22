#!/usr/bin/env python3
"""Drive the live GOIP app and record the browser. No writes, no new Switch messages."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path("/Users/valikalasudeshchandra/Documents/Personal_exp/switch/goip")
TOKEN_PATH = ROOT / "data/secrets/operator-token"
OUT = ROOT / "docs/hackathon/demo-video/recordings"
OUT.mkdir(parents=True, exist_ok=True)
CUES = OUT / "cues.json"
SCRUB = r"""() => {
  const scrub = () => {
    document.querySelectorAll("p, span, li, h1, h2, strong, a").forEach((el) => {
      el.childNodes.forEach((node) => {
        if (node.nodeType !== 3 || !/telegram/i.test(node.textContent || "")) return;
        node.textContent = node.textContent
          .replace(/\s*·\s*telegram\s+\S+/ig, "")
          .replace(/Telegram carries the report\.\s*/g, "");
      });
    });
    document.querySelectorAll("div").forEach((el) => {
      const label = el.querySelector(":scope > span");
      if (label && /^telegram$/i.test((label.textContent || "").trim())) el.remove();
    });
  };
  scrub();
  if (!window.__goipScrub) window.__goipScrub = setInterval(scrub, 200);
}"""


def main() -> int:
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    if len(token) < 20:
        print("operator token missing", file=sys.stderr)
        return 2
    cues: list[dict] = []
    started: dict[str, float] = {}

    def mark(name: str) -> None:
        cues.append({"t": round(time.monotonic() - started["t"], 3), "name": name})
        print(f"cue {name} {cues[-1]['t']}", flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(OUT),
            record_video_size={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )
        page = context.new_page()
        video = page.video
        started["t"] = time.monotonic()
        code = 0
        try:
            mark("clock")
            page.goto("http://127.0.0.1:8001/", wait_until="networkidle")
            page.evaluate(SCRUB)
            page.locator("#token").fill(token)
            page.locator("#login button.primary").click()
            page.locator("text=Companies stored").wait_for()
            page.evaluate(SCRUB)
            overview = page.locator("#view").inner_text()
            required = ["27", "65", "14", "connected"]
            missing = [item for item in required if item not in overview]
            if missing:
                print("overview missing " + ",".join(missing), file=sys.stderr)
                return 3
            mark("overview")
            page.wait_for_timeout(22000)
            mark("overview_counts")
            page.wait_for_timeout(16000)

            page.locator("button[data-view='explorer']").click()
            page.locator("#leads table").wait_for()
            page.evaluate(SCRUB)
            mark("list")
            page.wait_for_timeout(14000)
            page.locator("#q").fill("Stitch")
            page.locator("#status").select_option("needs_review")
            page.locator("#filter").click()
            page.locator("#leads >> text=G900BE3A9").wait_for()
            page.evaluate(SCRUB)
            mark("needs_review")
            page.wait_for_timeout(12000)
            page.locator("#leads >> text=G900BE3A9").click()
            page.locator("text=Freelance fit").first.wait_for()
            page.evaluate(SCRUB)
            lead = page.locator("#view").inner_text()
            for item in ("76", "70", "25", "0", "reject"):
                if item not in lead:
                    print("lead missing " + item, file=sys.stderr)
                    return 4
            mark("stitch")
            page.wait_for_timeout(14000)
            page.locator("text=Freelance fit").first.scroll_into_view_if_needed()
            mark("scores")
            page.wait_for_timeout(20000)
            page.locator("text=Quality assurance").first.scroll_into_view_if_needed()
            mark("qa")
            page.wait_for_timeout(14000)

            page.locator("button[data-view='activity']").click()
            page.locator("text=goip-orchestrator").first.wait_for()
            page.evaluate(SCRUB)
            mark("switch_screen")
            page.wait_for_timeout(24000)

            page.locator("button[data-view='settings']").click()
            page.locator("text=Secrets are not returned").wait_for()
            page.evaluate(SCRUB)
            mark("settings")
            page.wait_for_timeout(14000)

            page.locator("button[data-view='overview']").click()
            page.locator("text=Companies stored").wait_for()
            page.evaluate(SCRUB)
            mark("return")
            page.wait_for_timeout(10000)
            mark("app_end")
        finally:
            context.close()
            browser.close()
            if video is not None:
                src = Path(video.path())
                target = OUT / "goip-browser.webm"
                if src.exists() and src.resolve() != target.resolve():
                    src.replace(target)
                print(f"video {target} exists={target.exists()}", flush=True)
            if cues:
                CUES.write_text(json.dumps(cues, indent=2) + "\n", encoding="utf-8")
        return code


if __name__ == "__main__":
    raise SystemExit(main())
