"""
FastAPI service for churn prediction and retention decision-making.
Integrates with Supabase (Actions Log) and n8n (Webhook Automation).
"""

import os
import uuid
import datetime
from fastapi import FastAPI, HTTPException, Depends, Header, status
from pydantic import BaseModel, Field
import joblib
import pandas as pd
import httpx
from dotenv import load_dotenv

from decision_logic import decide_action

# Load environment variables from .env file
load_dotenv()

app = FastAPI(
    title="Churn Prediction & Retention Agent",
    description="Predicts customer churn risk, recommends retention actions, and triggers n8n workflows.",
    version="1.1.0",
)


async def verify_api_key(x_api_key: str | None = Header(None, alias="X-API-Key")):
    expected_key = os.getenv("API_KEY")
    if not expected_key or x_api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
        )
    return x_api_key

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class CustomerFeatures(BaseModel):
    customer_id: str | None = Field(None, description="Optional customer identifier")
    customer_name: str | None = None
    customer_email: str | None = None
    subscription_id: str | None = None
    payment_id: str | None = None
    downgrade_plan_id: str | None = None

    # Core Model Features
    tenure_months: int = Field(..., ge=1, le=36)
    plan_value: float = Field(..., gt=0)
    num_failed_payments_30d: int = Field(..., ge=0, le=6)
    failure_reason_dominant: str = Field(
        ...,
        pattern="^(insufficient_funds|card_declined|expired_card|network_error|none)$",
    )
    payment_method: str = Field(..., pattern="^(card|upi|netbanking)$")
    days_since_last_failure: int = Field(..., ge=0, le=30)
    failure_clustering_near_billing_date: bool


class PredictionResponse(BaseModel):
    risk_score: float
    risk_flags: list[str]
    action: str
    reasoning: str
    confidence: float
    action_log_id: str
    n8n_triggered: bool


class SimulateRequest(BaseModel):
    customer_id: str


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

_artifact = None

