"""
Đồ án: Tối ưu siêu tham số Random Forest trong phát hiện giao dịch bất thường
So sánh Grid Search, Random Search, Bayesian Optimization (TPE / Optuna)

Cách chạy:
    pip install scikit-learn optuna pandas matplotlib scipy
    python rf_hpo.py                          # dữ liệu mô phỏng, ngân sách mặc định
    python rf_hpo.py --budget 100 --seeds 5   # đúng ngân sách trong báo cáo
    python rf_hpo.py --csv giaodich.csv --target is_fraud   # dùng dữ liệu thật

Kết quả nằm trong thư mục results/ (csv, biểu đồ, report.md).
"""
import argparse
import itertools
import os
import time
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import optuna
import pandas as pd
from scipy.stats import friedmanchisquare
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)

METHODS = ["Grid Search", "Random Search", "Bayesian (TPE)"]

# Lưới cho Grid Search: 2*3*2*2*3 = 72 tổ hợp (không vượt ngân sách 100)
N_MAX = 1000
GRID = {
    "n": [100, 1000],
    "d": [5, 15, 50],
    "ms": [2, 20],
    "ml": [1, 10],
    "mf": ["sqrt", "log2", "all"],
}


# ----------------------------------------------------------------------------
# 1. Dữ liệu
# ----------------------------------------------------------------------------
def make_fraud_data(n=4000, seed=0):
    """Dữ liệu giao dịch mô phỏng (mất cân bằng ~6% gian lận, có giá trị thiếu)."""
    r = np.random.default_rng(seed)
    amount = r.lognormal(4.0, 1.2, n)
    hour = r.integers(0, 24, n)
    distance = r.gamma(2.0, 15.0, n)
    tx24 = r.poisson(3, n)
    age = r.integers(1, 3000, n)
    merch = r.beta(2, 5, n)
    card = r.choice(["debit", "credit", "prepaid", "virtual"], n, p=[.4, .35, .15, .1])
    loc = r.choice(["home", "domestic", "abroad", "unknown", "vpn"], n, p=[.45, .3, .1, .1, .05])
    z = (-7.9 + 1.1 * np.log(amount) - 0.5 * np.log(age)
         + 0.012 * distance + 0.25 * tx24 + 2.5 * merch
         + 0.9 * (card == "prepaid") + 0.7 * (card == "virtual")
         + 1.0 * (loc == "abroad") + 1.2 * (loc == "vpn")
         + 2.2 * ((hour < 5) & (amount > 100))                 # tương tác phi tuyến
         + 2.0 * ((tx24 > 5) & (distance > 40))
         + r.normal(0, 0.5, n))
    y = (r.random(n) < 1 / (1 + np.exp(-z))).astype(int)
    df = pd.DataFrame(dict(amount=amount, hour=hour, distance_km=distance, tx_count_24h=tx24,
                           account_age_days=age, merchant_risk=merch, card_type=card,
                           device_location=loc, is_fraud=y))
    for c in ["amount", "distance_km", "merchant_risk"]:       # giả lập giá trị thiếu
        df.loc[r.random(n) < 0.03, c] = np.nan
    return df


def build_preprocessor(X):
    num = X.select_dtypes(include="number").columns.tolist()
    cat = [c for c in X.columns if c not in num]
    return ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), num),
        ("cat", Pipeline([("imp", SimpleImputer(strategy="most_frequent")),
                          ("oh", OneHotEncoder(handle_unknown="ignore"))]), cat),
    ])


# ----------------------------------------------------------------------------
# 2. Hàm mục tiêu (hộp đen): AUC trung bình 5-fold CV
# ----------------------------------------------------------------------------
def make_model(p, seed, n_jobs):
    mf = None if p["mf"] == "all" else p["mf"]
    return RandomForestClassifier(
        n_estimators=p["n"], max_depth=p["d"], min_samples_split=p["ms"],
        min_samples_leaf=p["ml"], max_features=mf, random_state=seed,
        n_jobs=n_jobs, class_weight="balanced_subsample")


