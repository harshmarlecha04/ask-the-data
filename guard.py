"""
The safety check that sits between the model and the database.

A model writes the SQL, so nothing it writes is trusted. A query only runs if it
is a single read-only SELECT, and even then the database is opened read-only,
the work is capped, and the number of rows that come back is capped.
"""

import re
import sqlite3

MAX_ROWS = 200
MAX_STEPS = 2_000_000          # SQLite work units before a runaway query is stopped

BLOCKED = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "ATTACH", "DETACH",
           "PRAGMA", "VACUUM", "REINDEX", "TRUNCATE", "GRANT", "REVOKE"]


class UnsafeQuery(Exception):
    """The model wrote something that is not a single read-only query."""


class QueryFailed(Exception):
    """The query was allowed but the database could not run it."""


def clean(text):
    """Pull the SQL out of a model reply: drop code fences, surrounding chatter and the final semicolon."""
    text = text.strip()
    fenced = re.search(r"```(?:sql|sqlite)?\s*(.*?)```", text, flags=re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    return text.rstrip(";").strip()


def without_text_and_comments(sql):
    """Blank out quoted strings and comments, so a word like DELETE inside a string is not mistaken for a command."""
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r'"(?:[^"]|"")*"', '""', sql)
    return sql


def check(sql):
    """Return the cleaned query if it is safe to run. Raise UnsafeQuery if it is not."""
    sql = clean(sql)
    if not sql:
        raise UnsafeQuery("The model returned no SQL")
    bare = without_text_and_comments(sql)
    if ";" in bare:
        raise UnsafeQuery("More than one statement")
    if not re.match(r"\s*(SELECT|WITH)\b", bare, flags=re.I):
        raise UnsafeQuery("Only SELECT queries are allowed")
    for word in BLOCKED:
        if re.search(rf"\b{word}\b", bare, flags=re.I):
            raise UnsafeQuery(f"{word} is not allowed")
    if re.search(r"\bREPLACE\s+INTO\b", bare, flags=re.I):
        raise UnsafeQuery("REPLACE INTO is not allowed")
    return sql


def open_read_only(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.execute("PRAGMA query_only = ON")
    return db


def run(db, sql):
    """Check the query, run it, and return (column names, rows). At most MAX_ROWS rows come back."""
    sql = check(sql)
    steps = {"n": 0}

    def watchdog():
        steps["n"] += 1000
        return 1 if steps["n"] > MAX_STEPS else 0   # returning 1 makes SQLite stop the query

    db.set_progress_handler(watchdog, 1000)
    try:
        cursor = db.execute(sql)
        columns = [c[0] for c in cursor.description]
        rows = cursor.fetchmany(MAX_ROWS)
    except sqlite3.Error as problem:
        raise QueryFailed(str(problem)) from None
    finally:
        db.set_progress_handler(None, 0)
    return columns, rows
