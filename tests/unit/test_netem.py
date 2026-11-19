import statistics
import threading
import time

import pytest

from airq.devices.netem import DelayedRunner, NetEm, NetParams


def test_loss_rate_is_within_two_percent_of_the_configured_rate():
    for rate in (0.05, 0.10, 0.20):
        em = NetEm(NetParams(loss_rate=rate), seed=1)
        n = 20000
        dropped = sum(em.plan("A") is None for _ in range(n))
        assert abs(dropped / n - rate) <= 0.02  # spec test 10: netem loss within +-2%


def test_no_emulation_means_no_loss_and_no_delay():
    em = NetEm(seed=2)
    assert all(em.plan("A") == 0.0 for _ in range(1000))


def test_delay_and_jitter_follow_the_parameters_and_never_go_negative():
    em = NetEm(NetParams(delay_ms=200, jitter_ms=50), seed=3)
    d = [em.plan("A") for _ in range(5000)]
    assert abs(statistics.mean(d) - 0.2) < 0.01
    assert 0.03 < statistics.pstdev(d) < 0.07 and min(d) >= 0.0
    fixed = NetEm(NetParams(delay_ms=300), seed=3)
    assert {fixed.plan("A") for _ in range(100)} == {0.3}


def test_reorder_adds_extra_delay_to_the_configured_share_of_messages():
    em = NetEm(NetParams(delay_ms=100, reorder_rate=0.25), seed=4)
    d = [em.plan("A") for _ in range(8000)]
    late = sum(x > 0.1 + 1e-9 for x in d) / len(d)
    assert abs(late - 0.25) < 0.03 and max(d) == pytest.approx(0.3)  # 100 + max(200, 100)


def test_per_station_override_reset_and_validation():
    em = NetEm(seed=5)
    em.set(NetParams(loss_rate=1.0), station="Dongsi")
    assert em.plan("Dongsi") is None and em.plan("Huairou") == 0.0
    em.set(NetParams(delay_ms=50))
    assert em.plan("Huairou") == 0.05 and em.plan("Dongsi") is None  # override still wins
    em.reset()
    assert em.plan("Dongsi") == 0.0
    with pytest.raises(ValueError):
        em.set(NetParams(loss_rate=1.5))
    with pytest.raises(ValueError):
        NetParams(delay_ms=-1).validate()


def test_same_seed_gives_the_same_decisions():
    a = NetEm(NetParams(loss_rate=0.3, delay_ms=10, jitter_ms=5), seed=9)
    b = NetEm(NetParams(loss_rate=0.3, delay_ms=10, jitter_ms=5), seed=9)
    assert [a.plan("A") for _ in range(200)] == [b.plan("A") for _ in range(200)]


def test_parse_accepts_any_subset_and_rejects_unknown_keys():
    p = NetParams.parse("loss=0.1, delay=200")
    assert (p.loss_rate, p.delay_ms, p.jitter_ms) == (0.1, 200.0, 0.0)
    assert NetParams.parse("") == NetParams()
    with pytest.raises(ValueError):
        NetParams.parse("speed=3")


def test_delayed_runner_runs_calls_in_due_order_and_drains():
    runner = DelayedRunner()
    out, lock = [], threading.Lock()

    def add(x):
        with lock:
            out.append(x)

    t0 = time.monotonic()
    runner.call_later(0.12, lambda: add("c"))
    runner.call_later(0.02, lambda: add("a"))
    runner.call_later(0.06, lambda: add("b"))
    assert runner.drain(5.0)
    runner.stop()
    assert out == ["a", "b", "c"] and time.monotonic() - t0 >= 0.1
