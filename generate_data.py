"""
Synthetic dataset generator for churn prediction.
Generates 200 customers across 5 archetypes with realistic correlations.
"""

import os
import uuid
import random
import numpy as np
import pandas as pd

PLAN_VALUES = [499, 999, 1299, 1499, 1999, 2499, 4499, 4999, 5999]
FAILURE_REASONS = ["insufficient_funds", "card_declined", "expired_card", "network_error", "none"]
PAYMENT_METHODS = ["card", "upi", "netbanking"]

random.seed(42)
np.random.seed(42)


def _clamp(val, lo, hi):
    return max(lo, min(hi, val))


def generate_archetype_1(n: int) -> list[dict]:
    """Price-sensitive: short tenure, higher plan_value, 2-3 failures, insufficient_funds, higher churn."""
    rows = []
    for _ in range(n):
        tenure = random.randint(1, 6)
        plan = random.choice([1499, 1999, 2499, 4499, 4999])
        failures = random.choice([2, 2, 3, 3, 1])
        reason = np.random.choice(
            ["insufficient_funds", "card_declined", "network_error"],
            p=[0.70, 0.20, 0.10],
        )
        method = np.random.choice(PAYMENT_METHODS, p=[0.3, 0.5, 0.2])
        days_since = random.randint(0, 15)
        clustering = random.random() < 0.35
        churned = random.random() < 0.72
        rows.append(dict(
            customer_id=str(uuid.uuid4()),
            tenure_months=tenure,
            plan_value=float(plan),
            num_failed_payments_30d=failures,
            failure_reason_dominant=reason,
            payment_method=method,
            days_since_last_failure=days_since,
            failure_clustering_near_billing_date=clustering,
            churned=churned,
        ))
    return rows


def generate_archetype_2(n: int) -> list[dict]:
    """Card-issue: long tenure, card_declined/expired_card, moderate churn (recoverable)."""
    rows = []
    for _ in range(n):
        tenure = random.randint(8, 15)
        plan = random.choice([499, 999, 1299, 1499, 1999])
        failures = random.choice([1, 2, 2, 3])
        reason = np.random.choice(
            ["card_declined", "expired_card", "insufficient_funds"],
            p=[0.50, 0.35, 0.15],
        )
        method = np.random.choice(["card", "upi", "netbanking"], p=[0.75, 0.15, 0.10])
        days_since = random.randint(1, 20)
        clustering = random.random() < 0.25
        churned = random.random() < 0.38
        rows.append(dict(
            customer_id=str(uuid.uuid4()),
            tenure_months=tenure,
            plan_value=float(plan),
            num_failed_payments_30d=failures,
            failure_reason_dominant=reason,
            payment_method=method,
            days_since_last_failure=days_since,
            failure_clustering_near_billing_date=clustering,
            churned=churned,
        ))
    return rows


def generate_archetype_3(n: int) -> list[dict]:
    """High-value occasional: long tenure, high plan_value, 1 failure, low churn."""
    rows = []
    for _ in range(n):
        tenure = random.randint(18, 36)
        plan = random.choice([4499, 4999, 5999])
        failures = random.choice([0, 1, 1])
        reason = np.random.choice(
            ["network_error", "insufficient_funds", "none"],
            p=[0.45, 0.30, 0.25],
        )
        if failures == 0:
            reason = "none"
        method = np.random.choice(PAYMENT_METHODS, p=[0.5, 0.3, 0.2])
        days_since = random.randint(5, 30)
        clustering = random.random() < 0.15
        churned = random.random() < 0.15
        rows.append(dict(
            customer_id=str(uuid.uuid4()),
            tenure_months=tenure,
            plan_value=float(plan),
            num_failed_payments_30d=failures,
            failure_reason_dominant=reason,
            payment_method=method,
            days_since_last_failure=days_since,
            failure_clustering_near_billing_date=clustering,
            churned=churned,
        ))
    return rows


def generate_archetype_4(n: int) -> list[dict]:
    """Timing-pattern: medium tenure, clustering=true, insufficient_funds, low-moderate churn."""
    rows = []
    for _ in range(n):
        tenure = random.randint(5, 10)
        plan = random.choice([999, 1299, 1499, 1999])
        failures = random.choice([1, 2, 2, 3])
        reason = np.random.choice(
            ["insufficient_funds", "card_declined", "network_error"],
            p=[0.65, 0.20, 0.15],
        )
        method = np.random.choice(PAYMENT_METHODS, p=[0.35, 0.45, 0.20])
        days_since = random.randint(0, 5)  # recent, near billing
        clustering = random.random() < 0.88  # high likelihood of clustering
        churned = random.random() < 0.30
        rows.append(dict(
            customer_id=str(uuid.uuid4()),
            tenure_months=tenure,
            plan_value=float(plan),
            num_failed_payments_30d=failures,
            failure_reason_dominant=reason,
            payment_method=method,
            days_since_last_failure=days_since,
            failure_clustering_near_billing_date=clustering,
            churned=churned,
        ))
    return rows


def generate_archetype_5(n: int) -> list[dict]:
    """At-risk/low-engagement: very short tenure, 3+ failures, high churn."""
    rows = []
    for _ in range(n):
        tenure = random.randint(1, 3)
        plan = random.choice([499, 999, 1299, 1499])
        failures = random.choice([3, 4, 4, 5, 6])
        reason = np.random.choice(
            ["insufficient_funds", "card_declined", "expired_card"],
            p=[0.50, 0.35, 0.15],
        )
        method = np.random.choice(PAYMENT_METHODS, p=[0.30, 0.50, 0.20])
        days_since = random.randint(0, 7)
        clustering = random.random() < 0.45
        churned = random.random() < 0.82
        rows.append(dict(
            customer_id=str(uuid.uuid4()),
            tenure_months=tenure,
            plan_value=float(plan),
            num_failed_payments_30d=failures,
            failure_reason_dominant=reason,
            payment_method=method,
            days_since_last_failure=days_since,
            failure_clustering_near_billing_date=clustering,
            churned=churned,
        ))
    return rows


def main():
    rows = []
    rows.extend(generate_archetype_1(40))
    rows.extend(generate_archetype_2(40))
    rows.extend(generate_archetype_3(40))
    rows.extend(generate_archetype_4(40))
    rows.extend(generate_archetype_5(40))

    df = pd.DataFrame(rows)
    # Shuffle so archetypes aren't in order
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)

    os.makedirs("data", exist_ok=True)
    df.to_csv("data/customers.csv", index=False)

    print(f"Generated {len(df)} customers -> data/customers.csv")
    print(f"Churn rate: {df['churned'].mean():.2%}")
    print(f"\nColumn dtypes:\n{df.dtypes}")
    print(f"\nSample rows:\n{df.head()}")


if __name__ == "__main__":
    main()
