import pytest

import struct

import warnings

from mock import Mock

from six import itervalues

from rig.netlist import Net as RigNet

from rig.machine_control.machine_controller import SystemInfo, ChipInfo
from rig.machine_control.consts import AppState
from rig.links import Links

from rig.place_and_route import Cores

from rig.place_and_route import place, allocate, route
from rig.place_and_route.constraints import \
    ReserveResourceConstraint, LocationConstraint

from network_tester.experiment import \
    Experiment, Core, Flow, Group, _ReinjectionCore, APIChangedError

from network_tester.commands import NT_CMD

from network_tester.counters import Counters

from network_tester.errors import NetworkTesterError

from network_tester.results import Results


def test_hostname_or_machine_controler(monkeypatch):
    # If a hostname is passed in, a new MC should be made
    from network_tester import experiment
    mock_mc = Mock()
    monkeypatch.setattr(experiment, "MachineController", mock_mc)
    Experiment("localhost")
    mock_mc.assert_called_once_with("localhost")
    mock_mc.reset_mock()

    # If an MC is passed in, that should be used
    Experiment(mock_mc)
    assert not mock_mc.called


def test_new_functions():
    # Make sure the e.new_* functions all work as expected
    e = Experiment(Mock())

    # Types should be appropriate
    core0 = e.new_core()
    assert isinstance(core0, Core)
    flow0 = e.new_flow(core0, core0)
    assert isinstance(flow0, Flow)
    group0 = e.new_group()
    assert isinstance(group0, Group)

    # Everything should be given unique names
    core1 = e.new_core()
    flow1 = e.new_flow(core1, core1)
    group1 = e.new_group()
    assert core0.name != core1.name
    assert flow0.name != flow1.name
    assert group0.name != group1.name

    # Custom names should be allowed
    core_foo = e.new_core(name="foo")
    flow_bar = e.new_flow(core_foo, core_foo, name="bar")
    group_baz = e.new_group(name="baz")
    assert core_foo.name == "foo"
    assert flow_bar.name == "bar"
    assert group_baz.name == "baz"

    # The objects should all give their name/type in their repr string
    assert repr(core0) == "<Core 0>"
    assert repr(flow0) == "<Flow 0>"
    assert repr(group0) == "<Group 0>"

    assert repr(core1) == "<Core 1>"
    assert repr(flow1) == "<Flow 1>"
    assert repr(group1) == "<Group 1>"

    assert repr(core_foo) == "<Core 'foo'>"
    assert repr(flow_bar) == "<Flow 'bar'>"
    assert repr(group_baz) == "<Group 'baz'>"


