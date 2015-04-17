"""Representation of various kinds of Traffic Nodes"""


class TrafficNode(object):
    """A base class for all traffic node types."""
    
    def __init__(self):
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
    
    def __init__(self, period, probability=1.0, phase=0.0, n_packets=1, packet_interval=0.0):
        """Create a BernoulliNode.
        
        Parameters
        ----------
        period : float
            Number of seconds between possibly sending out a packet.
        probability : float
            Probability of a packet being sent each period seconds. 0-1.
        phase : float
            Phase offset for the Bernoulli period.
        n_packets : int
            Number of packet to send when the period elapses and the random
            distribution determines that a packet will be sent.
        packet_interval : float
            Number of seconds between the sending of each of the n_packets to be
            sent.
        """
        super(BernoulliNode, self).__init__()
        
        assert period > 0.0
        assert 0.0 <= probability <= 1.0
        assert n_packets >= 1
        assert packet_interval >= 0.0
        
        self.period = period
        self.probability = probability
        self.n_packets = n_packets
        self.packet_interval = packet_interval


class RelayNode(TrafficNode):
    """A packet repeater."""
    
    def __init__(self):
        """Create a packet repeater."""
        super(RelayNode, self).__init__()
