# Wahu Collections Reconciliation Platform

Daily/weekly collections reconciliation across Wahu Fleet (WF) and TSA fleets. 12-agent workflow driven by SOP requirements.

## Sprint 0 Scaffold

**Backend:** FastAPI + Postgres + Pydantic schemas  
**Frontend:** Next.js 14 + Tailwind  
**Scheduler:** APScheduler (12-step daily/weekly triggers)  
**Storage:** Filesystem (dev) / S3-compatible (prod)  

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+
- Node.js 18+

### Local Development

1. **Start services:**
   ```bash
   docker-compose up -d
   ```

2. **Backend setup:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Run FastAPI:**
   ```bash
   cd api
   uvicorn main:app --reload --port 8000
   ```

4. **Frontend setup:**
   ```bash
   cd web
   npm install
   npm run dev
   ```

5. **Access:**
   - Frontend: http://localhost:3000
   - API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

### Environment

Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
```

## Architecture

**12-Step Agent Workflow (SOP §4):**
1. Rider Population (daily 06:00)
2. Org Split (daily)
3. Weekly Billing (Sunday 23:59)
4. Payments Reconciliation (daily)
5. Suspense & Exceptions (daily)
6. Bolt Earnings Ingest (weekly)
7. Earnings Deduction (weekly)
8. Rider Statements (weekly)
9. MTD Ranking (daily 07:00)
10. SMS Reminders (Wed 10:00, Fri 09:00)
11. Collections Memo (Mon 10:00)
12. QB Posting (Mon 11:00)

**Data Sources (MVP):**
- Slot 1: MTN MoMo daily (CSV)
- Slot 2: Telecel MoMo daily (CSV)
- Slot 3: Wahu Hero app daily (CSV)
- Slot 4: Zoho Billing invoices (API export)
- Slot 5: Zoho Subscriptions (API export)
- Slot 6: Bolt Food weekly earnings (CSV)

**Three Formal Reports:**
- **Report A:** Collections (active billing)
- **Report B:** Recovery (aged debt, churned riders)
- **Report C:** Completed Riders (fully paid-out)

## Database Schema

See `schema.sql` for full Postgres DDL. Key tables:
- `users` (RBAC)
- `runs` (step orchestration)
- `step_results` (output tracking)
- `exceptions` (alerts)
- `suspense_items` (unmatched receipts)
- `payment_application_log` (FIFO idempotency)
- `completion_events` (Report C)
- `mtd_rankings` (Step 9 output)

## Development Workflow

**Pydantic Models:** `api/models/schemas.py`  
**Agents:** `api/agents/step_*.py` (pure functions returning `AgentResult`)  
**Integrations:** `api/integrations/{zoho,hubtel_sms}/`  
**Storage:** `api/storage/` (filesystem/S3 abstraction)  
**Scheduler:** `api/scheduler/` (APScheduler wired for 12 steps)

## Deployment

Staging/prod uses S3 for file storage and deployed to cloud platform (TBD).

## References

- **SOP:** Wahu_Collections_Reconciliation_Procedure.docx (authoritative)
- **Data Design:** See `DATA_DESIGN.md`
- **Sprint Plan:** Sprints 0–10 in SOP §21