def test_option_getters_setters():
    """Make sure the internal option get/set API works."""
    e = Experiment(Mock())

    group0 = e.new_group()
    core0 = e.new_core()
    core1 = e.new_core()
    flow0 = e.new_flow(core0, core1)
    flow1 = e.new_flow(core1, core0)

    # Make sure the getters setters use specific values with the correct
    # priority.

    # Should get global (default) value
    assert e._get_option_value("timestep") == 0.001
    assert e._get_option_value("timestep", group=group0) == 0.001
    assert e._get_option_value("timestep", core_or_flow=core0) == 0.001
    assert e._get_option_value("timestep", core_or_flow=flow0) == 0.001
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=core0) == 0.001
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=flow0) == 0.001

    # Should be able to change the default value
    e._set_option_value("timestep", 0.1)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 0.1
    assert e._get_option_value("timestep", core_or_flow=core0) == 0.1
    assert e._get_option_value("timestep", core_or_flow=flow0) == 0.1
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=core0) == 0.1
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=flow0) == 0.1

    # Should be able to change the value for a particular core
    e._set_option_value("timestep", 0.5, core_or_flow=core0)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 0.1
    assert e._get_option_value("timestep", core_or_flow=core0) == 0.5
    assert e._get_option_value("timestep", core_or_flow=flow0) == 0.5
    assert e._get_option_value("timestep", core_or_flow=flow1) == 0.1
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=core0) == 0.5
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=flow0) == 0.5
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=flow1) == 0.1

    # Should be able to change the value for a particular flow
    e._set_option_value("timestep", 0.6, core_or_flow=flow0)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 0.1
    assert e._get_option_value("timestep", core_or_flow=core0) == 0.5
    assert e._get_option_value("timestep", core_or_flow=flow0) == 0.6
    assert e._get_option_value("timestep", core_or_flow=flow1) == 0.1
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=core0) == 0.5
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=flow0) == 0.6
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=flow1) == 0.1

    # Should be able to change the value for a particular group (core/flow
    # values should override still)
    e._set_option_value("timestep", 1.0, group=group0)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 1.0
    assert e._get_option_value("timestep", core_or_flow=core0) == 0.5
    assert e._get_option_value("timestep", core_or_flow=flow0) == 0.6
    assert e._get_option_value("timestep", core_or_flow=flow1) == 0.1
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=core0) == 0.5
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=flow0) == 0.6
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=flow1) == 1.0

    # Should be able to change the value for a particular core-group pair and
    # the flow value should still take priority
    e._set_option_value("timestep", 10.0, group=group0, core_or_flow=core0)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 1.0
    assert e._get_option_value("timestep", core_or_flow=core0) == 0.5
    assert e._get_option_value("timestep", core_or_flow=flow0) == 0.6
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=core0) == 10.0
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=flow0) == 0.6

    # Should be able to change the value for a particular core-group pair and
    # implicitly set a flow value which has not been overridden.
    e._set_option_value("timestep", 20.0, group=group0, core_or_flow=core1)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 1.0
    assert e._get_option_value("timestep", core_or_flow=core1) == 0.1
    assert e._get_option_value("timestep", core_or_flow=flow1) == 0.1
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=core1) == 20.0
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=flow1) == 20.0

    # Should be able to change the value for a particular flow-group pair and
    # it should take priority over anything else in that group.
    e._set_option_value("timestep", 30.0, group=group0, core_or_flow=flow0)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 1.0
    assert e._get_option_value("timestep", core_or_flow=core0) == 0.5
    assert e._get_option_value("timestep", core_or_flow=flow0) == 0.6
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=core0) == 10.0
    assert e._get_option_value("timestep",
                               group=group0,
                               core_or_flow=flow0) == 30.0

    # Should be able to get values which don't support exceptions
    assert e._get_option_value("record_sent") is False
    assert e._get_option_value("record_sent", group=group0) is False
    assert e._get_option_value("record_sent", core_or_flow=core0) is False
    assert e._get_option_value("record_sent",
                               group=group0,
                               core_or_flow=core0) is False

    # Should be able to set values which don't support exceptions
    e._set_option_value("record_sent", True)
    assert e._get_option_value("record_sent") is True
    assert e._get_option_value("record_sent", group=group0) is True
    assert e._get_option_value("record_sent", core_or_flow=core0) is True
    assert e._get_option_value("record_sent",
                               group=group0,
                               core_or_flow=core0) is True

    # Shouldn't be able to set exceptions to options which don't support them
    with pytest.raises(ValueError):
        e._set_option_value("record_sent", False, group=group0)
    with pytest.raises(ValueError):
        e._set_option_value("record_sent", False, core_or_flow=core0)
    with pytest.raises(ValueError):
        e._set_option_value("record_sent",
                            False,
                            group=group0,
                            core_or_flow=core0)


def test_option_descriptors():
    """Make sure the option descriptors work."""
    e = Experiment(Mock())

    # Defualts should work
    assert e.seed is None
    assert e.probability == 1.0

    # Should be able to set
    e.probability = 0.1
    assert e.probability == 0.1

    # Should be able to set exceptions for groups
    with e.new_group():
        assert e.probability == 0.1
        e.probability = 1.0
        assert e.probability == 1.0

    assert e.probability == 0.1

    # Should be able to set non-exception-supporting options globally
    assert e.record_sent is False
    e.record_sent = True
    assert e.record_sent is True

    # Should be able to set exceptions for cores
    core0 = e.new_core()
    assert core0.probability == 0.1
    core0.probability = 0.5
    assert core0.probability == 0.5
    assert e.probability == 0.1

    # Should be able to set exceptions for flows
    flow0 = e.new_flow(core0, core0)
    assert flow0.probability == 0.5
    flow0.probability = 0.6
    assert flow0.probability == 0.6
    assert core0.probability == 0.5
    assert e.probability == 0.1

    # Should be able to set exceptions in groups for cores and flows
    with e.new_group():
        assert e.probability == 0.1
        assert core0.probability == 0.5
        assert flow0.probability == 0.6

        # Group probability shouldn't override core/flow probability
        e.probability = 1.0
        assert e.probability == 1.0
        assert core0.probability == 0.5
        assert flow0.probability == 0.6

        # Group+core probability should take precidence (but not over flows)
        core0.probability = 10.0
        assert e.probability == 1.0
        assert core0.probability == 10.0
        assert flow0.probability == 0.6

        # Group+flow probability should take overall precidence
        flow0.probability = 20.0
        assert e.probability == 1.0
        assert core0.probability == 10.0
        assert flow0.probability == 20.0

        # Should be able to get non-exception supporting options
        assert e.record_sent is True

        # Shouldn't be able to set non-exception-supporting options
        with pytest.raises(ValueError):
            e.record_sent = False

    # ...but only within the group
    assert e.probability == 0.1
    assert core0.probability == 0.5
    assert flow0.probability == 0.6


