-- Database Schema for Razorpay Churn Prediction & Retention Agent

-- 1. Customers Table
CREATE TABLE IF NOT EXISTS customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT,
    tenure_months INTEGER NOT NULL,
    plan_value NUMERIC NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Subscriptions Table
CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    plan_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    billing_cycle TEXT NOT NULL DEFAULT 'monthly',
    next_billing_date DATE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Payment Events Table
CREATE TABLE IF NOT EXISTS payment_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID REFERENCES subscriptions(id) ON DELETE CASCADE,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    status TEXT NOT NULL, -- 'success', 'failed'
    failure_reason TEXT,   -- 'insufficient_funds', 'card_declined', 'expired_card', 'network_error', 'none'
    payment_method TEXT NOT NULL, -- 'card', 'upi', 'netbanking'
    amount NUMERIC NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Actions Log Table
CREATE TABLE IF NOT EXISTS actions_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,
    payment_event_id UUID REFERENCES payment_events(id) ON DELETE SET NULL,
    risk_score NUMERIC NOT NULL,
    risk_flags JSONB DEFAULT '[]'::jsonb,
    action_taken TEXT NOT NULL, -- 'winback_offer', 'downgrade', 'payment_nudge', 'smart_retry', 'pause'
    action_details JSONB,
    outcome TEXT DEFAULT 'pending', -- 'pending', 'success', 'failed'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indices for fast querying
CREATE INDEX IF NOT EXISTS idx_subscriptions_customer_id ON subscriptions(customer_id);
CREATE INDEX IF NOT EXISTS idx_payment_events_customer_id ON payment_events(customer_id);
CREATE INDEX IF NOT EXISTS idx_payment_events_attempted_at ON payment_events(attempted_at);
CREATE INDEX IF NOT EXISTS idx_actions_log_customer_id ON actions_log(customer_id);
