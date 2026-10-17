#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib import request

QUESTION_URL = "https://raw.githubusercontent.com/FaisalXL/dso429-hourly-quiz/main/questions.csv"
PRACTICE_KEYS_URL = "https://raw.githubusercontent.com/FaisalXL/dso429-hourly-quiz/main/practice_keys.csv"


def fetch_csv(url: str) -> str:
    with request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def read_rows(csv_text: str) -> List[Dict[str, str]]:
    return list(csv.DictReader(io.StringIO(csv_text)))


def parse_money(value: Optional[str]) -> Optional[Decimal]:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    cleaned = cleaned.replace("$", "").replace(",", "").replace("%", "")
    cleaned = cleaned.replace(" units", "").replace(" euros", "")
    if cleaned in {"", "-"}:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    return Decimal(match.group(0))


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_date_text(date_text: str) -> datetime:
    return datetime.strptime(date_text.strip(), "%d %B %Y")


def parse_option_value(option_text: str) -> Optional[Decimal]:
    if option_text is None:
        return None
    text = str(option_text).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{1,2} [A-Za-z]+ \d{4}", text):
        return None
    if re.fullmatch(r"\d+ units", text):
        return Decimal(re.search(r"\d+", text).group(0))
    if text.endswith("%"):
        return Decimal(text.rstrip("%").replace(",", ""))
    if text.startswith("$") or re.search(r"\d", text):
        return parse_money(text)
    return None


def nearest_option_for_value(options: Iterable[Tuple[str, str]], value: Decimal, *, integer: bool = False) -> str:
    candidates: List[Tuple[Decimal, str]] = []
    for letter, option_text in options:
        parsed = parse_option_value(option_text)
        if parsed is None:
            continue
        candidates.append((abs(parsed - value), letter))
    if not candidates:
        raise ValueError(f"No numeric options available for value {value}")
    _, chosen = min(candidates, key=lambda item: item[0])
    return chosen


def date_option_letter(options: Iterable[Tuple[str, str]], date_value: datetime) -> str:
    for letter, option_text in options:
        text = option_text.strip()
        if re.fullmatch(r"\d{1,2} [A-Za-z]+ \d{4}", text):
            if parse_date_text(text) == date_value:
                return letter
    raise ValueError(f"No date option matched {date_value.isoformat()}")


