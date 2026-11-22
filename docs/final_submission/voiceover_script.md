# Voice-over script

Narration is rendered. Reference memo: `switch/voice_sample/20261109 145722.m4a` (copied to `video/voiceover/source/`). Local clone with **mlx-audio** and `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit` on Apple Silicon. Reference transcript from on-device Whisper. Sixteen scene clips in `video/voiceover/segments/`, master track `video/voiceover/narration_full.wav`, muxed into `GOIP_FINAL_DEMO.mp4`.

Times below match the silent film's scenes. They will move if the cut changes. Pronounce GOIP as the letters G-O-I-P. Pronounce FastAPI as "fast A-P-I". Pronounce Stitch.ai as "Stitch dot A-I". Say websocket as one word.

| Scene | Start | End | Say this |
| --- | --- | --- | --- |
| Open | 0:00 | 0:12 | I built GOIP because finding a company is easy, and deciding it deserves a pitch is not. The desk can research a lead and still refuse it. |
| Dashboard | 0:12 | 0:40 | These are stored rows. Twenty-seven companies. Sixty-five signals are not linked to a company. Fourteen high-priority labels and seven qualified labels are the first scorer. They have not been rewritten. |
| List | 0:40 | 0:54 | Historical score, business signal, technical evidence, and freelance fit stay in separate columns. |
| Filter | 0:54 | 1:06 | Six leads are in review. This search shows Stitch.ai only. Opening the row does not change it. |
| History | 1:06 | 1:20 | The historical score is still 76. That number is the old composite. |
| Scores | 1:20 | 1:40 | The later reading is business 70, technical 25, freelance fit 0. A launch can be notable and still not be a freelance job. |
| QA | 1:40 | 1:54 | Quality assurance rejected the service line, not the company. The company stays in review. Nothing was sent. |
| Map | 1:54 | 2:16 | FastAPI receives the browser and runs each stage. Switch is the room. OpenRouter is the model. Those are three different things. |
| Stage | 2:16 | 2:38 | One stage is a task posted into the room, work done in GOIP, and a result posted back. The agents do not all run at once. |
| Refusal | 2:38 | 2:58 | The three scores stay apart. Commercial intent is not added into them. A person still has to decide. |
| Console | 2:58 | 3:16 | This is the existing room. I did not type during this recording. |
| Earlier reply | 3:16 | 3:28 | This still is from an earlier recording. I addressed the orchestrator. The strategy agent replied that no outreach was sent. |
| GOIP Switch view | 3:28 | 3:50 | GOIP stores those messages itself. Seven agents are members of the room. |
| Settings | 3:50 | 4:02 | Settings shows what is configured. The secret values are not on the page. |
| Limits | 4:02 | 4:18 | Sixty-five signals are still unlinked. The older labels are still the first scorer. Thirty-four backend tests passed. This card is not a live terminal. |
| Close | 4:18 | 4:32 | The desk can research a company and still refuse to pitch it. Switch is the room where that argument is visible. |

The clock at the end depends on the encode. Read `captions.srt` after the render and slide these if a scene moved.

When the sample is in place, generate one audio file per row, keep the source file untouched, and do not send the sample to a remote API unless I have said that is allowed.
