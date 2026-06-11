# SLAP Bug Triage Prototype — Claude Context

## What this project is

A prototype of an agentic bug triage system for **SLAP** (Shop Like A Pro —
Flipkart's GenAI conversational shopping app). It takes a raw bug report email
(as a .txt file), fetches real historical bugs from the FLIPPI Jira project,
finds duplicates, suggests an owner, scores severity, and outputs a
dev-ready Jira ticket draft as JSON.

**This is a prototype only. It never writes to Jira. All Jira access is read-only.**

---

## Project structure

```
slap-bug-triage/
├── main.py                  # Orchestrator — runs the full 8-step pipeline
├── src/
│   ├── parser.py            # Step 2: Claude API parses raw email → BugReport dataclass
│   ├── jira_client.py       # Step 3: Read-only Jira REST v3 wrapper (FLIPPI project)
│   ├── similarity.py        # Steps 4+5: Local embeddings, cosine similarity, dedup, owner routing
│   ├── severity_scorer.py   # Step 6: Claude API scores P0–P4 using bug + similar history
│   └── ticket_builder.py    # Step 7: Assembles ADF Jira JSON draft
├── data/                    # Input bug report emails (.txt files)
│   ├── bug_report.txt                    # original sample
│   ├── bug_01_p0_checkout_crash.txt      # P0 test case
│   ├── bug_02_p1_search_wrong_results.txt # P1 test case
│   ├── bug_03_p2_image_not_loading.txt   # P2 test case
│   ├── bug_04_duplicate_of_bug_report.txt # duplicate test (generic)
│   ├── bug_05_vague_minimal_info.txt     # vague report test
│   ├── bug_dup_FLIPPI3044_secrets.txt    # duplicate of real FLIPPI-3044
│   ├── bug_dup_FLIPPI2905_dedup.txt      # duplicate of real FLIPPI-2905
│   └── bug_dup_FLIPPI2902_auth.txt       # duplicate of real FLIPPI-2902
├── output/                  # Generated ticket drafts land here (gitignored)
├── .env                     # Secrets — never commit
├── .env.example             # Template for .env
└── requirements.txt
```

---

## How to run

```bash
# Install dependencies (first time only)
pip install -r requirements.txt

# Run on default input (data/bug_report.txt)
python main.py

# Run on a specific bug report
python main.py data/bug_01_p0_checkout_crash.txt
python main.py data/bug_dup_FLIPPI2902_auth.txt
```

Output is written to `output/ticket_draft_<timestamp>.json`.

---

## Environment variables (.env)

```
JIRA_EMAIL=angaraju.v@flipkart.com
JIRA_TOKEN=<flipkart atlassian API token>
JIRA_BASE_URL=https://flipkart.atlassian.net
JIRA_PROJECT=FLIPPI
ANTHROPIC_API_KEY=<claude API key>
```

**Jira token**: Already created. Token name: GetJiraInfo_APItoken.
Verified working against flipkart.atlassian.net on 2026-06-10.

**Anthropic API key**: Pending — console.anthropic.com is blocked on Flipkart
network. Key will be provided by the team shortly.

---

## Pipeline steps

```
bug_report.txt (input)
    ↓
[Step 1]  Read raw text from file
[Step 2]  Claude API → parse into BugReport (title, steps, platform, version, impact...)
[Step 3]  Jira REST API → fetch 300 recent FLIPPI bugs (READ ONLY)
[Step 4]  sentence-transformers → embed all 300 bugs locally
[Step 5]  Cosine similarity → find top-5 similar bugs
            → duplicate flag if similarity > 0.88
            → owner suggestion from assignee frequency
[Step 6]  Claude API → score severity P0–P4 using bug + similar history
[Step 7]  ticket_builder.py → assemble ADF Jira JSON draft
[Step 8]  Write output/ticket_draft_<timestamp>.json
```

---

## Production mapping

| Prototype | Production (Flipkart PaaS) |
|---|---|
| bug_report.txt | Gmail email via fk-mart-ai-pulse |
| direct Python calls | Synapse (auth/routing) |
| Python script | Astral (agent runtime) |
| Claude API | Genvoy / FK-GPT |
| sentence-transformers + numpy | Vector One (managed vector DB) |
| Jira REST API (read) | Jira via MART MCP |
| output JSON | Pulse SMTP reply to reporter |

Swapping prototype → production is a one-line change per component.
All business logic stays the same.

---

## Jira details (FLIPPI project)

- **Base URL**: https://flipkart.atlassian.net
- **Project key**: FLIPPI (name: SLAP)
- **Project ID**: 11206
- **Bug issue type ID**: 10036
- **Auth**: HTTP Basic — email:token
- **Search endpoint**: POST /rest/api/3/search/jql (v3, NOT the old GET endpoint which is 410 Gone)
- **Read-only guardrail**: jira_client.py has NO write methods. All writes are OFF by design.

### Real bugs fetched from FLIPPI (verified 2026-06-10):
- FLIPPI-3044: "Grayskull Integration for Secrets in Edison" — P0
- FLIPPI-2905: "Add product family dedup in journey continuation search results" — P0, assignee: Saumya Chauhan
- FLIPPI-2902: "Getting 'Failed to verify' on authenticating with credentials: 7087935097" — P3, assignee: Saumya Chauhan

---

## Duplicate detection logic

- Each bug (new + historical) is embedded using `all-MiniLM-L6-v2` (sentence-transformers)
- Cosine similarity computed between new bug and all 300 historical bugs
- **Similarity > 0.88** → flagged as duplicate candidate
- **Similarity 0.70–0.87** → shown as "similar bug" in draft
- Owner suggestion: most frequent assignee among top-5 similar bugs
- The 3 `bug_dup_FLIPPI*.txt` files are designed to match their respective real tickets

---

## Key constraints (from team design decisions)

1. **No auto-write to Jira** — agent produces draft only, human files the ticket
2. **No auto-merge duplicates** — engineer verifies before linking
3. **Human in the loop always** — this is a deliberate design decision, not a limitation
4. **Read-only Jira access** — jira_client.py enforces this

---

## Current status

- All code written and ready
- Jira token verified working
- Anthropic API key pending
- Sample test data: 9 bug report files in data/
- Not yet run end-to-end (blocked on API key)
