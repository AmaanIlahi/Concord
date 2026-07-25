# Concord — Architecture Plan

A generic entity-matching and conflict-detection system: upload any two datasets,
get back matched records, flagged conflicts, and confidence scores — validated
against real benchmark data, not a single hardcoded example.

---

## 1. Goal

Demonstrate the core FDE/data-integration skill: take messy, inconsistent
multi-source data, normalize it, decide what's trustworthy, and surface
uncertainty instead of silently guessing — in a way that generalizes across
datasets, not just one demo case.

---

## 2. Tech stack

| Layer | Choice |
|---|---|
| Backend | FastAPI |
| Embeddings | OpenAI `text-embedding-3-small` |
| Vector search / DB | Postgres + pgvector |
| Ambiguous-match judge | LLM (GPT-4o-mini), structured JSON output |
| Frontend | Minimal static HTML/CSS/JS served by FastAPI (no framework) |
| Deployment | Single service — Render or Fly.io (backend + static frontend together), Supabase for managed pgvector Postgres |

---

## 3. Data model (Postgres)

```sql
datasets (
  id UUID PRIMARY KEY,
  name TEXT,
  source_filename TEXT,
  schema_mapping JSONB,       -- inferred column -> canonical field mapping
  uploaded_at TIMESTAMP
)

records (
  id UUID PRIMARY KEY,
  dataset_id UUID REFERENCES datasets(id),
  raw_json JSONB,             -- original row, untouched
  canonical_json JSONB,       -- normalized fields per schema_mapping
  embedding VECTOR(1536)
)

match_jobs (
  id UUID PRIMARY KEY,
  dataset_a_id UUID REFERENCES datasets(id),
  dataset_b_id UUID REFERENCES datasets(id),
  status TEXT,                -- pending / running / done / rejected_incompatible
  compatibility_check JSONB,  -- verdict, reasoning, field_overlap/domain/centroid scores
  created_at TIMESTAMP
)

matches (
  id UUID PRIMARY KEY,
  job_id UUID REFERENCES match_jobs(id),
  record_a_id UUID REFERENCES records(id),
  record_b_id UUID REFERENCES records(id),
  blocking_score FLOAT,       -- cosine similarity from pgvector search
  hybrid_score FLOAT,         -- combined string + embedding score
  llm_verdict JSONB,          -- null if not sent to judge
  final_status TEXT           -- auto_accepted / flagged / rejected
)

conflicts (
  id UUID PRIMARY KEY,
  match_id UUID REFERENCES matches(id),
  field_name TEXT,
  value_a TEXT,
  value_b TEXT,
  conflict_type TEXT          -- unit_mismatch / stale_data / contradiction / formatting_difference
)

eval_runs (
  id UUID PRIMARY KEY,
  eval_type TEXT,             -- matching_accuracy / conflict_accuracy / calibration / compatibility_check / cost_efficiency
  dataset_pair_name TEXT,      -- e.g. "amazon_google", "walmart_amazon"
  metrics JSONB,               -- precision/recall/F1, calibration buckets, confusion matrix, etc.
  run_at TIMESTAMP
)
```

---

## 4. Pipeline stages

1. **Upload** — accept two files (CSV/JSON), store raw rows in `records.raw_json`
2. **Schema mapping** — LLM call: given both files' headers + sample rows,
   infer a canonical field mapping; store in `datasets.schema_mapping`;
   populate `canonical_json` per record
3. **Domain compatibility check** — before any matching runs, decide whether
   the two datasets are even plausibly the same kind of thing. Three signals,
   combined into one verdict:
   - **Field overlap** — how many canonical fields the schema-mapping step
     matched across *both* datasets (e.g. name, price, category). Below a
     minimum (e.g. fewer than 2 shared identifying fields) is a strong signal
     of incompatibility
   - **Domain classification** — one LLM call per dataset: "what kind of
     real-world entity do these rows represent?" (e.g. "electronics products",
     "restaurant listings", "employee records"). Compare the two labels
   - **Embedding centroid distance** — average the embeddings of a sample of
     records from each dataset; low cosine similarity between the two
     centroids means the datasets occupy very different semantic space
   - If the combined signals say "incompatible" (e.g. restaurant data vs.
     electronics data), stop here and return a clear reason instead of
     running matching — this is a cheap, fast rejection *before* the
     expensive blocking/embedding-per-record work, and it directly
     demonstrates "surface uncertainty instead of silently guessing" at the
     dataset level, not just the field level
   - Result stored on `match_jobs.compatibility_check` (JSONB: verdict +
     reasoning + the three signal scores)
4. **Embed** — embed each `canonical_json` record with `text-embedding-3-small`,
   store in `records.embedding`
5. **Blocking** — for each record in dataset A, use pgvector `<->` cosine
   distance to pull top-k candidates from dataset B (avoids full cross join)
6. **Matching (hybrid score)** — combine string similarity (rapidfuzz on key
   fields) + embedding cosine similarity into one score
   - score is high/low confidence → auto-accept / auto-reject, no LLM call
   - score in ambiguous middle band → send to LLM judge
7. **LLM judge** — structured JSON output:
   ```json
   {
     "match": true,
     "confidence": "medium",
     "reasoning": "same product, description differs due to bundle vs single unit",
     "conflicts": [
       {"field": "price", "value_a": "49.99", "value_b": "52.00", "type": "contradiction"}
     ]
   }
   ```
   → populates `matches.llm_verdict` and fans out rows into `conflicts`
