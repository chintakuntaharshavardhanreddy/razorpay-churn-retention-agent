"""
batch_simulation.py

Runs churn prediction + decision logic against every customer currently
in Supabase, WITHOUT triggering n8n or writing to actions_log. Produces
a summary report: revenue at risk, revenue protected per lever, and a
stopping-rule confirmation (one decision per customer, no duplicates).

Requires SUPABASE_URL and SUPABASE_ANON_KEY in .env, and model.pkl to
already exist (run train_model.py first if not).
"""

import os
import json
import datetime
import requests
import pandas as pd
from collections import defaultdict
from dotenv import load_dotenv

from decision_logic import decide_action
import joblib

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]

HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
}

RISK_THRESHOLD = 0.6


def fetch_all(table, select="*"):
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/{table}?select={select}",
        headers=HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def build_customer_features(customer, events):
    """Compute the exact same feature set used by /simulate-payment-failure in main.py."""
    now = datetime.datetime.now(datetime.timezone.utc)
    failed_events = [e for e in events if e.get("status") == "failed"]

    failures_30d = 0
    reasons = {}
    days_since = 30

    for e in failed_events:
        try:
            dt_str = e.get("attempted_at", "").replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            days_diff = (now - dt).days

            if 0 <= days_diff <= 30:
                failures_30d += 1
                r = e.get("failure_reason", "none")
                reasons[r] = reasons.get(r, 0) + 1
                if days_diff < days_since:
                    days_since = days_diff
        except Exception as e:
            print(f"Error parsing event: {e}")

    dominant_reason = "none"
    if reasons:
        dominant_reason = max(reasons, key=reasons.get)
        if dominant_reason not in ["insufficient_funds", "card_declined", "expired_card", "network_error", "none"]:
            dominant_reason = "none"

    clustering = (failures_30d >= 2 and days_since <= 5)

    payment_method = "card"
    if events and len(events) > 0:
        payment_method = events[0].get("payment_method", "card")

    return {
        "tenure_months": customer["tenure_months"],
        "plan_value": float(customer["plan_value"]),
        "num_failed_payments_30d": failures_30d,
        "failure_reason_dominant": dominant_reason,
        "payment_method": payment_method,
        "days_since_last_failure": days_since if failures_30d > 0 else 30,
        "failure_clustering_near_billing_date": clustering,
    }


def main():
    print("Loading model artifact...")
    artifact = joblib.load("model.pkl")
    model = artifact["model"]
    label_encoders = artifact["label_encoders"]
    feature_names = artifact["feature_names"]
    categorical_cols = artifact["categorical_cols"]
    bool_col = artifact["bool_col"]

    print("Fetching customers, subscriptions, payment_events from Supabase...")
    customers = fetch_all("customers")
    subscriptions = fetch_all("subscriptions")
    payment_events = fetch_all("payment_events")

    sub_by_customer = {s["customer_id"]: s["id"] for s in subscriptions}
    events_by_sub = defaultdict(list)
    events_by_customer = defaultdict(list)
    for ev in payment_events:
        if "subscription_id" in ev and ev["subscription_id"]:
            events_by_sub[ev["subscription_id"]].append(ev)
        if "customer_id" in ev and ev["customer_id"]:
            events_by_customer[ev["customer_id"]].append(ev)

    seen_customer_ids = set()
    results = []
    action_counts = defaultdict(int)
    action_value = defaultdict(float)
    high_risk_value = 0.0
    high_risk_count = 0
    low_risk_count = 0
    duplicates_found = 0

    for cust in customers:
        cust_id = cust["id"]

        if cust_id in seen_customer_ids:
            duplicates_found += 1
            continue
        seen_customer_ids.add(cust_id)

        cust["subscription_id"] = sub_by_customer.get(cust_id)
        events = events_by_customer.get(cust_id) or events_by_sub.get(cust["subscription_id"], [])
        events = sorted(events, key=lambda e: e.get("attempted_at", ""), reverse=True)

        features = build_customer_features(cust, events)

        # --- Predict risk score exactly matching main.py ---
        try:
            model_input = {}
            for fname in feature_names:
                if fname in features and features[fname] is not None:
                    model_input[fname] = features[fname]
                else:
                    model_input[fname] = 0

            # Encode boolean column
            model_input[bool_col] = int(model_input[bool_col])

            # Encode categorical columns
            for col in categorical_cols:
                le = label_encoders[col]
                val = model_input[col]
                if val not in le.classes_:
                    model_input[col] = 0
                else:
                    model_input[col] = le.transform([val])[0]

            row = pd.DataFrame([model_input])[feature_names]
            proba = model.predict_proba(row)[0]
            risk_score = float(proba[1])
        except Exception as e:
            print(f"  ! Prediction failed for {cust_id}: {e}")
            continue

        decision = decide_action(risk_score, features)
        action = decision["action"]

        action_counts[action] += 1
        action_value[action] += features["plan_value"]

        if risk_score >= RISK_THRESHOLD:
            high_risk_count += 1
            high_risk_value += features["plan_value"]
        else:
            low_risk_count += 1

        results.append({
            "customer_id": cust_id,
            "name": cust["name"],
            "risk_score": round(risk_score, 4),
            "action": action,
            "plan_value": features["plan_value"],
        })

    total = len(seen_customer_ids)

    print("\n" + "=" * 60)
    print("BATCH SIMULATION SUMMARY")
    print("=" * 60)
    print(f"Total customers processed: {total}")
    print(f"High-risk (>= {RISK_THRESHOLD}): {high_risk_count}")
    print(f"Low-risk: {low_risk_count}")
    print(f"Revenue at risk (sum of plan_value for high-risk customers): INR {high_risk_value:,.2f}")
    print("\nAction breakdown:")
    for action, count in sorted(action_counts.items(), key=lambda x: -x[1]):
        print(f"  {action:20s} count={count:3d}   plan_value_covered=INR {action_value[action]:,.2f}")
    print(f"\nStopping rule check: {duplicates_found} duplicate customer decisions found (should be 0)")
    print("=" * 60)

    summary = {
        "total_customers": total,
        "high_risk_count": high_risk_count,
        "low_risk_count": low_risk_count,
        "revenue_at_risk": round(high_risk_value, 2),
        "action_breakdown": {
            action: {"count": count, "plan_value_covered": round(action_value[action], 2)}
            for action, count in action_counts.items()
        },
        "duplicate_decisions_found": duplicates_found,
        "results": results,
    }

    with open("batch_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("\nSaved full results to batch_summary.json")


if __name__ == "__main__":
    main()