def test_group_num_samples():
    e = Experiment(Mock())

    # When the recording interval is zero, only one sample per group should be
    # made, regardless of group duration.
    with e.new_group() as group:
        e.record_interval = 0.0
        e.duration = 0.0
        assert group.num_samples == 1

    with e.new_group() as group:
        e.record_interval = 0.0
        e.duration = 10.0
        assert group.num_samples == 1

    # When the recording interval set longer than the group, no recordings
    # should be made.
    with e.new_group() as group:
        e.record_interval = 2.0
        e.duration = 1.0
        assert group.num_samples == 0

    # When the recording interval is equal to the group, duration, one
    # recording should be made.
    with e.new_group() as group:
        e.record_interval = 1.0
        e.duration = 1.0
        assert group.num_samples == 1

    # When the recording interval is a fraction of the group duration, the
    # appropriate number of recordings should be made.
    with e.new_group() as group:
        e.record_interval = 0.1
        e.duration = 1.0
        assert group.num_samples == 10


def test_non_nestable_groups():
    # Experimental groups must not be allowed to nest
    e = Experiment(Mock())

    with e.new_group() as group0:
        assert e._cur_group is group0

        with pytest.raises(Exception):
            with e.new_group():
                pass  # pragma: no cover

        # Group should not have been changed
        assert e._cur_group is group0


def test_group_labels():
    # Make sure groups can have labels added
    e = Experiment(Mock())
    group0 = e.new_group()
    group0.add_label("group", 123)
    group0.add_label("colour", "green")

    assert group0.labels == {
        "group": 123,
        "colour": "green",
    }


def test_new_flow():
    # Make sure flows are created and the arguments are those supported by
    # Rig's Net construct.
    e = Experiment(Mock())

    cores = [e.new_core() for _ in range(10)]

    # Arguments should be passed through
    flow = e.new_flow(cores[0], cores[1:])
    assert isinstance(flow, RigNet)
    assert flow.source == cores[0]
    assert flow.sinks == cores[1:]
    assert flow.weight == 1.0

    # As should kwargs
    flow = e.new_flow(source=cores[0], sinks=cores[9], weight=123)
    assert isinstance(flow, RigNet)
    assert flow.source == cores[0]
    assert flow.sinks == [cores[9]]
    assert flow.weight == 123


def test_system_info(monkeypatch):
    # Make sure lazy-loading of the system_info works
    mock_system_info = Mock()
    mock_mc = Mock()
    mock_mc.get_system_info.return_value = mock_system_info
    e = Experiment(mock_mc)

    # First time the system info should be fetched
    assert not mock_mc.get_system_info.called
    assert e.system_info is mock_system_info
    assert mock_mc.get_system_info.called
    mock_mc.get_system_info.reset_mock()

    # Next time it shouldn't
    assert e.system_info is mock_system_info
    assert not mock_mc.get_system_info.called

    # It shouldn't if set manually either...
    mock_machine2 = Mock()
    e.system_info = mock_machine2
    assert e.system_info is mock_machine2
    assert not mock_mc.get_system_info.called

    # It should if reset manually
    e.system_info = None
    assert e.system_info is mock_system_info
    assert mock_mc.get_system_info.called


