# NowAware — A Personal AI Agent That Notices What Matters

> **"Don't make people repeatedly check everything. Let their agent notice what matters."**

NowAware is a personal AI agent that monitors public information sources (HTML webpages, RSS/Atom feeds, announcements, policy notices, scholarships, regulations) and alerts users only when substantive changes occur that match their stated goals.

It combines autonomous change detection with natural-language understanding, evidence extraction, and a **"Quiet by Default"** philosophy: cosmetic layout edits, copyright year bumps, and telemetry noise are suppressed, while genuine changes are surfaced with side-by-side evidence quotes and recommended next actions.

---

## Key Features

1. **Natural-Language Monitoring Goals:** Express objectives in plain English (e.g., *"Watch this scholarship announcement and alert me if the deadline changes"* or *"Track this RSS feed for new clean energy grant solicitations"*).
2. **Quiet by Default:** Uses diff analysis and semantic classification to ignore layout alterations, ad banners, cookie notices, and minor styling updates.
3. **Evidence-Backed Alerts:** Every alert quotes direct snippets from the source, isolates prior and updated values, and explains why the change matters to your goal.
4. **Zero-Trust SSRF Defense:** Enforces rigorous network safeguards: blocks localhost, private IPv4/IPv6 subnets, AWS/cloud metadata services (`169.254.169.254`), embedded credentials, and redirects.
5. **Dual Architecture Modes:**
   - **Local Demo Mode:** Runs completely offline without cloud credentials using a local SQLite database and preconfigured simulation scenarios.
   - **AWS Cloud Mode:** Leverages Amazon Bedrock (Claude 3.5 Sonnet), Amazon DynamoDB, AWS Lambda scheduled background workers, Amazon EventBridge, and Amazon SES.
6. **Background Scheduled Monitoring:** Works independently of the UI through an event-driven Lambda worker invoked periodically via EventBridge.

---

## Architecture Overview

```
                      ┌──────────────────────────────────────────────┐
                      │              Streamlit Frontend              │
                      │  Dashboard | Alert Inbox | Monitor Config   │
                      └──────────────────────┬───────────────────────┘
                                             │
                      ┌──────────────────────▼───────────────────────┐
                      │       Monitoring Service Orchestration       │
                      │  (Baseline Creation, Fetching, Parser, Diff) │
                      └──────────────┬───────────────┬───────────────┘
                                     │               │
        ┌────────────────────────────▼───┐       ┌───▼──────────────────────────┐
        │       Security Boundary        │       │   Strands Agent & Bedrock    │
        │ - SSRF Validation & DNS Pinning│       │ - Strands Custom Tools       │
        │ - Cloud Metadata Blocker       │       │ - Structured Change Analysis │
        │ - DoS Size & Protocol Caps     │       │ - Evidence & Action Suggest  │
        └────────────────────────────────┘       └──────────────────────────────┘
                                     │
           ┌─────────────────────────┴────────────────────────┐
           ▼                                                  ▼
┌─────────────────────────────┐                    ┌────────────────────────────┐
│      Local Demo Mode        │                    │       AWS Cloud Mode       │
│ - SQLite Repository         │                    │ - Amazon DynamoDB Tables   │
│ - In-Memory / Fixture Tests │                    │ - AWS Lambda Worker        │
│ - In-App Notification State │                    │ - Amazon EventBridge Cron  │
│                             │                    │ - Amazon SES Email Delivery│
└─────────────────────────────┘                    └────────────────────────────┘
```

---

## Directory Structure

