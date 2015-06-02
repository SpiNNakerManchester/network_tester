import pytest

from mock import Mock

from rig.machine_control import MachineController

from network_tester import Experiment
from network_tester import TrafficNode
from network_tester import RelayNode

import struct


@pytest.fixture
def mock_mc():
    return Mock(spec_set=MachineController)

@pytest.fixture
def e(mock_mc):
    e = Experiment(mock_mc)
    e.duration = 0.000255
    return e

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


def test__get_nn_config_data(nn):
    # Check config data when empty
    data = nn._get_nn_config_data()
    assert data == (
        b"\x10\x00\x00\x00"  # Length prefix
        b"\xFF\xFF\x00\x00"  # key_seq_mask (bottom 16 bits)
        b"\xFF\x00\x00\x00"  # duration
        b"\x00\x00\x00\x00"  # num_traffic_nodes (0)
        b"\x10\x00\x00\x00"  # traffic_nodes (array starts after this struct)
    )
    assert nn.get_config_data_size() == len(data) == 20
    
    
    # Add some traffic nodes and ensure these are packed correctly
    tn1 = nn.new_traffic_node(RelayNode())
    tn2 = nn.new_traffic_node(RelayNode())
    # By adding a sink to one node and not the other, the two traffic node
    # structures will be given different sizes (tn1 will be larger).
    tn2.add_sink(tn1)
    
    data = nn._get_nn_config_data()
    assert data == (
        struct.pack("<I", nn.get_config_data_size() - 4) +  # Length prefix
        b"\xFF\xFF\x00\x00"    # key_seq_mask (bottom 16 bits)
        b"\xFF\x00\x00\x00"    # duration
        b"\x02\x00\x00\x00"    # num_traffic_nodes (2)
        b"\x10\x00\x00\x00" +  # traffic_nodes (array starts after this struct)
        # traffic_nodes array
        struct.pack("<I", 16 + 8) +  # offset of tn1 struct
        struct.pack("<I", 16 + 8
                      + tn1.get_config_data_size())  # offset of tn2 struct
    )
    assert nn.get_config_data_size() == (
        20 + 8 + tn1.get_config_data_size() + tn2.get_config_data_size())
