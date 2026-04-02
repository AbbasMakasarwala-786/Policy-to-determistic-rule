# Document AI — AP/HR Policy Rule Extraction
Video walk through - https://www.loom.com/share/6e8d1b6f84824a7fb8a765c25907e2fa

## Stack
- Backend: FastAPI (Python)
- Frontend: Next.js (App Router, TypeScript)
- LLM: Mistral (`langchain-mistralai`) in hybrid assist mode

## What It Does
- Upload policy docs (`.md`, `.txt`, `.pdf`)
- Parse sections/clauses/subclauses
- Extract rules into structured JSON
- Preserve AP-specific required visibility:
  - `three_way_match`
  - `compliance_tax`
  - `approval_matrix`
- Detect conflicts
- Evaluate rules on sample invoice/claim JSON
- Show filters in UI (category + matched/not matched + required rules quick filters)

## Architecture
The system follows a modular pipeline:

1. `Document Loader`
- Accepts `.md/.txt/.pdf`
- Extracts raw text (`pdfplumber` for PDF)

2. `Document Parser`
- Splits content into `Section -> Clause -> Subclause`
- Captures source traceability (`source_clause`, `section_id`)

3. `Rule Extractor` (hybrid)
- Deterministic-first extraction always runs
- LLM assist (`llm_mode=assist`) refines only weak/generic clauses
- LLM calls are capped with `max_llm_calls`
- Output normalized into deterministic `Rule` schema

4. `Rule Structurer`
- Deduplicates and normalizes rules
- Enforces confidence bounds and review flags

5. `Conflict Detector`
- Detects overlap/contradiction patterns (notably approval and policy-intent conflicts)

6. `Rule Engine`
- Evaluates rule conditions on sample invoice/claim JSON
- Returns `matched/not matched` with reasons

7. `Notifier`
- Emits deviation notifications
- Uses SMTP if configured, otherwise logs notification events

### Runtime Flow
- Frontend uploads document -> backend parses and stores it in memory (`document_id`)
- Frontend runs pipeline -> backend returns rules, conflicts, execution results, notifications (`run_id`)
- Frontend renders:
  - required AP category visibility
  - searchable/filterable rule list
  - conflicts and execution status
  - decision graph visualization

## AI Agents Used during this Assigment 
To build and ship a good system fast. I made use of following AI Agents.
- For building fast building the backend scafolding i use codex with GPT-5.3.
- For testing and major bug fixing i used Claude sonnet 4.6 in rovodev
- For Building minimalistic, clean and user-friendly UI, I used [UI/UX pro max skill's](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) along with codex 


## Project Structure
- `backend/` FastAPI + parser/extractor/conflict/rule engine
- `frontend/` Next.js dashboard + graph + filters

## Quick Start

### 1) Backend
```powershell
cd "C:\Users\91835\OneDrive\Desktop\document AI\backend"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create `backend/.env`:
```env
MISTRAL_API_KEY=your_key
MISTRAL_MODEL=mistral-small-latest
MISTRAL_BASE_URL=https://api.mistral.ai/v1
ENABLE_LLM=true
LLM_TIMEOUT_SECONDS=60
```

Run backend:
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

### 2) Frontend
```powershell
cd "C:\Users\91835\OneDrive\Desktop\document AI\frontend"
npm install
npm run dev
```

Open: `http://localhost:3000`

## API (main)
- `POST /api/v1/documents/upload`
- `GET /api/v1/documents/{document_id}`
- `POST /api/v1/pipeline/run/{document_id}`
- `GET /api/v1/runs/{run_id}`

## Hybrid LLM Mode
Pipeline request supports:
- `llm_mode`: `off | assist | full`
- `max_llm_calls`: integer cap

Default behavior is deterministic-first with selective LLM assist.

## Notes
- If SMTP is not configured, notification events are logged (not sent).
- Sample payloads are in `backend/sample_payloads/`.