```
noaware/
├── app.py                      # Main Streamlit web application
├── requirements.txt            # Production dependencies
├── .env.example                # Configuration template
├── .gitignore                  # Git ignore rules
├── Dockerfile                  # Container definition for App Runner / Docker
├── template.yaml               # AWS SAM Serverless CloudFormation Template
├── README.md                   # Complete documentation
├── .streamlit/
│   └── config.toml             # Theme settings (Dark Navy & Warm Amber)
├── src/
│   ├── config.py               # Application configuration and settings
│   ├── security/
│   │   └── url_validator.py    # Strict SSRF, IP range, and redirect validator
│   ├── schemas/
│   │   ├── monitoring.py       # MonitoringRule and SourceSnapshot schemas
│   │   └── changes.py          # ChangeEvent and ChangeAnalysisResult schemas
│   ├── monitoring/
│   │   ├── fetcher.py          # Safe HTTP client with size & timeout limits
│   │   ├── parser.py           # HTML and RSS/Atom feed parsing engine
│   │   ├── normalizer.py       # Whitespace cleaner & SHA-256 content hashing
│   │   ├── diff_engine.py      # Line-by-line diff and value isolation
│   │   ├── classifier.py       # Heuristic & rule-based change classifier
│   │   └── service.py          # MonitoringService orchestration engine
│   ├── agent/
│   │   ├── prompts.py          # System guardrails & injection defenses
│   │   ├── tools.py            # Custom Strands agent tools
│   │   └── factory.py          # Strands Agent factory (Bedrock / Fallback)
│   ├── storage/
│   │   ├── base.py             # Abstract repository interface
│   │   ├── sqlite_store.py     # SQLite persistence for local/demo mode
│   │   └── dynamodb_store.py   # DynamoDB persistence for AWS mode
│   ├── notifications/
│   │   ├── base.py             # Notification provider interface
│   │   └── ses_email.py        # Amazon SES email dispatcher
│   └── scheduling/
│       └── worker.py           # AWS Lambda handler & scheduled cron worker
├── fixtures/
│   └── scenarios.py            # Baseline HTML/RSS sources and demo scenarios
└── tests/
    ├── unit/                   # 31 comprehensive unit tests
    │   ├── test_security_url.py
    │   ├── test_normalizer_diff.py
    │   ├── test_parser.py
    │   ├── test_classifier.py
    │   ├── test_storage.py
    │   ├── test_service.py
    │   ├── test_agent_tools.py
    │   └── test_worker.py
    └── evaluation.py           # Quantitative evaluation benchmark suite
```

---

## Quickstart & Local Demo Mode

### 1. Installation

Ensure Python 3.11+ is installed, then run:

```bash
git clone https://github.com/nowaware/nowaware.git
cd nowaware

pip install -r requirements.txt
```

### 2. Run Application Locally

```bash
streamlit run app.py
```

The web dashboard will open at `http://localhost:8501`.

By default, NowAware launches in **Local Demo Mode** without requiring any AWS credentials. It comes pre-seeded with two example monitors and five interactive simulation scenarios.

### 3. Interactive Demo Scenarios

In the left sidebar, click **Demo Scenarios** to test the core workflows:
1. **Scenario 1 (Critical Deadline Change):** Foundation moves a deadline from May 15 to April 10. Generates a verified, evidence-backed alert in your inbox.
2. **Scenario 2 (Cosmetic Layout / CSS Noise):** Foundation updates website theme, nav menu, and copyright year. Cleanly suppressed by the *Quiet by Default* filter.
3. **Scenario 3 (New RSS Grant Announcement):** Clean energy feed publishes a new $2M grant. Extracted and notified immediately.
4. **Scenario 4 (Source 503 Outage):** Remote website goes down. NowAware records the retrieval failure without falsely claiming the source was unchanged, and preserves the existing baseline.
5. **Scenario 5 (Duplicate Prevention):** Re-running identical checks detects the duplicate fingerprint and avoids sending repeat alerts.

---

## Testing & Quantitative Evaluation

NowAware includes a test suite covering security, parsing, diffing, classification, storage, agent tools, and scheduled worker handlers.

### Run Unit Tests

```bash
python -m pytest tests/unit -v
```
*(All 31 unit tests pass).*

### Run Quantitative Evaluation Benchmark

