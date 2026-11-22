# Switch live proof

Room: `GOIP Opportunity Intelligence`  
Room id: `8b33bb27-9fb9-4b9a-8b47-592b0df0a956`  
Agent API: `http://127.0.0.1:50990`  
Gateway used for the human message: `http://127.0.0.1:50990/gateway`

Agents registered and given sockets: goip-discovery, goip-company-research, goip-technical-intelligence, goip-qualification, goip-strategy, goip-quality-assurance, goip-orchestrator. Keys are in `goip/data/secrets/switch-agents.json` and are not copied here. Owners reported at registration were `Agent Bootstrap`. Addressing was changed from `owner_and_owner_agents` to `anyone` so a room member who is not that owner can mention them. Room membership is still required to post.

| Check | Result | Evidence |
|---|---|---|
| Health | Verified | `GET /health` on port 50990 returned `{"status":"ok"}` |
| Registration | Verified earlier in this session | Seven agents exist and authenticate to the socket |
| Room | Verified | `read_context` returns this room id |
| Agent task delivery | Verified | Run `8611aed0-4395-4b7c-bc61-fde51cabd8b9`. Local rows show orchestrator `out/delivered` and the specialist `in/received` for each stage, then `GOIP-RESULT` back |
| Human instruction | Verified as an automated admin session | Gateway `POST /chats/{room}/messages` as user Admin, kind `human`, message `sw_fd267860d3db4fc691c9e8b595775e5b` |
| Agent response | Verified | goip-company-research posted the Tencent follow-up. Local row at 2026-11-08 16:39:00Z. No draft was created |
| First admin attempt | Refused by Switch | Message `sw_a636c5e9fab84368aa2b031e5da44bfb`. The orchestrator answered that the operator had restricted who can address it. That was before addressing was set to `anyone` |
| Console UI | Not verified | Cursor Computer Use reported that Accessibility and Screen Recording are off |
| Independent person at the keyboard | Not verified | The admin exchange was performed by this session through the gateway |

`read_context` shows both the admin message and the research reply in the room. A local database row is not treated as delivery. Delivery for agent tasks is the Switch operation result plus the other agent's received row.

Sockets dropped once with close code 1006 during a restart (`no close frame received or sent`) and the client reconnected. Health now follows whether all seven sockets have reached `connection_state`, and a later successful state clears the stale error.
