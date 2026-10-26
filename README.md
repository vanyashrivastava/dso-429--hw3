# dso-429--hw3

DSO 429 Homework 3: The Hourly Quiz.

Answers for each round live in `answers/round-NNNN.json` (25 answers per round, `q1`..`q25`).

## How the answers are produced

Every question in `questions.csv` is generated from one of 12 business-arithmetic
templates (compound interest, gross margin, break-even, date arithmetic, weighted
average, and so on). `tools/solve.py` is a stdlib-only Python script that:

1. parses each question with a regex for its template,
2. computes the exact answer with `Decimal`,
3. picks the option that equals that answer at the option's own displayed precision.

If a question matches no template, or its computed value matches zero or more than
one option, the round is reported as unresolved and **no file is written for it**.
Nothing is guessed.

No LLM is used for the answers.

## Checking it

```
python3 tools/solve.py --fetch --check
```

This grades the solver against the published practice keys (rounds 1-48).
Current result: 1200/1200 correct.

## Running it for new rounds

```
python3 tools/solve.py --fetch --write
```

`--write` skips files that already exist (use `--overwrite` to replace them).
The CSVs are downloaded into `data/` (git-ignored) from
https://github.com/FaisalXL/dso429-hourly-quiz.
