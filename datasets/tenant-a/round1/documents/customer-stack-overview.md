# Marlowe Freight Group: stack overview (as of the discovery call)

Prepared by Dana Okafor, from two calls with the platform engineering team.

Marlowe moves refrigerated and dry freight across the US Midwest and Southeast with about 3,100 tractors and 9,400 trailers. Every tractor reports telematics and ELD (electronic logging device) data every 15 seconds.

## Compute and delivery
- Six EKS clusters on AWS (two production regions, us-east-2 and us-east-1, plus staging, data and two shared tooling clusters).
- About 420 microservices, mostly Go and Java 17, deployed with Argo CD. Kafka (MSK, 18 brokers) carries telematics.
- Platform engineering is 34 people under Ines Calderon, VP Platform Engineering.

## Observability today
- Logs: Splunk Cloud, roughly 11 TB per day ingested. Annual contract about $4.2M, renewal 31 March 2027.
- Metrics: Prometheus per cluster, remote-written into Grafana Mimir. About 62 million active series.
- Traces: OpenTelemetry SDKs in roughly 70 percent of services, sent to a self-hosted Tempo that the team describes as "fragile". The rest is vendor APM agents on legacy Java services.
- Collection: OpenTelemetry Collector as a DaemonSet, no central routing layer. Every team writes its own processors.

## Numbers the team quoted
- Observability spend grew 38 percent year over year; headcount grew 6 percent.
- Mean time to resolve Sev-2 incidents: 47 minutes.
- Splunk daily ingest includes an estimated 45 percent of debug and health-check logs nobody queries (from a sampling of saved searches, not a full audit).
