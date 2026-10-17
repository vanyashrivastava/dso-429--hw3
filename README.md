# DSO 429 Homework 3

This repository contains a small automation script that reads the public hourly-quiz CSV, solves each question pattern, and writes one JSON answer file per round in the required `answers/round-####.json` format.

## Usage

```bash
python quiz_solver.py --start-round 1 --end-round 48 --output-dir answers
```

The script is intentionally pattern-based and is designed for the quiz types used in the assignment.

## Output format

```json
{
  "round_id": 1,
  "answers": {
    "q1": "C",
    "q2": "A"
  }
}
```
