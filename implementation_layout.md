### This is just a rough and sample implementation disscuesd for this problem statment 
---

**Stage 1 — Document Parser**

This is pure deterministic code, no LLM needed. Use `pymupdf` or `pdfplumber` to extract text from the PDF, then regex + heuristics to segment it into a tree: `Section → Subsection → Clause`. The key output is a list of *chunks*, each tagged with its source location (e.g. `Section 2.2(c)`). Cross-references like "Refer Section 4.1" get resolved here too — you build a lookup map so the extractor in Stage 2 can follow them.

---

**Stage 2 — LLM Rule Extractor**

This is where the agent thinking goes. For each chunk, you call the LLM with a structured prompt that asks it to extract one or more rules in a specific JSON skeleton. The trick is to pass the chunk *plus* any resolved cross-references so the LLM has full context. Use a chain-of-thought style prompt: ask it to first identify the *type* of rule (threshold, tax check, approval routing), then fill in the `condition` / `action` / `exception` fields. Also ask for a confidence score (0–1) and a flag if anything is ambiguous. Low-confidence rules go into a human-review queue.

---

**Stage 3 — Rule Structurer**

This is a deterministic post-processor. Takes the LLM's raw JSON output and normalizes it — validates field names, resolves formula strings like `"po_amount * 1.10"` into a structured operand tree, deduplicates identical rules extracted from cross-referenced sections, and stamps every rule with its `source_clause`.

---

**Stage 4 — Conflict Detector**

Again mostly deterministic. Load all rules into memory, then check: do any two rules have overlapping `condition` ranges (e.g. both claim to handle invoices in the 1L–10L band) but different `action`s? For the approval matrix this is a simple range-overlap check. For tax rules it's a logical satisfiability check. Flag the pairs with the conflicting clause references.

---

**Stage 5 — Execution Engine (bonus)**

A simple rule runner. Takes a sample invoice JSON and evaluates each rule's condition tree against it. Returns a list of `{rule_id, result: pass|fail, reason}`. This is what proves the output is actually deterministic and machine-executable.

---

**The agent/chain glue**

You can wire stages 2–3 as a LangGraph or a simple Python pipeline where each stage is a node. Stage 2 might loop — if confidence is low on a chunk, retry with a more targeted prompt. Stage 4 and 5 are just pure Python functions called after the LLM work is done. You don't need a heavyweight framework; a clean Python class per stage with a `run(input) → output` interface is enough.



### more details 
Let me lay out the full system design before you write a single line of code.Here's the complete system architecture — full stack, all 5 bonus features included.Now here's the full breakdown of every decision — tech stack, folder structure, and how each bonus maps to actual code.

---

## Tech stack decisions

**Backend — FastAPI (Python)**

FastAPI is the right call here because you need SSE streaming (pipeline progress to the UI), async LLM calls, and clean Pydantic models for your rule schema. Use `pdfplumber` for PDF parsing (better than PyPDF2 for tables and structured text), `anthropic` SDK for LLM calls, and `smtplib` or `sendgrid` for email.

**Frontend — Next.js (App Router)**

Use App Router with React Server Components for the static pages, client components only where you need interactivity. `React Flow` handles the visual rule graph (Bonus 3) — it's purpose-built for node/edge diagrams and saves you a ton of work. `React Query` for data fetching and `Zustand` for pipeline state. Tailwind for styling.

---

## Folder structure

