"""
Builds the sample database: 600 made-up orders and the customers who placed them.

    python make_data.py

Writes orders.csv, customers.csv and shop.db (SQLite). The data is seeded, so it
comes out the same every time, and it is the same 600 orders the demo on my site uses.
"""

import csv
import math
import os
import random
import sqlite3

MONTH_WEIGHTS = [6, 5, 6, 7, 7, 8, 7, 8, 9, 10, 14, 13]       # busier toward the holidays
CATEGORIES = ["Audio", "Wearables", "Home", "Gaming", "Accessories"]
PRICE = {"Audio": 140, "Wearables": 210, "Home": 95, "Gaming": 180, "Accessories": 35}
RETURN_RATE = {"Audio": 0.07, "Wearables": 0.16, "Home": 0.05, "Gaming": 0.09, "Accessories": 0.03}
DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def site_random(seed=2025):
    """The small random number generator the demo on my site uses, so both produce the same orders."""
    state = seed & 0xFFFFFFFF

    def imul(a, b):
        return (a * b) & 0xFFFFFFFF

    def rnd():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = imul(state ^ (state >> 15), 1 | state)
        t = ((t + imul(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF) ^ t
        return (t ^ (t >> 14)) / 4294967296

    return rnd


def build_orders(count=600):
    rnd = site_random()
    days = random.Random(11)                      # separate generator for the day of the month

    def choose(names, weights):
        r = rnd() * sum(weights)
        for name, weight in zip(names, weights):
            r -= weight
            if r <= 0:
                return name
        return names[-1]

    orders = []
    for number in range(1, count + 1):
        category = choose(CATEGORIES, [22, 16, 20, 14, 28])
        channel = choose(["App", "Web", "Store"], [34, 46, 20])
        month = choose(list(range(1, 13)), MONTH_WEIGHTS)
        region = choose(["West", "East", "South", "North"], [31, 27, 24, 18])
        revenue = math.floor(PRICE[category] * (0.6 + rnd() * 0.9) * (1.18 if channel == "App" else 1) + 0.5)
        returned = 1 if rnd() < RETURN_RATE[category] else 0
        customer = f"C-{100 + math.floor(rnd() ** 2.2 * 90)}"
        day = days.randint(1, DAYS_IN_MONTH[month - 1])
        orders.append({
            "order_id": f"O-{number:04d}",
            "order_date": f"2025-{month:02d}-{day:02d}",
            "customer_id": customer,
            "region": region,
            "category": category,
            "channel": channel,
            "revenue": revenue,
            "returned": returned,
        })
    return orders


def build_customers(orders):
    pick = random.Random(23)
    customers = []
    for customer_id in sorted({o["customer_id"] for o in orders}):
        first = min(o["order_date"] for o in orders if o["customer_id"] == customer_id)
        customers.append({
            "customer_id": customer_id,
            "segment": pick.choices(["Consumer", "Business"], [70, 30])[0],
            "first_order_date": first,
        })
    return customers


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_database(path, orders, customers):
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE customers (
            customer_id      TEXT PRIMARY KEY,
            segment          TEXT NOT NULL,      -- Consumer or Business
            first_order_date TEXT NOT NULL       -- YYYY-MM-DD
        );
        CREATE TABLE orders (
            order_id    TEXT PRIMARY KEY,
            order_date  TEXT NOT NULL,           -- YYYY-MM-DD, all in 2025
            customer_id TEXT NOT NULL REFERENCES customers(customer_id),
            region      TEXT NOT NULL,           -- West, East, South, North
            category    TEXT NOT NULL,           -- Audio, Wearables, Home, Gaming, Accessories
            channel     TEXT NOT NULL,           -- App, Web, Store
            revenue     INTEGER NOT NULL,        -- whole dollars
            returned    INTEGER NOT NULL         -- 1 if the order was returned, else 0
        );
    """)
    db.executemany("INSERT INTO customers VALUES (:customer_id, :segment, :first_order_date)", customers)
    db.executemany("INSERT INTO orders VALUES (:order_id, :order_date, :customer_id, :region, :category, :channel, :revenue, :returned)", orders)
    db.commit()
    db.close()


def main():
    orders = build_orders()
    customers = build_customers(orders)
    write_csv("orders.csv", orders)
    write_csv("customers.csv", customers)
    build_database("shop.db", orders, customers)
    print(f"Wrote orders.csv ({len(orders)} orders), customers.csv ({len(customers)} customers) and shop.db")


if __name__ == "__main__":
    main()
