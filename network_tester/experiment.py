"""Top level experiment object."""

import pkg_resources

from six import itervalues

from rig.bitfield import BitField
from rig.netlist import Net
from rig.machine import Cores
from rig.place_and_route import place, allocate, route
from rig.place_and_route.constraints import ReserveResourceConstraint
from rig.place_and_route.util import build_application_map, build_routing_tables

from .network_node import NetworkNode


class Experiment(object):
    """An experiment."""
    
    def __init__(self, machine_controller):
        """Create an experiment.
        
        Paramters
        ---------
        machine_controller : :py:class:`rig.machine_control.MachineController`
            A machine controller connected to an available SpiNNaker machine to
            use for this experiment.
        """
        self.mc = machine_controller
        
        # Routing keyspace definitions
        self._keyspace = BitField(32)
        
        # Field which will contain a unique (though wrapping...) identifier code
        # for each packet sent.
        self._keyspace.add_field("packet_id", 16, 0, tags="PacketID")
        
        # Field which identifies which traffic node produced a given packet.
        self._keyspace.add_field("traffic_node", tags="Routing")
        
        # Incrementing counter used to allocate keyspace "traffic_node" keys to
        # trafic nodes.
        self._next_traffic_node_key = 0
        
        # A list of the network node objects involved in the experiment
        self.nns = []
    
    def _get_traffic_node_key(self):
        """Produce a new BitField with a unique traffic_node value."""
        key = self._next_traffic_node_key
        self._next_traffic_node_key += 1
        return self._keyspace(traffic_node=key)
    
    def new_network_node(self):
        """Create a new :py:class:`network_tester.NetworkNode` and return it."""
        nn = NetworkNode(self)
        self.nns.append(nn)
        return nn
    
    
    def _place_and_route(self, machine):
        """Perform placement on the experiment's nodes.
        
        Sets the positional metadata of all nodes and generates placement
        and routing data for all nodes.
        
        Arguments
        ---------
        machine : :py:class:`rig.machine.Machine`
            The machine model describing the machine onto which the network
            tester should be placed and routed.
        
        Returns
        -------
        (application_map, routing_tables)
            Where `application_map` is of the type suitable for
            :py:meth:`rig.machine_control.MachineController.load_application`
            and `routing_tables` is of a type suitable for use with
            :py:meth:`rig.machine_control.MachineController.load_routing_tables`.
        """
        self._keyspace.assign_fields()
        
        # Assign one core to each network node
        vertices_resources = {nn: {Cores: 1} for nn in self.nns}
        
        # Create a net for each traffic node (though Nets must only refer to
        # network nodes)
        tn_to_net = {}
        nets = []
        for nn in self.nns:
            for tn in nn.tns:
                net = Net(nn, list(set(sink.network_node
                                       for sink in tn.sinks)))
                nets.append(net)
                tn_to_net[tn] = net
        
        # Don't allocate the monitor processor
        constraints = [ReserveResourceConstraint(Cores, slice(0, 1))]
        
        # Place-and-Route
        placements = place(vertices_resources, nets, machine, constraints)
        allocations = allocate(vertices_resources, nets, machine, constraints,
                               placements)
        routes = route(vertices_resources, nets, machine, constraints,
                       placements, allocations)
        
        # Add placement metadata to all network nodes
        for nn in self.nns:
            x, y = placements[nn]
            core = allocations[nn][Cores].start
            nn.location = (x, y, core)
        
        # Build application map to facilitate the loading of binaries
        binary = pkg_resources.resource_filename("network_tester", "binaries/rig_test.aplx")
        application_map = build_application_map({nn: binary for nn in self.nns},
                                                placements, allocations)
        
        # Build the full set of routing tables
        net_keys = {}
        for nn in self.nns:
            for tn in nn.tns:
                net_keys[tn_to_net[tn]] = (tn.key.get_value("Routing"),
                                           tn.key.get_mask("Routing"))
        routing_tables = build_routing_tables(routes, net_keys)
        
        return application_map, routing_tables
    
    
    def run(self, duration):
        """Load the experiment onto the machine and run it.
        
        Parameters
        ----------
        duration : float
        """
        # TODO
        raise NotImplementedError()
    
    
    @property
    def num_sent(self):
        """A dictionary from (x, y) to router multicast packet count.
        
        Reports the difference between the number of MC packets sent before and
        after the experiment has been run (based on router registers.
        """
        # TODO
        raise NotImplementedError()
    
    
    @property
    def num_dropped(self):
        """A dictionary from (x, y) to router multicast packet drop count.
        
        Reports the difference between the number of MC packets dropped before
        and after the experiment has been run (based on router registers.
        """
        # TODO
        raise NotImplementedError()