def test_machine(monkeypatch):
    # Make sure requesting the machine works, is read-only and produces a
    # deprecation warning.
    from network_tester import experiment
    mock_system_info = Mock()
    mock_machine = Mock()
    mock_build_machine = Mock(return_value=mock_machine)
    mock_mc = Mock()
    monkeypatch.setattr(experiment, "build_machine", mock_build_machine)

    e = Experiment(mock_mc)
    e.system_info = mock_system_info

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # Machine object should be returned built from the system info.
        assert not mock_build_machine.called
        assert e.machine is mock_machine
        mock_build_machine.called_once_with(mock_system_info)

        # Should be flagged as deprecated
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)

    # Machine should be regenerated every time (i.e. is explicitly read-only)
    mock_build_machine.reset_mock()
    assert e.machine is mock_machine
    mock_build_machine.called_once_with(mock_system_info)


@pytest.mark.parametrize("router_register", [
    c.name for c in Counters if c.router_counter])
def test_any_router_registers_used(router_register):
    # Should return true if any router register is set to be recorded
    e = Experiment(Mock())

    # Should not be true by default
    assert not e._any_router_registers_used()

    # Should be true when any register enabled
    setattr(e, "record_{}".format(router_register), True)
    assert e._any_router_registers_used()

    # But not when disabled again
    setattr(e, "record_{}".format(router_register), False)
    assert not e._any_router_registers_used()

    # Should be true if reinjection is used
    e.reinject_packets = True
    assert e._any_router_registers_used()
    e.reinject_packets = False
    assert not e._any_router_registers_used()

    # Should be true when a timeout is set
    e.router_timeout = 16
    assert e._any_router_registers_used()
    e.router_timeout = (16, 16)
    assert e._any_router_registers_used()
    e.router_timeout = None
    assert not e._any_router_registers_used()
    with e.new_group():
        e.router_timeout = 16
    assert e._any_router_registers_used()


@pytest.mark.parametrize("reinjection_register", [
    c.name for c in Counters if c.reinjector_counter])
def test_reinjection_used(reinjection_register):
    # Should return true if any router register is set to be recorded
    e = Experiment(Mock())

    # Should not be true by default
    assert not e._reinjection_used()

    # Should be true when any register enabled
    setattr(e, "record_{}".format(reinjection_register), True)
    assert e._reinjection_used()

    # But not when disabled again
    setattr(e, "record_{}".format(reinjection_register), False)
    assert not e._reinjection_used()

    # Should be true when reinjection is enabled at any point
    e.reinject_packets = True
    assert e._reinjection_used()
    e.reinject_packets = False
    assert not e._reinjection_used()
    with e.new_group():
        e.reinject_packets = True
    assert e._reinjection_used()


