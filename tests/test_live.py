"""Tests which run against actual SpiNNaker hardware.

These tests partly act as integration tests but also serve as tests of the
SpiNNaker application itself.
"""

import pytest

import numpy as np

from network_tester.experiment import Experiment

from network_tester.errors import NetworkTesterError


@pytest.fixture
def experiment(spinnaker_ip):
    return Experiment(spinnaker_ip)


def test_router_recording(experiment):
    """In this experiment, no traffic nodes are present but all router counters
    are recorded."""

    experiment.timestep = 1e-5  # 10us
    experiment.record_interval = 1e-3  # 1000us
    experiment.duration = 0.1  # 100,000us

    experiment.record_local_multicast = True
    experiment.record_external_multicast = True
    experiment.record_local_p2p = True
    experiment.record_external_p2p = True
    experiment.record_local_nearest_neighbour = True
    experiment.record_external_nearest_neighbour = True
    experiment.record_local_fixed_route = True
    experiment.record_external_fixed_route = True
    experiment.record_dropped_multicast = True
    experiment.record_dropped_p2p = True
    experiment.record_dropped_nearest_neighbour = True
    experiment.record_dropped_fixed_route = True
    experiment.record_counter12 = True
    experiment.record_counter13 = True
    experiment.record_counter14 = True
    experiment.record_counter15 = True

    experiment.new_group()

    results = experiment.run()

    router_counters = results.router_counters()

    # There should be more than one chip worth of counters
    chip_coordinates = set()
    for result in router_counters:
        chip_coordinates.add((result["x"], result["y"]))
    assert len(chip_coordinates) > 1
    assert len(router_counters) == len(chip_coordinates) * 100

    assert np.sum(router_counters["local_multicast"]) == 0
    assert np.sum(router_counters["external_multicast"]) == 0
    assert np.sum(router_counters["local_p2p"]) == 0
    assert np.sum(router_counters["external_p2p"]) == 0
    assert np.sum(router_counters["local_fixed_route"]) == 0
    assert np.sum(router_counters["external_fixed_route"]) == 0
    assert np.sum(router_counters["dropped_multicast"]) == 0
    assert np.sum(router_counters["dropped_p2p"]) == 0
    assert np.sum(router_counters["dropped_fixed_route"]) == 0


def test_transmission(experiment):
    """In this experiment we check that the traffic generators all run at the
    rate expected."""

    experiment.timestep = 1e-4  # 100us
    experiment.record_interval = 1e-3  # 1000us
    experiment.duration = 1e-2  # 10000us

    experiment.record_sent = True

    experiment.probability = 1.0

    # No bursting for this pair
    c0 = experiment.new_core()
    c1 = experiment.new_core()
    f0 = experiment.new_flow(c0, [c0, c1])

    # Bursting 40% of the time, twice during the run
    c2 = experiment.new_core()
    c3 = experiment.new_core()
    f1 = experiment.new_flow(c2, [c2, c3])
    f1.burst_period = 5e-3  # 5000us
    f1.burst_duty = 0.4
    f1.burst_phase = 0.0

    # As above but phase-offset by 40%
    c4 = experiment.new_core()
    c5 = experiment.new_core()
    f2 = experiment.new_flow(c4, [c4, c5])
    f2.burst_period = 5e-3  # 5000us
    f2.burst_duty = 0.4
    f2.burst_phase = 0.4

    # 0% probability
    c6 = experiment.new_core()
    c7 = experiment.new_core()
    f3 = experiment.new_flow(c6, [c6, c7])
    f3.probability = 0.0

    # 50% probability
    c8 = experiment.new_core()
    c9 = experiment.new_core()
    f4 = experiment.new_flow(c8, [c8, c9])
    f4.probability = 0.5

    experiment.new_group()
    results = experiment.run()

    flow_totals = results.flow_totals()

    # Packets should be sent every cycle
    assert (flow_totals[flow_totals["flow"] == f0]["sent"] ==
            [10, 10, 10, 10, 10, 10, 10, 10, 10, 10]).all()

    # Check duty-cycle is correct
    n1_sent = flow_totals[flow_totals["flow"] == f1]["sent"]
    counts, bins = np.histogram(n1_sent, [0, 5, 11])
    assert (counts == [6, 4]).all()

    n2_sent = flow_totals[flow_totals["flow"] == f2]["sent"]

    # Check the phase is adjusted
    assert (n2_sent == np.roll(n1_sent, -2)).all()

    # No packets should be sent
    assert (flow_totals[flow_totals["flow"] == f3]["sent"] ==
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]).all()

    # Approximately 50% of packets should be sent
    assert 20 < np.sum(flow_totals[flow_totals["flow"] == f4]["sent"]) < 80


def test_recipt(experiment):
    """In this experiment we simply check that multiple arriving streams can be
    differentiated."""

    experiment.timestep = 1e-4  # 100us
    experiment.record_interval = 0
    experiment.duration = 1e-2  # 10000us

    experiment.record_received = True

    target = experiment.new_core()
    source0 = experiment.new_core()
    source1 = experiment.new_core()

    flow0 = experiment.new_flow(source0, target)
    flow1 = experiment.new_flow(source1, target)

    flow0.probability = 0.25
    flow1.probability = 0.75

    experiment.new_group()
    results = experiment.run()

    flow_totals = results.flow_totals()

    # Approximately the right number of packets should arrive for each counter
    assert (10 <
            np.sum(flow_totals[flow_totals["flow"] == flow0]["received"]) <
            40)
    assert (60 <
            np.sum(flow_totals[flow_totals["flow"] == flow1]["received"]) <
            90)


def test_consume(experiment):
    """In this experiment we check that toggling packet consumption causes
    packets to be dropped."""

    experiment.timestep = 1e-5  # 10us
    experiment.record_interval = 0
    experiment.duration = 1e-3  # 1000us

    experiment.record_received = True
    experiment.record_dropped_multicast = True

    target = experiment.new_core()
    source = experiment.new_core()
    flow = experiment.new_flow(source, target)
    flow.probability = 1.0

    # The first group doesn't accept packets
    with experiment.new_group() as group_noconsume:
        experiment.consume_packets = False

    # The second group does (thus making sure the network gets flushed)
    with experiment.new_group() as group_consume:
        experiment.consume_packets = True

    results = experiment.run()

    totals = results.totals()
    totals_noconsume = totals[totals["group"] == group_noconsume]
    totals_consume = totals[totals["group"] == group_consume]

    # During the non-consuming phase, some packets must be dropped
    assert totals_noconsume["dropped_multicast"] > 0
    assert totals_noconsume["received"] == 0

    # During the consuming phase (almost) all packets should get through
    assert totals_consume["dropped_multicast"] == 0
    assert totals_consume["received"] >= 95


def test_impossible_deadline(experiment):
    """In this experiment we give a timestep less than a clock-cycle and make
    sure we get a deadline missed notification. We should, however, still have
    the right number of timesteps executed."""

    experiment.timestep = 1e-9  # 1ns
    experiment.warmup = 0
    experiment.duration = 1e-8  # 10ns
    experiment.cooldown = 0

    experiment.record_sent = True

    target = experiment.new_core()
    source = experiment.new_core()
    flow = experiment.new_flow(source, target)
    flow.probability = 1.0

    experiment.new_group()

    # Should suffer from deadline issues.
    with pytest.raises(NetworkTesterError) as exc_info:
        experiment.run()
    assert "deadline" in str(exc_info.value).lower()

    totals = exc_info.value.results.totals()

    # All packets should still have been sent
    assert totals["sent"] == 10

    # But deadline misses should have been counted
    assert totals["deadlines_missed"] > 0
