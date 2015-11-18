import pytest

from mock import Mock

import struct

import numpy as np

from network_tester.results import Results, to_csv

from network_tester.experiment import Experiment

from network_tester.errors import NT_ERR

from network_tester.counters import Counters

from rig.place_and_route.routing_tree import RoutingTree
from rig.routing_table import Routes


@pytest.fixture
def example_experiment():
    """The experiment used in example_results."""
    return Experiment(Mock())


@pytest.fixture
def example_cores(example_experiment):
    """The set of cores used in example_results."""
    c0 = example_experiment.new_core(name="c0")
    c1 = example_experiment.new_core(name=1)
    c2 = example_experiment.new_core(name=2)
    c3 = example_experiment.new_core(name=3)
    c4 = example_experiment.new_core(name=4)
    return (c0, c1, c2, c3, c4)


@pytest.fixture
def example_flows(example_experiment, example_cores):
    """The set of flows used in example_results."""
    c0, c1, c2, c3, c4 = example_cores
    f0 = example_experiment.new_flow(c0, [c2, c3], name="f0")
    f1 = example_experiment.new_flow(c0, c1, name=1)
    f2 = example_experiment.new_flow(c2, c2, name=2)
    return (f0, f1, f2)


@pytest.fixture
def example_groups(example_experiment):
    """The set of groups used in example_results."""
    with example_experiment.new_group(name="g0") as g0:
        g0.add_label("foobar", "foo")
        g0.add_label("only_group0", 1234)

        example_experiment.duration = 1.0
        example_experiment.record_interval = 0.0  # Just one recording

    with example_experiment.new_group(name=1) as g1:
        g1.add_label("foobar", "bar")
        g1.add_label("only_group1", 4321)

        example_experiment.duration = 0.2
        example_experiment.record_interval = 0.1

    return (g0, g1)


