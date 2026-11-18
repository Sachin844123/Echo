# ECHO retrieval evaluation — M4 and M5

Compare **A: keyword**, **B: semantic**, **C: hybrid RRF**, and
**D: hybrid with contextual reranking** on identical,
fully indexed documents and selected labelled queries, using the production
ingestion/search engine. Method D's weights are configurable, untuned placeholders;
[the reranking guide](../docs/reranking.md) defines normalized signals and sweeps.

**No research corpus, labels or research results are supplied.** Provide your
own authorized documents and relevance judgments. Tests create tiny synthetic
TEST DATA fixtures in temporary directories; these are not research evidence.

## Run a comparison

Install the development/evaluation dependencies and prepare the offline MiniLM
model following the [main README](../README.md). M4 adds `psutil` to measure
native process RSS on Windows, including parser children. Evaluation never
downloads models or contacts external services.

From the repository root:

```powershell
.\.venv\Scripts\python.exe evaluation\run_eval.py `
  --dataset .local\datasets\my-study\dataset.json `
  --config evaluation\config.example.json `
  --split tuning `
  --output .local\evaluation\my-study-tuning-01
```

Replace the dataset path with your manifest. The output directory must be new;
existing results and the normal application DB are never overwritten. Without
`--output`, a timestamp/UUID directory is created under `.local/evaluation/`.
The model defaults to `.local/models/all-MiniLM-L6-v2`; `--model-dir` selects
another prepared directory. Operational `ECHO_*` settings are not inherited:
the explicit config, model argument and fixed backend defaults define this run.

Choose settings using **only tuning queries**, copy the selected configuration
to a private frozen file, then evaluate the final test split:

```powershell
.\.venv\Scripts\python.exe evaluation\run_eval.py `
  --dataset .local\datasets\my-study\dataset.json `
  --config .local\datasets\my-study\frozen-config.json `
  --split test `
  --output .local\evaluation\my-study-final-01
```

`--split` defaults to tuning; test requires an explicit `--config`. Configuration
hashes expose changes between reports. No automatic winner selection or combined-split
scores exist. Example settings are engineering defaults, not proven optimal.

### Weight sweeps: tuning only

Add `--weight-sweep evaluation\weights.example.json` to the tuning command to
run D for every explicit setting on the same index. Grid settings must name all
five weights and use unique IDs (case-insensitive); at most 100 settings are
allowed. Settings execute in seeded shuffled order. Each receives fresh warmup/
measured searches with the same query-order seed; no candidates are cached to
artificially reduce measured latency.

`--weight-sweep` with `--split test` fails before inputs/output are touched;
internal entry points enforce the same rule. The report contains all per-setting
metrics, timings and query results on tuning only. `weight-sweep.csv` gives one
row per setting; `configs/weights-<id>.json` saves reusable full configurations.
Select a configuration using tuning evidence and a predeclared objective, then
pass it to a test run **without** `--weight-sweep`. No winner is chosen for you.
The [detailed workflow](../docs/reranking.md) includes commands and limitations.

## Dataset contract

The UTF-8 JSON manifest is at most 32 MiB. Duplicate keys and unknown fields are
rejected. IDs use 1–64 ASCII letters/digits/underscores/hyphens, starting with a
letter or digit. Prefer opaque IDs: query and document IDs appear in reports.

| Top-level field | Contract |
| --- | --- |
| `schema_version` | `1` |
| `id` | Opaque study ID |
| `kind` | `research` or `test_fixture` |
| `documents` | Nonempty document array |
| `queries.tuning` | Nonempty tuning query array |
| `queries.test` | Nonempty held-out query array |

| Document field | Contract |
| --- | --- |
| `id` | Unique document ID referenced by labels |
| `path` | Captured-file path relative to the manifest directory |
| `title` | Nonblank title, at most 200 characters; used by FTS |
| `source_type` | `pdf`, `txt`, `markdown`, `docx`, or `note`; must match validated input |
| `captured_at` | Explicit ISO timestamp with timezone |
| `collections` | Optional collection-ID list, default empty |

