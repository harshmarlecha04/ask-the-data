"""
Ask the data

Type a business question in plain English. A language model writes the SQL,
the SQL is checked and run against the database, and you get the query, the
rows and a one-sentence answer.

    python ask.py "Which region brings in the most revenue?"
    python ask.py "Do app customers spend more?" --no-summary

Needs an API key. See the README.
"""

import argparse
import sys

import guard
from model import ClaudeModel, MissingKey

SYSTEM = """You write SQL for a SQLite database. You will be given the schema and a question.
Reply with one SELECT statement that answers the question, and nothing else: no explanation, no markdown.
Rules:
- SQLite syntax only. Dates are text in YYYY-MM-DD form, so use strftime for months and years.
- Use only the tables and columns in the schema. Match text values exactly as they appear in the schema notes.
- Return only the columns the question asks for, with clear names.
- Round money and percentages to at most 2 decimal places.
- If the question asks for a top N, use ORDER BY and LIMIT.
- If the schema cannot answer the question, reply with exactly: CANNOT ANSWER"""

SUMMARY_SYSTEM = """You are given a question, the SQL that was run, and the rows that came back.
Answer the question in one plain sentence using the numbers in the rows. Do not mention SQL or tables.
If the rows do not answer the question, say so."""


class CannotAnswer(Exception):
    pass


def describe(db):
    """The schema as text for the model: each table's definition, plus the values of short text columns."""
    parts = []
    tables = db.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    for name, sql in tables:
        parts.append(sql.strip() + ";")
        rows = db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        notes = [f"-- {name} has {rows} rows"]
        for _, column, kind, *_ in db.execute(f'PRAGMA table_info("{name}")').fetchall():
            if "TEXT" not in (kind or "").upper():
                continue
            values = [r[0] for r in db.execute(f'SELECT DISTINCT "{column}" FROM "{name}" ORDER BY 1 LIMIT 13').fetchall()]
            if len(values) <= 12:
                notes.append(f"-- {name}.{column} is one of: {', '.join(repr(v) for v in values)}")
        parts.append("\n".join(notes))
    return "\n\n".join(parts)


def write_sql(model, schema, question, previous=None):
    """Ask the model for a query. If an earlier attempt failed, show it the attempt and the error."""
    prompt = f"Schema:\n{schema}\n\nQuestion: {question}"
    if previous:
        bad_sql, error = previous
        prompt += f"\n\nYour last query was:\n{bad_sql}\n\nIt failed with: {error}\nWrite a corrected query."
    reply = model.complete(SYSTEM, prompt)
    if "CANNOT ANSWER" in reply.upper():
        raise CannotAnswer("The model says this database can't answer that question")
    return guard.clean(reply)


def ask(db, model, question, retries=1):
    """Question in, (sql, columns, rows) out. Gives the model one chance to fix a query the database rejects."""
    schema = describe(db)
    previous = None
    for attempt in range(retries + 1):
        sql = write_sql(model, schema, question, previous)
        try:
            columns, rows = guard.run(db, sql)
            return sql, columns, rows
        except guard.QueryFailed as problem:
            if attempt == retries:
                raise
            previous = (sql, str(problem))


def summarise(model, question, sql, columns, rows):
    shown = "\n".join(" | ".join(str(v) for v in row) for row in rows[:25])
    prompt = f"Question: {question}\n\nSQL:\n{sql}\n\nColumns: {' | '.join(columns)}\nRows:\n{shown}"
    return model.complete(SUMMARY_SYSTEM, prompt).strip()


def table(columns, rows, limit=20):
    """Rows as an aligned text table."""
    cells = [[str(c) for c in columns]] + [["" if v is None else str(v) for v in row] for row in rows[:limit]]
    widths = [max(len(line[i]) for line in cells) for i in range(len(columns))]
    lines = ["  " + "  ".join(value.ljust(width) for value, width in zip(line, widths)) for line in cells]
    lines.insert(1, "  " + "  ".join("-" * width for width in widths))
    if len(rows) > limit:
        lines.append(f"  ... and {len(rows) - limit} more rows")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ask a database a question in plain English.")
    parser.add_argument("question", help="the question, in quotes")
    parser.add_argument("--db", default="shop.db", help="SQLite database to ask (default shop.db)")
    parser.add_argument("--model", default=None, help="model to use (default claude-haiku-5-5)")
    parser.add_argument("--no-summary", action="store_true", help="skip the one-sentence answer")
    args = parser.parse_args(argv)

    try:
        db = guard.open_read_only(args.db)
        db.execute("SELECT 1 FROM sqlite_master").fetchall()
    except Exception:
        print(f"Can't open the database '{args.db}'. Run 'python make_data.py' to create the sample one.", file=sys.stderr)
        return 1
    try:
        model = ClaudeModel(args.model)
        sql, columns, rows = ask(db, model, args.question)
    except MissingKey as problem:
        print(problem, file=sys.stderr)
        return 1
    except CannotAnswer as problem:
        print(f"\n{problem}.\n")
        return 0
    except guard.UnsafeQuery as problem:
        print(f"\nThe model wrote a query that was blocked: {problem}.\n", file=sys.stderr)
        return 1
    except guard.QueryFailed as problem:
        print(f"\nThe query still failed after one retry: {problem}\n", file=sys.stderr)
        return 1

    print(f"\n{sql}\n")
    print(table(columns, rows) if rows else "  (no rows)")
    if rows and not args.no_summary:
        print(f"\n{summarise(model, args.question, sql, columns, rows)}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
