"""
seed_supabase_batch.py

Generates ~80 additional synthetic customers directly into Supabase
(customers, subscriptions, payment_events tables) to give the batch
simulation a realistic sample size (~95 total with the original 15).

Requires SUPABASE_URL and SUPABASE_ANON_KEY in .env
"""

import os
import uuid
import random
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]

HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json",
}

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna",
    "Ishaan", "Rohan", "Ananya", "Diya", "Aadhya", "Kavya", "Saanvi", "Myra",
    "Aarohi", "Anika", "Riya", "Isha", "Kabir", "Yash", "Dev", "Raj", "Nikhil",
    "Pooja", "Sneha", "Neha", "Priya", "Meera", "Tanvi", "Aryan", "Karan",
]
LAST_NAMES = [
    "Sharma", "Verma", "Gupta", "Iyer", "Nair", "Reddy", "Rao", "Menon",
    "Kapoor", "Malhotra", "Chopra", "Bose", "Mehta", "Joshi", "Kulkarni",
    "Pillai", "Desai", "Agarwal", "Bhatt", "Chauhan",
]

PLAN_CATALOG = {
    "Basic": 999,
    "Standard": 1499,
    "Pro": 1999,
    "Premium": 2499,
    "Business": 4499,
    "Enterprise": 4999,
}

ARCHETYPES = [
    "price_sensitive",
    "card_issue",
    "high_value_occasional",
    "timing_pattern",
    "at_risk_low_engagement",
]

TOTAL_NEW_CUSTOMERS = 80
PER_ARCHETYPE = TOTAL_NEW_CUSTOMERS // len(ARCHETYPES)


def random_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def days_ago(n):
    return (datetime.utcnow() - timedelta(days=n)).isoformat()


def days_from_now(n):
    return (datetime.utcnow() + timedelta(days=n)).date().isoformat()


def build_customer(index, archetype):
    cust_id = str(uuid.uuid4())
    name = random_name()
    email = f"customer{index}@example.com"
    phone = f"98{random.randint(10000000, 99999999)}"

    if archetype == "price_sensitive":
        tenure = random.randint(1, 6)
        plan_name = random.choice(["Standard", "Pro"])
        plan_value = PLAN_CATALOG[plan_name]
        num_failures = random.randint(2, 3)
        reason = "insufficient_funds"
        method = random.choice(["card", "upi"])
        clustering = False

    elif archetype == "card_issue":
        tenure = random.randint(8, 15)
        plan_name = random.choice(["Basic", "Standard"])
        plan_value = PLAN_CATALOG[plan_name]
        num_failures = random.randint(1, 2)
        reason = random.choice(["card_declined", "expired_card"])
        method = "card"
        clustering = False

    elif archetype == "high_value_occasional":
        tenure = random.randint(18, 36)
        plan_name = random.choice(["Business", "Enterprise"])
        plan_value = PLAN_CATALOG[plan_name]
        num_failures = 1
        reason = random.choice(["network_error", "insufficient_funds"])
        method = random.choice(["card", "upi"])
        clustering = False

    elif archetype == "timing_pattern":
        tenure = random.randint(5, 10)
        plan_name = random.choice(["Standard", "Premium"])
        plan_value = PLAN_CATALOG[plan_name]
        num_failures = random.randint(1, 2)
        reason = "insufficient_funds"
        method = random.choice(["upi", "netbanking"])
        clustering = True

    else:  # at_risk_low_engagement
        tenure = random.randint(1, 3)
        plan_name = random.choice(["Basic", "Standard"])
        plan_value = PLAN_CATALOG[plan_name]
        num_failures = random.randint(3, 4)
        reason = random.choice(["insufficient_funds", "card_declined"])
        method = "card"
        clustering = False

    customer_row = {
        "id": cust_id,
        "name": name,
        "email": email,
        "phone": phone,
        "tenure_months": tenure,
        "plan_value": plan_value,
    }

    sub_id = str(uuid.uuid4())
    subscription_row = {
        "id": sub_id,
        "customer_id": cust_id,
        "plan_name": plan_name,
        "status": "active",
        "billing_cycle": "monthly",
        "next_billing_date": days_from_now(random.randint(1, 30)),
    }

    payment_event_rows = []
    for _ in range(num_failures):
        payment_event_rows.append({
            "subscription_id": sub_id,
            "customer_id": cust_id,
            "status": "failed",
            "failure_reason": reason,
            "payment_method": method,
            "amount": plan_value,
            "attempted_at": days_ago(
                random.randint(1, 3) if clustering else random.randint(1, 10)
            ),
        })

    return customer_row, subscription_row, payment_event_rows


def insert_row(table, row):
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers={**HEADERS, "Prefer": "return=minimal"},
        json=row,
        timeout=15,
    )
    if resp.status_code not in (200, 201, 204):
        print(f"  ! Failed inserting into {table}: {resp.status_code} {resp.text}")
    return resp.status_code in (200, 201, 204)


def main():
    print(f"Seeding {TOTAL_NEW_CUSTOMERS} customers across {len(ARCHETYPES)} archetypes...")
    inserted = 0

    for archetype in ARCHETYPES:
        for i in range(PER_ARCHETYPE):
            index = inserted + 1
            customer_row, subscription_row, payment_event_rows = build_customer(index, archetype)

            ok = insert_row("customers", customer_row)
            if ok:
                ok = insert_row("subscriptions", subscription_row)
            if ok:
                for ev in payment_event_rows:
                    insert_row("payment_events", ev)

            inserted += 1
            print(f"Inserted customer {inserted}/{TOTAL_NEW_CUSTOMERS} ({archetype})")

    # Confirm final count
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/customers?select=id",
        headers={**HEADERS, "Prefer": "count=exact"},
        timeout=15,
    )
    count = resp.headers.get("content-range", "unknown")
    print(f"\nDone. customers table content-range header: {count}")
    print("(Format is 'start-end/total' - the number after '/' is your total row count)")


if __name__ == "__main__":
    main()
