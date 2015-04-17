import pytest

from mock import Mock

from rig.machine_control import MachineController

from network_tester import Experiment
from network_tester import TrafficNode


@pytest.fixture
def mock_mc():
    return Mock(spec_set=MachineController)

@pytest.fixture
def e(mock_mc):
    return Experiment(mock_mc)

@pytest.fixture
def nn(e):
    return e.new_network_node()


def test_add_sink(nn):
    tn1 = nn.new_traffic_node(TrafficNode())
    tn2 = nn.new_traffic_node(TrafficNode())
    tn3 = nn.new_traffic_node(TrafficNode())
    
    tn1.add_sink(tn1)
    tn1.add_sink(tn2)
    tn1.add_sink(tn3)
    
    tn3.add_sink(tn1)
    
    # Make sure all the source/sink pointers get setup correctly
    assert set(tn1.sources) == set([tn1, tn3])
    assert set(tn1.sinks) == set([tn1, tn2, tn3])
    
    assert set(tn2.sources) == set([tn1])
    assert set(tn2.sinks) == set()
    
    assert set(tn3.sources) == set([tn1])
    assert set(tn3.sinks) == set([tn1])