8. **Confidence & trust layer** — rule-based decision on top of steps 6-7:
   - match=true, no conflicts → `auto_accepted`
   - match=true, conflicts present → accept match, flag conflicting field(s)
   - match=false or confidence=low → `flagged` for human review
   - below blocking threshold entirely → never surfaced, logged for recall analysis only
9. **Evaluation** — full results-judgement scope covered in Section 8 below;
   results are stored in `eval_runs`, not just printed to a console

---

## 5. API surface

| Endpoint | Purpose |
|---|---|
| `POST /datasets` | Upload a file, returns `dataset_id` + inferred schema mapping |
| `GET /datasets/{id}` | Inspect a dataset's schema mapping and sample records |
| `POST /match` | Kick off a match job between two dataset_ids — runs the compatibility check first; returns 422 with reasoning if datasets are deemed incompatible, otherwise proceeds to matching |
| `GET /match-jobs/{id}/compatibility` | Inspect the compatibility verdict and signal scores for a job, independent of whether matching proceeded |
| `GET /matches/{job_id}` | Matched pairs with scores, conflicts, reasoning |
| `POST /eval` | Run pipeline against a labeled benchmark pair, return precision/recall/F1 |
| `POST /eval/calibration` | Run confidence-calibration check across completed match jobs, return accuracy-by-confidence-bucket |
| `POST /eval/compatibility-check` | Run the compatibility check against a set of known compatible + known incompatible pairs, return pass/fail table |
| `GET /eval/{eval_type}/history` | List past eval runs of a given type, for tracking whether changes improved or regressed results |
| `GET /docs` | FastAPI auto-generated Swagger UI — usable as a live demo surface on its own |

---

## 6. Minimal frontend scope

Three pieces only, plain HTML/CSS + vanilla JS `fetch()`:
1. Upload form — two file inputs, submit to `POST /datasets` twice, then `POST /match`
2. Results table — matched pairs with confidence badges (auto-accepted / flagged / rejected)
3. Expandable row detail — shows field-level conflicts + LLM reasoning per pair

No framework, no build step — served directly by FastAPI's `StaticFiles`.

---

## 7. Public deployment guardrails

- Rate limit uploads per IP (e.g. 3/hour)
- Hard caps: max rows per file, max file size
- Cache embeddings by content hash to avoid re-embedding repeated uploads
- Set an OpenAI usage/budget cap and alert
- Strict file-type validation before any data touches the pipeline
- No persistent storage of uploads beyond a session/TTL; make this explicit in the UI
- Default to a "try with sample dataset" option so most visitors don't need to upload anything

---

## 8. Evaluation & results judging

This is treated as a first-class module, not a one-off script — every run
writes to `eval_runs` so results are inspectable and comparable over time,
not just printed once and forgotten.

**8.1 Matching accuracy** (uses labeled gold pairs shipped with the benchmark datasets)
- Precision, recall, F1 — computed **per dataset separately** (Amazon-Google,
  Walmart-Amazon, Abt-Buy), not pooled, so the numbers prove generalization
  rather than one dataset carrying the average

**8.2 Conflict-detection accuracy** (requires a small hand-labeled set)
- Manually tag conflict type on ~30-50 matched pairs
- Compare against the LLM judge's `conflict_type` output
- Report as a confusion matrix (unit_mismatch / stale_data / contradiction / formatting_difference / none)

**8.3 Confidence calibration** (the most distinctive metric for this project)
- Bucket predictions by declared confidence (high / medium / low)
- Compute actual correctness rate within each bucket
- A well-calibrated system: high-confidence predictions should be correct
  far more often than low-confidence ones. If the gap is small or absent,
  the confidence score isn't doing real work — report this honestly rather
  than hiding it, since it directly demonstrates (or disproves) the
  "surface uncertainty instead of guessing" claim

**8.4 Compatibility-check accuracy**
- Feed a mix of genuinely compatible pairs and deliberately mismatched pairs
  (e.g. Fodors-Zagat restaurants vs. Amazon-Google products)
- Simple pass/fail table: did it correctly accept the compatible ones and
  reject the incompatible ones

**8.5 Cost efficiency**
- % of candidate pairs resolved by the cheap string+embedding score alone
  vs. escalated to the LLM judge
- A well-tuned threshold keeps LLM calls to a minority of cases — this is
  an engineering-judgment signal, not an accuracy signal

All five write structured results into `eval_runs`, retrievable via the
`/eval/*` endpoints — so "how do you judge the results" has a concrete,
inspectable answer in the running system, not just a claim in conversation.

---

## 9. Suggested build order

1. Ingestion + LLM schema mapping (single dataset pair, no matching yet)
2. Domain compatibility check (field overlap + domain classification + centroid distance) — test it explicitly against one compatible pair and one deliberately mismatched pair (e.g. products vs. restaurants) to confirm it actually rejects nonsense input
3. Embed + store in pgvector
4. Blocking via pgvector cosine search
5. Hybrid scorer (string + embedding)
6. LLM judge for ambiguous band, writing `conflicts` rows
7. Confidence/trust rule layer + `/matches` endpoint
8. Evaluation module (Section 8): matching accuracy, conflict-detection accuracy, calibration, compatibility-check accuracy, cost efficiency — build this against multiple benchmark pairs before moving on, since it's what proves everything above actually works
9. Minimal HTML/CSS/JS frontend, including a simple results/eval view
10. Deploy (Render/Fly.io + Supabase), add rate limiting and cost guardrails before making it public
