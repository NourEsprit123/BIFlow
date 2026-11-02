# Data Cleaning Agent evaluation · 20261102T122501Z

## Runs

| Case | Run | Status | Labelled cells handled | Restore accuracy | Untouched cells kept | Duplicates left | Safety | Turns | Seconds | Invalid requests | Builtin first | Groq calls | Drops |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sales_small | 1 | failed | 78.6% | 69.0% | 87.0% | 0 | 8/8 | 27 | 300.5 | 0.0 | 1.0 | 0 | turn_budget 1, local_correction_error 1 |

## Outcome by problem type (all runs)

| Column:problem | Cells | Handled | Results |
|---|---|---|---|
| is_active:boolean_variant | 8 | 100% | restored 8 |
| quantity:blank | 2 | 100% | imputed_marked 2 |
| quantity:junk | 1 | 100% | imputed_marked 1 |
| quantity:outlier | 3 | 100% | kept_for_review 3 |
| quantity:words | 1 | 100% | restored 1 |
| region:whitespace | 9 | 0% | wrong_value 9 |
| revenue:blank | 2 | 100% | imputed_marked 2 |
| revenue:currency | 1 | 100% | restored 1 |
| revenue:k_suffix | 1 | 100% | restored 1 |
| revenue:marker | 3 | 100% | imputed_marked 3 |
| revenue:words | 3 | 100% | restored 3 |
| signup_date:blank | 1 | 100% | nulled 1 |
| signup_date:junk | 1 | 100% | nulled 1 |
| signup_date:month_name | 5 | 100% | restored 5 |
| signup_date:slash | 1 | 100% | restored 1 |
| untouched_cells | 238 | 87% | kept 207, wrong_value 31 |

## Safety failures

None.

Labelled cells handled counts restored values, correctly blanked junk, marked fills and outliers left for review. Untouched cells kept is the share of never-corrupted cells that still hold their value in the canonical form. The profiling report is an oracle built from the answer key, so these scores isolate the cleaning agent.
