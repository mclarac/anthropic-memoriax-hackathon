# Competitive update from Pellucid product management, 9 October 2026

**Cascadia Observe** (competitor) announced a bundled telemetry pipeline included in its observability platform at no extra charge, for customers who commit to its backend. It supports OTLP, but routing to third-party backends is limited to three destinations and unsupported for Splunk HEC at general availability.

What it means for Marlowe: Marlowe is a Splunk customer with Mimir and Tempo on the side, so a bundle that routes mostly to its own backend is a weak fit. Expect Cascadia to pitch "free pipeline" and a full backend migration together.

**Our response, shipping in Tracebase 4.2 (GA 20 October):**
- Lossless archive tier: unmodified copies of selected streams written to the customer's S3 bucket with object lock, in parallel with the sampled path.
- Per-stream bypass: streams tagged as compliance-class are never filtered or sampled, and the bypass is visible in an audit report.
- Splunk HEC output with indexer acknowledgement support.

Do not claim Cascadia is unable to replace Splunk; say it routes to few destinations.
