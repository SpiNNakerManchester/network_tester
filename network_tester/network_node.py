"""Representation of a Network Node"""

class NetworkNode(object):
    """A SpiNNaker-core worth of traffic nodes."""
    
    def __init__(self, experiment):
        """Create a new NetworkNode.
        
        Users should use :py:meth:`network_tester.Experiment.new_network_node`
        to instantiate this object.
        """
        self.experiment = experiment
        
        # A list of traffic nodes contained by this network node
        self.tns = []
        
        # The (x, y, core) allocated to this node
        self.location = None
    
    def new_traffic_node(self, tn):
        """Add a :py:class:`network_tester.TrafficNode` to this traffic node."""
        tn.network_node = self
        
        # Allocate a routing key for packets sent from this node
        tn.key = self.experiment._get_traffic_node_key()
        
        self.tns.append(tn)
        
        return tn


