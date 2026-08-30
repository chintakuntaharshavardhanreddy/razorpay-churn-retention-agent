# Architecture

## Design Philosophy

Most churn-prevention tools treat payment failures as a plumbing problem: a card gets declined, so you retry it a few times and move on. This project starts from a different premise — **a payment failure is the earliest, clearest, most actionable churn signal a subscription business gets**, and it deserves a decision engine of its own rather than a retry loop bolted onto a payments API.

Two principles follow from that:

1. **Payment failure as the trigger, not general churn signals.** Usage drop-off, support tickets, and NPS scores are slow and noisy. A failed payment is immediate, unambiguous, and gives you a real intervention window *before* the subscription actually lapses.
2. **Subscription management as a first-class feature.** Instead of one action ("retry the card"), the system distinguishes between five distinct situations — a price-sensitive customer, a genuine card issue, unlucky billing-date timing, a high-value loyal customer, or an at-risk newcomer — and picks the retention lever that actually fits the situation, not a one-size-fits-all retry.

The result is a system that treats churn risk as a spectrum to be diagnosed, not a binary to be reacted to.

## System Overview

```
                    ┌─────────────────────────┐
                    │   Payment Failure Event │
                    │  (Razorpay Test Mode)   │
                    └────────────┬────────────┘
                                 │
                                 ▼
                 ┌───────────────────────────────┐
                 │   FastAPI Service (main.py)   │
                 │                               │
                 │  /simulate-payment-failure    │
                 │  → fetches customer + payment │
                 │    event history from Supabase│
                 │  → computes feature vector    │
                 │   (tenure, plan value, failure│
                 │    count/reason, clustering)  │
                 └────────────┬──────────────────┘
                                 │
                                 ▼
                 ┌───────────────────────────────┐
                 │   XGBoost Model               │
                 │   (trained on 200 synthetic   │
                 │   customers, 5 archetypes)    │
                 │   → churn risk_score (0–1)    │
                 └────────────┬──────────────────┘
                                 │
                                 ▼
                 ┌───────────────────────────────┐
                 │   Decision Engine             │
                 │   (decision_logic.py)         │
                 │   → rule-based mapping of     │
                 │     risk_score + features to  │
                 │     one retention action      │
                 │→ full reasoning trail returned│
                 └────────────┬──────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                   ▼
        ┌──────────┐      ┌────────────┐      ┌──────────────┐
        │ Supabase │      │  n8n Cloud │      │   Response   │
        │ actions_ │◄─────┤  Webhook   │      │   returned   │
        │ log write│      │  Workflow  │      │   to caller  │
        └──────────┘      └──────┬─────┘      └──────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼              ▼
              ┌──────────┐ ┌───────────┐ ┌──────────────┐
              │ Razorpay │ │  Resend   │ │  Supabase    │
              │ API call │ │  Email    │ │  outcome log │
              │ (pause/  │ │  (offer/  │ │  (success/   │
              │downgrade/│ │  nudge)   │ │  error)      │
              │ retry)   │ │           │ │              │
              └──────────┘ └───────────┘ └──────────────┘
```

## Component Breakdown

### 1. Feature Computation (`main.py` — `simulate_payment_failure`)

Given only a `customer_id`, the service reconstructs the exact feature vector the model expects:
- Pulls the customer record and full payment event history from Supabase
- Filters failed events to a rolling 30-day window
- Determines the dominant failure reason (most frequent reason among recent failures)
- Detects **billing-date clustering** — a heuristic flag for 2+ failures within 5 days, which distinguishes "this customer keeps trying and failing near their renewal date" (a timing problem) from a more spread-out failure pattern (a deeper risk signal)

This step exists so the system can be triggered by nothing more than a customer ID — the caller doesn't need to know or pass any derived features themselves.

### 2. Risk Scoring (`train_model.py`, `model.pkl`)

An XGBoost classifier trained on 200 synthetic customers across 5 archetypes (price-sensitive, card-issue, high-value occasional, timing-pattern, at-risk newcomer). Categorical features (`failure_reason_dominant`, `payment_method`) are label-encoded and the encoders are persisted alongside the model so training and inference stay consistent. Output is a single `risk_score` between 0 and 1 — the probability the customer churns.

### 3. Decision Engine (`decision_logic.py`)

This is the core design decision of the project: **risk_score alone doesn't determine the action.** The engine evaluates risk_score together with tenure, plan value, failure count, failure reason, and clustering, through an ordered set of rules, to land on one of five actions:

| Priority | Action | Core Trigger |
|---|---|---|
| 1 | `winback_offer` | High-value plan + low recent failures + established tenure |
| 2 | `downgrade` | Elevated risk + short tenure + mid/high plan |
| 3 | `payment_nudge` | Card declined / expired card |
| 4 | `smart_retry` | Billing-date clustering + manageable risk |
| 5 | `pause` | High risk + very short tenure |

Notably, `winback_offer` is checked **first** and is deliberately decoupled from `risk_score` — a high-value, low-failure, long-tenure customer should get a proactive winback offer regardless of their current risk score, because waiting for risk_score to climb before rewarding loyalty defeats the purpose of retention.

Every decision returns a full reasoning trail: which risk flags were observed, and which rule ultimately fired — so the "why" behind any action is inspectable, not a black box.

### 4. Orchestration (n8n Cloud)

The decision is forwarded via webhook to an n8n workflow, which is where the decision actually becomes a real-world action:
- A **Switch node** routes on the `action` field into one of five branches
- Each branch calls the **Razorpay API** (Test Mode) to execute the actual subscription change, and/or sends an email via **Resend**
- **Continue On Fail** is enabled on all Razorpay nodes, since Test Mode calls can return expected 404s — this ensures the email and logging steps still execute even when the payment-side call doesn't succeed, which matters for demonstrating the full flow in a sandbox environment
- The outcome (success/error) is written back to Supabase's `actions_log` table, closing the loop

### 5. Logging (Supabase)

Every decision — regardless of whether the downstream n8n action succeeds — is logged to `actions_log` with the risk score, risk flags, action taken, and outcome. This is the audit trail: it means the system's decisions are traceable and reviewable after the fact, not just fire-and-forget.

## Key Engineering Decisions & Trade-offs

- **Rule-based decision layer on top of an ML risk score**, rather than a single end-to-end model predicting the action directly. This keeps the mapping from risk to action interpretable and easy to adjust without retraining — a real consideration for a system that's directly triggering financial actions on a customer's subscription.
- **Synthetic, archetype-based training data** rather than real customer data — appropriate for a buildathon context, but means the model's learned patterns reflect the archetypes' construction rather than genuine, messy real-world churn behavior.
- **Webhook-triggered automation (n8n) rather than in-process side effects** — decouples "decide what to do" from "actually do it," so the retention action logic (Razorpay calls, email sends) can evolve independently of the prediction service, and failures in one don't take down the other.

## Known Limitations

- No authentication was originally required on the decision-triggering endpoints; API-key auth has since been added, but rate limiting and idempotency protection (to prevent duplicate actions from repeated calls) are still open items.
- The Supabase REST calls in `simulate_payment_failure` interpolate `customer_id` directly into the query string rather than using a parameterized client — fine for a trusted internal caller, but not hardened against malformed input.
- Confidence scores returned alongside each decision are heuristic constants tied to each rule, not a calibrated statistical confidence — they indicate how confident the *rule* is, not a probability in the model's terms.
