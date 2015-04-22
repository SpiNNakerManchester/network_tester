import pytest

from mock import Mock

from rig.machine_control import MachineController

from network_tester import Experiment
from network_tester import TrafficNode
from network_tester import RelayNode


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


def test_get_config_data_empty(nn):
    # Check config data when empty
    data = nn.get_config_data()
    assert data == (
        b"\x0C\x00\x00\x00"  # Length prefix
        b"\xFF\xFF\x00\x00"  # key_seq_mask (bottom 16 bits)
        b"\x00\x00\x00\x00"  # num_traffic_nodes (0)
        b"\x0C\x00\x00\x00"  # traffic_nodes (array starts after this struct)
    )
    assert nn.get_config_data_size() == len(data) == 16
    
    
    # Add some traffic nodes and ensure these are packed correctly
    tn1 = nn.new_traffic_node(RelayNode())
    tn2 = nn.new_traffic_node(RelayNode())
    # By adding a sink to one node and not the other, the two traffic node
    # structures will be given different sizes (tn1 will be larger).
    tn2.add_sink(tn1)
    
    data = nn.get_config_data()
    assert data == (
        b"\x84\x00\x00\x00"  # Length prefix
        b"\xFF\xFF\x00\x00"  # key_seq_mask (bottom 16 bits)
        b"\x02\x00\x00\x00"  # num_traffic_nodes (2)
        b"\x0C\x00\x00\x00"  # traffic_nodes (array starts after this struct)
        # traffic_nodes array
        b"\x14\x00\x00\x00"  # offset of tn1 struct
        b"\x54\x00\x00\x00"  # offset of tn2 struct
        # tn1 struct
        b"\x01\x00\x00\x00"  # type (relay == 1)
        b"\x00\x00\x00\x00"  # key (ID = 0)
        b"\x00\x00\x00\x00"  # payload (False)
        b"\x00\x00\x00\x00"  # num_sent (0)
        b"\x01\x00\x00\x00"  # num_sources (1)
        b"\x30\x00\x00\x00"  # sources (end of struct)
        + (b"\x00"*24) +
        # tn1's source struct
        b"\x00\x00\x01\x00"  # tn2's Key (ID = 1)
        b"\x00\x00\x00\x00"  # num_received (0)
        b"\x00\x00\x00\x00"  # num_received_with_payload (0)
        b"\x00\x00\x00\x00"  # num_out_of_order (0)
        # tn2 struct
        b"\x01\x00\x00\x00"  # type (relay == 1)
        b"\x00\x00\x01\x00"  # key (ID = 1)
        b"\x00\x00\x00\x00"  # payload (False)
        b"\x00\x00\x00\x00"  # num_sent (0)
        b"\x00\x00\x00\x00"  # num_sources (0)
        b"\x30\x00\x00\x00"  # sources (end of struct)
        + (b"\x00"*24)
    )
    assert nn.get_config_data_size() == len(data) == 136
