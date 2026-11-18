# Contextual reranking and tuning — M5

Method D, `hybrid_contextual`, reranks the **same chunk-candidate union** as
method C, `hybrid`. It adds no documents or embeddings. Hard filters run before
candidate selection; reranking happens before grouping chunks into source
results, so the best excerpt can change. Dates remain filters, never boosts.

Defaults and the example sweep are **untuned placeholders**. No improvement in
research accuracy has been established without the user's labelled dataset.

## Signals and score

For query-token set Q, coverage of text T is `|Q ∩ tokens(T)| / |Q|`, or zero
when Q is empty. Tokenization uses Unicode NFKC, case folding and `\w+`; tokens
are unique. There is no stemming, fuzzy matching, stopword removal or accent
stripping. Repeated occurrences do not increase overlap.

| Signal | Normalized definition |
| --- | --- |
| `rrf` | Raw hybrid RRF divided by theoretical maximum `2/(k+1)` |
| `title_heading` | Maximum of query coverage in the title and in the heading; missing headings contribute zero |
| `keyword_overlap` | Query coverage in the candidate chunk text |
| `source_type` | 1 if its type matches an explicitly supplied soft source-type hint; otherwise 0 |
| `collection` | 1 if its source belongs to the explicitly hinted collection; otherwise 0 |

Every signal is in `[0,1]` before combining. With configured nonnegative weights
`w`, the score is `sum((w_i / sum(w)) * signal_i)`. At least one weight must be
positive; values must be finite and at most 100. Normalized RRF uses a fixed
theoretical denominator, not per-query minimum/maximum scaling. A candidate
appearing in only one list has normalized RRF at most 0.5.

Ties use descending original RRF, then ascending chunk ID. With only `rrf`
weighted, D preserves C's result and excerpt ordering. If all weighted context
signals are absent/zero, the original RRF order breaks ties. Normalized scores
are ranking values, not confidence probabilities.

Configuration defaults:

```json
{"rrf":1.0,"title_heading":0.2,"keyword_overlap":0.2,"source_type":0.1,"collection":0.1}
```

For the API process, set a JSON object in `ECHO_RERANK_WEIGHTS` before startup.
Partial objects inherit defaults; evaluation reports always record the effective
full object. For experiments, set `rerank_weights` in the run configuration.
The shared validated configuration model is the source of defaults; no request
body can override server weights. No model retraining/reindexing is required.

## Soft context versus hard filters

Example authenticated `POST /api/v1/search` body:

```json
{
  "query": "solar battery notes",
  "mode": "hybrid_contextual",
  "source_types": ["pdf", "note"],
  "context": {"source_types": ["note"], "collection_id": 2}
}
```

Here top-level `source_types` excludes other source types; nested context merely
prefers notes and collection 2. Top-level `collection_id` remains a hard filter.
Soft hints never bypass hard filters, add candidates or invent a collection.
An absent/unmatched hint has zero signal. Multiple matching types or memberships
do not multiply the binary signal. Hints are explicit; ECHO does not infer them
from query wording, recency, relevance labels or browsing history.

Keyword/semantic/hybrid modes accept but ignore soft context. Only D consumes
it. This makes the comparison transparent: all methods share query text and hard
filters, while D can also use supplied remembered context. Collect those hints
independently of rankings and relevance judgments; deriving hints from known
positive documents would leak answers into the experiment.

Responses retain all normal source/excerpt references and component ranks.
D additionally includes each hit's original `rrf_score`, five `rerank_signals`,
and top-level `reranking.version` / effective `weights`. No query text, hint
history or content-bearing operational logs are added.

## Evaluation method D

The normal runner now compares A/B/C/D and emits report version 2. Existing M4
datasets/configurations remain usable; omitted context is empty and omitted
weights take the documented placeholders. The new optional dataset query field
uses the manifest's opaque collection ID, not an internal SQLite ID:

```json
"context": {"source_types": ["note"], "collection": "research_notes"}
```

The collection must exist in the declared document memberships. Unlike a hard
filter, a hint may disagree with a positive document's type or collection.
The runner translates context IDs and sends the same request fields to all four
methods. Reports fingerprint the context-containing dataset/selected queries
without exporting raw query text or hints. The reranker formula version and
effective weights are recorded separately from the embedding-model fingerprint.

## Tuning-only weight sweep

The explicit [example grid](../evaluation/weights.example.json) includes an
RRF-only ablation, the placeholders, and a higher-context setting. These are
examples to test, not recommended optimum weights. A grid contains 1–100 named
settings, each explicitly specifying all five weights. IDs must be unique even
ignoring case; duplicate exact vectors are rejected. Proportional weight vectors
are equivalent under normalization; avoid redundant settings yourself.

```powershell
Set-Location C:\Projects\Echo
.\.venv\Scripts\python.exe evaluation\run_eval.py `
  --dataset .local\datasets\my-study\dataset.json `
  --config evaluation\config.example.json --split tuning `
  --weight-sweep evaluation\weights.example.json `
  --output .local\evaluation\my-study-sweep-01
```

The run builds one fully indexed corpus, performs the normal A/B/C/D comparison,
then evaluates D for every grid setting on **tuning queries only**. Settings are
shuffled with the recorded seed; each setting uses the same query-order seed,
warmups, repetitions and backend candidates. These are full search timings,
including query embedding and reranking; candidate/results caching does not
artificially remove that work. Indexing cost is shared across settings.

Additional artifacts:

- `weight-sweep.csv`: every setting's weights, P@5, R@5, MRR@10, NDCG@10 and
  measured median/p95 latency/sample count, labelled `tuning` and dataset kind.
- `report.json` → `weight_sweep`: per-setting query results, raw timings,
  effective configuration/hash, grid hash and execution order.
- `configs/weights-<id>.json`: reusable full configurations, with a safe filename
  prefix for Windows. Report JSON is still published last as the completion marker.

The runner chooses **no winner**. Choose according to a predeclared objective
using tuning evidence only, then use that saved configuration for final test:

```powershell
.\.venv\Scripts\python.exe evaluation\run_eval.py `
  --dataset .local\datasets\my-study\dataset.json --split test `
  --config .local\evaluation\my-study-sweep-01\configs\weights-placeholder.json `
  --output .local\evaluation\my-study-final-01
```

Replace the example choice with the setting actually selected from tuning.
`--weight-sweep` with `--split test` fails before reading inputs or creating
output; the internal runner/helper also enforce tuning-only access. Test runs
evaluate one frozen setting, never a sweep. Semantic paraphrase leakage or a
human repeatedly adjusting weights after seeing test results still require
experimental discipline; software guards cannot establish a blinded study.

Sweep reports retain only tuning query results. Whole-run memory measurements
include both the base comparison and all sweep settings; method-phase peaks
aggregate resident shared-model/index memory, not isolated per-setting costs.
More settings increase work; no speed/memory/quality guarantee is inferred.
No new dependencies, database migration, frontend or M6 hardening are added.
