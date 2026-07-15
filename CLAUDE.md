# AEGIS — Project Rules for Claude Code

## AWS cost guardrails (NEVER violate without asking first)
This is a student hackathon project on the AWS **Free Plan**. Surprise bills are unacceptable.
Before creating ANY AWS resource, obey these rules. If a task seems to require breaking one,
STOP and ask me first — do not work around it silently.

- NEVER create a NAT Gateway. (~$33/month just for existing; not needed here.)
- NEVER use RDS — the database is Neon (managed Postgres 17, serverless). No RDS instances.
- NEVER allocate Elastic IPs, or leave any unattached.
- Do NOT create standalone Load Balancers — App Runner provides HTTPS without one.
- Only ONE region. No resources in a second region.
- Set CloudWatch log retention to 7 days on any log group you create (never default/forever).
- Always tag resources with `project=aegis` so they're easy to find and tear down.

## Standing config (use these exact values)
- Region: **ap-south-1 (Mumbai)** — for latency + India DPDPA data residency.
- Database: **Neon** (managed Postgres 17, serverless). No local Postgres instance. Connection string read from `DATABASE_URL` env var; for local dev, put it in `.env` (gitignored).
- Deploy target: **App Runner** (single container). Not EKS, not raw EC2, not ECS-by-hand.
- The app is a SINGLE container: FastAPI serves both the API and the static dashboard.

## Verification discipline
- Never report a task "done" until you've run the actual command and shown me the output.
- If something fails, show the error and your fix — don't silently work around it.
