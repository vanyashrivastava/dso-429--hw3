from __future__ import annotations

import csv
import json
import math
import re
import warnings
from pathlib import Path
from typing import Sequence

OPTION_LETTERS = ("A", "B", "C", "D")


def _clean_numeric(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace("$", "").replace(",", "").replace("%", "")
    text = text.replace("(", "-").replace(")", "")
    if text.lower() in {"nan", "inf", "-inf"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _money_values(text: str) -> list[float]:
    values = []
    dollar_matches = re.findall(r"\$\s?-?\d[\d,]*(?:\.\d+)?", text)
    for match in dollar_matches:
        num = _clean_numeric(match)
        if num is not None:
            values.append(num)

    if values:
        return sorted(values, reverse=True)

    bare_matches = re.findall(r"\b\d[\d,]*(?:\.\d+)?\b", text)
    for match in bare_matches:
        if match and not re.search(rf"(?<!\d){re.escape(match)}\s*%", text):
            num = _clean_numeric(match)
            if num is not None:
                values.append(num)

    return sorted(values, reverse=True)


def _percent_values(text: str) -> list[float]:
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*%", text)
    return [float(match) for match in matches]


def _select_rate(question_text: str, percent_values: Sequence[float]) -> float | None:
    if not percent_values:
        return None
    lower = question_text.lower()
    keywords = ["interest", "rate", "compounded", "growth", "increase", "discount", "markup", "tax", "sale", "percent"]
    keyword_positions = []
    for keyword in keywords:
        index = lower.find(keyword)
        if index != -1:
            keyword_positions.append(index)
    anchor = min(keyword_positions) if keyword_positions else 0

    best_index = 0
    best_distance = float("inf")
    for idx, value in enumerate(percent_values):
        value_text = str(int(value)) if value.is_integer() else str(value)
        position = lower.find(value_text)
        if position == -1:
            distance = float("inf")
        else:
            distance = abs(anchor - position)
        if distance < best_distance:
            best_distance = distance
            best_index = idx
    return percent_values[best_index] / 100.0


def _principal_amount(text: str, amount_values: Sequence[float]) -> float | None:
    if not amount_values:
        return None
    lower = text.lower()
    anchors = ["investment", "principal", "price", "cost", "loan", "amount", "value", "balance", "pays", "sells", "worth"]
    anchor_positions = []
    for anchor in anchors:
        index = lower.find(anchor)
        if index != -1:
            anchor_positions.append(index)
    if anchor_positions:
        anchor = min(anchor_positions)
        candidates = []
        for value in amount_values:
            value_text = str(int(value)) if value.is_integer() else str(value)
            position = lower.find(value_text)
            if position != -1:
                candidates.append((abs(anchor - position), value))
        if candidates:
            return min(candidates, key=lambda item: item[0])[1]
    return max(amount_values)


def _time_values(text: str) -> list[float]:
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*(years?|yrs?|months?|mos?|quarters?|qtrs?)", text, re.IGNORECASE)
    values = []
    for value, unit in matches:
        number = float(value)
        unit_name = unit.lower()
        if unit_name.startswith(("year", "yr")):
            values.append(number)
        elif unit_name.startswith(("month", "mo")):
            values.append(number / 12.0)
        elif unit_name.startswith(("quarter", "qtr")):
            values.append(number / 4.0)
        else:
            values.append(number)
    return values


def _candidate_values(question_text: str, options: Sequence[str]) -> list[float]:
    text = question_text.strip()
    lower = text.lower()
    amount_values = _money_values(text)
    percent_values = _percent_values(text)
    time_values = _time_values(text)
    principal = _principal_amount(text, amount_values)
    known_rate = _select_rate(text, percent_values)
    years = time_values[0] if time_values else None

    candidates: list[float] = []

    if principal is not None and known_rate is not None:
        if any(word in lower for word in ["discount", "marked down", "sale price", "sale", "off", "reduced", "decrease", "decreased"]):
            candidates.append(principal * (1.0 - known_rate))
        elif any(word in lower for word in ["tax", "markup", "increase", "increased", "appreciation", "inflation", "added", "more than"]):
            candidates.append(principal * (1.0 + known_rate))
        elif (" of " in lower or "percent of" in lower) and "what is" in lower:
            candidates.append(principal * known_rate)

    is_compound_growth = principal is not None and known_rate is not None and any(
        word in lower for word in ["grow", "grows", "compounded", "compound", "future value", "appreciates"]
    )
    excluded_growth_terms = [
        "discount", "marked down", "sale price", "sale", "off", "reduced", "decrease", "decreased",
        "tax", "markup", "increase", "increased", "appreciation", "inflation", "added", "more than",
    ]
    if is_compound_growth and not any(word in lower for word in excluded_growth_terms):
        if years is None:
            years = 1.0
        candidates.append(principal * ((1.0 + known_rate) ** years))

    if principal is not None and known_rate is not None and "simple interest" in lower:
        if years is None:
            years = 1.0
        candidates.append(principal * (1.0 + known_rate * years))

    if principal is not None and known_rate is not None and any(word in lower for word in ["loan", "payment", "monthly payment"]):
        if years is None:
            years = 1.0
        periods = max(1, int(round(years * 12)))
        monthly_rate = known_rate / 12.0
        if monthly_rate > 0:
            candidate = principal * monthly_rate / (1.0 - (1.0 + monthly_rate) ** (-periods))
            candidates.append(candidate)

    if not candidates:
        for option in options:
            parsed = _clean_numeric(option)
            if parsed is not None:
                candidates.append(parsed)

    return candidates


def solve_question(question_text: str, options: Sequence[str]) -> str | None:
    if not options:
        return None

    values = []
    for index, option in enumerate(options[:4]):
        numeric = _clean_numeric(option)
        if numeric is not None:
            values.append((OPTION_LETTERS[index], numeric))
    if not values:
        return None

    candidates = _candidate_values(question_text, options)
    if not candidates:
        return None

    best_letter = None
    best_distance = math.inf
    for candidate in candidates:
        for letter, option_value in values:
            distance = abs(candidate - option_value)
            if distance < best_distance:
                best_distance = distance
                best_letter = letter
    return best_letter


def answers_for_round(round_rows: Sequence[dict]) -> dict[str, str]:
    ordered: dict[str, str] = {}
    for row in round_rows:
        q_index = row.get("q_index") or row.get("qIndex")
        if q_index is None:
            continue
        question_text = row.get("question_text") or row.get("question") or ""
        options = [
            row.get("option_a"),
            row.get("option_b"),
            row.get("option_c"),
            row.get("option_d"),
        ]
        answer = solve_question(question_text, options)
        if answer is None:
            warnings.warn(f"Skipping unsolved question q_index={q_index}")
            continue
        ordered[f"q{int(q_index)}"] = answer
    return ordered


def generate_answers_csv(question_csv: str | Path, output_dir: str | Path) -> None:
    with open(question_csv, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        raw_round_id = row.get("round_id") or ""
        round_id = str(raw_round_id).strip()
        if not round_id:
            continue
        try:
            int(round_id)
        except ValueError:
            continue
        grouped.setdefault(round_id, []).append(row)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for round_id, round_rows in sorted(grouped.items(), key=lambda item: int(item[0])):
        answers = answers_for_round(round_rows)
        payload = {"round_id": int(round_id), "answers": answers}
        path = output_path / f"round-{int(round_id):04d}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Solve DSO 429 quiz questions.")
    parser.add_argument("--questions", type=Path, required=True, help="Path to questions.csv")
    parser.add_argument("--out", type=Path, required=True, help="Directory for answer files")
    args = parser.parse_args()
    generate_answers_csv(args.questions, args.out)