```bash
python tests/evaluation.py
```

**Benchmark Results:**
```
============================================================
NOWAWARE QUANTITATIVE EVALUATION BENCHMARK RESULTS
============================================================
Overall Pass Rate:           100.0% (5/5)
Meaningful Change Recall:    100.0%
Noise Suppression Rate:      100.0%
------------------------------------------------------------
[PASS] Meaningful Deadline Change Detection: Correctly classified as meaningful with evidence.
[PASS] Irrelevant Layout Noise Suppression: Irrelevant noise cleanly suppressed ('Quiet by Default').
[PASS] New RSS Feed Opportunity Detection: Correctly classified as meaningful with evidence.
[PASS] Source Outage & Baseline Preservation: Outage caught, baseline preserved.
[PASS] Duplicate Alert Rejection: Second check cleanly deduplicated.
============================================================
```

---

## AWS Cloud Mode Deployment

To run NowAware as an enterprise serverless monitoring system on AWS:

### 1. Prerequisites
- An active AWS Account.
- AWS CLI configured (`aws configure`).
- Model access enabled in Amazon Bedrock for **Anthropic Claude 3.5 Sonnet** (or model ID of your choice).
- A verified Amazon SES sender identity (email address or domain).
- AWS SAM CLI installed (`sam --version`).

### 2. Configure Environment

Copy `.env.example` to `.env` and configure:

```ini
NOWAWARE_MODE=aws
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
DYNAMODB_RULES_TABLE=nowaware-monitoring-rules-dev
DYNAMODB_SNAPSHOTS_TABLE=nowaware-source-snapshots-dev
DYNAMODB_ALERTS_TABLE=nowaware-change-alerts-dev
SES_SENDER_EMAIL=alerts@yourdomain.com
SES_RECIPIENT_OVERRIDE=your-email@yourdomain.com
```

### 3. Deploy Serverless Backend with AWS SAM

Deploy the DynamoDB tables, Lambda scheduled worker, EventBridge rule, and IAM policies:

```bash
sam build
sam deploy --guided
```

SAM will prompt you for:
- **Stack Name:** `nowaware-backend`
- **AWS Region:** `us-east-1`
- **BedrockModelId:** `anthropic.claude-3-5-sonnet-20241022-v2:0`
- **SesSenderEmail:** Your verified SES email address.

### 4. Deploying the Streamlit Web Interface

The frontend can be deployed via:
- **AWS App Runner** using the included `Dockerfile`.
- **Amazon ECS / Fargate**.
- **EC2 or Lightsail instance**.

Build and test the Docker container locally:
```bash
docker build -t nowaware:latest .
docker run -p 8501:8501 --env-file .env nowaware:latest
```

---

## Security & SSRF Defense Model

Every source URL submitted to NowAware undergoes rigorous multi-layer inspection before any network call is dispatched:

1. **Protocol Whitelist:** Only standard `http://` and `https://` schemes are accepted.
2. **Host Resolution & IP Inspection:** Hostnames are resolved via DNS, and all resolved IPs are validated against restricted ranges:
   - Loopback (`127.0.0.0/8`, `::1`)
   - Private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`)
   - Link-local and cloud metadata addresses (`169.254.169.254`, `169.254.0.0/16`)
   - Internal cloud hostnames (`metadata.google.internal`, `instance-data`)
3. **Recursive Redirect Validation:** Every HTTP 301/302 redirect destination is re-validated through the SSRF boundary before following.
4. **Credential Rejection:** URLs containing embedded user info (`user:pass@host`) are immediately rejected.
5. **DoS Body Limit:** Ingestion buffers are strictly capped at 1MB to prevent memory exhaustion.
6. **No Script Execution:** External HTML is parsed purely via BeautifulSoup and feedparser; no JavaScript or browser runtime is executed against external untrusted content.

---

## License

MIT License. Built for the personal AI monitoring challenge.
