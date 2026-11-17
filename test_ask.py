"""
Run with:  python -m unittest

None of these tests call a real model. They use a stand-in that returns
prepared replies, so they need no key and no network.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest

import ask
import evaluate
import guard
import make_data
from model import ScriptedModel

HERE = os.path.dirname(os.path.abspath(__file__))


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.path = os.path.join(cls.folder, "shop.db")
        orders = make_data.build_orders()
        make_data.build_database(cls.path, orders, make_data.build_customers(orders))
        cls.db = guard.open_read_only(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        shutil.rmtree(cls.folder)


class GuardTests(Base):
    def test_allows_plain_select(self):
        self.assertEqual(guard.check("SELECT 1;"), "SELECT 1")

    def test_allows_with_clause(self):
        guard.check("WITH t AS (SELECT region FROM orders) SELECT COUNT(*) FROM t")

    def test_pulls_sql_out_of_a_code_fence(self):
        self.assertEqual(guard.check("Here you go:\n```sql\nSELECT 1;\n```"), "SELECT 1")

    def test_blocks_anything_that_writes(self):
        for sql in ("DELETE FROM orders", "DROP TABLE orders", "UPDATE orders SET revenue = 0",
                    "INSERT INTO orders VALUES (1)", "PRAGMA table_info(orders)",
                    "WITH t AS (SELECT 1) DELETE FROM orders", "ATTACH 'x.db' AS x"):
            with self.assertRaises(guard.UnsafeQuery, msg=sql):
                guard.check(sql)

    def test_blocks_two_statements(self):
        with self.assertRaises(guard.UnsafeQuery):
            guard.check("SELECT 1; DROP TABLE orders")

    def test_blocks_empty_reply(self):
        with self.assertRaises(guard.UnsafeQuery):
            guard.check("   ")

    def test_word_inside_a_string_is_fine(self):
        guard.check("SELECT COUNT(*) FROM orders WHERE category = 'DELETE; DROP'")

    def test_replace_function_is_fine_but_replace_into_is_not(self):
        guard.check("SELECT REPLACE(region, 'West', 'W') FROM orders")
        with self.assertRaises(guard.UnsafeQuery):
            guard.check("WITH t AS (SELECT 1) REPLACE INTO orders SELECT * FROM t")

    def test_database_itself_refuses_writes(self):
        # second line of defence: even with the check skipped, the connection is read-only
        with self.assertRaises(sqlite3.Error):
            self.db.execute("DELETE FROM orders")

    def test_bad_column_is_reported_not_crashed(self):
        with self.assertRaises(guard.QueryFailed):
            guard.run(self.db, "SELECT nonsense FROM orders")

    def test_row_cap(self):
        _, rows = guard.run(self.db, "SELECT * FROM orders")
        self.assertEqual(len(rows), guard.MAX_ROWS)

    def test_runaway_query_is_stopped(self):
        with self.assertRaises(guard.QueryFailed):
            guard.run(self.db, "SELECT COUNT(*) FROM orders a, orders b, orders c, orders d")


class DataTests(Base):
    """The numbers the demo on my site shows. If the data changes, these fail."""

    def one(self, sql):
        return guard.run(self.db, sql)[1]

    def test_sizes(self):
        self.assertEqual(self.one("SELECT COUNT(*) FROM orders"), [(600,)])
        self.assertEqual(self.one("SELECT COUNT(*) FROM customers"), [(87,)])

    def test_top_region(self):
        self.assertEqual(self.one("SELECT region, SUM(revenue) FROM orders GROUP BY 1 ORDER BY 2 DESC LIMIT 1"), [("West", 27096)])

    def test_best_month(self):
        self.assertEqual(self.one("SELECT strftime('%m', order_date), SUM(revenue) FROM orders GROUP BY 1 ORDER BY 2 DESC LIMIT 1"), [("11", 12702)])

    def test_every_order_has_a_customer(self):
        self.assertEqual(self.one("SELECT COUNT(*) FROM orders o LEFT JOIN customers c USING (customer_id) WHERE c.customer_id IS NULL"), [(0,)])


class AskTests(Base):
    def test_schema_description_names_tables_and_values(self):
        text = ask.describe(self.db)
        self.assertIn("CREATE TABLE orders", text)
        self.assertIn("'App', 'Store', 'Web'", text)
        self.assertNotIn("customer_id is one of", text)      # too many values to list

    def test_question_to_rows(self):
        model = ScriptedModel(["SELECT region, SUM(revenue) AS revenue FROM orders GROUP BY region ORDER BY revenue DESC LIMIT 1"])
        sql, columns, rows = ask.ask(self.db, model, "Which region brings in the most?")
        self.assertEqual(columns, ["region", "revenue"])
        self.assertEqual(rows, [("West", 27096)])
        self.assertIn("Which region brings in the most?", model.asked[0][1])

    def test_one_retry_after_a_bad_query(self):
        model = ScriptedModel(["SELECT sales FROM orders", "SELECT SUM(revenue) FROM orders"])
        sql, _, rows = ask.ask(self.db, model, "Total revenue?")
        self.assertEqual(sql, "SELECT SUM(revenue) FROM orders")
        self.assertIn("no such column", model.asked[1][1])   # the error was shown to the model

    def test_gives_up_after_the_retry(self):
        model = ScriptedModel(["SELECT sales FROM orders", "SELECT sales FROM orders"])
        with self.assertRaises(guard.QueryFailed):
            ask.ask(self.db, model, "Total revenue?")

    def test_unsafe_reply_is_never_run(self):
        model = ScriptedModel(["DROP TABLE orders"])
        with self.assertRaises(guard.UnsafeQuery):
            ask.ask(self.db, model, "Delete everything")
        self.assertEqual(guard.run(self.db, "SELECT COUNT(*) FROM orders")[1], [(600,)])

    def test_cannot_answer(self):
        with self.assertRaises(ask.CannotAnswer):
            ask.ask(self.db, ScriptedModel(["CANNOT ANSWER"]), "What is the weather?")

    def test_table_layout(self):
        text = ask.table(["region", "revenue"], [("West", 27096), ("East", 20188)])
        self.assertEqual(text.splitlines()[0].split(), ["region", "revenue"])
        self.assertEqual(len(text.splitlines()), 4)


class ScoringTests(Base):
    def test_same_rows_ignores_order_and_number_type(self):
        self.assertTrue(evaluate.same_rows([("a", 1), ("b", 2.0)], [("b", 2), ("a", 1.004)], ordered=False))

    def test_order_matters_when_asked(self):
        self.assertFalse(evaluate.same_rows([("a", 1), ("b", 2)], [("b", 2), ("a", 1)], ordered=True))

    def test_wrong_numbers_fail(self):
        self.assertFalse(evaluate.same_rows([("a", 1)], [("a", 2)], ordered=False))

    def test_my_own_queries_score_full_marks(self):
        with open(os.path.join(HERE, "questions.json")) as f:
            questions = json.load(f)
        results = evaluate.score(self.db, ScriptedModel([q["sql"] for q in questions]), questions)
        self.assertEqual(sum(1 for r in results if r[1]), len(questions))

    def test_a_wrong_answer_is_caught(self):
        questions = [{"question": "How many orders?", "sql": "SELECT COUNT(*) FROM orders"}]
        results = evaluate.score(self.db, ScriptedModel(["SELECT COUNT(*) FROM customers"]), questions)
        self.assertFalse(results[0][1])

    def test_a_differently_written_right_answer_passes(self):
        questions = [{"question": "How many orders?", "sql": "SELECT COUNT(*) FROM orders"}]
        results = evaluate.score(self.db, ScriptedModel(["SELECT SUM(1) AS n FROM orders WHERE revenue >= 0"]), questions)
        self.assertTrue(results[0][1])


if __name__ == "__main__":
    unittest.main()
