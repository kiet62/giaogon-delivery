"""Run a reproducible 200-seed comparison of NN, GA, and PSO on one route.

Input CSV needs columns: name,lat,lon. The depot is supplied by CLI options.
Distances use Haversine straight-line estimates, matching the app's estimate mode.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from algorithms import distances, length, solve, validate_matrix  # noqa: E402


def load_points(path: Path, depot_name: str, depot_lat: float, depot_lon: float):
    points = [{"name": depot_name, "lat": depot_lat, "lon": depot_lon}]
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required = {"name", "lat", "lon"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("CSV cần có các cột: name,lat,lon")
        for row_number, row in enumerate(reader, start=2):
            try:
                name = (row.get("name") or "").strip() or f"Điểm {row_number - 1}"
                lat, lon = float(row["lat"]), float(row["lon"])
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(f"Dòng {row_number} có tọa độ không hợp lệ.") from exc
            if not np.isfinite([lat, lon]).all() or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError(f"Dòng {row_number} có lat/lon ngoài giới hạn.")
            points.append({"name": name, "lat": lat, "lon": lon})
    if len(points) < 3:
        raise ValueError("Cần ít nhất 2 điểm giao hàng và 1 kho trong bộ dữ liệu.")
    return points


def write_csv(path: Path, fieldnames, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="So sánh 200 seed NN / GA / PSO trên cùng bộ điểm giao.")
    parser.add_argument("--input", type=Path, default=ROOT / "samples" / "benchmark_points.csv",
                        help="CSV có các cột name,lat,lon (mặc định: bộ benchmark 16 điểm mẫu)")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmark-results")
    parser.add_argument("--runs", type=int, default=200, help="Số seed chạy cho mỗi thuật toán")
    parser.add_argument("--population", type=int, default=60)
    parser.add_argument("--iterations", type=int, default=150)
    parser.add_argument("--objective", choices=("distance", "time"), default="distance")
    parser.add_argument("--speed", type=float, default=25, help="Tốc độ ước tính km/h")
    parser.add_argument("--open-route", action="store_true", help="Không tính chặng quay về kho")
    parser.add_argument("--depot-name", default="Kho trung tâm")
    parser.add_argument("--depot-lat", type=float, default=10.7769)
    parser.add_argument("--depot-lon", type=float, default=106.7009)
    args = parser.parse_args()

    if args.runs < 1 or args.population < 4 or args.iterations < 1 or args.speed <= 0:
        parser.error("runs, iterations, speed phải dương; population tối thiểu là 4.")
    points = load_points(args.input, args.depot_name, args.depot_lat, args.depot_lon)
    distance_matrix = validate_matrix(distances(points, "haversine"), len(points))
    objective_matrix = distance_matrix.copy()
    if args.objective == "time":
        objective_matrix /= args.speed
        objective_matrix *= 60
    if args.open_route:
        objective_matrix[:, 0] = 0

    cfg = {"population": args.population, "iterations": args.iterations,
           "crossover": 0.9, "mutation": 0.15, "inertia": 0.7, "c1": 1.5, "c2": 1.5}
    # Same deterministic NN baseline is recorded alongside every stochastic trial.
    baseline = solve(objective_matrix, 0, "NN", cfg, seed=0)
    algorithms = ("NN", "GA", "PSO")
    raw_rows = []
    convergence = []
    score_values = {name: [] for name in algorithms}
    runtime_values = {name: [] for name in algorithms}
    best_routes = {}

    for algorithm in algorithms:
        trial_count = 1 if algorithm == "NN" else args.runs
        for trial in range(trial_count):
            seed = 0 if algorithm == "NN" else 20261023 + trial
            result = baseline if algorithm == "NN" else solve(objective_matrix, 0, algorithm, cfg, seed)
            route = result["route"]
            distance_km = length(route, distance_matrix)
            travel_minutes = distance_km / args.speed * 60
            score = result["distance"]
            score_values[algorithm].append(score)
            runtime_values[algorithm].append(result["time_ms"])
            if algorithm not in best_routes or score < best_routes[algorithm][0]:
                best_routes[algorithm] = (score, route)
            raw_rows.append({
                "algorithm": algorithm,
                "trial": trial + 1,
                "seed": seed,
                "objective": args.objective,
                "objective_value": round(score, 8),
                "distance_km_estimated": round(distance_km, 8),
                "travel_minutes_estimated": round(travel_minutes, 8),
                "compute_time_ms": round(result["time_ms"], 5),
                "iterations": result["iterations"],
                "route": " -> ".join(points[index]["name"] for index in route),
                "convergence": json.dumps([round(float(value), 8) for value in result["history"]], ensure_ascii=False),
            })
            history = result["history"]
            for step, value in enumerate(history):
                convergence.append({"algorithm": algorithm, "trial": trial + 1, "seed": seed,
                                    "iteration": step, "best_objective_so_far": round(float(value), 8)})

    baseline_score = baseline["distance"]
    summary = []
    for algorithm in algorithms:
        scores = score_values[algorithm]
        runtimes = runtime_values[algorithm]
        best_index = int(np.argmin(scores))
        mean_score = statistics.fmean(scores)
        summary.append({
            "algorithm": algorithm,
            "runs": len(scores),
            "best_objective": round(min(scores), 8),
            "mean_objective": round(mean_score, 8),
            "median_objective": round(statistics.median(scores), 8),
            "std_objective": round(statistics.pstdev(scores), 8),
            "worst_objective": round(max(scores), 8),
            "best_distance_km_estimated": round(length(best_routes[algorithm][1], distance_matrix), 8),
            "mean_compute_time_ms": round(statistics.fmean(runtimes), 5),
            "improvement_vs_NN_best_percent": round((baseline_score - min(scores)) / baseline_score * 100, 6) if baseline_score else 0,
            "improvement_vs_NN_mean_percent": round((baseline_score - mean_score) / baseline_score * 100, 6) if baseline_score else 0,
            "best_seed": 0 if algorithm == "NN" else 20261023 + best_index,
        })

    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output / "benchmark_200_runs.csv", list(raw_rows[0]), raw_rows)
    write_csv(args.output / "benchmark_200_summary.csv", list(summary[0]), summary)
    write_csv(args.output / "benchmark_200_convergence.csv", list(convergence[0]), convergence)
    print(f"Điểm gồm kho và điểm giao: {len(points)}")
    print(f"Baseline NN: {length(baseline['route'], distance_matrix):.3f} km ước tính")
    print(f"Đã lưu {len(raw_rows)} dòng kết quả và {len(convergence)} điểm hội tụ tại: {args.output.resolve()}")
    print("Kết quả tốt nhất tìm được theo objective (không phải bảo đảm tối ưu toàn cục):")
    for row in summary:
        print(f"{row['algorithm']}: tốt nhất={row['best_objective']}, trung bình={row['mean_objective']}, "
              f"độ lệch chuẩn={row['std_objective']}, thời gian TB={row['mean_compute_time_ms']} ms, "
              f"cải thiện TB so với NN={row['improvement_vs_NN_mean_percent']}%")


if __name__ == "__main__":
    main()