@pytest.fixture
def example_results(example_experiment, example_cores, example_flows,
                    example_groups):
    """This fixture produces a Results object with a particular artificial set
    of results.
        +-------+
        | c4    |
        |       |
        |       |
        +-------+
         (0, 1)


        +-------+  f0    +-------+
        |  c0---+---+----+->c2-+f|
        |  |f1  |    \   |   ^-+2|
        |  c1   |     ----->c3   |
        +-------+        +-------+
         (0, 0)           (1, 0)

    In this system there are five cores, c0-c4. Cores 0-3 are nominally
    those inserted as part of the experiment. Core 4 is a core inserted for
    the purpose of recording router registers on chip (0, 1). This gives
    examples of both router-only cores and dual-purpose cores.

    Cores 0, 2 and 4 record the external_p2p, local_p2p and reinjected counters
    on their local router. All cores record packets send and packets received
    by any flows at that core.

    The cores are named by their number, except for c0 which is named "c0".

    There are three flows, f0-f2.
    * Flow 0 is sourced by core 0 and is sunk by c2 and c3 giving an example
      of a multicast flow.
    * Flow 1 is also sourced by core 0 and is sunk by c1 which gives a unicast
      flow and also shows multiple flows sourced at a single core.
    * Flow 2 is sourced and sunk by core 2 giving an example of a cyclic flow
      and also a core with multiple sunk flows.
    Cores 1 and 3 give examples of cores with no sourced flows. Cores 0
    and 4 give an example of cores with no sunk flows.

    The flows are named by their number, except for f0 which is named "f0".

    There are two experimental groups, group 0 and group 1.
    * Group 0 lasts 1 second and has one recorded sample. It has two labelled
      values: foobar = "foo" and only_group0 = 1234. It has the name "g0"
      (a string).
    * Group 1 lasts 0.2 seconds and has two recorded samples, one at 0.1
      seconds and the other at 0.2 seconds. It has two labelled values: foobar
      = "bar" and only_group1 = 4321. It has the name 1 (an integer). Just to
      make the two distinguishable, every counter will be one count higher in
      the second sample for group one.

    In all examples, the traffic through each flow will be:
    * Flow 0: 20 packets per second.
    * Flow 1: 30 packets per second.
    * Flow 2: 40 packets per second.

    Further, the router counters on each chip will increment as follows:
    * (0, 0) local_p2p 10 packets per second.
    * (0, 0) external_p2p 20 packets per second.
    * (0, 0) reinjected 70 packets per second.
    * (1, 0) local_p2p 30 packets per second.
    * (1, 0) external_p2p 40 packets per second.
    * (1, 0) reinjected 80 packets per second.
    * (0, 1) local_p2p 50 packets per second.
    * (0, 1) external_p2p 60 packets per second.
    * (0, 1) reinjected 90 packets per second.
    """
    c0, c1, c2, c3, c4 = example_cores
    f0, f1, f2 = example_flows

    # The last router-recording-only core is not listed in the core list
    cores = [c0, c1, c2, c3]

    router_recording_cores = set([c0, c2, c4])
    placements = {c0: (0, 0),
                  c1: (0, 0),
                  c2: (1, 0),
                  c3: (1, 0),
                  c4: (0, 1)}
    routes = {
        f0: RoutingTree((0, 0),
                        set([(Routes.east,
                              RoutingTree((1, 0),
                                          set([(Routes.core_1, c2),
                                               (Routes.core_2, c3)])))])),
        f1: RoutingTree((0, 0),
                        set([(Routes.core_2, c1)])),
        f2: RoutingTree((1, 0),
                        set([(Routes.core_1, c2)])),
    }
    cores_records = {c0: [((0, 0), Counters.local_p2p),
                          ((0, 0), Counters.external_p2p),
                          ((0, 0), Counters.reinjected),
                          (f0, Counters.sent),
                          (f1, Counters.sent)],
                     c1: [(f1, Counters.received)],
                     c2: [((1, 0), Counters.local_p2p),
                          ((1, 0), Counters.external_p2p),
                          ((1, 0), Counters.reinjected),
                          (f2, Counters.sent),
                          (f0, Counters.received),
                          (f2, Counters.received)],
                     c3: [(f0, Counters.received)],
                     c4: [((0, 1), Counters.local_p2p),
                          ((0, 1), Counters.external_p2p),
                          ((0, 1), Counters.reinjected)]}

    def pack(*args):
        """Pack a series of result values."""
        return struct.pack("<I{}I".format(len(args)),
                           0x00000000,  # No errors
                           *args)

    cores_result_data = {
        #         lp2p,ep2p,rein,n0src,n1src
        c0: pack(10, 20, 70, 20, 30,  # g0s0
                 1, 2, 7, 2, 3,  # g1s0
                 2, 3, 8, 3, 4),  # g1s1
        #         n1snk
        c1: pack(30,  # g0s0
                 3,  # g1s0
                 4),  # g1s1
        #         lp2p,ep2p,rein,n2src,n0snk,n2snk
        c2: pack(30, 40, 80, 40, 20, 40,  # g0s0
                 3, 4, 8, 4, 2, 4,  # g1s0
                 4, 5, 9, 5, 3, 5),  # g1s1
        #         n0snk
        c3: pack(20,  # g0s0
                 2,  # g1s0
                 3),  # g1s1
        #         lp2p,ep2p,rein
        c4: pack(50, 60, 90,  # g0s0
                 5, 6, 9,  # g1s0
                 6, 7, 10),  # g1s1
    }

    r = Results(example_experiment, cores, example_flows, cores_records,
                router_recording_cores, placements, routes,
                cores_result_data, example_groups)

    return r


@pytest.mark.parametrize("num_cores,num_flows_per_core", [
    # Absolutely nothing
    (0, 0),
    # Nothing to record with various numbers of
    # flows/cores doesn't do anything
    (1, 0),
    (1, 1),
    (2, 2),
])
def test_empty(num_cores, num_flows_per_core):
    """Test that we can produce a Result object for various scenarios where no
    results will exist."""
    experiment = Experiment(Mock())

    cores = [experiment.new_core() for _ in range(num_cores)]
    flows = [experiment.new_flow(c, c)
             for c in cores
             for _ in range(num_flows_per_core)]
    router_recording_cores = set()
    placements = {c: (0, 0) for c in cores}
    routes = {f: RoutingTree((0, 0),
                             set([(Routes.core(cores.index(f.sinks[0])),
                                   f.sinks[0])]))
              for f in flows}
    cores_result_data = {c: b"\0\0\0\0" for c in cores}
    groups = {}
    cores_records = {c: [] for c in cores}

    r = Results(experiment, cores, flows, cores_records,
                router_recording_cores, placements, routes,
                cores_result_data, groups)

    assert r.errors == set()

    assert len(r.totals()) == 0
    assert len(r.core_totals()) == 0
    assert len(r.flow_totals()) == 0
    assert len(r.flow_counters()) == 0
    assert len(r.router_counters()) == 0


