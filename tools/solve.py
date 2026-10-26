#!/usr/bin/env python3
"""
solve.py - Hourly Quiz solver for DSO 429 HW3.

Every question in questions.csv comes from one of 12 business-arithmetic
templates. Each template is parsed with a regex, the answer is computed
exactly (Decimal), and the option whose value matches at its own displayed
precision is chosen. Nothing is guessed: a question that matches no template,
or whose computed value matches zero (or more than one) option, is reported
as UNRESOLVED and no answer file is written for that round.

Usage
  python3 tools/solve.py --check            # grade the solver on practice rounds 1-48
  python3 tools/solve.py --fetch --write    # download latest CSV, write answers/round-NNNN.json
  python3 tools/solve.py --write --rounds 49-60
  python3 tools/solve.py --write --overwrite   # also rewrite files that already exist
"""
import argparse, csv, json, os, re, sys, urllib.request
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 40

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
ANSWERS = os.path.join(ROOT, "answers")
BASE = "https://raw.githubusercontent.com/FaisalXL/dso429-hourly-quiz/main/"
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
LETTERS = "ABCD"


def D(s):
    return Decimal(str(s).replace(",", "").replace("$", ""))


def money(pattern_name):
    return r"\$(?P<%s>[\d,]+(?:\.\d+)?)" % pattern_name


# ---- template solvers: return (kind, value) -------------------------------
# kind "num" -> Decimal compared at the option's precision, "date" -> date

def s_compound(m):
    return "num", D(m["p"]) * (1 + D(m["r"]) / 100) ** int(m["n"])


def s_margin(m):
    rev, cogs = D(m["rev"]), D(m["cogs"])
    return "num", (rev - cogs) / rev * 100


def s_sequence(m):
    xs = [D(x) for x in re.findall(r"-?\d+(?:\.\d+)?", m["seq"])]
    diffs = [b - a for a, b in zip(xs, xs[1:])]
    if len(set(diffs)) == 1:
        return "num", xs[-1] + diffs[0]
    if all(x != 0 for x in xs[:-1]):
        ratios = [b / a for a, b in zip(xs, xs[1:])]
        if len(set(ratios)) == 1:
            return "num", xs[-1] * ratios[0]
    d2 = [b - a for a, b in zip(diffs, diffs[1:])]
    if len(set(d2)) == 1:
        return "num", xs[-1] + diffs[-1] + d2[0]
    raise ValueError("unrecognised sequence pattern")


def s_discount(m):
    return "num", D(m["p"]) * (1 - D(m["d"]) / 100)


def s_pct_change(m):
    a, b = D(m["a"]), D(m["b"])
    return "num", (b - a) / a * 100


def s_date(m):
    d0 = date(int(m["y"]), MONTHS.index(m["mon"]) + 1, int(m["d"]))
    return "date", d0 + timedelta(days=int(m["n"]))


def s_breakeven(m):
    return "num", D(m["fixed"]) / (D(m["price"]) - D(m["var"]))


def s_ratio(m):
    a, b = D(m["a"]), D(m["b"])
    share = a if m["which"] == "first" else b
    return "num", D(m["budget"]) * share / (a + b)


def s_weighted(m):
    n1, a1, n2, a2 = D(m["n1"]), D(m["a1"]), D(m["n2"]), D(m["a2"])
    return "num", (n1 * a1 + n2 * a2) / (n1 + n2)


def s_euro(m):
    return "num", D(m["usd"]) * D(m["rate"])


def s_prob(m):
    counts = {"billing": D(m["b"]), "technical": D(m["t"]), "account": D(m["a"])}
    return "num", counts[m["kind"]] / sum(counts.values()) * 100


def s_revenue(m):
    return "num", D(m["n"]) * D(m["p"])