@pytest.mark.parametrize("record_reinjected", [True, False])
def test_place_and_route(record_reinjected):
    mock_mc = Mock()
    mock_mc.get_system_info.return_value = SystemInfo(2, 2, {
        (x, y): ChipInfo(num_cores=18,
                         core_states=[AppState.run] + [AppState.idle] * 17,
                         working_links=set(Links),
                         largest_free_sdram_block=110*1024*1024,
                         largest_free_sram_block=1024*1024)
        for x in range(2)
        for y in range(2)
    })
    mock_place = Mock(side_effect=place)
    mock_allocate = Mock(side_effect=allocate)
    mock_route = Mock(side_effect=route)

    e = Experiment(mock_mc)
    c0 = e.new_core(0, 0)
    c1 = e.new_core()
    f0 = e.new_flow(c0, c1)
    e.record_reinjected = record_reinjected

    # Prior to place-and-route the placements, allocations and routes should
    # not be available
    with pytest.raises(AttributeError):
        e.placements
    with pytest.raises(AttributeError):
        e.allocations
    with pytest.raises(AttributeError):
        e.routes

    e._place_and_route(place=mock_place,
                       allocate=mock_allocate,
                       route=mock_route)
    assert mock_place.called
    assert mock_allocate.called
    assert mock_route.called

    # Check constraints
    constraints = list(mock_place.mock_calls[0][2]["constraints"])

    # Should reserve core 0 as the monitor
    reserved_monitor = False
    for i, constraint in enumerate(constraints):  # pragma: no branch
        if (  # pragma: no branch
                isinstance(constraint, ReserveResourceConstraint) and
                constraint.resource is Cores and
                constraint.reservation == slice(0, 1) and
                constraint.location is None):
            reserved_monitor = True
            del constraints[i]
            break
    assert reserved_monitor

    # Should force the location of c0
    c0_constrained = False
    for i, constraint in enumerate(constraints):  # pragma: no branch
        if (isinstance(constraint, LocationConstraint) and  # pragma: no branch
                constraint.vertex is c0 and
                constraint.location == (0, 0)):
            c0_constrained = True
            del constraints[i]
            break
    assert c0_constrained

    # If reinjection is used, a reinjection core should have been added for
    # each chip. Record it in a dict {(x, y): _ReinjectionCore, ...}
    reinjection_cores = {}
    for i, constraint in reversed(  # pragma: no branch
            list(enumerate(constraints))):
        if (isinstance(constraint, LocationConstraint) and  # pragma: no branch
                isinstance(constraint.vertex, _ReinjectionCore)):
            reinjection_cores[constraint.location] = constraint.vertex
            del constraints[i]

    if record_reinjected:
        # Should have one reinjection core per chip
        assert set(reinjection_cores) == set(e.system_info)
    else:
        assert len(reinjection_cores) == 0

    # No other constraints should exist
    assert len(constraints) == 0

    # Check that recording cores were not added to chips which already had a
    # core on.
    router_recording_cores = set(e._placements).difference(
        set([c0, c1]).union(set(itervalues(reinjection_cores)))
    )
    core_placements = set([e._placements[c0], e._placements[c1]])
    assert core_placements.isdisjoint(  # pragma: no branch
        set(e._placements[c] for c in router_recording_cores))

    # Check that all chips have a router-recording vertex if reinjection is
    # used but otherwise no cores have been added.
    if record_reinjected:
        all_used_chips = core_placements.union(
            set(e._placements[c] for c in router_recording_cores))
        assert all_used_chips == set(e.system_info)
    else:
        assert len(router_recording_cores) == 0

    # In the placements and allocations reported we should have include the
    # extra cores for recording and reinjection.
    assert set(e._placements) == set(e._allocations)

    # The routes generated should correspond to the flows created
    assert set(e._routes) == set([f0])

    # Finally, check the placements, allocations and routes reported back only
    # include user-created vertices.
    assert set(e.placements) == set([c0, c1])
    assert set(e.allocations) == set([c0, c1])
    assert set(e.routes) == set([f0])


@pytest.mark.parametrize("router_access_core", [True, False])
def test_construct_core_commands(router_access_core):
    # XXX: This test is *very* far from being complete. In particular, though
    # the problem supplied is realistic, the output is not checked thouroughly
    # enough.
    e = Experiment(Mock())

    # A simple example network as follows:
    #       f0
    #  c0 ---+--> c1
    #   |    '--> c2
    #   +-------> c3
    #      f1
    # We'll pretend all of them are on the same chip and core0 is the one
    # designated as the router-value recording core.

    core0 = e.new_core()
    core1 = e.new_core()
    core2 = e.new_core()
    core3 = e.new_core()

    cores = [core0, core1, core2, core3]

    flow0 = e.new_flow(core0, [core1, core2])
    flow1 = e.new_flow(core0, core3)

    # Seed randomly
    e.seed = None

    e.timestep = 1e-6
    e.warmup = 0.001
    e.duration = 1.0
    e.cooldown = 0.001
    e.flush_time = 0.01

    e.record_sent = True

    e.reinject_packets = True

    # By default, nothing should send and everything should consume
    e.probability = 0.0
    e.consume = True
    e.router_timeout = 240

    # In group0, everything consumes and f0 sends 100% packets and f1 sends 50%
    # packets.
    with e.new_group():
        flow0.probability = 1.0
        flow1.probability = 0.5

    # In group1, nothing consumes and f0 and f1 send 100%
    with e.new_group():
        flow0.probability = 1.0
        flow1.probability = 1.0
        e.consume = False
        e.router_timeout = 0

    # In group2, we have a timeout with emergency routing enabled
    with e.new_group():
        e.router_timeout = (16, 16)

    flow_keys = {flow0: 0xAA00, flow1: 0xBB00}

    cores_source_flows = {
        core0: [flow0, flow1],
        core1: [],
        core2: [],
        core3: [],
    }
    cores_sink_flows = {
        core0: [],
        core1: [flow0],
        core2: [flow0],
        core3: [flow1],
    }

    core_commands = {
        core: e._construct_core_commands(
            core=core,
            source_flows=cores_source_flows[core],
            sink_flows=cores_sink_flows[core],
            flow_keys=flow_keys,
            records=[Counters.deadlines_missed, Counters.sent],
            router_access_core=router_access_core).pack()
        for core in cores
    }

    # Make sure all cores have the right number of sources/sinks set
    for core in cores:
        commands = core_commands[core]
        num_sources = len(cores_source_flows[core])
        num_sinks = len(cores_sink_flows[core])
        ref_cmd = struct.pack("<II", NT_CMD.NUM,
                              (num_sources | num_sinks << 16))
        assert ref_cmd in commands

    # Make sure all cores have the right set of sources and sinks
    for core in cores:
        commands = core_commands[core]
        sources = cores_source_flows[core]
        sinks = cores_sink_flows[core]

        for source_num, source_flow in enumerate(sources):
            ref_cmd = struct.pack("<II", NT_CMD.SOURCE_KEY | (source_num << 8),
                                  flow_keys[source_flow])
            assert ref_cmd in commands

        for sink_num, sink_flow in enumerate(sinks):
            ref_cmd = struct.pack("<II", NT_CMD.SINK_KEY | (sink_num << 8),
                                  flow_keys[sink_flow])
            assert ref_cmd in commands

    # Make sure all cores have the right set of timing values
    for core in cores:
        commands = core_commands[core]

        ref_cmd = struct.pack("<II", NT_CMD.TIMESTEP, 1000)
        assert ref_cmd in commands

    # Make sure all cores have the right timeout set
    for core in cores:
        commands = core_commands[core]

        ref_cmd0 = struct.pack("<I", NT_CMD.ROUTER_TIMEOUT)
        ref_cmd1 = struct.pack("<I", NT_CMD.ROUTER_TIMEOUT_RESTORE)
        if router_access_core:
            assert ref_cmd0 in commands
            assert ref_cmd1 in commands
        else:
            assert ref_cmd0 not in commands
            assert ref_cmd1 not in commands

    # Make sure all cores packet reinjection enabled if requested
    for core in cores:
        commands = core_commands[core]

        ref_cmd0 = struct.pack("<I", NT_CMD.REINJECTION_ENABLE)
        ref_cmd1 = struct.pack("<I", NT_CMD.REINJECTION_DISABLE)
        if router_access_core:
            assert ref_cmd0 in commands
            assert ref_cmd1 in commands
        else:
            assert ref_cmd0 not in commands
            assert ref_cmd1 not in commands


