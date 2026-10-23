# Call notes: Marlowe Freight, 14 October 2026

Attendees: Ines Calderon, Theo Bell, Priya Venkataraman, Marlowe's compliance counsel Reggie Foss (new to the thread), Dana Okafor.

## What changed
- The dual-collector design from the 30 September architecture review landed well. Ines said O1 (extra hop failing during incidents) is no longer her blocker. Theo Bell agreed after seeing the fail-open demo.
- **New objection (O4): log retention for compliance.** Reggie Foss says ELD driver hours-of-service logs must be retained unsampled for 6 months for DOT audit, and some dispatch audit logs for 7 years. He does not want any component that can drop or sample those streams, and asked how we would prove to an auditor that the pipeline never touched them. Ines says if legal says no, it is no.
- Priya has now modelled the Splunk renegotiation: about 12 percent savings, not the 30 she assumed. O3 is weaker but still open.
- Final pitch moved to 22 October, and Tomas Hjelm will attend the whole session.

## Open
- Whether a lossless archive to S3 would satisfy Reggie, and who at Marlowe owns the audit evidence.
