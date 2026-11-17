"""
Scores the model on a fixed set of questions.

Each question in questions.json comes with a query I wrote by hand. The model's
query does not have to look like mine. It passes if it returns the same rows.

    python evaluate.py              needs an API key
    python evaluate.py --offline    no key: feeds my own queries through, to check the scoring works
"""

import argparse
import json
import sys

import ask
import guard
from model import ClaudeModel, MissingKey, ScriptedModel


def normal(value):
    """Make 3, 3.0 and 3.004 compare as equal, and leave text alone."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return value


def same_rows(got, expected, ordered):
    """True if two results hold the same values. Column names are ignored. Row order only matters if `ordered`."""
    a = [tuple(normal(v) for v in row) for row in got]
    b = [tuple(normal(v) for v in row) for row in expected]
    if not ordered:
        a, b = sorted(a, key=repr), sorted(b, key=repr)
    return a == b


def score(db, model, questions):
    """Run every question. Returns a list of (question, passed, note, sql)."""
    results = []
    for item in questions:
        _, expected = guard.run(db, item["sql"])
        try:
            sql, _, rows = ask.ask(db, model, item["question"])
        except ask.CannotAnswer:
            results.append((item["question"], False, "model said it could not answer", ""))
            continue
        except guard.UnsafeQuery as problem:
            results.append((item["question"], False, f"blocked: {problem}", ""))
            continue
        except guard.QueryFailed as problem:
            results.append((item["question"], False, f"query failed: {problem}", ""))
            continue
        if same_rows(rows, expected, item.get("ordered", False)):
            results.append((item["question"], True, "", sql))
        elif rows and expected and len(rows[0]) != len(expected[0]):
            results.append((item["question"], False, f"returned {len(rows[0])} columns, expected {len(expected[0])}", sql))
        else:
            results.append((item["question"], False, "different rows", sql))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Score the model on the question set.")
    parser.add_argument("--db", default="shop.db")
    parser.add_argument("--questions", default="questions.json")
    parser.add_argument("--model", default=None)
    parser.add_argument("--offline", action="store_true", help="no model: run my own queries through the scorer")
    parser.add_argument("--show-sql", action="store_true", help="print the query the model wrote for each question")
    args = parser.parse_args(argv)

    with open(args.questions) as f:
        questions = json.load(f)
    try:
        db = guard.open_read_only(args.db)
        model = ScriptedModel([q["sql"] for q in questions]) if args.offline else ClaudeModel(args.model)
    except MissingKey as problem:
        print(problem, file=sys.stderr)
        return 1

    results = score(db, model, questions)
    print()
    for question, passed, note, sql in results:
        print(f"  {'pass' if passed else 'FAIL'}  {question}" + (f"   [{note}]" if note else ""))
        if args.show_sql and sql:
            print(f"        {sql}")
    passed = sum(1 for r in results if r[1])
    name = "my own queries (offline check)" if args.offline else getattr(model, "model", "model")
    print(f"\n  {passed} of {len(results)} correct, using {name}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