def test_core_chip_incomplete():
    # If only X or only Y are specified, things should fail
    mock_mc = Mock()
    e = Experiment(mock_mc)

    with pytest.raises(ValueError):
        e.new_core(chip_x=0)
    with pytest.raises(ValueError):
        e.new_core(chip_y=0)


def test_get_core_record_lookup():
    # Make sure this internal utility produces appropriate results.
    e = Experiment(Mock())

    # Two cores, one will eventually record router values, the other will not.
    core0 = e.new_core()
    core1 = e.new_core()
    cores = [core0, core1]
    e._placements = {core0: (0, 0), core1: (0, 0)}
    e._router_recording_cores = set()

    # Two flows, one connected loop-back, one connected to the other core.
    flow0 = e.new_flow(core0, core0)
    flow1 = e.new_flow(core0, core1)
    cores_source_flows = {core0: [flow0, flow1], core1: []}
    cores_sink_flows = {core0: [flow0], core1: [flow1]}

    # If nothing is being recorded, the sets should just contain permanent
    # counters
    cores_records = e._get_core_record_lookup(
        cores, cores_source_flows, cores_sink_flows)
    assert cores_records == {
        core0: [(core0, Counters.deadlines_missed)],
        core1: [(core1, Counters.deadlines_missed)],
    }

    # If only core counters are being used, they should be included
    e.record_sent = True
    e.record_received = True
    cores_records = e._get_core_record_lookup(
        cores, cores_source_flows, cores_sink_flows)
    assert cores_records == {
        core0: [(core0, Counters.deadlines_missed),
                (flow0, Counters.sent), (flow1, Counters.sent),
                (flow0, Counters.received)],
        core1: [(core1, Counters.deadlines_missed),
                (flow1, Counters.received)],
    }

    # If any routing table entries are present, they should be added to
    # anything in the router_recording_cores lookup.
    e._router_recording_cores = set([core0])
    e.record_external_multicast = True
    cores_records = e._get_core_record_lookup(
        cores,
        cores_source_flows,
        cores_sink_flows)
    assert cores_records == {
        core0: [(core0, Counters.deadlines_missed),
                ((0, 0), Counters.external_multicast),
                (flow0, Counters.sent), (flow1, Counters.sent),
                (flow0, Counters.received)],
        core1: [(core1, Counters.deadlines_missed),
                (flow1, Counters.received)],
    }


