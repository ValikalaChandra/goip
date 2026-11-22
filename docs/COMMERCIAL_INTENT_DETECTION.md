# Commercial intent detection

Commercial intent is computed from stored source text when a lead is read. It is not written onto the opportunity, and it is not added into business signal, technical evidence, or freelance fit.

| Class | Meaning |
|---|---|
| explicit_external | Freelance, contractor, consulting, RFP, outsourcing, or vendor language |
| strong_indicator | A contract role or a request for external technical help |
| indirect_indicator | A launch, funding event, or hiring mention, without an external purchase |
| no_demonstrated_intent | None of that language |
| unknown | No stored text |

On the 22 leads the read-time result was 17 indirect indicators and 5 with no demonstrated intent. None were explicit. Stitch.ai is indirect: the launch sentence describes a workspace for freelancers. It does not ask for a freelancer.

A full-time vacancy would be hiring evidence, not freelance evidence, unless the posting says contract or freelance. No careers-page connector is installed, so no vacancy was checked for freshness and none is described as open.

Service recommendations still require a technical requirement that the text states. Commercial intent does not create a service by itself. If the requirement is missing, the version-2 result remains further research.