def _load_model():
    global _artifact
    if _artifact is None:
        try:
            _artifact = joblib.load("model.pkl")
        except FileNotFoundError:
            raise HTTPException(
                status_code=503,
                detail="Model not found. Run `python train_model.py` first.",
            )
    return _artifact


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/predict-and-decide", response_model=PredictionResponse, dependencies=[Depends(verify_api_key)])
async def predict_and_decide(body: CustomerFeatures):
    artifact = _load_model()
    model = artifact["model"]
    label_encoders = artifact["label_encoders"]
    feature_names = artifact["feature_names"]
    categorical_cols = artifact["categorical_cols"]
    bool_col = artifact["bool_col"]

    raw = body.model_dump()

    # Extract only the exact features expected by the trained model
    model_input = {}
    for fname in feature_names:
        if fname in raw and raw[fname] is not None:
            model_input[fname] = raw[fname]
        else:
            model_input[fname] = 0  # Fallback (shouldn't happen with strict Pydantic rules)

    # Encode booleans
    model_input[bool_col] = int(model_input[bool_col])

    # Encode categoricals
    for col in categorical_cols:
        le = label_encoders[col]
        val = model_input[col]
        if val not in le.classes_:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown value '{val}' for column '{col}'. "
                       f"Known values: {list(le.classes_)}",
            )
        model_input[col] = le.transform([val])[0]

    # Create feature vector in correct order
    row = pd.DataFrame([model_input])[feature_names]

    # Predict Risk
    proba = model.predict_proba(row)[0]
    risk_score = float(proba[1])  # P(churned=1)

    # Decision Engine
    decision = decide_action(risk_score, raw)

    # Separate risk flags (signal observations) from rule explanations
    risk_flags = [r for r in decision["reasoning"] if not r.startswith("RULE:")]
    rule_reasoning = [r for r in decision["reasoning"] if r.startswith("RULE:")]
    final_action = decision["action"]

    # -----------------------------------------------------------------------
    # Post-Prediction Actions (Supabase Logging + n8n Trigger)
    # -----------------------------------------------------------------------
    action_log_id = str(uuid.uuid4())
    n8n_triggered = False

    sb_url = os.getenv("SUPABASE_URL")
    sb_key = os.getenv("SUPABASE_ANON_KEY")
    n8n_url = os.getenv("N8N_WEBHOOK_URL")

    # 1. Log to Supabase actions_log
    if sb_url and sb_key:
        try:
            sb_headers = {
                "apikey": sb_key,
                "Authorization": f"Bearer {sb_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            }
            sb_payload = {
                "id": action_log_id,
                "customer_id": body.customer_id,
                "risk_score": risk_score,
                "risk_flags": risk_flags,
                "action_taken": final_action,
                "outcome": "pending"
            }
            async with httpx.AsyncClient() as client:
                res = await client.post(f"{sb_url}/rest/v1/actions_log", headers=sb_headers, json=sb_payload)
                res.raise_for_status()
        except Exception as e:
            print(f"Supabase logging failed: {e}")

    # 2. Trigger n8n Webhook
    if n8n_url:
        try:
            webhook_payload = {
                "action_log_id": action_log_id,
                "action": final_action,
                "risk_score": risk_score,
                "customer_id": body.customer_id,
                "customer_name": body.customer_name,
                "customer_email": body.customer_email,
                "subscription_id": body.subscription_id,
                "payment_id": body.payment_id,
                "downgrade_plan_id": body.downgrade_plan_id
            }
            async with httpx.AsyncClient() as client:
                res = await client.post(n8n_url, json=webhook_payload)
                res.raise_for_status()
            n8n_triggered = True
        except Exception as e:
            print(f"n8n webhook failed: {e}")

    return PredictionResponse(
        risk_score=round(risk_score, 4),
        risk_flags=risk_flags,
        action=final_action,
        reasoning="; ".join(rule_reasoning) if rule_reasoning else "default",
        confidence=decision["confidence"],
        action_log_id=action_log_id,
        n8n_triggered=n8n_triggered
    )


@app.post("/simulate-payment-failure", response_model=PredictionResponse, dependencies=[Depends(verify_api_key)])
async def simulate_payment_failure(req: SimulateRequest):
    """
    Fetches real customer and event data from Supabase, computes the feature vector,
    and forwards it through the standard predict_and_decide flow.
    """
    sb_url = os.getenv("SUPABASE_URL")
    sb_key = os.getenv("SUPABASE_ANON_KEY")

    if not sb_url or not sb_key:
        raise HTTPException(status_code=500, detail="Supabase credentials missing from .env")

    headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}"
    }

    async with httpx.AsyncClient() as client:
        # 1. Fetch Customer
        cust_res = await client.get(
            f"{sb_url}/rest/v1/customers?id=eq.{req.customer_id}&select=*", 
            headers=headers
        )
        cust_res.raise_for_status()
        cust_data = cust_res.json()
        if not cust_data:
            raise HTTPException(status_code=404, detail=f"Customer {req.customer_id} not found in Supabase")
        c = cust_data[0]

        # 2. Fetch Payment Events
        ev_res = await client.get(
            f"{sb_url}/rest/v1/payment_events?customer_id=eq.{req.customer_id}&select=*&order=attempted_at.desc", 
            headers=headers
        )
        ev_res.raise_for_status()
        events = ev_res.json()

    # 3. Compute Features dynamically
    now = datetime.datetime.now(datetime.timezone.utc)
    failed_events = [e for e in events if e.get("status") == "failed"]

    failures_30d = 0
    reasons = {}
    days_since = 30

    for e in failed_events:
        try:
            # Handle ISO formatting securely across Python versions
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

    # Simple heuristic: clustered if 2+ failures within 5 days
    clustering = (failures_30d >= 2 and days_since <= 5)

    # Extract payment method from latest event or fallback
    payment_method = "card"
    if events and len(events) > 0:
        payment_method = events[0].get("payment_method", "card")

    # 4. Construct internal feature payload and trigger standard flow
    features = CustomerFeatures(
        customer_id=c.get("id", req.customer_id),
        customer_name=c.get("name") or c.get("customer_name"),
        customer_email=c.get("email") or c.get("customer_email"),
        subscription_id=events[0].get("subscription_id") if events else None,
        tenure_months=c.get("tenure_months", 1),
        plan_value=float(c.get("plan_value", 999.0)),
        payment_method=payment_method,
        num_failed_payments_30d=failures_30d,
        failure_reason_dominant=dominant_reason,
        days_since_last_failure=days_since if failures_30d > 0 else 30,
        failure_clustering_near_billing_date=clustering
    )

    # Delegate directly to our main async handler to process prediction, Supabase logging, and n8n webhook
    return await predict_and_decide(features)
