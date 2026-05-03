"""Train a 1-hour-ahead aquaculture risk model.

The target is future risk:
    target_t1 = Health_Status at the next timestamp

This file is intentionally compact so the notebook and Streamlit app can reuse
the same feature assumptions without data leakage.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


DATA_PATH = Path("Data_Model_IoTMLCQ_2024.xlsx")
MODEL_PATH = Path("model.pkl")
RANDOM_STATE = 42


LEAKAGE_COLUMNS = {
    "Survival_Rate",
    "Thermal_Risk_Index",
    "Low_Oxygen_Alert",
    "Corrective_Measures",
    "Oxygenation_Interventions",
    "Oxygenation_Automatic",
    "Corrective_Interventions",
    "Disease_Occurrence",
}

FEATURE_COLUMNS = [
    "Temperature_C",
    "Dissolved_Oxygen_mg_L",
    "pH",
    "Turbidity_NTU",
    "DO_lag_1",
    "Temp_lag_1",
    "pH_lag_1",
    "DO_delta",
    "Temp_delta",
    "DO_mean_3",
    "DO_std_3",
    "hour_sin",
    "hour_cos",
]


def clean_column_name(name: str) -> str:
    """Make column names code-friendly and normalize the sensor names."""
    cleaned = str(name).strip().replace(" ", "_")
    cleaned = cleaned.replace("(°C)", "C")
    cleaned = cleaned.replace("(mg/L)", "mg_L")
    cleaned = cleaned.replace("(NTU)", "NTU")
    cleaned = cleaned.replace("(%)", "")
    cleaned = cleaned.replace("(Cases)", "")
    cleaned = cleaned.replace("__", "_").strip("_")
    return cleaned


def load_and_clean_data(path: Path = DATA_PATH) -> pd.DataFrame:
    """Load, clean names, parse time, sort, and remove leakage columns."""
    df = pd.read_excel(path)
    df.columns = [clean_column_name(col) for col in df.columns]

    rename_map = {
        "Temperature_C": "Temperature_C",
        "Dissolved_Oxygen_mg_L": "Dissolved_Oxygen_mg_L",
        "Turbidity_NTU": "Turbidity_NTU",
        "Health_Status": "Health_Status",
    }
    df = df.rename(columns=rename_map)

    if "Datetime" not in df.columns:
        raise ValueError("Dataset must include a Datetime column.")
    if "Health_Status" not in df.columns:
        raise ValueError("Dataset must include a Health_Status column.")

    df["Datetime"] = pd.to_datetime(df["Datetime"], errors="coerce")
    df = df.dropna(subset=["Datetime"]).sort_values("Datetime").reset_index(drop=True)

    drop_cols = []
    for col in df.columns:
        base = col.replace("_", " ")
        if any(col.startswith(leak) for leak in LEAKAGE_COLUMNS):
            drop_cols.append(col)
        elif any(term in base.lower() for term in ["alert", "intervention", "corrective", "survival", "thermal risk"]):
            drop_cols.append(col)
    return df.drop(columns=sorted(set(drop_cols)), errors="ignore")


def make_binary_status(series: pd.Series) -> pd.Series:
    """Convert Stable / At Risk labels to 0 / 1."""
    normalized = series.astype(str).str.strip().str.lower()
    return normalized.map({"stable": 0, "at risk": 1, "atrisk": 1, "risk": 1})


def create_features_and_target(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Create temporal features and the shifted t+1 target."""
    required = ["Temperature_C", "Dissolved_Oxygen_mg_L", "pH", "Turbidity_NTU", "Health_Status"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    data = df.copy()
    data["Health_Status_binary"] = make_binary_status(data["Health_Status"])
    data["target_t1"] = data["Health_Status_binary"].shift(-1)

    data["DO_lag_1"] = data["Dissolved_Oxygen_mg_L"].shift(1)
    data["Temp_lag_1"] = data["Temperature_C"].shift(1)
    data["pH_lag_1"] = data["pH"].shift(1)
    data["DO_delta"] = data["Dissolved_Oxygen_mg_L"] - data["DO_lag_1"]
    data["Temp_delta"] = data["Temperature_C"] - data["Temp_lag_1"]
    data["DO_mean_3"] = data["Dissolved_Oxygen_mg_L"].rolling(window=3).mean()
    data["DO_std_3"] = data["Dissolved_Oxygen_mg_L"].rolling(window=3).std()

    hour = data["Datetime"].dt.hour
    data["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    data["hour_cos"] = np.cos(2 * np.pi * hour / 24)

    model_data = data.dropna(subset=FEATURE_COLUMNS + ["target_t1"]).copy()
    X = model_data[FEATURE_COLUMNS]
    y = model_data["target_t1"].astype(int)
    return X, y


def build_models() -> dict[str, object]:
    """Define baseline and main models with imbalance handling."""
    return {
        "Logistic Regression": Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                ("model", LogisticRegression(class_weight="balanced", max_iter=1000, random_state=RANDOM_STATE)),
            ]
        ),
        "Extra Trees Baseline": ExtraTreesClassifier(
            n_estimators=200,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        ),
        "Random Forest": RandomForestClassifier(
            n_estimators=200,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        ),
    }


def train_and_evaluate() -> dict[str, object]:
    """Train all models, print metrics, and save the Random Forest artifact."""
    df = load_and_clean_data(DATA_PATH)
    X, y = create_features_and_target(df)

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        stratify=y,
        random_state=RANDOM_STATE,
    )

    print("Class balance in shifted t+1 target:")
    print(y.value_counts().rename(index={0: "Stable", 1: "At Risk"}))

    models = build_models()
    fitted_models = {}
    for name, model in models.items():
        print(f"\n{name}")
        print("-" * len(name))
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
        print("Confusion Matrix:")
        print(confusion_matrix(y_test, y_pred))
        print("Classification Report:")
        print(classification_report(y_test, y_pred, target_names=["Stable", "At Risk"]))
        fitted_models[name] = model

    artifact = {
        "model": fitted_models["Random Forest"],
        "feature_columns": FEATURE_COLUMNS,
        "target": "target_t1",
        "class_labels": {0: "Stable", 1: "At Risk"},
        "lag_strategy": "Streamlit uses current readings as lag placeholders when prior readings are unavailable.",
    }
    joblib.dump(artifact, MODEL_PATH)
    print(f"\nSaved model artifact to {MODEL_PATH.resolve()}")
    return artifact


if __name__ == "__main__":
    train_and_evaluate()