@pytest.mark.parametrize("cores_result_data,expected_errors", [
    # No errors
    ([], set()),
    ([b"\0\0\0\0"], set()),
    ([b"\0\0\0\0", b"\0\0\0\0"], set()),
    # Non-overlapping errors should get merged
    ([b"\x01\0\0\0"], set([NT_ERR.STILL_RUNNING])),
    ([b"\x01\0\0\0", b"\x02\0\0\0"],
     set([NT_ERR.STILL_RUNNING, NT_ERR.MALLOC])),
    # Overlapping errors should also get merged
    ([b"\x01\0\0\0", b"\x01\0\0\0"],
     set([NT_ERR.STILL_RUNNING])),
])
def test_errors(cores_result_data, expected_errors):
    """Test that we can produce a Result object for various scenarios where no
    results will exist."""
    experiment = Experiment(Mock())

    cores_result_data = {experiment.new_core(): d
                         for d in cores_result_data}
    cores = list(cores_result_data)
    flows = []
    router_recording_cores = set()
    placements = {}
    routes = {}
    groups = {}
    cores_records = {c: [] for c in cores}

    r = Results(experiment, cores, flows, cores_records,
                router_recording_cores, placements, routes,
                cores_result_data, groups)

    assert r.errors == expected_errors

    if expected_errors:
        assert "error" in repr(r)
    else:
        assert "error" not in repr(r)


def test_num_samples(example_results):
    """Make sure the total sample count is correct."""
    assert example_results._num_samples == 3


def test_recorded(example_results):
    """Make sure full set of recorded counters is correct."""
    assert example_results._recorded == [Counters.local_p2p,
                                         Counters.external_p2p,
                                         Counters.reinjected,
                                         Counters.sent,
                                         Counters.received]


def test_cores_results(example_results, example_cores):
    """Make sure the results are unpacked correctly."""
    c0, c1, c2, c3, c4 = example_cores
    model_cores_results = {
        #             lp2p,ep2p,rein,n0src,n1src
        c0: np.array([[10, 20, 70, 20, 30],  # g0s0
                      [1, 2, 7, 2, 3],  # g1s0
                      [2, 3, 8, 3, 4]],  # g1s1
                     dtype=np.uint),
        #             n1snk
        c1: np.array([[30],  # g0s0
                      [3],  # g1s0
                      [4]],  # g1s1
                     dtype=np.uint),
        #             lp2p,ep2p,rein,n2src,n0snk,n2snk
        c2: np.array([[30, 40, 80, 40, 20, 40],  # g0s0
                      [3, 4, 8, 4, 2, 4],  # g1s0
                      [4, 5, 9, 5, 3, 5]],  # g1s1
                     dtype=np.uint),
        #             n0snk
        c3: np.array([[20],  # g0s0
                      [2],  # g1s0
                      [3]],  # g1s1
                     dtype=np.uint),
        #             lp2p,ep2p,rein
        c4: np.array([[50, 60, 90],  # g0s0
                      [5, 6, 9],  # g1s0
                      [6, 7, 10]],  # g1s1
                     dtype=np.uint),
    }
    for core in example_cores:
        assert (example_results._cores_results[core] ==
                model_cores_results[core]).all()


def test_make_result_array(example_results, example_groups):
    """Make sure the common set of columns are correct."""
    g0, g1 = example_groups

    # Just the basic columns
    a = example_results._make_result_array([])
    assert a.dtype.names == ("foobar",
                             "only_group0",
                             "only_group1",
                             "group",
                             "time")
    assert (a["foobar"] == np.array(["foo", "bar", "bar"], dtype=object)).all()
    assert (a["only_group0"] == np.array([1234, None, None],
                                         dtype=object)).all()
    assert (a["only_group1"] == np.array([None, 4321, 4321],
                                         dtype=object)).all()
    assert (a["group"] == np.array([g0, g1, g1], dtype=object)).all()
    assert (a["time"] == np.array([1.0, 0.1, 0.2], dtype=np.double)).all()

    # Adding additional columns should work
    a = example_results._make_result_array(["magic", ("moose", np.double)])
    assert a.dtype.names == ("foobar",
                             "only_group0",
                             "only_group1",
                             "group",
                             "time",
                             "magic",
                             "moose")
    assert (a["magic"] == np.array([0, 0, 0], dtype=np.uint)).all()
    assert (a["moose"] == np.array([0.0, 0.0, 0.0], dtype=np.double)).all()

    # Having multiple rows per sample should work too
    a = example_results._make_result_array(["magic", ("moose", np.double)],
                                           rows_per_sample=2)
    assert a.dtype.names == ("foobar",
                             "only_group0",
                             "only_group1",
                             "group",
                             "time",
                             "magic",
                             "moose")
    assert (a["foobar"] == np.array(["foo", "foo", "bar", "bar", "bar", "bar"],
                                    dtype=object)).all()
    assert (a["only_group0"] == np.array([1234, 1234, None, None, None, None],
                                         dtype=object)).all()
    assert (a["only_group1"] == np.array([None, None, 4321, 4321, 4321, 4321],
                                         dtype=object)).all()
    assert (a["group"] == np.array([g0, g0, g1, g1, g1, g1],
                                   dtype=object)).all()
    assert (a["time"] == np.array([1.0, 1.0, 0.1, 0.1, 0.2, 0.2],
                                  dtype=np.double)).all()
    assert (a["magic"] == np.array([0, 0, 0, 0, 0, 0],
                                   dtype=np.uint)).all()
    assert (a["moose"] == np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                                   dtype=np.double)).all()