@pytest.mark.parametrize("auto_create_group", [True, False])
@pytest.mark.parametrize("samples_per_group",
                         [[],  # No groups
                          [1],
                          [1, 100]])
@pytest.mark.parametrize("num_cores", [0, 1, 2])
@pytest.mark.parametrize("num_flows_per_core", [0, 1, 2])
@pytest.mark.parametrize("error,error_code", [(False, b"\0\0\0\0"),
                                              (True, b"\x20\0\0\0")])
@pytest.mark.parametrize("record", [True, False])
@pytest.mark.parametrize("reinject_packets", [True, False])
def test_run(auto_create_group, samples_per_group, num_cores,
             num_flows_per_core, error, error_code, record, reinject_packets):
    """Make sure that the run command carries out an experiment as would be
    expected."""
    system_info = SystemInfo(3, 1, {
        (x, y): ChipInfo(num_cores=18,
                         core_states=[AppState.run] + [AppState.idle] * 17,
                         working_links=set(Links),
                         largest_free_sdram_block=110*1024*1024,
                         largest_free_sram_block=1024*1024)
        for x in range(3)
        for y in range(1)
    })

    mock_mc = Mock()
    mock_mc.get_system_info.return_value = system_info

    mock_application_ctx = Mock()
    mock_application_ctx.__enter__ = Mock()
    mock_application_ctx.__exit__ = Mock()
    mock_mc.application.return_value = mock_application_ctx

    if reinject_packets:
        # If reinjecting, a core is added to every chip
        mock_mc.wait_for_cores_to_reach_state.return_value = len(system_info)
    else:
        # If not reinjecting, only the user-defined cores exist
        mock_mc.wait_for_cores_to_reach_state.return_value = num_cores

    def mock_sdram_file_read(size):
        return error_code + b"\0"*(size - 4)
    mock_sdram_file = Mock()
    mock_sdram_file.read.side_effect = mock_sdram_file_read

    mock_mc.sdram_alloc_as_filelike.return_value = mock_sdram_file

    e = Experiment(mock_mc)
    e.timestep = 1e-6
    e.warmup = 0.01
    e.duration = 0.01
    e.cooldown = 0.01
    e.flush_time = 0.01

    # Record the result of _construct_core_commands to allow checking of
    # memory allocation sizes
    construct_core_commands = e._construct_core_commands
    cores_commands = {}

    def wrapped_construct_core_commands(core, *args, **kwargs):
        commands = construct_core_commands(core=core, *args, **kwargs)
        cores_commands[core] = commands
        return commands
    e._construct_core_commands = Mock(
        side_effect=wrapped_construct_core_commands)

    if record:
        e.record_sent = True

    e.reinject_packets = reinject_packets

    # Create example cores. Cores are placed on sequential chips along the
    # x-axis.
    cores = [e.new_core(x, 0) for x in range(num_cores)]
    for c in cores:
        for _ in range(num_flows_per_core):
            e.new_flow(c, c)

    # Create example groups
    for num_samples in samples_per_group:
        with e.new_group():
            e.record_interval = e.duration / float(num_samples)

    # The run should fail with an exception when expected.
    if error and (num_cores > 0 or reinject_packets):
        with pytest.raises(NetworkTesterError) as exc_info:
            e.run(0x33, create_group_if_none_exist=auto_create_group)
        results = exc_info.value.results
    else:
        results = e.run(0x33, create_group_if_none_exist=auto_create_group)

    # The results should be of the correct type...
    assert isinstance(results, Results)

    # The results returned should be all zeros (since that is what was written
    # back)
    if record and num_cores > 0 and num_flows_per_core > 0:
        assert sum(results.totals()["sent"]) == 0

    # The supplied app ID should be used
    mock_mc.application.assert_called_once_with(0x33)

    # If reinjection is enabled, the binary should have been loaded
    print([call[1][0] for call in mock_mc.load_application.mock_calls])
    reinjector_loaded = any((len(call[1][0]) == 1 and
                             "reinjector.aplx" in list(call[1][0])[0])
                            for call in mock_mc.load_application.mock_calls)
    if reinject_packets:
        assert reinjector_loaded
    else:
        assert not reinjector_loaded

    # Each chip should have been issued with a suitable malloc for any cores
    # on it.
    for x, core in enumerate(cores):
        cmds_size = cores_commands[core].size
        if record:
            # The space required to record deadlines_missed and the sent
            # counters.
            result_size = (1 + ((1 + num_flows_per_core) *
                                sum(samples_per_group))) * 4
        else:
            # Just the status value and deadlines_missed
            result_size = (1 + sum(samples_per_group)) * 4
        size = max(cmds_size, result_size)
        core_num = e._allocations[core][Cores].start
        mock_mc.sdram_alloc_as_filelike.assert_any_call(size, x=x, y=0,
                                                        tag=core_num)

    # The correct number of barriers should have been reached
    num_groups = len(samples_per_group)
    if auto_create_group:
        num_groups = max(1, num_groups)
    assert len(mock_mc.send_signal.mock_calls) == num_groups