```
project/
├── backend/
│   ├── main.py                  # FastAPI app, routes
│   ├── pipeline/
│   │   ├── parser.py            # Stage 1 — PDF/text → chunks
│   │   ├── extractor.py         # Stage 2 — LLM rule extraction
│   │   ├── structurer.py        # Stage 3 — normalize to schema
│   │   ├── conflict_detector.py # Stage 4 — overlap/contradiction
│   │   └── engine.py            # Stage 5 — execute against invoice
│   ├── bonus/
│   │   ├── email_notifier.py    # Bonus 1 — email on deviation
│   │   ├── graph_builder.py     # Bonus 3 — build node/edge data
│   │   └── confidence.py        # Bonus 4 — scoring logic
│   ├── models/
│   │   ├── rule.py              # Pydantic Rule schema
│   │   ├── invoice.py           # Pydantic Invoice schema
│   │   └── conflict.py          # Pydantic Conflict schema
│   └── db.py                    # SQLite via SQLAlchemy
│
└── frontend/
    ├── app/
    │   ├── page.tsx             # Upload + pipeline trigger
    │   ├── rules/page.tsx       # Rule explorer (searchable table)
    │   ├── tester/page.tsx      # Invoice tester + results
    │   ├── conflicts/page.tsx   # Conflict viewer
    │   ├── graph/page.tsx       # React Flow rule graph (Bonus 3)
    │   └── emails/page.tsx      # Email notification log (Bonus 1)
    ├── components/
    │   ├── PipelineProgress.tsx # SSE consumer, live stage updates
    │   ├── RuleCard.tsx
    │   ├── ConflictBadge.tsx
    │   └── ConfidenceBar.tsx    # Bonus 4 — visual confidence score
    └── lib/
        ├── api.ts               # All fetch calls
        └── store.ts             # Zustand state
```

---

## How each bonus maps to actual code

**Bonus 1 — Email notifications** — `email_notifier.py` gets called by the rule engine whenever it fires a deviation action (e.g. `ESCALATE_TO_FINANCE_CONTROLLER`). It pulls the notification config right off the rule object (`rule.notification.to`, `rule.notification.within_minutes`) and sends via SMTP. The email log page in the UI just reads a `notifications` table in SQLite.

**Bonus 2 — Rule execution engine** — `engine.py` takes a `dict` (the sample invoice JSON) and a list of `Rule` objects. It walks each rule's condition tree recursively, evaluates it against the invoice fields, and returns `{rule_id, result, reason, matched_fields}`. The invoice tester page in the UI lets you paste invoice JSON and see pass/fail per rule in real time.

**Bonus 3 — Visual rule graph** — `graph_builder.py` converts your rules into a `{nodes: [], edges: []}` format that React Flow can render directly. Nodes are rules/decisions, edges are the routing paths (auto-approve → done, escalate → finance controller, etc.). The graph page in Next.js just fetches this JSON and hands it to `<ReactFlow>`.

**Bonus 4 — Confidence scoring** — The LLM extractor already asks for a confidence score per rule in its prompt. `confidence.py` applies a second pass: if a rule's conditions reference a cross-linked section and that section was also parsed, confidence goes up; if the clause text is ambiguous (phrases like "may require" or "at discretion"), it goes down. Rules below 0.7 get flagged with a `needs_review: true` field and show a yellow badge in the UI.

**Bonus 5 — Multi-doc support** — this is actually free once your pipeline is clean. The upload page accepts multiple files. Each file gets its own `document_id`, runs through the same pipeline, and its rules are stored with that `document_id`. The rules explorer has a document filter dropdown. Conflict detection runs both within a doc and across docs.

---

## The one tricky piece — SSE streaming

The pipeline takes 20–60 seconds to run (multiple LLM calls per chunk). You don't want the user staring at a spinner. Wire it up like this:

- `POST /upload` kicks off the pipeline as a background task and returns a `job_id` immediately
- `GET /jobs/{job_id}/stream` is an SSE endpoint that emits events as each stage completes: `{stage: "extractor", status: "done", rules_found: 14}`
- `PipelineProgress.tsx` in Next.js uses `EventSource` to consume this stream and updates a Zustand store that drives a live progress bar

This is the detail that makes the demo feel genuinely impressive rather than just a slow API call.

---

Want me to start with the backend scaffolding (the FastAPI app + Pydantic models + pipeline skeleton), or the frontend first?