def test_totals(example_results, example_groups):
    """Make sure the overall totals work."""
    g0, g1 = example_groups
    totals = example_results.totals()

    assert totals.dtype.names == ("foobar",
                                  "only_group0",
                                  "only_group1",
                                  "group",
                                  "time",
                                  "local_p2p",
                                  "external_p2p",
                                  "reinjected",
                                  "sent",
                                  "received",
                                  "ideal_received")
    assert (totals == np.array([("foo", 1234, None, g0,
                                 1.0, 90, 120, 240, 90, 110, 110),
                                ("bar", None, 4321, g1,
                                 0.1, 9, 12, 24, 9, 11, 11),
                                ("bar", None, 4321, g1,
                                 0.2, 12, 15, 27, 12, 15, 15)],
                               dtype=totals.dtype)).all()


def test_core_totals(example_results, example_groups, example_cores):
    """Make sure the per-core totals work."""
    g0, g1 = example_groups
    # Note that the router-recording-only-core should be omitted
    c0, c1, c2, c3 = example_cores[:4]
    totals = example_results.core_totals()

    assert totals.dtype.names == ("foobar",
                                  "only_group0",
                                  "only_group1",
                                  "group",
                                  "time",
                                  "core",
                                  "sent",
                                  "received",
                                  "ideal_received")
    assert (totals == np.array([("foo", 1234, None, g0, 1.0, c0, 50, 0, 0),
                                ("foo", 1234, None, g0, 1.0, c1, 0, 30, 30),
                                ("foo", 1234, None, g0, 1.0, c2, 40, 60, 60),
                                ("foo", 1234, None, g0, 1.0, c3, 0, 20, 20),
                                ("bar", None, 4321, g1, 0.1, c0, 5, 0, 0),
                                ("bar", None, 4321, g1, 0.1, c1, 0, 3, 3),
                                ("bar", None, 4321, g1, 0.1, c2, 4, 6, 6),
                                ("bar", None, 4321, g1, 0.1, c3, 0, 2, 2),
                                ("bar", None, 4321, g1, 0.2, c0, 7, 0, 0),
                                ("bar", None, 4321, g1, 0.2, c1, 0, 4, 4),
                                ("bar", None, 4321, g1, 0.2, c2, 5, 8, 8),
                                ("bar", None, 4321, g1, 0.2, c3, 0, 3, 3)],
                               dtype=totals.dtype)).all()


def test_flow_totals(example_results, example_groups, example_flows):
    """Make sure the per-flow totals work."""
    g0, g1 = example_groups
    f0, f1, f2 = example_flows
    totals = example_results.flow_totals()

    assert totals.dtype.names == ("foobar",
                                  "only_group0",
                                  "only_group1",
                                  "group",
                                  "time",
                                  "flow",
                                  "fan_out",
                                  "sent",
                                  "received")
    assert (totals == np.array([("foo", 1234, None, g0, 1.0, f0, 2, 20, 40),
                                ("foo", 1234, None, g0, 1.0, f1, 1, 30, 30),
                                ("foo", 1234, None, g0, 1.0, f2, 1, 40, 40),
                                ("bar", None, 4321, g1, 0.1, f0, 2, 2, 4),
                                ("bar", None, 4321, g1, 0.1, f1, 1, 3, 3),
                                ("bar", None, 4321, g1, 0.1, f2, 1, 4, 4),
                                ("bar", None, 4321, g1, 0.2, f0, 2, 3, 6),
                                ("bar", None, 4321, g1, 0.2, f1, 1, 4, 4),
                                ("bar", None, 4321, g1, 0.2, f2, 1, 5, 5)],
                               dtype=totals.dtype)).all()


