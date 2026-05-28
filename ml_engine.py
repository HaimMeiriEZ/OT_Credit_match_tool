# -*- coding: utf-8 -*-
"""
ml_engine — שכבת ה-AI של כלי התאמות קרדיט 2000.

אחראית על:
1. LabelStore — שמירה/טעינה של תיוגי משתמש (התאם/דחה) לקובץ JSON.
2. FeatureBuilder — בניית וקטור פיצ'רים לכל זוג (חריג קרדיט, חריג ספק).
3. MatchModel — XGBClassifier wrapper עם save/load/predict_proba.
4. suggest_matches — לוקח חריגי קרדיט+ספק ומחזיר הצעות מדורגות.

המודול לא תלוי ב-Qt — מקבל ומחזיר dicts/DataFrames בלבד.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

# Optional imports — נטענים בעצלות כדי לא לחסום הפעלת ה-UI אם xgboost חסר.
try:
    import xgboost as xgb
    _XGB_AVAILABLE = True
except ImportError:
    _XGB_AVAILABLE = False

try:
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import train_test_split
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False


# =====================================================================
# קבועי ML
# =====================================================================

ML_DATA_DIR_NAME = "ml_data"
LABELS_FILENAME = "labels.json"
MODEL_FILENAME_TPL = "model_{supplier_key}.json"
META_FILENAME = "model_meta.json"

MIN_SAMPLES_FOR_CONFIDENT_MODEL = 30
POSITIVE_STREAK_THRESHOLD = 5  # אחרי N חיוביים ברצף → הצע סימון דחיות
LABELS_VERSION = 1
FEATURES_VERSION = 1

# סדר הפיצ'רים — חייב להישמר זהה בין אימון להסקה!
FEATURE_COLUMNS = [
    "same_card",
    "same_pnr",
    "same_auth",
    "pnr_similarity",
    "auth_similarity",
    "amount_diff_abs",
    "amount_diff_pct",
    "amount_sign_match",
    "pnr_len_diff",
    "auth_len_diff",
]


# =====================================================================
# עזרי מסלולים
# =====================================================================

def get_ml_data_dir(base_dir: str | None = None) -> str:
    """מחזיר (ויוצר במידת הצורך) את תיקיית ml_data ליד הסקריפט."""
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, ML_DATA_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def labels_path(base_dir: str | None = None) -> str:
    return os.path.join(get_ml_data_dir(base_dir), LABELS_FILENAME)


def model_path(supplier_key: str, base_dir: str | None = None) -> str:
    safe_key = str(supplier_key).replace("/", "_").replace("\\", "_")
    return os.path.join(get_ml_data_dir(base_dir), MODEL_FILENAME_TPL.format(supplier_key=safe_key))


def meta_path(base_dir: str | None = None) -> str:
    return os.path.join(get_ml_data_dir(base_dir), META_FILENAME)


# =====================================================================
# LabelStore — ניהול תיוגי המשתמש
# =====================================================================

class LabelStore:
    """ניהול קובץ labels.json עם פעולות add/load/streak."""

    def __init__(self, base_dir: str | None = None):
        self.path = labels_path(base_dir)
        self._data = self._load()

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {"version": LABELS_VERSION, "labels": []}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "labels" not in data:
                data["labels"] = []
            return data
        except (json.JSONDecodeError, OSError):
            return {"version": LABELS_VERSION, "labels": []}

    def _save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def add_label(
        self,
        supplier_key: str,
        credit_row: dict,
        supplier_row: dict | None,
        label: int,
    ) -> str:
        """מוסיף תיוג. label=1 התאמה, label=0 דחיה. מחזיר id חדש."""
        record_id = str(uuid.uuid4())
        self._data["labels"].append({
            "id": record_id,
            "timestamp": datetime.utcnow().isoformat(),
            "supplier_key": supplier_key,
            "features_version": FEATURES_VERSION,
            "credit_row": _make_serializable(credit_row),
            "supplier_row": _make_serializable(supplier_row) if supplier_row else None,
            "label": int(label),
        })
        self._save()
        return record_id

    def all_labels(self) -> list[dict]:
        return list(self._data.get("labels", []))

    def labels_for_supplier(self, supplier_key: str) -> list[dict]:
        return [
            lbl for lbl in self._data.get("labels", [])
            if lbl.get("supplier_key") == supplier_key
        ]

    def count_total(self) -> int:
        return len(self._data.get("labels", []))

    def positive_streak(self) -> int:
        """כמה תיוגים חיוביים ברצף בסוף הרשימה (מתאפס כשמופיע label=0)."""
        streak = 0
        for lbl in reversed(self._data.get("labels", [])):
            if int(lbl.get("label", 0)) == 1:
                streak += 1
            else:
                break
        return streak

    def is_pair_labeled(self, credit_key: str, supplier_key_id: str) -> bool:
        """בדיקה האם זוג מסוים כבר תויג (לפי מפתחות זהות)."""
        for lbl in self._data.get("labels", []):
            if lbl.get("_credit_key") == credit_key and lbl.get("_supplier_key_id") == supplier_key_id:
                return True
        return False


def _make_serializable(obj: Any) -> Any:
    """ממיר אובייקטים שלא ניתנים לסריאליזציה ל-JSON (numpy, pandas, וכו')."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {str(k): _make_serializable(v) for k, v in obj.items() if not str(k).startswith("_raw_records")}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if pd.isna(obj) if not isinstance(obj, (str, dict, list)) else False:
        return None
    return obj


# =====================================================================
# FeatureBuilder — חילוץ פיצ'רים מזוג רשומות
# =====================================================================

def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val).strip()


