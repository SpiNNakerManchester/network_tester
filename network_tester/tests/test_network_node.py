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


def test_new_traffic_node(nn):
    # New nodes should be accumulated
    assert set(nn.tns) == set()
    tn1 = nn.new_traffic_node(TrafficNode())
    tn2 = nn.new_traffic_node(TrafficNode())
    assert set(nn.tns) == set([tn1, tn2])
    
    # Make sure they're distinct
    assert tn1 is not tn2
    assert tn1.key.traffic_node != tn2.key.traffic_node
    
    # Make sure the nns are initialised correctly
    for tn in [tn1, tn2]:
        assert tn.network_node is nn
        assert set(tn.sources) == set()
        assert set(tn.sinks) == set()


