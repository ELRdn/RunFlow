import importlib.util
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('measurements',Path(__file__).resolve().parents[1]/'scripts/analyze_measurements.py')
measurements=importlib.util.module_from_spec(spec)
spec.loader.exec_module(measurements)


def test_contact_proxy_requires_flight_and_ignores_small_recrossing():
    times=[i*.05 for i in range(13)]
    heights=[.2,.2,.2,.1,.02,-.02,.005,-.01,.2,.2,.2,.02,-.02]
    events=measurements.approaches(times,heights,0,min_airborne_s=.09)
    assert len(events)==2
    assert events[0]['time_s']==pytest.approx(.225)
    assert events[1]['time_s']==pytest.approx(.575)


def test_static_lowest_point_is_not_contact():
    assert measurements.approaches([0,.1,.2,.3],[0,0,0,0],0)==[]


@pytest.mark.parametrize('times,heights',[([0,0],[.2,.1]),([0,.1],[.2,float('nan')])])
def test_invalid_measurements_fail(times,heights):
    with pytest.raises(ValueError):
        measurements.approaches(times,heights,0)