def _safe_float(val: Any) -> float:
    if val is None:
        return 0.0
    s = _safe_str(val).replace(",", "").replace("₪", "").strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _string_similarity(a: str, b: str) -> float:
    """דמיון מחרוזות פשוט בטווח 0..1 (יחס תווים זהים מקסימום)."""
    a, b = _safe_str(a), _safe_str(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # חישוב מהיר: LCS-suffix מבוסס דמיון תווי קצה (לרוב PNR/auth נבדלים בקצוות)
    max_len = max(len(a), len(b))
    # נספור תווים זהים באותו אינדקס מהסוף
    matches = sum(1 for i in range(1, min(len(a), len(b)) + 1) if a[-i] == b[-i])
    return matches / max_len


def _get_match_field(record: dict, canonical_key: str, fallback_keys: list[str] | None = None) -> str:
    """מחזיר ערך עבור מפתח canonical (כמו match_card) או חלופות."""
    if not isinstance(record, dict):
        return ""
    # קודם מפתח canonical (אם הוטמע)
    val = record.get(canonical_key) or record.get(f"_{canonical_key}")
    if val:
        return _safe_str(val)
    if fallback_keys:
        for fk in fallback_keys:
            if fk in record and _safe_str(record[fk]):
                return _safe_str(record[fk])
    return ""


def _get_match_amount(record: dict) -> float:
    if not isinstance(record, dict):
        return 0.0
    for k in ("_match_amount", "match_amount", "סכום מקובץ", "סכום", "Amount",
             "סכום מטבע ראשי", "origin amount"):
        if k in record and _safe_str(record[k]):
            return _safe_float(record[k])
    return 0.0


def build_pair_features(credit_rec: dict, supplier_rec: dict) -> dict:
    """בונה וקטור פיצ'רים עבור זוג חריגים. מפתחות = FEATURE_COLUMNS."""
    c_card = _get_match_field(credit_rec, "match_card", ["טוקן", "Pan"])
    s_card = _get_match_field(supplier_rec, "match_card",
                              ["Details", "4 ספרות אחרונות", "Card", "Payment Method"])

    c_pnr = _get_match_field(credit_rec, "match_pnr", ["מספר הזמנה"])
    s_pnr = _get_match_field(supplier_rec, "match_pnr",
                             ["מס' תיק", "Pnr", "Credit Account Name"])

    c_auth = _get_match_field(credit_rec, "match_auth", ["מספר אישור"])
    s_auth = _get_match_field(supplier_rec, "match_auth",
                              ["מספר אישור", "ref", "Description"])

    c_amt = _get_match_amount(credit_rec)
    s_amt = _get_match_amount(supplier_rec)

    amt_diff = c_amt - s_amt
    amt_diff_abs = abs(amt_diff)
    denom = max(abs(c_amt), abs(s_amt), 1.0)
    amt_diff_pct = amt_diff_abs / denom

    return {
        "same_card": 1 if c_card and s_card and c_card == s_card else 0,
        "same_pnr": 1 if c_pnr and s_pnr and c_pnr == s_pnr else 0,
        "same_auth": 1 if c_auth and s_auth and c_auth == s_auth else 0,
        "pnr_similarity": _string_similarity(c_pnr, s_pnr),
        "auth_similarity": _string_similarity(c_auth, s_auth),
        "amount_diff_abs": amt_diff_abs,
        "amount_diff_pct": amt_diff_pct,
        "amount_sign_match": 1 if (c_amt >= 0) == (s_amt >= 0) else 0,
        "pnr_len_diff": abs(len(c_pnr) - len(s_pnr)),
        "auth_len_diff": abs(len(c_auth) - len(s_auth)),
    }


def features_to_dataframe(records: list[dict]) -> pd.DataFrame:
    """ממיר רשימת dict-פיצ'רים ל-DataFrame בסדר עמודות קבוע."""
    if not records:
        return pd.DataFrame(columns=FEATURE_COLUMNS)
    return pd.DataFrame(records, columns=FEATURE_COLUMNS).fillna(0)


# =====================================================================
# MatchModel — XGBoost wrapper
# =====================================================================

class MatchModel:
    """Wrapper דק סביב XGBClassifier בינארי."""

    def __init__(self):
        if not _XGB_AVAILABLE:
            raise RuntimeError("xgboost לא מותקן. הרץ: pip install xgboost")
        self.clf = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.1,
            objective="binary:logistic",
            eval_metric="logloss",
            random_state=42,
        )
        self.is_fitted = False
        self.feature_columns = list(FEATURE_COLUMNS)

    def fit(self, X: pd.DataFrame, y: list[int]) -> dict:
        """מאמן ומחזיר metrics dict: n_samples, n_positive, n_negative, auc, importances."""
        X = X[self.feature_columns].fillna(0)
        y_arr = np.asarray(y, dtype=int)
        n_samples = len(y_arr)
        n_pos = int((y_arr == 1).sum())
        n_neg = int((y_arr == 0).sum())

        auc = None
        # AUC רק אם יש מספיק דגימות משתי המחלקות
        if _SKLEARN_AVAILABLE and n_pos >= 2 and n_neg >= 2 and n_samples >= 8:
            try:
                X_tr, X_te, y_tr, y_te = train_test_split(
                    X, y_arr, test_size=0.25, random_state=42, stratify=y_arr,
                )
                self.clf.fit(X_tr, y_tr)
                preds = self.clf.predict_proba(X_te)[:, 1]
                auc = float(roc_auc_score(y_te, preds))
                # אימון מחדש על כל הדאטה לפני שמירה
                self.clf.fit(X, y_arr)
            except Exception:
                self.clf.fit(X, y_arr)
        else:
            self.clf.fit(X, y_arr)

        self.is_fitted = True
        importances = dict(zip(
            self.feature_columns,
            [float(v) for v in getattr(self.clf, "feature_importances_", [0.0] * len(self.feature_columns))]
        ))
        return {
            "n_samples": n_samples,
            "n_positive": n_pos,
            "n_negative": n_neg,
            "auc": auc,
            "importances": importances,
        }

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("המודל לא אומן עדיין.")
        X = X[self.feature_columns].fillna(0)
        return self.clf.predict_proba(X)[:, 1]

    def save(self, path: str) -> None:
        if not self.is_fitted:
            raise RuntimeError("אין מודל מאומן לשמירה.")
        self.clf.save_model(path)

    @classmethod
    def load(cls, path: str) -> "MatchModel":
        if not _XGB_AVAILABLE:
            raise RuntimeError("xgboost לא מותקן.")
        if not os.path.exists(path):
            raise FileNotFoundError(f"קובץ מודל לא נמצא: {path}")
        m = cls()
        m.clf.load_model(path)
        m.is_fitted = True
        return m


