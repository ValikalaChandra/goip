# Judge's read

I am scoring the submission as it stands after this pass, not the pitch I wish it were. I am not assigning points. The weights are the published ones: Switch 30, technical execution 25, creativity and impact 25, presentation 20.

## Use of Switch

Strengths. The collaborative path is real: seven registered agents, one room, websockets, `GOIP-TASK` and `GOIP-RESULT`, and a Console recording of that room. A separate earlier screenshot shows a human sentence and a strategy reply. The article tells a first-time user what Switch is not.

Weaknesses. The product can run without Switch. A judge who wants "it would stop" will not get that, and the film says so on purpose. The human reply in the screenshot is the outreach guard firing on a substring, not the orchestrator doing the research the human asked for. The final recording did not type a new message.

Evidence. `switch_runtime.py`, Switch `/health`, the Console clip, `gui-roundtrip.png`.

Risk. A judge skims the old root README, or `SYSTEM.md` before the correction, and thinks the bridge was missing or that Telegram is the integration.

Highest-impact improvement. One new Console exchange, typed by you, that asks the orchestrator a question which does not contain "send outreach", with the reply left on screen. I did not send that message.

## Technical execution

Strengths. Insert-only evaluation versions, three scores, QA that can reject a service, unlinked signals left unlinked, 34 tests on this pass, loopback bind, secrets kept out of the film.

Weaknesses. The API was down during the rebuild, so this pass did not re-click the UI. The original 21 labels are still the first scorer. Sixty-five signals have no company. Discovery is four sources.

Evidence. PostgreSQL counts, pytest output, the Stitch page in the film.

Risk. The test count gets quoted as if it included live Switch. It does not. The article says that.

Highest-impact improvement. Approve or explicitly reject the qualification migration, then show one old lead before and after. That is a write. It was not done.

## Creativity and impact

Strengths. The useful idea is a desk that can refuse a pitch. Stitch.ai makes that concrete: 76 beside 0, and a service line the source does not support.

Weaknesses. The user is one person. There is no evidence someone else runs this. Commercial intent does not change the scores, which is honest and also means the product does not yet close the loop from research to a sent conversation. Nothing is sent, by design.

Evidence. The Stitch sequence in the film and the case study in the article.

Risk. A judge hears "seven agents" and expects seven models with different judgments. The article warns them. The film should be watched, not just the title.

Highest-impact improvement. One paragraph, in the README a judge actually opens, with the 76 / 70 / 25 / 0 example above the fold. The root README now points at the film and the counts. The Stitch numbers are still mainly in the article.

## Presentation and documentation

Strengths. The new film spends about two minutes on readable architecture plates and an execution flow. The article has a setup sequence taken from this repo, a real console transcript, and a list of limits. The old film and the old article were kept.

Weaknesses. The website footage is from the earlier recording, not a process started today. The file is still a modest bitrate because the frames are mostly still, even at CRF 16. Someone cloning the project still depends on already owning Switch Console. I did not document a Console installer, because this repo does not contain one.

Evidence. `FINAL_DEMO.mp4`, `ARTICLE.md`, `ARCHITECTURE_EXPLANATION.md`.

Risk. Two films and two articles in the folder. The hackathon README now points at `FINAL_DEMO.mp4` and `ARTICLE.md`. `final-demo.mp4` is the previous 4:30 cut and should not be the one you upload.

Highest-impact improvement. Upload `FINAL_DEMO.mp4` and put the same path in the submission form. Watch the Switch section once with the sound off before you do.

## Best Blog, separately

Clarity. A first-time reader can follow the problem, the three scores, and the Stitch refusal. The setup section is specific to this machine's ports.

Accuracy. Counts were queried. The substring bug is described the way the code behaves. Telegram is a limit, not the demo.

Reproducibility. Postgres, env example, pytest, and `app.main` are real commands. Switch Console installation is not, because I would have been inventing it. A reader with Console already running can attach GOIP. A reader without Console cannot finish from this article alone.

Usefulness. The warning about "do not send outreach" containing "send outreach" is the kind of thing a first room teaches badly if nobody writes it down.

Architecture. The prose names the same paths as the TikZ pages. The pictures are not left to speak alone.

Authenticity. The partial run, the unlinked signals, the API being down, and the wrong reply in the console are in the article. That is the voice of the build.

I would not call the blog finished for a reader who has never installed Switch. I would call it finished for a reader who has the Console running and wants to see how a room, a model, and a database were kept apart.
