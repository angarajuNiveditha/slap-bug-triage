# SLAP Bug Triage — Test Suite

15 end-to-end tests run through the agent pipeline (`run_agent.py`).
Each test has three files:

- `<test_name>.txt`  — the raw bug report email fed in as input.
- `<test_name>.md`   — only the `triage_notes` portion of the agent's output, formatted for reading.
- `<test_name>.json` — same `triage_notes` content as raw pretty-printed JSON.

All Jira ticket references in the `.md` files are clickable links to `flipkart.atlassian.net`.

## Test index

| Test | What it checks | Team routed | Scoring layer | Duplicate of |
|---|---|---|---|---|
| [test_00_baseline_cart_freeze](test_00_baseline_cart_freeze.md) | Original cart-freeze sample (baseline for duplicate detection). | BE_Flippi | `L1-keyword` | — |
| [test_01_p0_checkout_crash](test_01_p0_checkout_crash.md) | P0 — 100%-repro checkout crash on Android, revenue-blocking. | BE_Flippi | `L1-keyword` | — |
| [test_02_p1_wrong_ai_recommendations](test_02_p1_wrong_ai_recommendations.md) | P1 — AI ignores price constraints and returns wrong recommendations. | BE_Flippi | `L1-keyword` | — |
| [test_03_p2_images_slow_network](test_03_p2_images_slow_network.md) | P2 — product images fail to load on 2G/3G networks. | UI | `L1-keyword` | — |
| [test_04_duplicate_of_baseline](test_04_duplicate_of_baseline.md) | Duplicate detection — same cart-freeze as the baseline. | BE_Flippi | `L4-impact-fallback` | — |
| [test_05_p3_vague_report](test_05_p3_vague_report.md) | P3 — vague report with no steps, falls back to low priority. | BE_Flippi | `L1-keyword` | — |
| [test_06_dup_FLIPPI3044_secrets](test_06_dup_FLIPPI3044_secrets.md) | Duplicate against real FLIPPI-3044 (Grayskull secrets, P0). | BE_Flippi | `L1-keyword` | [FLIPPI-3044](https://flipkart.atlassian.net/browse/FLIPPI-3044) |
| [test_07_dup_FLIPPI2905_dedup](test_07_dup_FLIPPI2905_dedup.md) | Duplicate against real FLIPPI-2905 (product family dedup, P0). | BE_Flippi | `L1-duplicate` | [FLIPPI-2905](https://flipkart.atlassian.net/browse/FLIPPI-2905) |
| [test_08_dup_FLIPPI2902_auth](test_08_dup_FLIPPI2902_auth.md) | Duplicate against real FLIPPI-2902 (auth verify failure, P3). | BE_Flippi | `L1-keyword` | — |
| [test_09_component_immersive_anr](test_09_component_immersive_anr.md) | Component routing — ANR in VTO SDK should go to Immersive. | Immersive | `L1-keyword` | — |
| [test_10_component_belabs_vton](test_10_component_belabs_vton.md) | Component routing — VTON gender mismatch should go to BE_Labs. | BE_Labs | `L1-keyword` | — |
| [test_11_component_ds_nps](test_11_component_ds_nps.md) | Component routing — NPS discrepancy should go to DS. | DS | `L2-template` | — |
| [test_12_component_ui_ios](test_12_component_ui_ios.md) | Component routing — iOS cold-start flash should go to UI. | UI | `L1-keyword` | — |
| [test_13_component_belippi_price](test_13_component_belippi_price.md) | Component routing — price-filter ignored should go to BE_Flippi. | BE_Flippi | `L1-keyword` | — |
| [test_14_component_unclassified](test_14_component_unclassified.md) | Component routing — vague bug should fall through to 'bugs'. | bugs | `L1-keyword` | — |

## How to re-run

```bash
python3 run_agent.py             # runs all data/*.txt
python3 tests/_build.py          # regenerates this tests/ folder from output/
```
