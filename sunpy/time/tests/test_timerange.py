# -*- coding: utf-8 -*-

from __future__ import absolute_import

import datetime

import pytest

import sunpy.time

start = datetime.datetime(year=2012, month=1, day=1)
end = datetime.datetime(year=2012, month=1, day=2)
delta = end - start

@pytest.mark.parametrize("inputs", [
    ('2012/1/1','2012/1/2'),
    ('2012/1/1',24*60*60),
    ('2012/1/1',datetime.timedelta(days=1))
])
def test_timerange_inputs(inputs):
    timerange = sunpy.time.TimeRange(*inputs)
    assert isinstance(timerange, sunpy.time.TimeRange)
    assert timerange.t1 == start
    assert timerange.t2 == end
    assert timerange.dt == delta

@pytest.mark.parametrize("ainput", [
    ('2012/1/1','2012/1/2'),
    ('2012/1/1',24*60*60),
    ('2012/1/1',datetime.timedelta(days=1)),
    (sunpy.time.TimeRange('2012/1/1','2012/1/2'))
])
def test_timerange_input(ainput):
    timerange = sunpy.time.TimeRange(ainput)
    assert isinstance(timerange, sunpy.time.TimeRange)
    assert timerange.t1 == start
    assert timerange.t2 == end
    assert timerange.dt == delta

def test_center():
    timerange = sunpy.time.TimeRange('2012/1/1','2012/1/2')
    assert timerange.center() == datetime.datetime(year=2012,day=1,month=1,hour=12)

def test_split():
    timerange = sunpy.time.TimeRange('2012/1/1','2012/1/2')
    expect = [sunpy.time.TimeRange('2012/1/1T00:00:00','2012/1/1T12:00:00'),
              sunpy.time.TimeRange('2012/1/1T12:00:00','2012/1/2T00:00:00')]
    split = timerange.split(n=2)
    #Doing direct comparisons seem to not work
    assert all([wi.t1 == ex.t1 and wi.t2 == ex.t2 for wi, ex in zip(split, expect)])

def test_split_n_0():
    timerange = sunpy.time.TimeRange('2012/1/1','2012/1/2')
    with pytest.raises(ValueError):
        timerange.split(n=0)

def test_window():
    timerange = sunpy.time.TimeRange('2012/1/1','2012/1/2')
    window = timerange.window(12*60*60, 10)
    expect = [sunpy.time.TimeRange('2012/1/1T00:00:00','2012/1/1T00:00:10'),
              sunpy.time.TimeRange('2012/1/1T12:00:00','2012/1/1T12:00:10'),
              sunpy.time.TimeRange('2012/1/2T00:00:00','2012/1/2T00:00:10')]
    assert isinstance(window, list)
    #Doing direct comparisons seem to not work
    assert all([wi.t1 == ex.t1 and wi.t2 == ex.t2 for wi, ex in zip(window, expect)])

def test_window_timedelta():
    timerange = sunpy.time.TimeRange('2012/1/1','2012/1/2')
    window = timerange.window(datetime.timedelta(hours=12), datetime.timedelta(seconds=10))
    expect = [sunpy.time.TimeRange('2012/1/1T00:00:00','2012/1/1T00:00:10'),
              sunpy.time.TimeRange('2012/1/1T12:00:00','2012/1/1T12:00:10'),
              sunpy.time.TimeRange('2012/1/2T00:00:00','2012/1/2T00:00:10')]
    assert isinstance(window, list)
    #Doing direct comparisons seem to not work
    assert all([wi.t1 == ex.t1 and wi.t2 == ex.t2 for wi, ex in zip(window, expect)])

def test_days():
    timerange = sunpy.time.TimeRange('2012/1/1','2012/1/2')
    assert timerange.days() == 1

def test_start():
    timerange = sunpy.time.TimeRange('2012/1/1','2012/1/2')
    assert timerange.start() == start

def test_end():
    timerange = sunpy.time.TimeRange('2012/1/1','2012/1/2')
    assert timerange.end() == end

def test_seconds():
    timerange = sunpy.time.TimeRange('2012/1/1','2012/1/2')
    assert timerange.seconds() == 24*60*60

def test_minutes():
    timerange = sunpy.time.TimeRange('2012/1/1','2012/1/2')
    assert timerange.minutes() == 24*60

def test_next():
    timerange = sunpy.time.TimeRange('2012/1/1','2012/1/2')
    timerange.next()
    assert isinstance(timerange, sunpy.time.TimeRange)
    assert timerange.t1 == start + delta
    assert timerange.t2 == end + delta
    assert timerange.dt == delta

def test_previous():
    timerange = sunpy.time.TimeRange('2012/1/1','2012/1/2')
    timerange.previous()
    assert isinstance(timerange, sunpy.time.TimeRange)
    assert timerange.t1 == start - delta
    assert timerange.t2 == end - delta
    assert timerange.dt == delta

def test_extend():
    timerange = sunpy.time.TimeRange('2012/1/1','2012/1/2')
    timerange.extend(delta, delta)
    assert isinstance(timerange, sunpy.time.TimeRange)
    assert timerange.t1 == start + delta
    assert timerange.t2 == end + delta
    assert timerange.dt == delta

def test_contains():
    before = datetime.datetime(year=1990, month=1, day=1)
    after = datetime.datetime(year=2022, month=1, day=1)
    between = datetime.datetime(year=2014, month=5, day=4)
    timerange = sunpy.time.TimeRange('2014/05/03 12:00', '2014/05/05 21:00')
    assert between in timerange
    assert before not in timerange
    assert after not in timerange
    assert timerange.t1 in timerange
    assert timerange.t2 in timerange
    assert '2014/05/04 15:21' in timerange
    assert '1975/4/13' not in timerange
    assert '2100/1/1'not in timerange
    assert '2014/05/03 12:00' in timerange
    assert '2014/05/05 21:00' in timerange