NUM = r"[\d,]+(?:\.\d+)?"
TEMPLATES = [
    ("compound", s_compound, re.compile(
        r"An investment of \$(?P<p>%s) grows at (?P<r>[\d.]+)%% compounded annually\. "
        r"What is its value after (?P<n>\d+) years\?" % NUM)),
    ("margin", s_margin, re.compile(
        r"A product line generates \$(?P<rev>%s) in revenue against \$(?P<cogs>%s) "
        r"in cost of goods sold\. What is the gross margin\?" % (NUM, NUM))),
    ("sequence", s_sequence, re.compile(
        r"A monthly headcount series runs (?P<seq>[-\d., ]+)\. "
        r"If the pattern continues, what is the next value\?")),
    ("discount", s_discount, re.compile(
        r"An item listed at \$(?P<p>%s) is discounted by (?P<d>[\d.]+)%%\. "
        r"What is the sale price\?" % NUM)),
    ("pct_change", s_pct_change, re.compile(
        r"Quarterly revenue moved from \$(?P<a>%s) to \$(?P<b>%s)\. "
        r"What is the percentage change\?" % (NUM, NUM))),
    ("date", s_date, re.compile(
        r"A contract signed on (?P<d>\d{1,2}) (?P<mon>[A-Za-z]+) (?P<y>\d{4}) has a "
        r"(?P<n>\d+)-day settlement period\. On what date does it settle\?")),
    ("breakeven", s_breakeven, re.compile(
        r"Fixed costs are \$(?P<fixed>%s)\. Each unit sells for \$(?P<price>%s) with a "
        r"variable cost of \$(?P<var>%s)\. How many units must be sold to break even, "
        r"to the nearest unit\?" % (NUM, NUM, NUM))),
    ("ratio", s_ratio, re.compile(
        r"A \$(?P<budget>%s) marketing budget is split between two channels in the ratio "
        r"(?P<a>\d+):(?P<b>\d+)\. What does the (?P<which>first|second) channel receive\?" % NUM)),
    ("weighted", s_weighted, re.compile(
        r"Region A had (?P<n1>\d+) orders averaging \$(?P<a1>%s); region B had (?P<n2>\d+) "
        r"orders averaging \$(?P<a2>%s)\. What is the overall average order value\?" % (NUM, NUM))),
    ("euro", s_euro, re.compile(
        r"An invoice for \$(?P<usd>%s) is converted to euros at (?P<rate>[\d.]+) euros per "
        r"US dollar\. How many euros is that\?" % NUM)),
    ("prob", s_prob, re.compile(
        r"A support queue holds (?P<b>\d+) billing tickets, (?P<t>\d+) technical tickets and "
        r"(?P<a>\d+) account tickets\. If one is drawn at random, what is the probability it "
        r"is an? (?P<kind>billing|technical|account) ticket\?")),
    ("revenue", s_revenue, re.compile(
        r"A retailer sells (?P<n>\d+) units at \$(?P<p>%s) each\. What is total revenue\?" % NUM)),
]


# ---- option matching ---------------------------------------------------------

def parse_date(s):
    m = re.fullmatch(r"\s*(\d{1,2}) ([A-Za-z]+) (\d{4})\s*", s)
    if not m or m.group(2) not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS.index(m.group(2)) + 1, int(m.group(1)))


def parse_num(s):
    """Return (Decimal value, decimal places) or None."""
    m = re.search(r"-?\d[\d,]*(?:\.(\d+))?", s)
    if not m:
        return None
    txt = m.group(0)
    neg = s.strip().startswith("-") or s.strip().startswith("$-") or s.strip().startswith("-$")
    val = Decimal(txt.replace(",", "").lstrip("-"))
    return (-val if neg else val), len(m.group(1) or "")


def quantize(v, places):
    return v.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def solve_question(row):
    """Return (letter, why). letter is None when unresolved."""
    text = row["question_text"].strip()
    opts = [row["option_" + c.lower()] for c in LETTERS]
    for name, fn, rx in TEMPLATES:
        m = rx.fullmatch(text)
        if not m:
            continue
        try:
            kind, val = fn(m)
        except Exception as e:  # noqa: BLE001 - report, never guess
            return None, "%s: solver error %s" % (name, e)
        hits = []
        for i, o in enumerate(opts):
            if kind == "date":
                if parse_date(o) == val:
                    hits.append(i)
            else:
                p = parse_num(o)
                if p and quantize(val, p[1]) == p[0]:
                    hits.append(i)
        if len(hits) == 1:
            return LETTERS[hits[0]], name
        return None, "%s: %d options match computed %s" % (name, len(hits), val)
    return None, "no template matches"


