"""Streamlit app for 1-hour-ahead fish risk prediction."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import streamlit as st


MODEL_PATH = Path("model.pkl")


def build_input_features(
    temperature: float,
    dissolved_oxygen: float,
    ph_value: float,
    turbidity: float,
) -> pd.DataFrame:
    """Create the same feature columns used during training.

    In a live deployment, lag and rolling features should come from the last
    stored sensor readings. For a simple one-screen demo, the app uses the
    current reading as a neutral lag placeholder and sets deltas to zero.
    """
    hour = datetime.now().hour
    row = {
        "Temperature_C": temperature,
        "Dissolved_Oxygen_mg_L": dissolved_oxygen,
        "pH": ph_value,
        "Turbidity_NTU": turbidity,
        "DO_lag_1": dissolved_oxygen,
        "Temp_lag_1": temperature,
        "pH_lag_1": ph_value,
        "DO_delta": 0.0,
        "Temp_delta": 0.0,
        "DO_mean_3": dissolved_oxygen,
        "DO_std_3": 0.0,
        "hour_sin": np.sin(2 * np.pi * hour / 24),
        "hour_cos": np.cos(2 * np.pi * hour / 24),
    }
    return pd.DataFrame([row])


@st.cache_resource
def load_model() -> dict[str, object]:
    if not MODEL_PATH.exists():
        raise FileNotFoundError("model.pkl not found. Run train_pipeline.py first.")
    return joblib.load(MODEL_PATH)


st.set_page_config(page_title="Aquaculture Risk DSS", layout="centered")
st.title("Aquaculture Risk Decision Support")
st.caption("Predicts whether fish will be at risk in the next 1 hour.")

artifact = load_model()
model = artifact["model"]
feature_columns = artifact["feature_columns"]

with st.form("prediction_form"):
    temperature = st.number_input("Temperature (°C)", min_value=0.0, max_value=45.0, value=28.0, step=0.1)
    dissolved_oxygen = st.number_input("Dissolved Oxygen (mg/L)", min_value=0.0, max_value=20.0, value=6.0, step=0.1)
    ph_value = st.number_input("pH", min_value=0.0, max_value=14.0, value=7.5, step=0.1)
    turbidity = st.number_input("Turbidity (NTU)", min_value=0.0, max_value=100.0, value=3.0, step=0.1)
    submitted = st.form_submit_button("Predict next-hour risk")

if submitted:
    X_live = build_input_features(temperature, dissolved_oxygen, ph_value, turbidity)
    X_live = X_live[feature_columns]

    risk_probability = float(model.predict_proba(X_live)[0][1])
    prediction = int(risk_probability >= 0.5)

    if prediction == 1:
        st.error("Prediction: At Risk")
    else:
        st.success("Prediction: Stable")

    st.metric("Risk probability", f"{risk_probability * 100:.1f}%")

    if risk_probability >= 0.7:
        st.warning("High next-hour risk. Check aeration, oxygen level, temperature, and water exchange immediately.")
    elif risk_probability >= 0.5:
        st.warning("Moderate risk. Increase monitoring frequency and prepare corrective action.")
    else:
        st.info("Current readings suggest low next-hour risk.")

    with st.expander("Feature note"):
        st.write(
            "Lag and rolling features normally require the previous 1-3 sensor readings. "
            "For this standalone demo, the app uses the current readings as neutral placeholders."
        )