| Query field | Contract |
| --- | --- |
| `id` | Unique query ID across both splits |
| `text` | Nonblank query, at most 2,000 characters |
| `filters` | Optional `source_types`, `captured_from`, `captured_to`, `collection` |
| `context` | Optional soft `source_types` and `collection` hints, used by D only |
| `relevance` | Document-ID-to-integer-grade map, grades 0–3; at least one positive |

Relative file paths may use either slash style. Absolute/drive/UNC paths,
traversal, alternate streams, missing files and resolved paths outside the
manifest directory are rejected. Files must be nonempty and at most 20 MiB;
normal format/parser limits apply. Notes are explicit text files imported with
their note titles. No URL fetching or arbitrary-folder scanning occurs.

Dates are timezone-aware and filter endpoints are inclusive. Collections are
created from document memberships; query collection IDs must exist. Positive
labels excluded by filters are invalid. Files with identical SHA-256 content
are rejected because production deduplication would collapse their identities.

Context collection IDs must also exist, but soft hints do not constrain positive
label eligibility or candidate inclusion. All four methods receive the same
text/hard filters; A–C ignore soft hints. Record remembered context independently
of rankings and relevance labels, not by copying metadata from positive answers.
Absent context gives zero source-type/collection signals. D still uses title/
heading and exact chunk-token overlap. Existing manifests need no new field.

This **structural TEST DATA example** illustrates the shape only. Its named file
and labels are illustrative, not a provided research dataset:

```json
{
  "schema_version": 1,
  "id": "test_example",
  "kind": "test_fixture",
  "documents": [{
    "id": "d1", "path": "documents/test-note.txt", "title": "TEST DATA note",
    "source_type": "note", "captured_at": "2026-01-01T00:00:00Z",
    "collections": ["c1"]
  }],
  "queries": {
    "tuning": [{"id": "q1", "text": "TEST DATA tuning query", "relevance": {"d1": 1}}],
    "test": [{"id": "q2", "text": "TEST DATA held-out query", "filters": {"collection": "c1"}, "relevance": {"d1": 1}}]
  }
}
```

## Constructing the study

1. Fix a representative corpus before tuning. Preserve original files, titles,
   capture dates and inclusion criteria. Use only authorized documents.
2. Write remembered-content queries independently of search output. Include
   plausible paraphrases and keywords representative of intended users.
3. Judge relevance at the **source/document level**, independently of rankings:
   `0 = not relevant`, `1 = marginal`, `2 = relevant`, `3 = highly relevant`.
   Binary 0/1 labels are valid. Document the rubric and use independent judging
   or adjudication where feasible. Do not derive labels from search results.
4. Label all relevant documents. Unjudged documents count as grade zero;
   incomplete judgments can bias results. This contract requires a positive
   for every query; no-answer behavior needs a separate study design.
5. Split queries before inspecting results. Keep paraphrases and related query
   families together. Duplicate IDs and NFKC/case/whitespace-normalized text are
   rejected across the dataset, but semantic paraphrase leakage needs human
   review. The same corpus is shared; **queries** are held out.
6. Select settings on tuning queries, freeze them, and evaluate test separately.
   The software cannot prevent a human reading held-out labels. Reranker
   weights must never be tuned against final-test queries.
7. Preserve private inputs/config/reports. Report counts, grading/split methods,
   exclusions and limitations. Tiny verification fixtures establish no research
   effectiveness or laptop-performance guarantee.

## Metrics

Methods retrieve up to ten distinct sources after normal candidate selection
and grouping. Top-50 chunk candidates may yield fewer than ten source results.

| Metric | Definition |
| --- | --- |
| Precision@5 | Positive sources in the first five divided by **5**, including when fewer results exist |
| Recall@5 | Positive sources in the first five divided by all positive labels for that query |
| MRR | First positive's reciprocal rank within ten results; zero if absent (**MRR@10**) |
| NDCG@10 | Top-ten DCG divided by ideal DCG from all labels; gain `2^grade - 1`, discount `log2(rank + 1)` |

Grades 1–3 are positive for binary metrics. Missing results contribute zero;
duplicate result IDs invalidate the run. Quality metrics are macro averages
over queries, each counted once. Repeats measure latency, not new labelled
observations. A changed ranking between repeats fails the run. JSON metadata
and the CSV header explicitly disclose MRR's cutoff.

