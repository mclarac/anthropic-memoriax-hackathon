# Objections raised in earlier calls

| ID | Objection | Raised by | Call date | Status |
|---|---|---|---|---|
| O1 | Another hop in the data path is another thing that can fail during an incident, exactly when we need logs. | Ines Calderon | 2026-09-02 | open |
| O2 | If the pipeline drops or samples traces, engineers stop trusting what they see and go back to asking for everything. | Theo Bell, staff SRE | 2026-09-02 | open |
| O3 | We can get the same savings by renegotiating the Splunk renewal and cutting retention ourselves. | Priya Venkataraman, FinOps lead | 2026-09-16 | open |

Notes from Dana: O1 is the one Ines keeps returning to. She was burned two years ago by a Kafka-based log shipper that back-pressured the app tier. O3 is a negotiating position more than a belief; FinOps has not actually modelled it.