class Evaluator:
    """Đánh giá một cấu hình; dùng chung cho cả 3 phương pháp để so sánh công bằng."""

    def __init__(self, X, y, prep, seed, n_jobs):
        self.X, self.y, self.prep, self.seed, self.n_jobs = X, y, prep, seed, n_jobs
        self.cv = StratifiedKFold(5, shuffle=True, random_state=seed)

    def __call__(self, p):
        pipe = Pipeline([("prep", self.prep), ("rf", make_model(p, self.seed, self.n_jobs))])
        t0 = time.perf_counter()
        auc = cross_val_score(pipe, self.X, self.y, cv=self.cv, scoring="roc_auc").mean()
        return float(auc), time.perf_counter() - t0


def latency_ms(p, X_tr, y_tr, X_te, prep, seed, n_jobs=1):
    """Độ trễ suy luận (ms / 1000 mẫu), đo trên 1 luồng để ổn định."""
    pipe = Pipeline([("prep", prep), ("rf", make_model(p, seed, n_jobs))]).fit(X_tr, y_tr)
    Xt = prep.transform(X_te)
    rf = pipe.named_steps["rf"]
    best = 1e9
    for _ in range(3):
        t0 = time.perf_counter()
        rf.predict_proba(Xt)
        best = min(best, time.perf_counter() - t0)
    return best / len(X_te) * 1000 * 1000


# ----------------------------------------------------------------------------
# 3. Ba phương pháp tìm kiếm
# ----------------------------------------------------------------------------
def suggest(trial):
    return dict(
        n=trial.suggest_int("n", 100, N_MAX, step=100),
        d=trial.suggest_int("d", 5, 50),
        ms=trial.suggest_int("ms", 2, 20),
        ml=trial.suggest_int("ml", 1, 20),
        mf=trial.suggest_categorical("mf", ["sqrt", "log2", "all"]),
    )


def run_grid(ev, budget, seed):
    keys = list(GRID)
    grid = {**GRID, "n": [100, N_MAX]}
    combos = [dict(zip(keys, v)) for v in itertools.product(*grid.values())]
    rng = np.random.default_rng(seed)
    rng.shuffle(combos)                  # đổi thứ tự duyệt theo seed (kết quả cuối không đổi nếu duyệt hết)
    return [(p, *ev(p)) for p in combos[:budget]]


def run_optuna(ev, budget, seed, sampler_name):
    sampler = (optuna.samplers.RandomSampler(seed=seed) if sampler_name == "random"
               else optuna.samplers.TPESampler(seed=seed, n_startup_trials=10))
    study = optuna.create_study(direction="maximize", sampler=sampler)
    out = []

    def obj(trial):
        p = suggest(trial)
        auc, t = ev(p)
        out.append((p, auc, t))
        return auc

    study.optimize(obj, n_trials=budget)
    return out


