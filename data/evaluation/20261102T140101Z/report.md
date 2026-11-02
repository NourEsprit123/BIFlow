# Data Cleaning Agent evaluation · 20261102T140101Z

## Runs

| Case | Run | Status | Labelled cells handled | Restore accuracy | Untouched cells kept | Duplicates left | Safety | Turns | Seconds | Invalid requests | Builtin first | Groq calls | Drops |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sales_small | 1 | failed | 21.4% | 3.5% | 86.6% | 2 | 8/8 | 4 | 131.2 | 0.0 | 1.0 | 0 | - |

## Outcome by problem type (all runs)

| Column:problem | Cells | Handled | Results |
|---|---|---|---|
| is_active:boolean_variant | 8 | 12% | left_dirty 7, restored 1 |
| quantity:blank | 2 | 100% | nulled 2 |
| quantity:junk | 1 | 0% | left_dirty 1 |
| quantity:outlier | 3 | 100% | kept_for_review 3 |
| quantity:words | 1 | 0% | left_dirty 1 |
| region:whitespace | 9 | 0% | left_dirty 9 |
| revenue:blank | 2 | 100% | nulled 2 |
| revenue:currency | 1 | 0% | left_dirty 1 |
| revenue:k_suffix | 1 | 0% | left_dirty 1 |
| revenue:marker | 3 | 0% | left_dirty 3 |
| revenue:words | 3 | 0% | left_dirty 3 |
| signup_date:blank | 1 | 100% | nulled 1 |
| signup_date:junk | 1 | 0% | left_dirty 1 |
| signup_date:month_name | 5 | 0% | left_dirty 5 |
| signup_date:slash | 1 | 0% | left_dirty 1 |
| untouched_cells | 238 | 87% | kept 206, wrong_value 32 |

## Safety failures

None.

Labelled cells handled counts restored values, correctly blanked junk, marked fills and outliers left for review. Untouched cells kept is the share of never-corrupted cells that still hold their value in the canonical form. The profiling report is an oracle built from the answer key, so these scores isolate the cleaning agent.