## Measurement protocol

- Each run creates a private corpus containing only declared documents, using
  normal validation/extraction/indexing and explicit metadata. All imports must
  succeed. Source IDs and exact chunk/FTS/embedding/vector ID sets must agree
  before and after queries; incomplete indexing aborts comparison.
- All four methods reuse that same index. Indexing wall time includes staging,
  validation, extraction, chunks, FTS, first model loading, embeddings, FAISS
  persistence and 20-ms completion polling. It excludes manifest/file preflight,
  DB setup and model-file hash verification. Total/per-document times are saved.
  Use a fresh CLI process for an unloaded model; OS caches are not cleared.
- Default warmup: every selected query/method once. Then three measured repeats,
  seeded query shuffling and rotating method order. These settings are recorded.
- Latency uses `perf_counter` around in-process production search, including
  query embedding, filters, ranking, grouping and result construction. HTTP,
  thread-pool dispatch and JSON serialization are excluded. Median and
  **nearest-rank p95** pool measured repetitions per method; sample counts and
  raw measurements are retained. Small sample p95 estimates are weak. These
  are warm retrieval latencies, not HTTP throughput or cold-start measurements.
- `psutil` samples parent RSS and summed parent/parser-child RSS at 50-ms
  intervals plus phase boundaries. Baseline is after manifest/file preflight
  and Python imports, before corpus setup. Aggregation uses bounded memory.
  Overall and indexing/warmup/method/shutdown peaks and missed child reads are
  reported. Each reading belongs to the phase at the start of sampling, even
  if the phase changes while process information is read. Peaks are
  **sampled lower bounds**: transient allocations/children
  can be missed, and shared pages may be double-counted across processes.
  Method-phase memory is whole-process residency with a shared model/index,
  not isolated algorithm-attributable memory. Sampling adds some overhead.
- A per-document soft deadline defaults to 600 seconds; shutdown waits for the
  current embedding batch. Parser timeout also applies. No failed document is
  silently omitted or retried, and no retrieval method silently falls back.

## Outputs, provenance and privacy

```text
corpus/          Private file copies, extracted text, SQLite and FAISS
summary.csv      Four method rows: quality metrics and measured latency
report.json      Completion marker, detailed results and provenance
weight-sweep.csv Optional tuning-only per-setting results
configs/         Optional frozen configurations from the sweep
```

Reports include dataset/split/config/model/code fingerprints, application/Python/
OS/package versions, counts, opaque query IDs, ranked document IDs, quality,
raw latency samples, indexing times and memory measurements. They omit content,
excerpts, titles, query text, input paths and tokens. IDs/hashes may still be
sensitive; reports are private artifacts. `test_fixture` is retained in JSON
and CSV, with `TEST DATA ONLY — NOT RESEARCH EVIDENCE` prominently in JSON.

M5 reports use `report_version: 2`, record the reranker formula version/effective
weights and include `weight_sweep` (null when absent). Whole-run memory includes
the base comparison and all sweep settings; method-phase peaks are shared-process
residency, not isolated per-weight-setting memory. No new dependency is required.

The CLI prints safe status only. No runtime network/AI calls occur and no
encryption is claimed. The private corpus remains for auditing; no input or
old run is automatically deleted. Default `.local/` artifacts and private
`evaluation/datasets/` inputs are Git-ignored. Do not force-add private data.

Failures after directory creation attempt to produce `failure.json` with a safe
error code; **no completed report** is published. If storage prevents writing
the failure artifact, the CLI retains the primary error code and logs the safe
`failure_artifact_write_failed` event. A final memory-sampling failure also
invalidates the run without replacing an existing primary failure.
Preflight failure may create no directory.
A partial directory is not a valid result. Fix inputs/config and choose a new
output path. Inspect private job state if more detail is needed.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_evaluation.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Tests cover hand-calculated graded metrics, cutoffs, latency percentiles,
invalid labels/paths, split leakage, duplicates, failures, no overwrites, real
child-process RSS, and a fresh-process run with actual offline MiniLM. That
integration test skips explicitly only if the model descriptor is absent.
Fixture scores and test runtime are not research findings.