# ----------------------------------------------------------------------------
# 4. Chạy thực nghiệm
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=100, help="số cấu hình / phương pháp / seed")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--rows", type=int, default=4000)
    ap.add_argument("--csv", type=str, default=None)
    ap.add_argument("--target", type=str, default="is_fraud")
    ap.add_argument("--latency_limit", type=float, default=None,
                    help="ngưỡng độ trễ ms/1000 mẫu; mặc định = trung vị các cấu hình tốt nhất")
    ap.add_argument("--n_max", type=int, default=1000, help="cận trên n_estimators (giảm để chạy nhanh)")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--out", type=str, default="results")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    global N_MAX
    N_MAX = a.n_max

    df = pd.read_csv(a.csv) if a.csv else make_fraud_data(a.rows)
    y = df[a.target].astype(int)
    X = df.drop(columns=[a.target])
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, stratify=y, random_state=42)
    prep = build_preprocessor(X)
    print(f"Dữ liệu: {len(df)} dòng, tỉ lệ bất thường {y.mean():.2%}; "
          f"train {len(X_tr)} / test {len(X_te)}")

    # Baseline: cấu hình mặc định của sklearn
    default_p = dict(n=100, d=None, ms=2, ml=1, mf="sqrt")
    rows, hist = [], []
    base = []
    for s in range(a.seeds):
        ev = Evaluator(X_tr, y_tr, prep, s, a.jobs)
        pipe_p = {**default_p}
        auc_cv, _ = ev(pipe_p)
        m = Pipeline([("prep", prep), ("rf", make_model(pipe_p, s, a.jobs))]).fit(X_tr, y_tr)
        pr = m.predict_proba(X_te)[:, 1]
        base.append(dict(seed=s, cv_auc=auc_cv, test_auc=roc_auc_score(y_te, pr),
                         test_ap=average_precision_score(y_te, pr)))
    base = pd.DataFrame(base)
    print("Baseline (mặc định):", base[["cv_auc", "test_auc"]].mean().round(4).to_dict())

    for s in range(a.seeds):
        for method in METHODS:
            ev = Evaluator(X_tr, y_tr, prep, s, a.jobs)
            t0 = time.perf_counter()
            if method == "Grid Search":
                trials = run_grid(ev, a.budget, s)
            elif method == "Random Search":
                trials = run_optuna(ev, a.budget, s, "random")
            else:
                trials = run_optuna(ev, a.budget, s, "tpe")
            wall = time.perf_counter() - t0

            aucs = np.array([t[1] for t in trials])
            for i, (p, auc, t) in enumerate(trials):
                hist.append(dict(method=method, seed=s, eval=i + 1, cv_auc=auc, fit_time=t,
                                 best_so_far=aucs[: i + 1].max(), **p))
            bi = int(aucs.argmax())
            bp = trials[bi][0]

            # đánh giá cuối trên tập test độc lập (chỉ dùng sau khi đã chọn cấu hình)
            m = Pipeline([("prep", prep), ("rf", make_model(bp, s, a.jobs))]).fit(X_tr, y_tr)
            pr = m.predict_proba(X_te)[:, 1]
            lat = latency_ms(bp, X_tr, y_tr, X_te, prep, s)
            thr = 0.99 * aucs.max()
            rows.append(dict(method=method, seed=s, best_cv_auc=aucs.max(),
                             test_auc=roc_auc_score(y_te, pr), test_ap=average_precision_score(y_te, pr),
                             wall_time_s=wall, evals_to_best=bi + 1,
                             evals_to_99pct=int(np.argmax(aucs >= thr) + 1),
                             latency_ms_per_1k=lat, **{f"best_{k}": v for k, v in bp.items()}))
            print(f"seed {s} | {method:<15} cv_auc={aucs.max():.4f} test_auc={rows[-1]['test_auc']:.4f} "
                  f"time={wall:6.1f}s best={bp}", flush=True)

    res, hist = pd.DataFrame(rows), pd.DataFrame(hist)
    res.to_csv(f"{a.out}/runs_summary.csv", index=False)
    hist.to_csv(f"{a.out}/all_trials.csv", index=False)
    base.to_csv(f"{a.out}/baseline.csv", index=False)

    analyze(res, hist, base, a)


# ----------------------------------------------------------------------------
# 5. Phân tích, biểu đồ, báo cáo
# ----------------------------------------------------------------------------
def pareto(df, x="latency", y="cv_auc"):
    """Các điểm không bị lấn át: độ trễ thấp hơn VÀ AUC cao hơn."""
    d = df.sort_values([x, y], ascending=[True, False])
    keep, best = [], -1
    for i, r in d.iterrows():
        if r[y] > best:
            keep.append(i)
            best = r[y]
    return d.loc[keep]