# =====================================================================
# אימון והסקה ברמת ספק
# =====================================================================

def train_supplier_model(
    supplier_key: str,
    label_store: LabelStore,
    base_dir: str | None = None,
) -> dict:
    """מאמן מודל לספק יחיד, שומר ל-disk, מעדכן מטא. מחזיר metrics dict."""
    labels = label_store.labels_for_supplier(supplier_key)
    if len(labels) < 2:
        return {
            "ok": False,
            "reason": "אין מספיק תיוגים לאימון (נדרשים לפחות 2).",
            "n_samples": len(labels),
        }

    feature_dicts = []
    y = []
    for lbl in labels:
        cred = lbl.get("credit_row") or {}
        sup = lbl.get("supplier_row") or {}
        feature_dicts.append(build_pair_features(cred, sup))
        y.append(int(lbl.get("label", 0)))

    n_pos = sum(y)
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return {
            "ok": False,
            "reason": "נדרש לפחות תיוג אחד מכל סוג (התאמה ודחיה).",
            "n_samples": len(y),
            "n_positive": n_pos,
            "n_negative": n_neg,
        }

    X = features_to_dataframe(feature_dicts)
    model = MatchModel()
    metrics = model.fit(X, y)
    model.save(model_path(supplier_key, base_dir))
    _update_meta(supplier_key, metrics, base_dir)
    metrics["ok"] = True
    return metrics