def test_flow_counters(example_results, example_groups, example_cores,
                       example_flows):
    """Make sure the all sources/sinks counters work."""
    g0, g1 = example_groups
    # Note that the router-recording-only-core should be omitted
    c0, c1, c2, c3 = example_cores[:4]
    f0, f1, f2 = example_flows
    counts = example_results.flow_counters()

    assert counts.dtype.names == ("foobar",
                                  "only_group0",
                                  "only_group1",
                                  "group",
                                  "time",
                                  "flow",
                                  "fan_out",
                                  "source_core",
                                  "sink_core",
                                  "num_hops",
                                  "sent",
                                  "received")
    assert (counts == np.array(
        [("foo", 1234, None, g0, 1.0, f0, 2, c0, c2, 1, 20, 20),
         ("foo", 1234, None, g0, 1.0, f0, 2, c0, c3, 1, 20, 20),
         ("foo", 1234, None, g0, 1.0, f1, 1, c0, c1, 0, 30, 30),
         ("foo", 1234, None, g0, 1.0, f2, 1, c2, c2, 0, 40, 40),
         ("bar", None, 4321, g1, 0.1, f0, 2, c0, c2, 1, 2, 2),
         ("bar", None, 4321, g1, 0.1, f0, 2, c0, c3, 1, 2, 2),
         ("bar", None, 4321, g1, 0.1, f1, 1, c0, c1, 0, 3, 3),
         ("bar", None, 4321, g1, 0.1, f2, 1, c2, c2, 0, 4, 4),
         ("bar", None, 4321, g1, 0.2, f0, 2, c0, c2, 1, 3, 3),
         ("bar", None, 4321, g1, 0.2, f0, 2, c0, c3, 1, 3, 3),
         ("bar", None, 4321, g1, 0.2, f1, 1, c0, c1, 0, 4, 4),
         ("bar", None, 4321, g1, 0.2, f2, 1, c2, c2, 0, 5, 5)],
        dtype=counts.dtype)).all()


def test_router_counters(example_results, example_groups):
    """Make sure the all router counters work."""
    g0, g1 = example_groups
    counts = example_results.router_counters()

    assert counts.dtype.names == ("foobar",
                                  "only_group0",
                                  "only_group1",
                                  "group",
                                  "time",
                                  "x",
                                  "y",
                                  "local_p2p",
                                  "external_p2p",
                                  "reinjected")
    assert (counts == np.array(
        [("foo", 1234, None, g0, 1.0, 0, 0, 10, 20, 70),
         ("foo", 1234, None, g0, 1.0, 1, 0, 30, 40, 80),
         ("foo", 1234, None, g0, 1.0, 0, 1, 50, 60, 90),
         ("bar", None, 4321, g1, 0.1, 0, 0, 1, 2, 7),
         ("bar", None, 4321, g1, 0.1, 1, 0, 3, 4, 8),
         ("bar", None, 4321, g1, 0.1, 0, 1, 5, 6, 9),
         ("bar", None, 4321, g1, 0.2, 0, 0, 2, 3, 8),
         ("bar", None, 4321, g1, 0.2, 1, 0, 4, 5, 9),
         ("bar", None, 4321, g1, 0.2, 0, 1, 6, 7, 10)],
        dtype=counts.dtype)).all()


def test_to_csv():
    """Make sure the CSV conversion utility actually works..."""
    dt = np.dtype([("a", np.uint), ("b", np.double), ("c", object)])

    e = Experiment(Mock())
    g0 = e.new_group("g0")
    g1 = e.new_group(1)
    c0 = e.new_core(name="c0")
    c1 = e.new_core(name=1)
    f0 = e.new_flow(c0, c0, name="f0")
    f1 = e.new_flow(c1, c1, name=1)

    # Empty dataset
    assert to_csv(np.zeros((0,), dtype=dt)) == "a,b,c"
    assert to_csv(np.zeros((0,), dtype=dt), False) == ""

    # Standard data types should be handled correctly
    a = np.zeros((2,), dtype=dt)
    assert to_csv(a) == ("a,b,c\n"
                         "0,0.0,0\n"
                         "0,0.0,0")
    assert to_csv(a, False) == ("0,0.0,0\n"
                                "0,0.0,0")

    # Nones should be printed specially
    a["c"][0] = None
    assert to_csv(a) == ("a,b,c\n"
                         "0,0.0,NA\n"
                         "0,0.0,0")

    # Groups, Flows and Cores should be printed specially
    a = np.zeros((6,), dtype=dt)
    a["c"][0] = g0
    a["c"][1] = g1
    a["c"][2] = c0
    a["c"][3] = c1
    a["c"][4] = f0
    a["c"][5] = f1
    assert to_csv(a) == ("a,b,c\n"
                         "0,0.0,g0\n"
                         "0,0.0,1\n"
                         "0,0.0,c0\n"
                         "0,0.0,1\n"
                         "0,0.0,f0\n"
                         "0,0.0,1")
