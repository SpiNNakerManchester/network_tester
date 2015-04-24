import pytest

from mock import Mock

from rig.machine import Machine, Cores
from rig.machine_control import MachineController

from network_tester import Experiment, BernoulliNode, RelayNode

import pkg_resources

@pytest.fixture
def mock_mc():
    return Mock(spec_set=MachineController)


@pytest.fixture
def machine():
    return Machine(2, 3)


@pytest.fixture
def e(mock_mc):
    return Experiment(mock_mc)


def test__get_traffic_node_key(e):
    # Make sure the keys are defined uniquely
    k1 = e._get_traffic_node_key()
    k2 = e._get_traffic_node_key()
    assert k1.traffic_node != k2.traffic_node


def test_new_network_node(e):
    # New nodes should be accumulated
    assert set(e.nns) == set()
    nn1 = e.new_network_node()
    nn2 = e.new_network_node()
    assert nn1 is not nn2
    assert set(e.nns) == set([nn1, nn2])
    
    # Make sure the nns are initialised correctly
    for nn in [nn1, nn2]:
        assert nn.experiment is e
        assert set(nn.tns) == set()
        assert nn.location is None


def test__place_and_route_empty(e, machine):
    # Test nothing fails for a null experiment
    application_map, routing_tables = e._place_and_route(machine)
    
    # Result should be empty
    assert application_map == {}
    assert routing_tables == {}


def test__place_and_route(e, machine):
    # Generate n_cores worth of network nodes where each node has a ring network
    # of relays and a single broadcast Bernoulli source
    n_nodes = (machine.chip_resources[Cores] - 1) * (machine.width *
                                                     machine.height)
    
    nns = []
    broadcast_tns = []
    ring_tns = []
    for _ in range(n_nodes):
        nn = e.new_network_node()
        nns.append(nn)
        
        broadcast_tn = nn.new_traffic_node(BernoulliNode(1))
        broadcast_tns.append(broadcast_tn)
        
        ring_tn = nn.new_traffic_node(RelayNode())
        ring_tns.append(ring_tn)
    
    for broadcast_tn in broadcast_tns:
        for tn in broadcast_tns:
            broadcast_tn.add_sink(tn)
    for n, ring_tn in enumerate(ring_tns):
        ring_tn.add_sink(ring_tns[(n + 1) % n_nodes])
    
    # Nothing should fail...
    application_map, routing_tables = e._place_and_route(machine)
    
    # Make sure every network node has a unique location and every traffic node
    # has a unique net.
    
    # Every core should be used (less monitor cores)
    binary = pkg_resources.resource_filename("network_tester",
                                             "binaries/network_tester.aplx")
    assert application_map == {binary: {  # pragma: no branch
        (x, y): set(range(1, machine.chip_resources[Cores]))
        for x in range(machine.width)
        for y in range(machine.height)
    }}
    
    # Every core should have some routes going to it
    assert set(routing_tables) == set((x, y)
                                      for x in range(machine.width)
                                      for y in range(machine.height))