def _update_meta(supplier_key: str, metrics: dict, base_dir: str | None) -> None:
    path = meta_path(base_dir)
    meta: dict = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            meta = {}
    meta.setdefault("models", {})
    meta["models"][supplier_key] = {
        "trained_at": datetime.utcnow().isoformat(),
        "features_version": FEATURES_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "n_samples": metrics.get("n_samples"),
        "n_positive": metrics.get("n_positive"),
        "n_negative": metrics.get("n_negative"),
        "auc": metrics.get("auc"),
        "importances": metrics.get("importances"),
        "supports_shap": False,  # יעבור ל-True בשלב 2
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def load_supplier_model(supplier_key: str, base_dir: str | None = None) -> MatchModel | None:
    """טוען מודל אם קיים, אחרת None (לא קורס)."""
    path = model_path(supplier_key, base_dir)
    if not os.path.exists(path) or not _XGB_AVAILABLE:
        return None
    try:
        return MatchModel.load(path)
    except Exception:
        return None


def get_model_meta(supplier_key: str, base_dir: str | None = None) -> dict | None:
    path = meta_path(base_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return meta.get("models", {}).get(supplier_key)
    except (json.JSONDecodeError, OSError):
        return None


# =====================================================================
# suggest_matches — הצעות אוטומטיות לחריגים
# =====================================================================

def suggest_matches(
    credit_exceptions: list[dict],
    supplier_exceptions: list[dict],
    model: MatchModel,
    threshold: float = 0.5,
) -> list[dict]:
    """
    לכל חריג קרדיט מחזיר את חריג הספק עם score גבוה ביותר (אם מעל threshold).

    Returns: list בגודל len(credit_exceptions). כל item הוא:
        {"best_supplier_idx": int|None, "score": float, "matched_label": str}
    """
    n_credit = len(credit_exceptions)
    n_sup = len(supplier_exceptions)
    if n_credit == 0:
        return []
    if n_sup == 0 or model is None or not model.is_fitted:
        return [{"best_supplier_idx": None, "score": 0.0, "matched_label": ""} for _ in range(n_credit)]

    results: list[dict] = []
    for c_rec in credit_exceptions:
        # candidate generation: רק זוגות עם לפחות התאמת כרטיס/PNR/auth אחת
        candidate_pairs: list[tuple[int, dict]] = []
        for idx, s_rec in enumerate(supplier_exceptions):
            feats = build_pair_features(c_rec, s_rec)
            if feats["same_card"] or feats["same_pnr"] or feats["same_auth"]:
                candidate_pairs.append((idx, feats))

        if not candidate_pairs:
            results.append({"best_supplier_idx": None, "score": 0.0, "matched_label": ""})
            continue

        X = features_to_dataframe([f for _, f in candidate_pairs])
        scores = model.predict_proba(X)
        best_local = int(np.argmax(scores))
        best_score = float(scores[best_local])
        best_idx = candidate_pairs[best_local][0]
        if best_score >= threshold:
            results.append({
                "best_supplier_idx": best_idx,
                "score": best_score,
                "matched_label": _short_label_for_record(supplier_exceptions[best_idx]),
            })
        else:
            results.append({"best_supplier_idx": None, "score": best_score, "matched_label": ""})
    return results


def _short_label_for_record(rec: dict) -> str:
    """תווית קצרה לרשומת ספק להצגה בעמודת 'הצעת AI'."""
    if not isinstance(rec, dict):
        return ""
    for k in ("מס' תיק", "Pnr", "Credit Account Name", "ref", "Doc number", "Description"):
        v = _safe_str(rec.get(k, ""))
        if v:
            return f"{k}={v}"
    return "ספק"


# =====================================================================
# Pair-key utilities — לבדיקת תיוגים קודמים
# =====================================================================

def build_pair_key(credit_rec: dict) -> str:
    """מפתח זהות לרשומת קרדיט (לזיהוי תיוגים קודמים)."""
    parts = [
        _get_match_field(credit_rec, "match_card", ["טוקן"]),
        _get_match_field(credit_rec, "match_pnr", ["מספר הזמנה"]),
        _get_match_field(credit_rec, "match_auth", ["מספר אישור"]),
        f"{_get_match_amount(credit_rec):.2f}",
    ]
    return "|".join(parts)


def build_supplier_key(supplier_rec: dict) -> str:
    parts = [
        _get_match_field(supplier_rec, "match_card",
                         ["Details", "4 ספרות אחרונות", "Card", "Payment Method"]),
        _get_match_field(supplier_rec, "match_pnr",
                         ["מס' תיק", "Pnr", "Credit Account Name"]),
        _get_match_field(supplier_rec, "match_auth",
                         ["מספר אישור", "ref", "Description"]),
        f"{_get_match_amount(supplier_rec):.2f}",
    ]
    return "|".join(parts)


__all__ = [
    "FEATURE_COLUMNS",
    "FEATURES_VERSION",
    "MIN_SAMPLES_FOR_CONFIDENT_MODEL",
    "POSITIVE_STREAK_THRESHOLD",
    "LabelStore",
    "MatchModel",
    "build_pair_features",
    "features_to_dataframe",
    "train_supplier_model",
    "load_supplier_model",
    "get_model_meta",
    "suggest_matches",
    "build_pair_key",
    "build_supplier_key",
    "get_ml_data_dir",
]
