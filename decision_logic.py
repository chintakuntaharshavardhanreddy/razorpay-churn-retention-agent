"""
Decision logic: maps a churn risk score + customer signals to a retention action.
"""


def decide_action(risk_score: float, customer_features: dict) -> dict:
    """
    Determine the best retention action given a churn risk score and customer features.

    Returns:
        dict with keys: action, risk_score, reasoning (list of triggered flags), confidence
    """
    plan_value = customer_features.get("plan_value", 0)
    tenure_months = customer_features.get("tenure_months", 0)
    num_failures = customer_features.get("num_failed_payments_30d", 0)
    failure_reason = customer_features.get("failure_reason_dominant", "none")
    clustering = customer_features.get("failure_clustering_near_billing_date", False)

    reasoning: list[str] = []
    action = "smart_retry"  # default
    confidence = 0.5

    # Collect risk flags
    if risk_score >= 0.7:
        reasoning.append(f"high_risk_score ({risk_score:.2f})")
    elif risk_score >= 0.5:
        reasoning.append(f"moderate_risk_score ({risk_score:.2f})")

    if num_failures >= 3:
        reasoning.append(f"multiple_payment_failures ({num_failures})")
    elif num_failures >= 1:
        reasoning.append(f"payment_failure_detected ({num_failures})")

    if failure_reason in ("card_declined", "expired_card"):
        reasoning.append(f"card_issue ({failure_reason})")

    if clustering:
        reasoning.append("failures_clustered_near_billing_date")

    if tenure_months <= 3:
        reasoning.append(f"very_short_tenure ({tenure_months}mo)")
    elif tenure_months <= 6:
        reasoning.append(f"short_tenure ({tenure_months}mo)")

    if plan_value >= 4000:
        reasoning.append(f"high_value_plan (INR {plan_value:.0f})")

    # --- Decision rules (evaluated in priority order) ---

    # Rule 1: High-value winback
    if plan_value >= 4000 and num_failures <= 1 and tenure_months >= 12:
        action = "winback_offer"
        confidence = 0.85
        reasoning.append("RULE: high-value customer with low recent failures and established tenure -> proactive winback offer")

    # Rule 2: Downgrade for price-sensitive short-tenure
    elif risk_score >= 0.6 and tenure_months <= 6 and plan_value >= 1499:
        action = "downgrade"
        confidence = 0.75
        reasoning.append("RULE: elevated risk + short tenure + mid-high plan -> downgrade")

    # Rule 3: Card / payment method issue
    elif failure_reason in ("card_declined", "expired_card"):
        action = "payment_nudge"
        confidence = 0.80
        reasoning.append("RULE: card issue detected -> payment_nudge")

    # Rule 4: Timing-based retry
    elif clustering and risk_score < 0.6:
        action = "smart_retry"
        confidence = 0.70
        reasoning.append("RULE: billing-date clustering + manageable risk -> smart_retry")

    # Rule 5: Pause for at-risk newcomers
    elif risk_score >= 0.65 and tenure_months <= 3:
        action = "pause"
        confidence = 0.65
        reasoning.append("RULE: high risk + very short tenure -> pause subscription")

    # Default
    else:
        action = "smart_retry"
        confidence = 0.50
        reasoning.append("RULE: no specific trigger matched -> default smart_retry")

    return {
        "action": action,
        "risk_score": round(risk_score, 4),
        "reasoning": reasoning,
        "confidence": round(confidence, 4),
    }
