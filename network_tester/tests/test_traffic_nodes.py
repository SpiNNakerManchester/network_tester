import pytest

from mock import Mock

from rig.machine_control import MachineController

from network_tester import Experiment
from network_tester import TrafficNode, BernoulliNode, RelayNode

import struct


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


def test_TrafficNode__get_config_data(e, nn):
    # Make sure config data is packed correctly
    
    # With and without payloads
    tn1 = nn.new_traffic_node(TrafficNode(payload=False))
    tn2 = nn.new_traffic_node(TrafficNode(payload=True))
    
    # A node with others sinking at it (note that they're added in a funny order
    # but will be in key order when loaded onto the machine).
    tn3 = nn.new_traffic_node(TrafficNode(payload=False))
    tn2.add_sink(tn3)
    tn1.add_sink(tn3)
    
    data = tn1._get_config_data(0xAB, b"")
    assert data == (
        b"\xAB\x00\x00\x00"  # type (0xAB)
        b"\x00\x00\x00\x00"  # key (ID = 0)
        b"\x00\x00\x00\x00"  # payload (False)
        b"\x00\x00\x00\x00"  # num_sent (0)
        b"\x00\x00\x00\x00"  # num_sources (0)
        b"\x24\x00\x00\x00"  # sources (end of struct)
        + (b"\x00"*12)
    )
    assert tn1.get_config_data_size() == len(data) == 36
    
    data = tn2._get_config_data(0xAB, b"hi")
    assert data == (
        b"\xAB\x00\x00\x00"  # type (0xAB)
        b"\x00\x00\x01\x00"  # key (ID = 1)
        b"\x01\x00\x00\x00"  # payload (True)
        b"\x00\x00\x00\x00"  # num_sent (0)
        b"\x00\x00\x00\x00"  # num_sources (0)
        b"\x24\x00\x00\x00"  # sources (end of struct)
        b"hi" + (b"\x00"*10)
    )
    assert tn2.get_config_data_size() == len(data) == 36
    
    data = tn3._get_config_data(0xAB, b"")
    assert data == (
        b"\xAB\x00\x00\x00"  # type (0xAB)
        b"\x00\x00\x02\x00"  # key (ID = 2)
        b"\x00\x00\x00\x00"  # payload (False)
        b"\x00\x00\x00\x00"  # num_sent (0)
        b"\x02\x00\x00\x00"  # num_sources (2)
        b"\x24\x00\x00\x00"  # sources (end of struct)
        + (b"\x00"*12) +
        # Source 1 (tn1)
        b"\x00\x00\x00\x00"  # Key (ID = 0)
        b"\x00\x00\x00\x00"  # num_received (0)
        b"\x00\x00\x00\x00"  # num_received_with_payload (0)
        b"\x00\x00\x00\x00"  # num_out_of_order (0)
        # Source 2 (tn2)
        b"\x00\x00\x01\x00"  # Key (ID = 1)
        b"\x00\x00\x00\x00"  # num_received (0)
        b"\x00\x00\x00\x00"  # num_received_with_payload (0)
        b"\x00\x00\x00\x00"  # num_out_of_order (0)
    )
    assert tn3.get_config_data_size() == len(data) == 36 + 16 + 16


def test_BernoulliNode__get_config_data(e, nn):
    # Make sure the BernoulliNode struct is packet correctly
    tn = nn.new_traffic_node(BernoulliNode(period=0.001,
                                           probability=0.5,
                                           phase=0.0005,
                                           num_packets=10,
                                           packet_interval=0.000001,
                                           payload=True))
    
    data = tn._get_config_data()
    assert data == (
        b"\x00\x00\x00\x00"                  # type (bernoulli == 0)
        b"\x00\x00\x00\x00"                  # key (ID = 0)
        b"\x01\x00\x00\x00"                  # payload (True)
        b"\x00\x00\x00\x00"                  # num_sent (0)
        b"\x00\x00\x00\x00"                  # num_sources (0)
        b"\x24\x00\x00\x00"                  # sources (end of struct)
        b"\x00\x00\x00\x00\x00\x00\xE0\x3F"  # probability
        b"\xE8\x03\x00\x00"                  # period
    )
    assert tn.get_config_data_size() == len(data) == 36


def test_RelayNode__get_config_data(e, nn):
    # Make sure the RelayNode struct is packet correctly
    tn = nn.new_traffic_node(RelayNode(payload=True))
    
    data = tn._get_config_data()
    assert data == (
        b"\x01\x00\x00\x00"  # type (relay == 1)
        b"\x00\x00\x00\x00"  # key (ID = 0)
        b"\x01\x00\x00\x00"  # payload (True)
        b"\x00\x00\x00\x00"  # num_sent (0)
        b"\x00\x00\x00\x00"  # num_sources (0)
        b"\x24\x00\x00\x00"  # sources (end of struct)
        + (b"\x00"*12)
    )
    assert tn.get_config_data_size() == len(data) == 36