def test_run_callbacks():
    """Make sure that the run command's callbacks occur at the right time."""
    num_groups = 3

    system_info = SystemInfo(3, 1, {
        (x, y): ChipInfo(num_cores=18,
                         core_states=[AppState.run] + [AppState.idle] * 17,
                         working_links=set(Links),
                         largest_free_sdram_block=110*1024*1024,
                         largest_free_sram_block=1024*1024)
        for x in range(3)
        for y in range(1)
    })

    mock_mc = Mock()
    mock_mc.get_system_info.return_value = system_info

    mock_application_ctx = Mock()
    mock_application_ctx.__enter__ = Mock()
    mock_application_ctx.__exit__ = Mock()
    mock_mc.application.return_value = mock_application_ctx

    mock_mc.wait_for_cores_to_reach_state.return_value = len(system_info)

    def mock_sdram_file_read(size):
        return b"\0\0\0\0" + b"\0"*(size - 4)
    mock_sdram_file = Mock()
    mock_sdram_file.read.side_effect = mock_sdram_file_read

    mock_mc.sdram_alloc_as_filelike.return_value = mock_sdram_file

    e = Experiment(mock_mc)
    e.timestep = 1e-6
    e.warmup = 0.01
    e.duration = 0.01
    e.cooldown = 0.01
    e.flush_time = 0.01

    # Enough to cause a recording core to be added to every chip
    e.record_dropped_multicast = True

    # Create a number of groups
    groups = []
    for group_num in range(num_groups):
        groups.append(e.new_group())

    before_load_calls = []
    before_group_calls = []
    before_read_results_calls = []

    def before_load(experiment):
        before_load_calls.append(experiment)

        assert experiment is e

        # Loading should not have started
        assert not mock_mc.sdram_alloc_as_filelike.called

    def before_group(experiment, group):
        before_group_calls.append((experiment, group))

        assert experiment is e

        # Loading should have ocurred
        assert mock_mc.sdram_alloc_as_filelike.called

        # The group should appear in the correct sequence
        assert group is groups.pop(0)

        # The number of barriers reached should be progressing
        assert len(mock_mc.wait_for_cores_to_reach_state.mock_calls) == \
            (num_groups - len(groups))

    def before_read_results(experiment):
        before_read_results_calls.append(experiment)

        assert experiment is e

        # All groups should have been run
        assert len(groups) == 0

        # Reading should not have started
        assert not mock_sdram_file.read.called

    # The run should fail with an exception when expected.
    results = e.run(0x33,
                    before_load=before_load,
                    before_group=before_group,
                    before_read_results=before_read_results)

    # The results should come out as usual...
    assert isinstance(results, Results)

    # All callbacks should have been called
    assert len(before_load_calls) == 1
    assert len(before_group_calls) == num_groups
    assert len(before_read_results_calls) == 1


def test_api_changed_errors():
    # Make sure all API-change errors work
    mock_mc = Mock()
    e = Experiment(mock_mc)

    with pytest.raises(APIChangedError):
        e.new_vertex()
    with pytest.raises(APIChangedError):
        e.new_net()
    with pytest.raises(APIChangedError):
        e.place_and_route()
    with pytest.raises(APIChangedError):
        e.placements = {}
    with pytest.raises(APIChangedError):
        e.allocations = {}
    with pytest.raises(APIChangedError):
        e.routes = {}
