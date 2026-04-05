"""
predictor.py — Model-based Real/Fake prediction for ScanSure
=============================================================
Loads model.pkl (sklearn LogisticRegression with 6 features) and converts
OCR-extracted label data into those 6 features.

Feature vector (6 values, all 0-1):
  [0] has_brand            — 1 if OCR found a brand name
  [1] has_product          — 1 if OCR found a product name
  [2] has_barcode          — 1 if a barcode / EAN was decoded
  [3] has_batch            — 1 if a batch/lot number was detected
  [4] ingredient_count_norm — min(n_ingredients, 10) / 10.0
  [5] text_length_norm      — min(len(raw_text), 500) / 500.0

Genuine products typically have all labels present and a long ingredient list.
Counterfeits often miss barcodes, batch numbers, or ingredients.
"""

import os
import pickle
import numpy as np

# ── Load model once at import time ──────────────────────────────────────────
_MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")
_model = None

def _load_model():
    global _model
    if _model is None:
        if not os.path.exists(_MODEL_PATH):
            raise FileNotFoundError(
                f"model.pkl not found at {_MODEL_PATH}. "
                "Run the training script to generate it."
            )
        with open(_MODEL_PATH, "rb") as f:
            _model = pickle.load(f)
    return _model


def extract_features(ocr_data: dict) -> np.ndarray:
    """Convert OCR-extracted dict → 1×6 feature array."""
    has_brand    = 1.0 if ocr_data.get("brand")    else 0.0
    has_product  = 1.0 if ocr_data.get("product")  else 0.0
    has_barcode  = 1.0 if ocr_data.get("barcode")  else 0.0
    has_batch    = 1.0 if ocr_data.get("batch")    else 0.0

    ingredients = ocr_data.get("ingredients") or []
    ingredient_count_norm = min(len(ingredients), 10) / 10.0

    raw_text = ocr_data.get("raw_text") or ""
    text_length_norm = min(len(raw_text), 500) / 500.0

    features = np.array([[
        has_brand,
        has_product,
        has_barcode,
        has_batch,
        ingredient_count_norm,
        text_length_norm,
    ]])
    return features


def predict(ocr_data: dict) -> dict:
    """
    Run the model on OCR data and return a prediction dict:
      {
        "label":      "Real" | "Fake",
        "confidence": float  (0.0 – 1.0, probability of predicted class)
      }
    Falls back to rule-based heuristic if model.pkl is unavailable.
    """
    try:
        model = _load_model()
        features = extract_features(ocr_data)

        label_int   = int(model.predict(features)[0])           # 1=Real, 0=Fake
        proba       = model.predict_proba(features)[0]          # [P(Fake), P(Real)]
        confidence  = float(proba[label_int])

        return {
            "label":      "Real" if label_int == 1 else "Fake",
            "confidence": round(confidence, 4),
            "source":     "model"
        }

    except FileNotFoundError:
        # Graceful fallback: rule-based heuristic
        feats = extract_features(ocr_data)
        score = float(np.mean(feats))          # avg of 6 binary/norm features
        label = "Real" if score >= 0.4 else "Fake"
        return {
            "label":      label,
            "confidence": round(score, 4),
            "source":     "heuristic"          # model.pkl not found
        }
