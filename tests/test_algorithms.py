"""Independent route/cost checks, tiny exact oracles, and offline road-service cases."""
import itertools
import numpy as np
import pytest
from algorithms import solve,length,validate_matrix,distances
from routing import plan,DEFAULT_DEPOT

CFG=dict(population=12,iterations=15,crossover=.9,mutation=.15,inertia=.7,c1=1.5,c2=1.5)

@pytest.mark.parametrize('algorithm',['NN','GA','PSO'])
@pytest.mark.parametrize('n',[1,2,6])
def test_permutations_cost_seed_and_convergence(algorithm,n):
    rng=np.random.default_rng(901);matrix=rng.uniform(1,40,(n,n));np.fill_diagonal(matrix,0)
    depot=n-1
    r=solve(matrix,depot,algorithm,CFG,42);again=solve(matrix,depot,algorithm,CFG,42)
    assert r['route'][0]==r['route'][-1]==depot
    assert sorted(r['route'][1:-1])==[i for i in range(n) if i!=depot]
    independent=sum(matrix[r['route'][i],r['route'][i+1]] for i in range(len(r['route'])-1))
    assert r['distance']==pytest.approx(independent)
    exact=min(sum(matrix[a,b] for a,b in zip([depot,*p,depot],[*p,depot])) for p in itertools.permutations(i for i in range(n) if i!=depot))
    assert r['distance']>=exact-1e-8
    assert r['route']==again['route'] and r['history']==again['history']
    assert all(a>=b for a,b in zip(r['history'],r['history'][1:]))
    assert r['history'][-1]==pytest.approx(r['distance'])
    assert r['time_ms']>=0

@pytest.mark.parametrize('bad',[[[0,1]],[[0,-1],[1,0]],[[1,1],[1,0]],[[0,float('nan')],[1,0]],[[0,float('inf')],[1,0]]])
def test_invalid_distance_matrices(bad):
    with pytest.raises(ValueError):validate_matrix(bad)

def test_known_distances_and_duplicate_points():
    m=distances([dict(x=0,y=0),dict(x=3,y=4)],'euclidean');assert m[0,1]==5
    h=distances([dict(lat=0,lon=0),dict(lat=0,lon=1),dict(lat=0,lon=0)],'haversine')
    assert h[0,1]==pytest.approx(111.195,abs=.01)
    assert h[0,2]==0 and np.allclose(h,h.T)

@pytest.mark.parametrize('roundtrip',[False,True])
@pytest.mark.parametrize('objective',['distance','time'])
def test_open_closed_plan_costs_and_nearest_baseline(roundtrip,objective):
    points=[DEFAULT_DEPOT,dict(name='A',lat=10.78,lon=106.72,service_minutes=4),dict(name='B',lat=10.8,lon=106.69,service_minutes=6)]
    r=plan(points,dict(return_to_depot=roundtrip,objective=objective,population=8,iterations=10,seeds=[42,123]))
    dm=distances(points,'haversine')
    assert r['route'][0]==0 and sorted(r['route'][1:-1] if roundtrip else r['route'][1:])==[1,2]
    expected=length(r['route'],dm)
    assert r['distance_km']==pytest.approx(expected)
    assert r['travel_minutes']==pytest.approx(expected/25*60)
    assert r['total_minutes']==pytest.approx(r['travel_minutes']+10)
    assert sum(l['distance_km'] for l in r['legs'])==pytest.approx(expected)
    assert r['distance_km']<=r['results'][0]['distance_km']+1e-8
    assert len(r['results'][1]['runs'])==len(r['results'][2]['runs'])==2
    assert 0<=r['improvement']<=100

def test_road_unit_conversion_and_geometry(monkeypatch):
    def road(path):
        if path.startswith('/table/'):
            return dict(distances=[[0,1000],[1200,0]],durations=[[0,120],[180,0]])
        return dict(routes=[dict(geometry=dict(type='LineString',coordinates=[[106.7,10.77],[106.71,10.78]]))])
    monkeypatch.setattr('routing.road_request',road)
    r=plan([DEFAULT_DEPOT,dict(name='A',lat=10.78,lon=106.71)],dict(source='road',return_to_depot=True,population=4,iterations=1,seeds=[42]))
    assert r['distance_km']==pytest.approx(2.2) and r['travel_minutes']==5
    assert r['geometry']['type']=='LineString'

def test_unreachable_road_rejected(monkeypatch):
    monkeypatch.setattr('routing.road_request',lambda path:dict(distances=[[0,None],[None,0]],durations=[[0,None],[None,0]]))
    with pytest.raises(ValueError,match='đường bộ'):
        plan([DEFAULT_DEPOT,dict(name='A',lat=10.78,lon=106.71)],dict(source='road'))
