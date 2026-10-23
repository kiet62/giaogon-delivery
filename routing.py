"""Routing calculations shared by the SQL Server delivery portal."""
import json
import math
import urllib.request
import numpy as np
from algorithms import distances, solve, validate_matrix

OSRM = 'https://router.project-osrm.org'
DEFAULT_DEPOT = dict(name='Kho trung tâm', address='Quận 1, TP.HCM', lat=10.7769, lon=106.7009)


def location(data):
    p = dict(name=str(data.get('name', '')).strip()[:150], address=str(data.get('address', '')).strip()[:300])
    if not p['name']:
        raise ValueError('Vui lòng nhập tên điểm lấy hàng hoặc người nhận.')
    for field, bound in [('lat', 90), ('lon', 180)]:
        if data.get(field) in (None, ''):
            raise ValueError('Chọn vị trí trên bản đồ hoặc nhập đủ vĩ độ và kinh độ.')
        p[field] = float(data[field])
        if not math.isfinite(p[field]) or not -bound <= p[field] <= bound:
            raise ValueError('Tọa độ không hợp lệ.')
    return p


def order_data(data):
    p = location(data)
    p['note'] = str(data.get('note', '')).strip()[:500]
    minutes = float(data.get('service_minutes', 3))
    if not math.isfinite(minutes) or not 0 <= minutes <= 60:
        raise ValueError('Thời gian giao tại mỗi điểm phải từ 0 đến 60 phút.')
    p['service_minutes'] = minutes
    return p


def road_request(path):
    try:
        req = urllib.request.Request(OSRM + path, headers={'User-Agent': 'ShipperRoute-StudentProject/1.0'})
        with urllib.request.urlopen(req, timeout=18) as response:
            data = json.load(response)
    except Exception as exc:
        raise ValueError('Chưa lấy được dữ liệu đường bộ. Kiểm tra Internet hoặc chọn chế độ ước tính đường thẳng.') from exc
    if data.get('code') != 'Ok':
        raise ValueError('Không tìm được tuyến đường bộ cho các vị trí đã chọn.')
    return data


def coordinates(ps):
    return ';'.join(f"{p['lon']:.7f},{p['lat']:.7f}" for p in ps)


def matrices(ps, source, speed):
    if source == 'road':
        data = road_request('/table/v1/driving/' + coordinates(ps) + '?annotations=distance,duration')
        if any(v is None for row in data['distances'] for v in row) or any(v is None for row in data['durations'] for v in row):
            raise ValueError('Có điểm không thể nối bằng đường bộ. Hãy điều chỉnh vị trí trên bản đồ.')
        return validate_matrix(np.array(data['distances']) / 1000, len(ps)), validate_matrix(np.array(data['durations']) / 60, len(ps))
    if source != 'estimate':
        raise ValueError('Nguồn khoảng cách không hợp lệ.')
    d = validate_matrix(distances(ps, 'haversine'), len(ps))
    return d, d / speed * 60


def plan(ps, cfg):
    source = cfg.get('source', 'estimate')
    objective = cfg.get('objective', 'distance')
    if objective not in ['distance', 'time']:
        raise ValueError('Mục tiêu tối ưu không hợp lệ.')
    speed = float(cfg.get('speed', 25))
    if not math.isfinite(speed) or not 5 <= speed <= 80:
        raise ValueError('Tốc độ ước tính phải từ 5 đến 80 km/h.')
    population_raw, iterations_raw = float(cfg.get('population', 60)), float(cfg.get('iterations', 150))
    if not all(math.isfinite(x) and x.is_integer() for x in [population_raw, iterations_raw]):
        raise ValueError('Số cá thể và số vòng lặp phải là số nguyên.')
    population, iterations = int(population_raw), int(iterations_raw)
    if not 4 <= population <= 100 or not 1 <= iterations <= 300:
        raise ValueError('Cá thể/hạt: 4–100; vòng lặp: 1–300.')
    seeds = cfg.get('seeds', [42, 123, 2026])
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 5 or any(type(x) is not int or not 0 <= x <= 4294967295 for x in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError('Nhập 1–5 seed nguyên không âm, không trùng nhau.')
    if type(cfg.get('return_to_depot', False)) is not bool:
        raise ValueError('Lựa chọn quay về kho không hợp lệ.')
    roundtrip = cfg.get('return_to_depot', False)
    dm, tm = matrices(ps, source, speed)
    cost_matrix = (dm if objective == 'distance' else tm).copy()
    if not roundtrip:
        # Reuse closed-tour solver: make the last-to-depot edge free, then omit it.
        cost_matrix[:, 0] = 0
    params = dict(population=population, iterations=iterations, crossover=.9, mutation=.15, inertia=.7, c1=1.5, c2=1.5)
    results = []
    service = sum(p.get('service_minutes', 0) for p in ps[1:])
    for alg in ['NN', 'GA', 'PSO']:
        alg_runs = []
        for seed in (seeds if alg != 'NN' else seeds[:1]):
            r = solve(cost_matrix, 0, alg, params, seed)
            if not roundtrip:
                r['route'] = r['route'][:-1]
            r['objective_cost'] = r.pop('distance')
            r['distance_km'] = float(sum(dm[a, b] for a, b in zip(r['route'], r['route'][1:])))
            r['travel_minutes'] = float(sum(tm[a, b] for a, b in zip(r['route'], r['route'][1:])))
            r['total_minutes'] = r['travel_minutes'] + service
            alg_runs.append(r)
        best = min(alg_runs, key=lambda r: r['objective_cost']).copy()
        best['runs'] = alg_runs
        results.append(best)
    winner = min(results, key=lambda r: r['objective_cost'])
    baseline = results[0]['objective_cost']
    legs, elapsed = [], 0
    for a, b in zip(winner['route'], winner['route'][1:]):
        elapsed += float(tm[a, b])
        arrival = elapsed
        service_at_stop = ps[b].get('service_minutes', 0) if b else 0
        elapsed += service_at_stop
        legs.append(dict(from_index=a, to_index=b, distance_km=float(dm[a, b]), travel_minutes=float(tm[a, b]), arrival_minutes=arrival, departure_minutes=elapsed, service_minutes=service_at_stop))
    geometry = None
    if source == 'road':
        road = road_request('/route/v1/driving/' + coordinates([ps[i] for i in winner['route']]) + '?overview=full&geometries=geojson&steps=false')
        geometry = road['routes'][0]['geometry']
    return dict(points=ps, config=dict(source=source, objective=objective, speed=speed, return_to_depot=roundtrip, population=population, iterations=iterations, seeds=seeds), results=results, winner=winner['algorithm'], selected_seed=winner['seed'], route=winner['route'], distance_km=winner['distance_km'], travel_minutes=winner['travel_minutes'], total_minutes=winner['total_minutes'], service_minutes=service, legs=legs, geometry=geometry, improvement=100*(baseline-winner['objective_cost'])/baseline if baseline else 0,
                source_label='OSRM · đường bộ · hồ sơ ô tô' if source == 'road' else 'Haversine · đường thẳng · thời gian theo tốc độ giả định')

