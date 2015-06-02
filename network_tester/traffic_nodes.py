"""Representation of various kinds of Traffic Nodes"""

from struct import Struct

from enum import IntEnum


class TrafficNodeType(IntEnum):
    """Traffic generator type, traffic_node_type_t in the C code."""
    
    bernoulli = 0
    relay = 1


class TrafficNode(object):
    """A base class for all traffic node types.
    
    The following attributes are set after read_result_data has been called on
    this (and all sink) traffic nodes.
    
    Attributes
    ----------
    num_sent : int
        The number of packets actually sent by this node during the experiment.
    num_arrived : int
        The total number of packets which arrived at all sinks.
    num_arrived_per_sink : {sink: int, ...}
        A dictionary which maps from each sink to the number of packets which
        arrived at that sink from this traffic node.
    num_out_of_order : int
        The total number of packets which arrived out of order at all sinks.
    num_out_of_order_per_sink : {sink: int, ...}
        A dictionary which maps from each sink to the number of packets which
        arrived out of order at that sink from this traffic node.
    """

    traffic_node_spec_t = Struct("<"     # (Little-endian)
                                 "I"     # traffic_node_type_t type;
                                 "I"     # uint32_t key;
                                 "I"     # bool payload;
                                 "I"     # uint32_t num_sent;
                                 "I"     # size_t num_sources;
                                 "I")    # traffic_node_source_t *sources;
    traffic_node_spec_t_union_size = 12

    traffic_node_source_t = Struct("<"   # (Little-endian)
                                   "I"   # uint32_t key;
                                   "I"   # uint32_t num_received;
                                   "I"   # uint32_t num_out_of_order;
                                   "I")  # uint32_t last_seq_num;

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
        
        # A file-like object which presents an interface to the SpiNNaker SDRAM
        # associated with the memory which stores the struct data for this
        # traffic node.
        self.sdram = None
        
        # Public result attributes (see class docstring)
        num_sent = None
        num_arrived = None
        num_arrived_per_sink = {}
        num_out_of_order = None
        num_out_of_order_per_sink = {}
        
    def add_sink(self, tn):
        """Send traffic produced by this traffic node to the specified traffic
        node."""
        self.sinks.append(tn)
        tn.sources.append(self)
    
    def _get_config_data(self, type, data_field):
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
    
    def write_config_data(self):
        """Write the traffic node's config data to the machine's SDRAM."""
        self.sdram.seek(0)
        self.sdram.write(self._get_config_data())
    
    def get_config_data_size(self):
        """Get the number of bytes required to store this traffic node."""
        return (TrafficNode.traffic_node_spec_t.size +
                TrafficNode.traffic_node_spec_t_union_size +
                (TrafficNode.traffic_node_source_t.size * len(self.sources)))
    
    def _unpack_results(self, data):
        """Given a copy of the data read back from the machine after an
        experiment, extract result data into this class' attributes."""
        traffic_node_config_data = data[:self.get_config_data_size()]
        
        TrafficNode.traffic_node_source_t.unpack(traffic_node_config_data)
    
    
    def read_result_data(self):
        self.sdram.seek(0)
        self._unpack_results(self.sdram.read(self.get_config_data_size()))


class BernoulliNode(TrafficNode):
    """A Bernoulli traffic distribution.
    
    Produces N packets every T seconds with probability P.
    """
    
    data_struct = Struct("<"   # (Little-endian)
                         "d"   # double probability;
                         "I")  # uint32_t period;
    
    def __init__(self, period, probability=1.0, phase=0.0, num_packets=1,
                 packet_interval=0.0, payload=False):
        """Create a BernoulliNode.
        
        Parameters
        ----------
        period : float
            Number of seconds between possibly sending out a packet.
        probability : float
            Probability of a packet being sent each period seconds. 0-1.
        """
        super(BernoulliNode, self).__init__(payload)
        
        assert period > 0.0
        assert 0.0 <= probability <= 1.0
        
        self.period = period
        self.probability = probability
    
    
    def _get_config_data(self):
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
                                              to_us(self.period))
        
        return super(BernoulliNode, self)._get_config_data(
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
    
    
    def _get_config_data(self):
        """Generate the configuration data to be loaded for this traffic node.
        
        Returns
        -------
        traffic_node_spec
            Two sets of bytes
            The config data for the current traffic node.
        """
        return super(RelayNode, self)._get_config_data(
            TrafficNodeType.relay, b"")
