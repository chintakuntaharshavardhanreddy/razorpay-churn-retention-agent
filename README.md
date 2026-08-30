# Churn Prediction & Retention Agent Service

A FastAPI microservice that predicts customer churn risk and recommends one of 5 retention actions based on payment failure signals, tenure, and plan value.

## Architecture

```
Customer JSON -> /predict-and-decide -> XGBoost model -> risk_score
                                            |
                                     Decision Logic -> action + reasoning
```

### Retention Actions

| Action | Trigger |
|---|---|
| `winback_offer` | High-value plan + low failures + established tenure |
| `downgrade` | Elevated risk + short tenure + mid-high plan |
| `payment_nudge` | Card declined or expired |
| `smart_retry` | Billing-date clustering or default fallback |
| `pause` | High risk + very short tenure newcomer |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy .env.template to .env and fill in your secrets
cp .env.template .env

# 3. Generate synthetic data (200 customers)
python generate_data.py

# 4. Train the model
python train_model.py

# 5. Start the API server
uvicorn main:app --reload
```

The API will be available at `http://127.0.0.1:8000`.  
Interactive docs at `http://127.0.0.1:8000/docs`.

## Authentication

All prediction endpoints require an `X-API-Key` header matching the `API_KEY` value in your `.env` file. The `/health` endpoint is unauthenticated.

## API Endpoints

### `GET /health`

Returns `{"status": "ok"}`. No authentication required.

### `POST /predict-and-decide`

**Headers:**
```
X-API-Key: your-secret-api-key
Content-Type: application/json
```

**Request body:**
```json
{
  "tenure_months": 3,
  "plan_value": 1999,
  "num_failed_payments_30d": 4,
  "failure_reason_dominant": "insufficient_funds",
  "payment_method": "upi",
  "days_since_last_failure": 2,
  "failure_clustering_near_billing_date": false
}
```

**Example (PowerShell):**
```powershell
$headers = @{ "X-API-Key" = "your-secret-api-key" }
$body = '{"tenure_months":3,"plan_value":1999,"num_failed_payments_30d":4,"failure_reason_dominant":"insufficient_funds","payment_method":"upi","days_since_last_failure":2,"failure_clustering_near_billing_date":false}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/predict-and-decide -Method Post -ContentType "application/json" -Headers $headers -Body $body | ConvertTo-Json -Depth 5
```

**Example (curl):**
```bash
curl -X POST http://127.0.0.1:8000/predict-and-decide \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-api-key" \
  -d '{"tenure_months":3,"plan_value":1999,"num_failed_payments_30d":4,"failure_reason_dominant":"insufficient_funds","payment_method":"upi","days_since_last_failure":2,"failure_clustering_near_billing_date":false}'
```

**Response:**
```json
{
  "risk_score": 0.8231,
  "risk_flags": [
    "high_risk_score (0.82)",
    "multiple_payment_failures (4)",
    "very_short_tenure (3mo)"
  ],
  "action": "pause",
  "reasoning": "RULE: high risk + very short tenure -> pause subscription",
  "confidence": 0.65,
  "action_log_id": "f86ce902-...",
  "n8n_triggered": true
}
```

### `POST /simulate-payment-failure`

Looks up real customer data from Supabase and runs the full predict + decide + webhook flow.

**Example (PowerShell):**
```powershell
$headers = @{ "X-API-Key" = "your-secret-api-key" }
$body = '{"customer_id": "11111111-1111-1111-1111-111111111101"}'
Invoke-RestMethod -Uri http://127.0.0.1:8000/simulate-payment-failure -Method Post -ContentType "application/json" -Headers $headers -Body $body | ConvertTo-Json -Depth 5
```

## Project Structure

```
churn-agent-service/
├── .env.template         # Environment variable template (tracked)
├── .gitignore
├── generate_data.py      # Step A: Synthetic dataset generator
├── train_model.py        # Step B: Model training & evaluation
├── decision_logic.py     # Step C: Rule-based decision engine
├── main.py               # Step D: FastAPI service
├── requirements.txt
├── data/
│   └── customers.csv     # Generated dataset
└── model.pkl             # Trained model artifact
```
