# Recording report for the architecture-led cut

Date: 9 November 2026.

## What was encoded

`goip/docs/hackathon/demo-video/FINAL_DEMO.mp4`

Probe after encode: 1920×1080, 30 fps, H.264, duration 00:05:12.33, about 9 MB, average video bitrate about 227 kb/s. The encoder used CRF 16. Average bitrate stays low because most frames are still. Intra frames were encoded at a very low quantizer, which is what keeps the UI text and the diagram labels sharp. The previous cut is `final-demo-v1.mp4` and also `final-demo.mp4` (the 4:30 file). Upload `FINAL_DEMO.mp4`.

Audio is silent.

## Answers

1. The website was not opened again. Port 8001 refused connections. The overview footage is the earlier Playwright recording. Its cards match the database read the same day: 27 companies, 65 unlinked, 6 needs review, 14 high priority, Switch connected.
2. Switch Console was not opened again. The room clip is the earlier window recording. Switch `/health` did answer `ok` during this pass, and Mattermost's ping returned 200.
3. The film shows the title, overview, opportunity list, Stitch.ai, the three scores, quality assurance, six architecture plates, the execution flow, the Console room, the earlier human-reply still, the GOIP Switch screen, Settings, a limits card, and the end card.
4. The Console clip shows stored stage messages. The human sentence is the labeled still from `docs/final-sprint/gui-roundtrip.png`, identified on screen as an earlier recording.
5. No full-desktop capture was made in this pass.
6. No new permission was requested.
7. `architecture.tex` and `execution-flow.tex` were written and compiled with Tectonic.
8. `architecture.pdf` has six pages. `execution-flow.pdf` has one.
9. `architecture.svg` and `architecture.png` are page one. `layer-1.png` through `layer-5.png` and `execution-flow.png` are the plates in the film.
10. `captions.srt` and `captions.ass` match this cut. `CAPTIONS.md` is the editable copy. `captions-v1.srt` is the previous timing.
11. The MP4 exists at the path above.
12. 5 minutes 12 seconds, 1920×1080, 30 fps.
13. Not done: a fresh website recording, a new Switch message, a live pytest terminal in the film, Telegram, and a side-by-side layout.

The limits card is typeset. It is not a recording of a terminal. The article and this report say the 34 tests were a real pytest run, in memory, during this pass.
