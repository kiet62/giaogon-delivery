"""Run the Random Forest HPO experiment from the authenticated web dashboard."""
from __future__ import annotations

import math
import statistics
import time

import numpy as np
import pandas as pd
from scipy.stats import friedmanchisquare
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

import rf_hpo as core


METHOD_NAMES = ("Grid Search", "Random Search", "Bayesian (TPE)")


def _finite(value):
    value = float(value)
    return value if math.isfinite(value) else None


def run_experiment(*, frame=None, target="is_fraud", rows=1000, budget=10, seeds=1,
                   n_max=300, jobs=1, progress=None):
    """Execute equal-budget searches and return JSON-safe comparison data."""
    synthetic = frame is None
    if synthetic:
        frame = core.make_fraud_data(n=rows, seed=42)
    else:
        frame = frame.copy()
    if target not in frame.columns:
        raise ValueError("Không tìm thấy cột nhãn mục tiêu trong CSV.")
    if not 20 <= len(frame) <= 20000:
        raise ValueError("Dữ liệu cần có từ 20 đến 20.000 dòng.")
    numeric_target = pd.to_numeric(frame[target], errors="raise")
    if numeric_target.isna().any() or not numeric_target.isin([0, 1]).all():
        raise ValueError("Cột mục tiêu phải có đúng hai nhãn số 0 và 1.")
    y = numeric_target.astype(int)
    if min(int(y.value_counts().get(0, 0)), int(y.value_counts().get(1, 0))) < 10:
        raise ValueError("Mỗi nhãn 0 và 1 cần ít nhất 10 dòng để chia dữ liệu và chạy 5-fold CV.")
    X = frame.drop(columns=[target])
    if X.shape[1] < 1 or X.shape[1] > 100:
        raise ValueError("Dữ liệu cần có từ 1 đến 100 cột đặc trưng.")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, stratify=y, random_state=42)
    prep = core.build_preprocessor(X_train)
    core.N_MAX = n_max

    baseline_parameters = dict(n=100, d=None, ms=2, ml=1, mf="sqrt")
    baseline_rows, result_rows, convergence = [], [], []
    total_searches = seeds * (1 + len(METHOD_NAMES) * budget)
    completed_searches = 0

    def update(stage):
        if progress:
            progress({"done": completed_searches, "total": total_searches, "stage": stage})

    for seed in range(seeds):
        evaluator = core.Evaluator(X_train, y_train, prep, seed, jobs)
        cv_auc, _ = evaluator(baseline_parameters)
        baseline_model = Pipeline([
            ("prep", prep), ("rf", core.make_model(baseline_parameters, seed, jobs))
        ]).fit(X_train, y_train)
        probabilities = baseline_model.predict_proba(X_test)[:, 1]
        baseline_rows.append({
            "seed": seed, "cv_auc": _finite(cv_auc),
            "test_auc": _finite(roc_auc_score(y_test, probabilities)),
            "test_ap": _finite(average_precision_score(y_test, probabilities)),
        })
        completed_searches += 1
        update(f"Đã đánh giá baseline · seed {seed + 1}/{seeds}")

        for method in METHOD_NAMES:
            update(f"Đang chạy {method} · seed {seed + 1}/{seeds}")
            started = time.perf_counter()
            if method == "Grid Search":
                trials = core.run_grid(evaluator, budget, seed)
            elif method == "Random Search":
                trials = core.run_optuna(evaluator, budget, seed, "random")
            else:
                trials = core.run_optuna(evaluator, budget, seed, "tpe")
            wall_time = time.perf_counter() - started
            scores = np.asarray([trial[1] for trial in trials], dtype=float)
            best_index = int(scores.argmax())
            best_99_index = int(np.flatnonzero(scores >= 0.99 * scores.max())[0])
            best_params = trials[best_index][0]
            model = Pipeline([
                ("prep", prep), ("rf", core.make_model(best_params, seed, jobs))
            ]).fit(X_train, y_train)
            probabilities = model.predict_proba(X_test)[:, 1]
            inference_latency = core.latency_ms(best_params, X_train, y_train, X_test, prep, seed)
            for index, (params, score, evaluation_seconds) in enumerate(trials, start=1):
                convergence.append({"method": method, "seed": seed, "evaluation": index,
                                    "cv_auc": _finite(score), "best_so_far": _finite(scores[:index].max())})
                result_rows.append({
                    "method": method, "seed": seed, "evaluation": index,
                    "cv_auc": _finite(score), "evaluation_time_s": _finite(evaluation_seconds),
                    **{f"{key}": value for key, value in params.items()},
                })
            result_rows.append({
                "method": method, "seed": seed, "evaluation": "best",
                "cv_auc": _finite(scores.max()),
                "test_auc": _finite(roc_auc_score(y_test, probabilities)),
                "test_ap": _finite(average_precision_score(y_test, probabilities)),
                "wall_time_s": _finite(wall_time),
                "inference_ms_per_1000": _finite(inference_latency),
                "evaluations_to_best": best_index + 1,
                "evaluations_to_99pct": best_99_index + 1,
                **{f"best_{key}": value for key, value in best_params.items()},
            })
            completed_searches += budget
            update(f"Hoàn tất {method} · seed {seed + 1}/{seeds}")

    summary = []
    for method in ("Baseline", *METHOD_NAMES):
        if method == "Baseline":
            group = baseline_rows
            metrics = {"cv_auc": [r["cv_auc"] for r in group],
                       "test_auc": [r["test_auc"] for r in group],
                       "test_ap": [r["test_ap"] for r in group]}
        else:
            group = [r for r in result_rows if r["method"] == method and r["evaluation"] == "best"]
            metrics = {key: [r[key] for r in group if r.get(key) is not None]
                       for key in ("cv_auc", "test_auc", "test_ap", "wall_time_s", "inference_ms_per_1000",
                                   "evaluations_to_best", "evaluations_to_99pct")}
        row = {"method": method, "seeds": len(group)}
        for key, values in metrics.items():
            if values:
                row[f"{key}_mean"] = _finite(statistics.fmean(values))
                row[f"{key}_std"] = _finite(statistics.pstdev(values))
        best = max(group, key=lambda item: item.get("cv_auc", item.get("cv_auc_mean", -1))) if group else {}
        if method != "Baseline":
            for key in ("best_n", "best_d", "best_ms", "best_ml", "best_mf"):
                if key in best:
                    row[key] = best[key]
        summary.append(row)

    p_value = None
    if seeds >= 3:
        values = []
        for method in METHOD_NAMES:
            values.append([next(r["cv_auc"] for r in result_rows
                                if r["method"] == method and r["seed"] == seed and r["evaluation"] == "best")
                           for seed in range(seeds)])
        try:
            p_value = _finite(friedmanchisquare(*values).pvalue)
        except (ValueError, FloatingPointError):
            pass

    convergence_summary = []
    for method in METHOD_NAMES:
        for evaluation in range(1, budget + 1):
            values = [row["best_so_far"] for row in convergence
                      if row["method"] == method and row["evaluation"] == evaluation]
            if values:
                convergence_summary.append({"method": method, "evaluation": evaluation,
                                            "mean_best_auc": _finite(statistics.fmean(values)),
                                            "std_best_auc": _finite(statistics.pstdev(values))})

    sensitivity = []
    if result_rows:
        trial_frame = pd.DataFrame([row for row in result_rows if row["evaluation"] != "best"])
        trial_frame["mf_code"] = trial_frame["mf"].map({"sqrt": 0, "log2": 1, "all": 2})
        for parameter in ("n", "d", "ms", "ml", "mf_code"):
            corr = trial_frame[parameter].rank().corr(trial_frame["cv_auc"].rank())
            sensitivity.append({"parameter": "mf" if parameter == "mf_code" else parameter,
                                "spearman_with_cv_auc": _finite(corr)})
    worst_trials = sorted((row for row in result_rows if row["evaluation"] != "best"),
                          key=lambda row: row["cv_auc"])[:5]
    pareto_front = []
    best_by_latency = sorted((row for row in result_rows if row["evaluation"] == "best"),
                              key=lambda row: row.get("inference_ms_per_1000", float("inf")))
    best_auc_so_far = -float("inf")
    for row in best_by_latency:
        score = row["cv_auc"]
        if score > best_auc_so_far:
            pareto_front.append({"method": row["method"], "seed": row["seed"],
                                 "inference_ms_per_1000": row["inference_ms_per_1000"], "cv_auc": score})
            best_auc_so_far = score

    return {
        "data": {"source": "Dữ liệu mô phỏng" if synthetic else "CSV tải lên",
                 "rows": int(len(frame)), "features": int(X.shape[1]),
                 "positive_rate": _finite(float(y.mean())), "target": target},
        "settings": {"budget": budget, "seeds": seeds, "folds": 5, "n_max": n_max},
        "summary": summary, "baseline_runs": baseline_rows,
        "best_runs": [r for r in result_rows if r["evaluation"] == "best"],
        "trials": [r for r in result_rows if r["evaluation"] != "best"],
        "convergence": convergence_summary, "friedman_p_value": p_value,
        "sensitivity": sensitivity, "worst_trials": worst_trials, "pareto_front": pareto_front,
    }
