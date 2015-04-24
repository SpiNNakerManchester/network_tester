"""Representation of various kinds of Traffic Nodes"""

from struct import Struct

from enum import IntEnum


class TrafficNodeType(IntEnum):
    """Traffic generator type, traffic_node_type_t in the C code."""
    
    bernoulli = 0
    relay = 1


class TrafficNode(object):
    """A base class for all traffic node types."""

    traffic_node_spec_t = Struct("<"     # (Little-endian)
                                 "I"     # traffic_node_type_t type;
                                 "I"     # uint32_t key;
                                 "I"     # bool payload;
                                 "I"     # uint32_t num_sent;
                                 "I"     # size_t num_sources;
                                 "I")    # traffic_node_source_t *sources;
    traffic_node_spec_t_union_size = 24

    traffic_node_source_t = Struct("<"   # (Little-endian)
                                   "I"   # uint32_t key;
                                   "I"   # uint32_t num_received;
                                   "I"   # uint32_t num_received_with_payload;
                                   "I")  # uint32_t num_out_of_order;

    def __init__(self, payload=False):
        """Create a TrafficNode instance.
        
        Parameters
        ----------
        payload : bool
            Should a payload be included with each packet?
        """
        self.payload = payload
        
        # The network node this traffic node is a member of
        self.network_node = None
        
        # The set of traffic nodes this traffic node sinks its traffic to
        self.sinks = []
        
        # The set of traffic nodes that sink their traffic in this node.
        self.sources = []
        
        # A rig BitField giving the keys for packets sent via this node
        self.key = None
    
    
    def add_sink(self, tn):
        """Send traffic produced by this traffic node to the specified traffic
        node."""
        self.sinks.append(tn)
        tn.sources.append(self)
    
    
    def get_config_data(self, type, data_field):
        """Generate the configuration data to be loaded for this traffic node.
        
        Parameters
        ----------
        type : :py:class:`.TrafficNodeType`
            The type number of the traffic generator.
        data_field : bytes
            The value of the data in the "data" field of the struct. This value
            is specific to the type of traffic being generated.
        
        Returns
        -------
        traffic_node_spec
            Two sets of bytes
            The config data for the current traffic node.
        """
        data = TrafficNode.traffic_node_spec_t.pack(
            type,
            self.key.get_value("Routing"),
            self.payload,
            0,  # num_sent
            len(self.sources),
            # The array of traffic_node_source_t will be placed immediately
            # after this struct
            (TrafficNode.traffic_node_spec_t.size +
             TrafficNode.traffic_node_spec_t_union_size))
        
        # Add union data
        data += data_field.ljust(TrafficNode.traffic_node_spec_t_union_size,
                                 b'\x00')
        
        # Populate the array of traffic source nodes and initialise counters to zero
        for source in sorted(self.sources, key=(lambda s:
                                                s.key.get_value("Routing"))):
            data += TrafficNode.traffic_node_source_t.pack(
                source.key.get_value("Routing"), 0, 0, 0)
        
        return data
    
    def get_config_data_size(self):
        """Get the number of bytes required to store this traffic node."""
        return (TrafficNode.traffic_node_spec_t.size +
                TrafficNode.traffic_node_spec_t_union_size +
                (TrafficNode.traffic_node_source_t.size * len(self.sources)))
    
    @property
    def num_sent(self):
        """The count of the number of packets sent by this traffic node."""
        # TODO
        raise NotImplementedError()
    
    
    @property
    def num_received(self):
        """The count of the number of packets sent by this traffic node which
        arrived at their destination."""
        # TODO
        raise NotImplementedError()
    
    
    @property
    def send_times(self):
        """A list of packet send times (in seconds)."""
        # TODO
        raise NotImplementedError()
    
    
    @property
    def receive_times(self):
        """A dictionary giving lists of packet arrival times (in seconds) for
        each destination traffic node."""
        # TODO
        raise NotImplementedError()
    
    
    @property
    def latencies(self):
        """A dictionary from destination traffic node and a list of packet
        latencies (in seconds) between a packet being sent and it arriving at
        the specified destination (based on network synchronised clocks)."""
        # TODO
        raise NotImplementedError()
    
    
    @property
    def roundtrips(self):
        """A list of latencies (in seconds) between a packet being sent and a
        packet arriving at this node with the same ID (e.g. following it being
        bounced by a RelayNode)."""
        # TODO
        raise NotImplementedError()


class BernoulliNode(TrafficNode):
    """A Bernoulli traffic distribution.
    
    Produces N packets every T seconds with probability P.
    """
    
    data_struct = Struct("<"   # (Little-endian)
                         "d"   # double probability;
                         "I"   # uint32_t period;
                         "I"   # uint32_t phase;
                         "I"   # uint32_t num_packets;
                         "I")  # uint32_t packet_interval;
    
    def __init__(self, period, probability=1.0, phase=0.0, num_packets=1,
                 packet_interval=0.0, payload=False):
        """Create a BernoulliNode.
        
        Parameters
        ----------
        period : float
            Number of seconds between possibly sending out a packet.
        probability : float
            Probability of a packet being sent each period seconds. 0-1.
        phase : float
            Phase offset for the Bernoulli period. (Must be +ve)
        num_packets : int
            Number of packet to send when the period elapses and the random
            distribution determines that a packet will be sent.
        packet_interval : float
            Number of seconds between the sending of each of the num_packets to be
            sent.
        payload : bool
            Should a payload be included with each packet?
        """
        super(BernoulliNode, self).__init__(payload)
        
        assert period > 0.0
        assert 0.0 <= probability <= 1.0
        assert num_packets >= 1
        assert 0.0 <= packet_interval <= (period / num_packets)
        assert 0.0 <= phase <= period
        
        self.period = period
        self.probability = probability
        self.phase = phase
        self.num_packets = num_packets
        self.packet_interval = packet_interval
    
    
    def get_config_data(self):
        """Generate the configuration data to be loaded for this traffic node.
        
        Returns
        -------
        traffic_node_spec
            Two sets of bytes
            The config data for the current traffic node.
        """
        
        def to_us(s):
            return int(s * 1000.0 * 1000.0)
        
        data = BernoulliNode.data_struct.pack(self.probability,
                                              to_us(self.period),
                                              to_us(self.phase),
                                              self.num_packets,
                                              to_us(self.packet_interval))
        
        return super(BernoulliNode, self).get_config_data(
            TrafficNodeType.bernoulli, data)


class RelayNode(TrafficNode):
    """A packet repeater."""
    
    def __init__(self, payload=False):
        """Create a packet repeater.
        
        Parameters
        ----------
        payload : bool
            Should a payload be included with each packet?
        """
        super(RelayNode, self).__init__(payload)
    
    
    def get_config_data(self):
        """Generate the configuration data to be loaded for this traffic node.
        
        Returns
        -------
        traffic_node_spec
            Two sets of bytes
            The config data for the current traffic node.
        """
        return super(RelayNode, self).get_config_data(
            TrafficNodeType.relay, b"")
