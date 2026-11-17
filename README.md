# Ask the data

Most people with a business question can't write SQL, so they wait for someone who can. This tool takes the question in plain English, has a language model write the SQL, checks the SQL is safe, runs it, and gives back the query, the rows and a one-sentence answer.

The interesting part is not the model call, which is a dozen lines. It is everything around it: making sure a model can never change the data, and being able to say how often it gets the answer right.

## How it works

1. **Describe the database.** The tool reads the table definitions and the values of short text columns (so the model knows the channel is `'App'`, not `'app'` or `'mobile'`).
2. **Ask the model for one query.** It gets the schema, the question and a short list of rules.
3. **Check the query before it runs.** See "Why a model can't break anything" below.
4. **Run it.** If the database rejects the query, the model gets the error back and one chance to fix it.
5. **Answer in a sentence.** A second, small call turns the rows into plain English.

## Why a model can't break anything

A model writes the SQL, so nothing it writes is trusted. There are four layers, and each works without the others:

- **Only one SELECT.** Anything that is not a single read-only statement is refused before it reaches the database. `DROP`, `DELETE`, `UPDATE`, `PRAGMA`, `ATTACH` and a second statement after a semicolon are all blocked.
- **Read-only connection.** The database is opened read-only, so even a query that slipped past the check could not write.
- **Work limit.** A query that runs away, like an accidental four-way join of every order with every order, is stopped.
- **Row limit.** At most 200 rows come back.

`guard.py` is the whole of this, and most of the tests are about it.

## Try it

You need Python 3.9 or newer.

```
pip install -r requirements.txt
python make_data.py
python -m unittest
```

Those three need no key. `make_data.py` builds the sample database (600 made-up orders from 87 customers) and the tests run with a stand-in for the model.

To ask real questions you need your own API key for the Claude API. Create one at https://platform.claude.com, then set it in your terminal:

```
export ANTHROPIC_API_KEY=your-key          (Mac or Linux)
setx ANTHROPIC_API_KEY your-key            (Windows, then open a new terminal)
```

The key is read from that setting each time. It is never written into the code or saved to a file, so it cannot end up on GitHub by accident. A question costs a fraction of a cent with the default model.

```
python ask.py "Which region brings in the most revenue?"
```

Here is the shape of what comes back. The rows are real output from the sample database, and the query shown is the hand-written one for that question:

```
SELECT region, SUM(revenue) AS revenue
FROM orders
GROUP BY region
ORDER BY revenue DESC

  region  revenue
  ------  -------
  West    27096  
  East    20188  
  South   19810  
  North   13952  
```

After that the tool prints one sentence that answers the question. Add `--no-summary` to skip it.

## Scoring it

"It usually works" is not good enough for something people will trust with numbers, so there is a test set. `questions.json` holds 15 questions, each with a query I wrote by hand. They cover totals, averages, percentages, top-N, date filters, a join and a nested query.

```
python evaluate.py
```

The model's query does not have to look like mine. It passes if it returns the same rows. The output is a pass or fail for each question and a score out of 15. Scores depend on the model, so run it with yours. To see what the model wrote for each question, add `--show-sql`.

To check the scoring itself without a key:

```
python evaluate.py --offline
```

That feeds my own queries through the scorer and should report 15 of 15.

## Use your own database

Point it at any SQLite file:

```
python ask.py "How many open tickets are older than 30 days?" --db support.db
```

Two things make the answers much better: column names that say what they hold, and comments in the table definitions. The sample database has both, and the model sees them.

## What it does not do

- **It can be confidently wrong.** A query can be valid SQL and still answer a slightly different question. That is why the query is always printed. Read it before trusting the number.
- **It only knows what the schema tells it.** Business rules that live in people's heads, like "revenue excludes returns", have to be written into the question or the table comments.
- **It is SQLite only.** Other databases would need their own read-only connection and their own date rules in the prompt.
- **The sample data is invented.** It is the same 600 orders the demo on my site uses.

## Files

- `ask.py` asks one question.
- `guard.py` is the safety check and the only code that touches the database.
- `model.py` is the model call, plus the stand-in the tests use.
- `evaluate.py` and `questions.json` are the test set and the scorer.
- `make_data.py` builds `orders.csv`, `customers.csv` and `shop.db`.
- `test_ask.py` holds 29 tests. None of them need a key or a network connection.
