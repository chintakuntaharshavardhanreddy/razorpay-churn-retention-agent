"""
Train a binary classifier to predict customer churn.
Uses XGBoost if available, falls back to sklearn GradientBoostingClassifier.
"""

import pandas as pd
import numpy as np
import joblib
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
from sklearn.preprocessing import LabelEncoder

try:
    from xgboost import XGBClassifier
    USE_XGB = True
except ImportError:
    from sklearn.ensemble import GradientBoostingClassifier
    USE_XGB = False


CATEGORICAL_COLS = ["failure_reason_dominant", "payment_method"]
BOOL_COL = "failure_clustering_near_billing_date"
LABEL_COL = "churned"
DROP_COLS = ["customer_id"]


def main():
    # --- Load data ---
    df = pd.read_csv("data/customers.csv")
    print(f"Loaded {len(df)} rows from data/customers.csv")

    # --- Encode booleans ---
    df[BOOL_COL] = df[BOOL_COL].astype(int)
    df[LABEL_COL] = df[LABEL_COL].astype(int)

    # --- Encode categoricals with LabelEncoder (saved for inference) ---
    label_encoders: dict[str, LabelEncoder] = {}
    for col in CATEGORICAL_COLS:
        le = LabelEncoder()
        df[col] = le.fit_transform(df[col].astype(str))
        label_encoders[col] = le

    # --- Features / target ---
    X = df.drop(columns=DROP_COLS + [LABEL_COL])
    y = df[LABEL_COL]
    feature_names = list(X.columns)

    # --- Split ---
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y,
    )
    print(f"Train: {len(X_train)}, Test: {len(X_test)}")

    # --- Train ---
    if USE_XGB:
        print("Using XGBClassifier")
        model = XGBClassifier(
            n_estimators=150,
            max_depth=4,
            learning_rate=0.1,
            use_label_encoder=False,
            eval_metric="logloss",
            random_state=42,
        )
    else:
        print("XGBoost not available — using sklearn GradientBoostingClassifier")
        model = GradientBoostingClassifier(
            n_estimators=150,
            max_depth=4,
            learning_rate=0.1,
            random_state=42,
        )

    model.fit(X_train, y_train)

    # --- Evaluate ---
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"\n{'='*50}")
    print(f"Test Accuracy: {acc:.4f}")
    print(f"{'='*50}")
    print(f"\nClassification Report:\n{classification_report(y_test, y_pred)}")

    # --- Feature importances ---
    importances = model.feature_importances_
    imp_df = pd.DataFrame({
        "feature": feature_names,
        "importance": importances,
    }).sort_values("importance", ascending=False)
    print("Feature Importances:")
    for _, row in imp_df.iterrows():
        bar = "#" * int(row["importance"] * 40)
        print(f"  {row['feature']:40s} {row['importance']:.4f}  {bar}")

    # --- Save model + encoders ---
    artifact = {
        "model": model,
        "label_encoders": label_encoders,
        "feature_names": feature_names,
        "categorical_cols": CATEGORICAL_COLS,
        "bool_col": BOOL_COL,
    }
    joblib.dump(artifact, "model.pkl")
    print(f"\nSaved model artifact -> model.pkl")


if __name__ == "__main__":
    main()