def analyze(res, hist, base, a):
    out = a.out
    agg = res.groupby("method").agg(
        cv_auc_mean=("best_cv_auc", "mean"), cv_auc_std=("best_cv_auc", lambda v: v.std(ddof=0)),
        test_auc_mean=("test_auc", "mean"), test_auc_std=("test_auc", lambda v: v.std(ddof=0)),
        test_ap_mean=("test_ap", "mean"),
        time_mean=("wall_time_s", "mean"), evals_to_99pct=("evals_to_99pct", "mean"),
        evals_to_best=("evals_to_best", "mean"), latency_mean=("latency_ms_per_1k", "mean"),
    ).reindex(METHODS)
    agg.to_csv(f"{out}/method_comparison.csv")

    # Friedman test trên AUC CV giữa 3 phương pháp (mỗi seed là một khối)
    piv = res.pivot(index="seed", columns="method", values="best_cv_auc")[METHODS]
    pval = None
    if len(piv) >= 3:
        try:
            pval = friedmanchisquare(*[piv[m] for m in METHODS]).pvalue
        except Exception:
            pass

    # ---- Phân tích độ nhạy: tương quan hạng giữa siêu tham số và AUC (gộp mọi trial)
    h = hist.copy()
    h["mf_code"] = h["mf"].map({"sqrt": 0, "log2": 1, "all": 2})
    sens = {k: h[k].rank().corr(h["cv_auc"].rank()) for k in ["n", "d", "ms", "ml", "mf_code"]}
    sens = pd.Series(sens).rename({"mf_code": "mf"})
    sens.to_csv(f"{out}/sensitivity.csv", header=["spearman_with_cv_auc"])
    mf_tab = h.groupby("mf")["cv_auc"].agg(["mean", "max", "count"])

    # ---- Failure cases: 5 cấu hình tệ nhất
    worst = h.sort_values("cv_auc").head(5)[["method", "n", "d", "ms", "ml", "mf", "cv_auc"]]

    # ---- Ràng buộc độ trễ: AUC cao nhất khi độ trễ <= ngưỡng (đo độ trễ cho các cấu hình tốt)
    top = (h.sort_values("cv_auc", ascending=False)
             .drop_duplicates(subset=["n", "d", "ms", "ml", "mf"]).head(40))
    Xtr_lat = pd.read_csv(a.csv) if a.csv else make_fraud_data(a.rows)
    yy = Xtr_lat[a.target].astype(int)
    XX = Xtr_lat.drop(columns=[a.target])
    Xa, Xb, ya, _ = train_test_split(XX, yy, test_size=0.25, stratify=yy, random_state=42)
    prep = build_preprocessor(XX)
    lats = []
    for _, r in top.iterrows():
        p = dict(n=int(r.n), d=int(r.d), ms=int(r.ms), ml=int(r.ml), mf=r.mf)
        lats.append(latency_ms(p, Xa, ya, Xb, prep, 0))
    top = top.assign(latency=lats)
    top.to_csv(f"{out}/top_configs_with_latency.csv", index=False)
    limit = a.latency_limit or float(top["latency"].median())
    ok = top[top["latency"] <= limit]
    best_c = ok.sort_values("cv_auc", ascending=False).iloc[0] if len(ok) else None
    best_u = top.sort_values("cv_auc", ascending=False).iloc[0]
    front = pareto(top)

    # ================= biểu đồ =================
    colors = dict(zip(METHODS, ["#c0504d", "#4f81bd", "#2e8b57"]))

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for m in METHODS:
        g = hist[hist.method == m].groupby("eval")["best_so_far"].agg(["mean", "std"]).fillna(0)
        ax.plot(g.index, g["mean"], label=m, color=colors[m], lw=2)
        ax.fill_between(g.index, g["mean"] - g["std"], g["mean"] + g["std"], color=colors[m], alpha=.15)
    ax.axhline(base.cv_auc.mean(), ls="--", c="gray", label="Mặc định (baseline)")
    ax.set_xlabel("Số cấu hình đã đánh giá"); ax.set_ylabel("AUC CV tốt nhất tới thời điểm đó")
    ax.set_title("Đường hội tụ (trung bình ± độ lệch chuẩn qua các seed)")
    ax.legend(); ax.grid(alpha=.3); fig.tight_layout(); fig.savefig(f"{out}/convergence.png", dpi=150); plt.close(fig)

    fig, axs = plt.subplots(1, 3, figsize=(12, 4))
    for ax, col, ttl in zip(axs, ["best_cv_auc", "test_auc", "wall_time_s"],
                            ["AUC CV tốt nhất", "AUC trên tập test", "Thời gian chạy (giây)"]):
        data = [res[res.method == m][col] for m in METHODS]
        bp = ax.boxplot(data, labels=["Grid", "Random", "TPE"], patch_artist=True)
        for patch, m in zip(bp["boxes"], METHODS):
            patch.set_facecolor(colors[m]); patch.set_alpha(.6)
        ax.set_title(ttl); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(f"{out}/boxplots.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 4))
    sens.sort_values().plot.barh(ax=ax, color="#4f81bd")
    ax.set_title("Độ nhạy: tương quan hạng (Spearman) với AUC CV"); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(f"{out}/sensitivity.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    ax.scatter(top["latency"], top["cv_auc"], c="lightgray", label="Cấu hình tốt (top 40)")
    ax.plot(front["latency"], front["cv_auc"], "o-", c="#c0504d", label="Pareto front")
    ax.axvline(limit, ls="--", c="gray", label=f"Ngưỡng {limit:.0f} ms/1k")
    ax.set_xlabel("Độ trễ suy luận (ms / 1000 mẫu)"); ax.set_ylabel("AUC CV")
    ax.set_title("Đánh đổi Accuracy - Latency"); ax.legend(); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(f"{out}/pareto_latency.png", dpi=150); plt.close(fig)

    # ================= báo cáo markdown =================
    best_row = res.sort_values("best_cv_auc", ascending=False).iloc[0]
    winner_auc = agg["cv_auc_mean"].idxmax()
    winner_speed = agg["evals_to_99pct"].idxmin()
    winner_stab = agg["cv_auc_std"].idxmin()
    imp = res["test_auc"].mean() - base["test_auc"].mean()

    L = ["# Kết quả thực nghiệm HPO cho Random Forest\n",
         f"Ngân sách: {a.budget} cấu hình / phương pháp / seed; {a.seeds} seed; 5-fold CV; tập test tách riêng.\n",
         "## 1. So sánh ba phương pháp\n", agg.round(4).to_markdown(), "",
         f"- AUC CV trung bình cao nhất: **{winner_auc}**",
         f"- Đạt 99% AUC tốt nhất nhanh nhất (ít lần đánh giá nhất): **{winner_speed}**",
         f"- Ổn định nhất (độ lệch chuẩn AUC CV nhỏ nhất): **{winner_stab}**"]
    if pval is not None:
        L.append(f"- Kiểm định Friedman trên AUC CV giữa 3 phương pháp: p = {pval:.3f} "
                 f"({'có' if pval < .05 else 'chưa có'} khác biệt có ý nghĩa ở mức 5%, n = {len(piv)} seed)")
    L += ["", "## 2. So với cấu hình mặc định (RQ4)\n",
          f"- Mặc định: AUC CV {base.cv_auc.mean():.4f}, AUC test {base.test_auc.mean():.4f}",
          f"- Sau tối ưu (trung bình 3 phương pháp): AUC test {res.test_auc.mean():.4f} "
          f"(chênh {imp:+.4f})", "",
          "## 3. Cấu hình tốt nhất tìm được\n",
          f"- {best_row['method']} (seed {int(best_row['seed'])}): AUC CV {best_row['best_cv_auc']:.4f}, "
          f"AUC test {best_row['test_auc']:.4f}",
          f"- n_estimators={int(best_row['best_n'])}, max_depth={int(best_row['best_d'])}, "
          f"min_samples_split={int(best_row['best_ms'])}, min_samples_leaf={int(best_row['best_ml'])}, "
          f"max_features={best_row['best_mf']}", "",
          "## 4. Độ nhạy siêu tham số\n", sens.round(3).to_markdown(), "",
          "AUC theo max_features:\n", mf_tab.round(4).to_markdown(), "",
          "## 5. Đánh đổi Accuracy - Latency\n",
          f"- Không ràng buộc: AUC CV {best_u.cv_auc:.4f}, độ trễ {best_u.latency:.0f} ms/1000 mẫu "
          f"(n={int(best_u.n)}, d={int(best_u.d)}, mf={best_u.mf})"]
    if best_c is not None:
        L.append(f"- Với ràng buộc độ trễ ≤ {limit:.0f} ms/1000 mẫu: AUC CV {best_c.cv_auc:.4f}, "
                 f"độ trễ {best_c.latency:.0f} ms "
                 f"(n={int(best_c.n)}, d={int(best_c.d)}, ms={int(best_c.ms)}, ml={int(best_c.ml)}, mf={best_c.mf})")
    L += ["", "## 6. Failure cases (5 cấu hình tệ nhất)\n", worst.round(4).to_markdown(index=False), "",
          "Biểu đồ: convergence.png, boxplots.png, sensitivity.png, pareto_latency.png"]
    open(f"{out}/report.md", "w", encoding="utf8").write("\n".join(L))
    print("\n" + "\n".join(L))


if __name__ == "__main__":
    main()
