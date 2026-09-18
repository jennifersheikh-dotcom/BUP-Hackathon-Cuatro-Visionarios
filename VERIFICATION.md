# Verification report

Executed on 2026-09-18 with Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0.

`python -m unittest discover -s tests -v`: 11 test methods passed. The public-optimizer method contains ten scenario subtests.

The provider-transport test used a local simulated HTTP provider. No live language model was called.

| Public case | Reference cost (BDT) | Computed cost (BDT) |
|---|---:|---:|
| SAMPLE-01 | 38365.00 | 38365.00 |
| SAMPLE-02 | 42885.00 | 42885.00 |
| SAMPLE-03 | 35480.00 | 35480.00 |
| SAMPLE-04 | 40495.00 | 40495.00 |
| SAMPLE-05 | 33950.00 | 33950.00 |
| SAMPLE-06 | 34090.00 | 34090.00 |
| SAMPLE-07 | 38550.00 | 38550.00 |
| SAMPLE-08 | 37665.00 | 37665.00 |
| SAMPLE-09 | 34873.00 | 34873.00 |
| SAMPLE-10 | 41620.00 | 41620.00 |

All computed schedules passed separate replay checks. Public ground-truth directives were supplied directly for these optimizer tests. These results do not measure live interpretation accuracy.

Not executed: real provider inference, Docker build/pull/run (Docker unavailable), deployment, external-network test, load test, official hidden tests. No credentials, published repository, deployed service, container image, or recorded video were created.

The package includes an actual model adapter and a live public-case testing command; the runtime has no fixture/fake-model mode. The team must perform the remaining checks and satisfy its own-work and event-timing obligations.

## Re-verification after import into the submission repository

Executed on 2026-09-18 with Python 3.11.15, NumPy 2.3.5, SciPy 1.17.0, from the project root after moving the code out of the original zip.

`python -m unittest discover -s tests -v`: 11 test methods passed (same suite as above; all ten public-optimizer subtests reproduced their reference costs exactly). `data/public_samples.json` was diffed against the organizer-supplied `BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json`: byte-identical `cases` array and `_meta` fields, confirming the sample data was not altered.

Still not executed: real provider inference, Docker build/run (no Docker daemon available in this sandbox), public deployment, official hidden tests.