# ---- IO ---------------------------------------------------------------------------

def fetch():
    os.makedirs(DATA, exist_ok=True)
    for fn in ("questions.csv", "practice_keys.csv"):
        with urllib.request.urlopen(BASE + fn, timeout=30) as r:
            body = r.read()
        with open(os.path.join(DATA, fn), "wb") as f:
            f.write(body)
        print("fetched %s (%d bytes)" % (fn, len(body)))


def load_rounds():
    rounds = defaultdict(list)
    with open(os.path.join(DATA, "questions.csv"), encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rounds[int(row["round_id"])].append(row)
    for r in rounds.values():
        r.sort(key=lambda x: int(x["q_index"]))
    return rounds


def parse_range(s, available):
    if not s:
        return sorted(available)
    out = set()
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return sorted(out & set(available))


def solve_round(rows):
    answers, problems = {}, []
    if len(rows) != 25 or [int(r["q_index"]) for r in rows] != list(range(1, 26)):
        problems.append("round does not have exactly q_index 1-25")
    for r in rows:
        letter, why = solve_question(r)
        if letter is None:
            problems.append("q%s: %s | %s" % (r["q_index"], why, r["question_text"]))
        else:
            answers["q" + r["q_index"]] = letter
    return answers, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fetch", action="store_true", help="download latest CSVs first")
    ap.add_argument("--check", action="store_true", help="grade solver against practice_keys.csv")
    ap.add_argument("--write", action="store_true", help="write answers/round-NNNN.json")
    ap.add_argument("--overwrite", action="store_true", help="rewrite answer files that already exist")
    ap.add_argument("--rounds", default="", help="e.g. 49-60 or 1,5,9 (default: all)")
    args = ap.parse_args()

    if args.fetch:
        fetch()
    rounds = load_rounds()
    chosen = parse_range(args.rounds, rounds)

    if args.check:
        keys = {}
        with open(os.path.join(DATA, "practice_keys.csv"), newline="") as f:
            for r in csv.DictReader(f):
                keys[(int(r["round_id"]), int(r["q_index"]))] = r["answer"]
        right = wrong = unresolved = 0
        for rid in [x for x in chosen if x <= 48]:
            for row in rounds[rid]:
                letter, why = solve_question(row)
                want = keys[(rid, int(row["q_index"]))]
                if letter is None:
                    unresolved += 1
                    print("UNRESOLVED r%d q%s: %s" % (rid, row["q_index"], why))
                elif letter == want:
                    right += 1
                else:
                    wrong += 1
                    print("WRONG r%d q%s: got %s want %s (%s)" % (rid, row["q_index"], letter, want, why))
        total = right + wrong + unresolved
        print("practice check: %d/%d correct, %d wrong, %d unresolved" % (right, total, wrong, unresolved))
        return 0 if wrong == 0 and unresolved == 0 else 1

    written = skipped = 0
    bad_rounds = []
    for rid in chosen:
        answers, problems = solve_round(rounds[rid])
        if problems:
            bad_rounds.append(rid)
            print("ROUND %d NOT WRITTEN:" % rid)
            for p in problems:
                print("   " + p)
            continue
        path = os.path.join(ANSWERS, "round-%04d.json" % rid)
        if args.write:
            if os.path.exists(path) and not args.overwrite:
                skipped += 1
                continue
            os.makedirs(ANSWERS, exist_ok=True)
            with open(path, "w") as f:
                json.dump({"round_id": rid, "answers": answers}, f, indent=2)
                f.write("\n")
            written += 1
    print("rounds considered: %d | written: %d | already existed: %d | unresolved rounds: %d"
          % (len(chosen), written, skipped, len(bad_rounds)))
    return 1 if bad_rounds else 0


if __name__ == "__main__":
    sys.exit(main())
