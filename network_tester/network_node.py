"""Representation of a Network Node"""

from struct import Struct, pack


class NetworkNode(object):
    """A SpiNNaker-core worth of traffic nodes."""
    
    network_node_spec_t = Struct("<"   # (Little-endian)
                                 "I"   # uint32_t key_seq_mask;
                                 "I"   # uint32_t duration;
                                 "I"   # size_t num_traffic_nodes;
                                 "I")  # traffic_node_spec_t **traffic_nodes;
    
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
        
        # A file-like object which presents an interface to the SpiNNaker SDRAM
        # associated with the memory which stores the struct data for this
        # network node. Accessed via the sdram property.
        self._sdram = None
    
    def new_traffic_node(self, tn):
        """Add a :py:class:`network_tester.TrafficNode` to this traffic node."""
        tn.network_node = self
        
        # Allocate a routing key for packets sent from this node
        tn.key = self.experiment._get_traffic_node_key()
        
        self.tns.append(tn)
        
        return tn
    
    @property
    def sdram(self):
        """Get the SDRAM file-like allocated to this network node struct."""
        return self._sdram
    
    @sdram.setter
    def sdram(self, sdram):
        """Set the SDRAM file-like to allocate to this NetworkNode and its
        traffic nodes."""
        self._sdram = sdram
        
        # The memory for the traffic nodes starts after...
        tn_offset = (4 +  # ...the data length field...
                     NetworkNode.network_node_spec_t.size +  # ...the NN data...
                     (4 * len(self.tns)))  # ...and the list of TN pointers.
        
        for tn in self.tns:
            tn_size = tn.get_config_data_size()
            tn.sdram = sdram[tn_offset:tn_offset + tn_size]
            tn_offset += tn_size

    def _get_nn_config_data(self):
        """Generate the configuration data to be loaded for this network node
        (but not its traffic nodes).
        
        All pointers are relative to the struct they live in. In the case of the
        traffic_nodes array, these pointers are relative to the address of the
        network_node_spec_t array.
        
        The data is prefixed with a 32-bit integer indicating the length of the
        data block which follows. The data block begins with the
        network_node_spec_t struct and follows with all other data pointed to by
        this struct.
        
        Returns
        -------
        bytes
            The configuration data to be loaded for this network node (but not
            its traffic nodes)
        """
        
        data = NetworkNode.network_node_spec_t.pack(
            self.experiment._keyspace.get_mask(field="seq_num"),
            int(self.experiment.duration * 1000000),
            len(self.tns),
            # The array of pointers to traffic node configs start immediately
            # after the network node block
            NetworkNode.network_node_spec_t.size
        )
        
        # Create an array of pointers to where the traffic node data will be
        # loaded. Intially these 
        cur_offset = len(data) + (4 * len(self.tns))
        for tn in self.tns:
            data += pack("<I", cur_offset)
            cur_offset += tn.get_config_data_size()
        
        # Prefix with the length
        data = pack("<I", cur_offset) + data
        
        return data
    
    
    def write_config_data(self):
        """Write the config data to the machine's SDRAM."""
        self.sdram.seek(0)
        self.sdram.write(self._get_nn_config_data())
        for tn in self.tns:
            tn.write_config_data()
    
    
    def get_config_data_size(self):
        """Get the number of bytes required to store this network node and its
        traffic nodes' configurations."""
        return (4 +  # Integer containing the length of data field
                NetworkNode.network_node_spec_t.size +
                sum(4 +  # Space used in the array of pointers
                    tn.get_config_data_size()  # Space for the traffic node
                    for tn in self.tns))
