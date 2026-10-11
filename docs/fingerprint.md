<!--
SPDX-FileCopyrightText: 2026 Ahmed Hemedan
SPDX-License-Identifier: Apache-2.0
-->

# Locked test-set fingerprint

The plan records one fingerprint of the locked test set. Before any update is evaluated, MedAgentRx recomputes it from the prediction file. A different value means the test set changed, and the update is outside the plan (check DATA-001).

## Algorithm, format version 1

1. Take the `row_id` and `y_true` of every row.
2. Sort the rows by `row_id` in Unicode code point order.
3. Write each row as `row_id`, a tab, `y_true` as `0` or `1`, then a line feed.
4. Encode the text as UTF-8 and take its SHA-256 hex digest.

A `row_id` may not contain a tab or a line break, so the text is unambiguous.

The fingerprint does not depend on row order, scores, subgroup columns or file format. Adding, removing or relabelling any row changes it.

## Worked example

| row_id | y_true |
|---|---|
| r2 | 1 |
| r1 | 0 |
| r3 | 0 |

After sorting, the text is `r1\t0\nr2\t1\nr3\t0\n`, where `\t` is a tab and `\n` a line feed. Its SHA-256 is:

```
2c73943c03c4ac1ea182d666a6e0ad41efed0bc3815349861d37220432c4f305
```

## Command

```bash
medagentrx fingerprint test-predictions.parquet
```

Any Unix shell reproduces the example:

```bash
printf 'r1\t0\nr2\t1\nr3\t0\n' | shasum -a 256
```