def solve_question(question_text: str, options: List[Tuple[str, str]]) -> str:
    question = question_text.strip()
    q_lower = question.lower()

    if "compounded annually" in q_lower:
        principal = parse_money(re.search(r"of\s+\$?([0-9,]+(?:\.\d+)?)", question, re.I).group(1))
        rate = Decimal(re.search(r"(\d+(?:\.\d+)?)%", question).group(1)) / Decimal("100")
        years = int(re.search(r"after\s+(\d+)\s+years", question, re.I).group(1))
        computed = principal * ((Decimal("1") + rate) ** years)
        return nearest_option_for_value(options, quantize_money(computed), integer=False)

    if "gross margin" in q_lower or "revenue against" in q_lower:
        revenue = parse_money(re.search(r"generates\s+\$?([0-9,]+(?:\.\d+)?)\s+in\s+revenue", question, re.I).group(1))
        cost = parse_money(re.search(r"against\s+\$?([0-9,]+(?:\.\d+)?)\s+in\s+cost", question, re.I).group(1))
        computed = ((revenue - cost) / revenue) * Decimal("100")
        return nearest_option_for_value(options, computed)

    if "discounted by" in q_lower:
        list_price = parse_money(re.search(r"listed at\s+\$?([0-9,]+(?:\.\d+)?)", question, re.I).group(1))
        discount_pct = Decimal(re.search(r"discounted by\s+(\d+(?:\.\d+)?)%", question, re.I).group(1)) / Decimal("100")
        computed = list_price * (Decimal("1") - discount_pct)
        return nearest_option_for_value(options, quantize_money(computed))

    if "settlement period" in q_lower:
        start_match = re.search(r"on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", question, re.I)
        start = parse_date_text(start_match.group(1))
        days = int(re.search(r"has a\s+(\d+)-day\s+settlement period", question, re.I).group(1))
        settle_date = start + timedelta(days=days)
        return date_option_letter(options, settle_date)

    if "converted to euros" in q_lower:
        usd_value = parse_money(re.search(r"for\s+\$?([0-9,]+(?:\.\d+)?)\s+is\s+converted", question, re.I).group(1))
        rate = Decimal(re.search(r"at\s+([0-9]+(?:\.\d+)?)\s+euros\s+per\s+US\s+dollar", question, re.I).group(1))
        computed = usd_value * rate
        return nearest_option_for_value(options, quantize_money(computed))

    if "break even" in q_lower:
        fixed_costs = parse_money(re.search(r"Fixed costs are\s+\$?([0-9,]+(?:\.\d+)?)", question, re.I).group(1))
        unit_price = parse_money(re.search(r"sells for\s+\$?([0-9,]+(?:\.\d+)?)", question, re.I).group(1))
        variable_cost = parse_money(re.search(r"variable cost of\s+\$?([0-9,]+(?:\.\d+)?)", question, re.I).group(1))
        computed = fixed_costs / (unit_price - variable_cost)
        return nearest_option_for_value(options, computed, integer=True)

    if "drawn at random" in q_lower:
        values = [Decimal(part) for part in re.findall(r"\d+(?:\.\d+)?", question)]
        favorable = values[0]
        total = sum(values)
        computed = (favorable / total) * Decimal("100")
        return nearest_option_for_value(options, computed)

    if "ratio" in q_lower:
        budget = parse_money(re.search(r"A\s+\$?([0-9,]+(?:\.\d+)?)\s+marketing budget", question, re.I).group(1))
        ratio_match = re.search(r"ratio\s+(\d+):(\d+)", question, re.I)
        a, b = map(Decimal, ratio_match.groups())
        computed = budget * (a / (a + b))
        return nearest_option_for_value(options, quantize_money(computed))

    if "overall average order value" in q_lower:
        match = re.search(
            r"Region A had\s+(\d+)\s+orders averaging\s+\$?([0-9,]+(?:\.\d+)?)\s*;\s*Region B had\s+(\d+)\s+orders averaging\s+\$?([0-9,]+(?:\.\d+)?)",
            question,
            re.I,
        )
        a_count, a_avg, b_count, b_avg = match.groups()
        computed = ((Decimal(a_count) * Decimal(a_avg.replace(",", "")) + Decimal(b_count) * Decimal(b_avg.replace(",", ""))) / (Decimal(a_count) + Decimal(b_count)))
        return nearest_option_for_value(options, quantize_money(computed))

    if "percentage change" in q_lower:
        match = re.search(r"from\s+\$?([0-9,]+(?:\.\d+)?)\s+to\s+\$?([0-9,]+(?:\.\d+)?)", question, re.I)
        old_value = Decimal(match.group(1).replace(",", ""))
        new_value = Decimal(match.group(2).replace(",", ""))
        computed = ((new_value - old_value) / old_value) * Decimal("100")
        return nearest_option_for_value(options, computed)

    if "sells" in q_lower and "total revenue" in q_lower:
        units = int(re.search(r"sells\s+(\d+)\s+units", question, re.I).group(1))
        unit_price = parse_money(re.search(r"at\s+\$?([0-9,]+(?:\.\d+)?)\s+each", question, re.I).group(1))
        computed = Decimal(units) * unit_price
        return nearest_option_for_value(options, quantize_money(computed))

    if "pattern continues" in q_lower or "series runs" in q_lower:
        numbers = [int(value) for value in re.findall(r"-?\d+", question)]
        if len(numbers) < 2:
            raise ValueError(f"Unable to determine arithmetic progression from question: {question}")
        diff = numbers[1] - numbers[0]
        computed = Decimal(numbers[-1] + diff)
        return nearest_option_for_value(options, computed, integer=True)

    raise ValueError(f"Unsupported question type: {question}")


def solve_round(round_id: int, rows: List[Dict[str, str]]) -> Dict[str, str]:
    answers: Dict[str, str] = {}
    for row in rows:
        if int(row["round_id"]) != round_id:
            continue
        q_index = int(row["q_index"])
        options = [("A", row["option_a"]), ("B", row["option_b"]), ("C", row["option_c"]), ("D", row["option_d"])]
        letter = solve_question(row["question_text"], options)
        answers[f"q{q_index}"] = letter
    return {"round_id": round_id, "answers": answers}


def write_round_file(output_dir: Path, round_id: int, payload: Dict[str, str]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"round-{round_id:04d}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_answers(rows: List[Dict[str, str]], start_round: int, end_round: Optional[int], output_dir: Path) -> List[Path]:
    if end_round is None:
        end_round = max(int(row["round_id"]) for row in rows)
    written_paths: List[Path] = []
    for round_id in range(start_round, end_round + 1):
        round_rows = [row for row in rows if int(row["round_id"]) == round_id]
        if not round_rows:
            continue
        payload = solve_round(round_id, rows)
        written_paths.append(write_round_file(output_dir, round_id, payload))
    return written_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate answer JSON files for the hourly quiz.")
    parser.add_argument("--questions-url", default=QUESTION_URL)
    parser.add_argument("--practice-keys-url", default=PRACTICE_KEYS_URL)
    parser.add_argument("--start-round", type=int, default=1)
    parser.add_argument("--end-round", type=int, default=None)
    parser.add_argument("--output-dir", default="answers")
    args = parser.parse_args()

    rows = read_rows(fetch_csv(args.questions_url))
    build_answers(rows, args.start_round, args.end_round, Path(args.output_dir))


if __name__ == "__main__":
    main()
