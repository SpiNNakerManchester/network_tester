"""Top level experiment object."""

from collections import OrderedDict

from weakref import WeakKeyDictionary

from rig.machine_control import MachineController


class Group(object):
    """An experimental group."""
    
    def __init__(self):
        self._labels = OrderedDict()
    
    
    def add_label(self, name, value):
        """Set the value of a label column for this group.
        
        Parameters
        ----------
        name : str
            The name of the column
        value
            The value in the column for results in this group.
        """
        self._labels[name] = value


class Node(object):
    """A node in the experiment.
    
    A node represents a single core running a traffic generator/consumer.
    """
    
    def __init__(self, experiment):
        self.experiment = experiment
    
    
    class _Option(object):
        """A descriptor which provides access to the experiment's _values
        dictionary."""
        
        def __init__(self, option):
            self.option = option
        
        def __get__(self, obj, type=None):
            return obj.experiment._get_option_value(
                self.option, obj.experiment.cur_group, self)
        
        def __set__(self, obj, value):
            return obj.experiment._set_option_value(
                self.option, value, obj.experiment.cur_group, self)
    
    seed = _Option("seed")
    
    record_sent = _Option("record_sent")
    record_blocked = _Option("record_blocked")
    record_received = _Option("record_received")
    
    probability = _Option("probability")
    
    burst_period = _Option("burst_period")
    burst_duty = _Option("burst_duty")
    burst_phase = _Option("burst_phase")
    
    key = _Option("key")
    
    use_payload = _Option("use_payload")
    
    consume_packets = _Option("consume_packets")


class Experiment(object):
    """A network experiment."""
    
    def __init__(self, hostname_or_machine_controller):
        """Create a network experiment.
        
        Paramters
        ---------
        hostname_or_machine_controller : \
                str or :py:class:`rig.machine_control.MachineController`
            The hostname of a SpiNNaker machine or a machine controller
            connected to an available SpiNNaker machine to use for this
            experiment.
        """
        if isinstance(hostname_or_machine_controller, str):
            self.mc = MachineController(hostname_or_machine_controller)
        else:
            self.mc = hostname_or_machine_controller
        
        # The experimental group currently being defined
        self._cur_group = None
        
        # A list of experimental groups which have been defined
        self._groups = []
        
        # A list of experimental nodes
        self._nodes = []
        
        # Holds the value of every option along with any special cases.
        # * The global default value has group == node == None.
        # * The value for a group has group==group and node==None.
        # * The value for a node has node==node and group==None.
        # * The value for a node and group has node==node and group==group.
        # {option: {(group, node): value, ...}, ...}
        self._values = {
            "seed": {(None, None): None},
            "timestep": {(None, None): 0.001},
            "record_local_multicast": {(None, None): False},
            "record_external_multicast": {(None, None): False},
            "record_local_p2p": {(None, None): False},
            "record_external_p2p": {(None, None): False},
            "record_local_nearest_neighbour": {(None, None): False},
            "record_external_nearest_neighbour": {(None, None): False},
            "record_local_fixed_route": {(None, None): False},
            "record_external_fixed_route": {(None, None): False},
            "record_dropped_multicast": {(None, None): False},
            "record_dropped_p2p": {(None, None): False},
            "record_dropped_nearest_neighbour": {(None, None): False},
            "record_dropped_fixed_route": {(None, None): False},
            "record_counter12": {(None, None): False},
            "record_counter13": {(None, None): False},
            "record_counter14": {(None, None): False},
            "record_counter15": {(None, None): False},
            "record_sent": {(None, None): False},
            "record_blocked": {(None, None): False},
            "record_received": {(None, None): False},
            "record_interval": {(None, None): 0.0},
            "probability": {(None, None): 0.0},
            "burst_period": {(None, None): 0.0},
            "burst_duty": {(None, None): 0.0},
            "burst_phase": {(None, None): 0.0},
        }
    
    
    def new_node(self):
        """Return a new traffic generator/consumer node."""
        n = Node(self)
        self._nodes.append(n)
        return n
    
    
    @property
    def cur_group(self):
        """Get the unique identifier of the experimental group currently being
        defined (or None if no group is being defined)."""
        
        return self._cur_group
    
    
    def __enter__(self):
        """Begin the definition of a new experimental group."""
        if self._cur_group is not None:
            raise Exception("Cannot nest experimental groups.")
        g = Group()
        self._groups.append(g)
        self._cur_group = g
        return g
    
    def __exit__(self, exc_type, exc_value, traceback):
        """Completes the definition of an experimental group."""
        self._cur_group = None
    
    
    def _get_option_value(self, option, group=None, node=None):
        """For internal use. Get an option's value for a given group/node."""
        values = self._values.get(option, {})
        
        global_value = values[(None, None)]
        group_value = values.get((group, None), global_value)
        node_value = values.get((None, node), group_value)
        return values.get((group, node), node_value)
    
    
    def _set_option_value(self, option, value, group=None, node=None):
        """For internal use. Set an option's value for a given group/node."""
        self._values[option][(group, node)] = value
    
    
    class _Option(object):
        """A descriptor which provides access to the _values dictionary."""
        
        def __init__(self, option):
            self.option = option
        
        def __get__(self, obj, type=None):
            return obj._get_option_value(self.option, obj.cur_group)
        
        def __set__(self, obj, value):
            return obj._set_option_value(self.option, value, obj.cur_group)
        
    seed = _Option("seed")
    
    timestep = _Option("timestep")
    
    record_local_multicast = _Option("record_local_multicast")
    record_external_multicast = _Option("record_external_multicast")
    record_local_p2p = _Option("record_local_p2p")
    record_external_p2p = _Option("record_external_p2p")
    record_local_nearest_neighbour = _Option("record_local_nearest_neighbour")
    record_external_nearest_neighbour = _Option("record_external_nearest_neighbour")
    record_local_fixed_route = _Option("record_local_fixed_route")
    record_external_fixed_route = _Option("record_external_fixed_route")
    record_dropped_multicast = _Option("record_dropped_multicast")
    record_dropped_p2p = _Option("record_dropped_p2p")
    record_dropped_nearest_neighbour = _Option("record_dropped_nearest_neighbour")
    record_dropped_fixed_route = _Option("record_dropped_fixed_route")
    record_counter12 = _Option("record_counter12")
    record_counter13 = _Option("record_counter13")
    record_counter14 = _Option("record_counter14")
    record_counter15 = _Option("record_counter15")
    
    record_sent = _Option("record_sent")
    record_blocked = _Option("record_blocked")
    record_received = _Option("record_received")
    
    record_interval = _Option("record_interval")
    
    probability = _Option("probability")
    
    burst_period = _Option("burst_period")
    burst_duty = _Option("burst_duty")
    burst_phase = _Option("burst_phase")
    
    key = _Option("key")
    
    use_payload = _Option("use_payload")
    
    consume_packets = _Option("consume_packets")
