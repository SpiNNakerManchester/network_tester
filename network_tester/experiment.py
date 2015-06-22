"""Top level experiment object."""

from collections import OrderedDict

from rig.machine import Cores

from rig.machine_control import MachineController

from rig.netlist import Net

from rig.place_and_route import place, allocate, route

from rig.place_and_route.constraints import ReserveResourceConstraint


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


class Vertex(object):
    """A vertex in the experiment.
    
    A vertex represents a single core running a traffic generator/consumer.
    """
    
    def __init__(self, experiment):
        self._experiment = experiment
    
    
    class _Option(object):
        """A descriptor which provides access to the experiment's _values
        dictionary."""
        
        def __init__(self, option):
            self.option = option
        
        def __get__(self, obj, type=None):
            return obj._experiment._get_option_value(
                self.option, obj._experiment.cur_group, self)
        
        def __set__(self, obj, value):
            return obj._experiment._set_option_value(
                self.option, value, obj._experiment.cur_group, self)
    
    seed = _Option("seed")
    
    record_sent = _Option("record_sent")
    record_blocked = _Option("record_blocked")
    record_received = _Option("record_received")
    
    probability = _Option("probability")
    
    burst_period = _Option("burst_period")
    burst_duty = _Option("burst_duty")
    burst_phase = _Option("burst_phase")
    
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
            self._mc = MachineController(hostname_or_machine_controller)
        else:
            self._mc = hostname_or_machine_controller
        
        # A cached reference to the SpiNNaker machine the experiment will run
        # in. To be accessed via .machine which automatically fetches the
        # machine the first time it is requested.
        self._machine = None
        
        # A set of placements, allocations and routes for the
        # traffic-generating/consuming vertices.
        self._placements = None
        self._allocations = None
        self._routes = None
        
        # The experimental group currently being defined
        self._cur_group = None
        
        # A list of experimental groups which have been defined
        self._groups = []
        
        # A list of vertices in the experiment
        self._vertices = []
        
        # A list of nets in the experiment
        self._nets = []
        
        # Holds the value of every option along with any special cases.
        # * The global default value has group == vertex == None.
        # * The value for a group has group==group and vertex==None.
        # * The value for a vertex has vertex==vertex and group==None.
        # * The value for a vertex and group has vertex==vertex and group==group.
        # {option: {(group, vertex): value, ...}, ...}
        self._values = {
            "seed": {(None, None): None},
            "timestep": {(None, None): 0.001},
            "warmup": {(None, None): 1.0},
            "duration": {(None, None): 1.0},
            "cooldown": {(None, None): None},
            "flush_time": {(None, None): 0.001},
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
            "use_payload": {(None, None): False},
            "consume_packets": {(None, None): True},
        }
    
    
    def new_vertex(self):
        """Return a new traffic generator/consumer vertex."""
        v = Vertex(self)
        self._vertices.append(v)
        
        # Adding a new vertex invalidates any existing placement solution
        self.placements = None
        
        return v
    
    
    def new_net(self, *args, **kwargs):
        """Return a new net to connect a set of vertices."""
        n = Net(*args, **kwargs)
        
        # Adding a new net invalidates any routing solution.
        self.routes = None
        
        self._nets.append(n)
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
    
    
    def _any_router_registers_recorded(self, group=None):
        """Are any router registers being recorded?"""
        return any(self._get_option_value(option, group)
                   for option in [
                       "record_local_multicast",
                       "record_external_multicast",
                       "record_local_p2p",
                       "record_external_p2p",
                       "record_local_nearest_neighbour",
                       "record_external_nearest_neighbour",
                       "record_local_fixed_route",
                       "record_external_fixed_route",
                       "record_dropped_multicast",
                       "record_dropped_p2p",
                       "record_dropped_nearest_neighbour",
                       "record_dropped_fixed_route",
                       "record_counter12",
                       "record_counter13",
                       "record_counter14",
                       "record_counter15",
                   ])
    
    
    @property
    def machine(self):
        if self._machine is None:
            self._machine = self._mc.get_machine()
        return self._machine
    
    @machine.setter
    def machine(self, value):
        self._machine = value
    
    
    @property
    def placements(self):
        return self._placements
    
    @placements.setter
    def placements(self, value):
        self._placements = value
        self.allocation = None
        self.routes = None
    
    @property
    def allocations(self):
        return self._allocations
    
    @allocations.setter
    def allocations(self, value):
        self._allocations = value
        self.routes = None
    
    @property
    def routes(self):
        return self._routes
    
    @routes.setter
    def routes(self, value):
        self._routes = value
    
    
    def place_and_route(self,
                        constraints=[],
                        place=place, place_kwargs={},
                        allocate=allocate, allocate_kwargs={},
                        route=route, route_kwargs={}):
        """Place and route the current experiment, as required.
        
        This is called automatically by :py:meth:`.run` if required. If
        placement, allocation or routing have already been carried out (e.g.
        by setting the placements, allocations or routes attributes), they will
        not be carried out again. Set these to None to force re-running any of
        these algorithms.
        
        Parameters
        ----------
        constraints : [constraint, ...]
            A list of additional constraints to apply. A
            :py:class:`rig.place_and_route.constraints.ReserveResourceConstraint`
            will be applied to reserve the monitor processor on top of this
            constraint.
        place : placer
            A Rig-API complaint placement algorithm.
        place_kwargs : dict
            Additional algorithm-specific keyword arguments to supply to the
            placer.
        allocate : allocator
            A Rig-API complaint allocation algorithm.
        allocate_kwargs : dict
            Additional algorithm-specific keyword arguments to supply to the
            allocator.
        route : router
            A Rig-API complaint route algorithm.
        route_kwargs : dict
            Additional algorithm-specific keyword arguments to supply to the
            router.
        """
        # Each traffic generator consumes a core and a negligible amount of
        # memory.
        vertices_resources = {vertex: {Cores: 1} for vertex in
                              self._vertices}
        
        # Reserve the monitor processor for each chip
        constraints += [ReserveResourceConstraint(Cores, slice(0, 1))]
        
        if self.placements is None:
            self.placements = place(vertices_resources=vertices_resources,
                                    nets=self._nets,
                                    machine=self.machine,
                                    constraints=constraints,
                                    **place_kwargs)
            self.allocations = None
            self.routes = None
        
        if self.allocations is None:
            self.allocations = allocate(vertices_resources=vertices_resources,
                                        nets=self._nets,
                                        machine=self.machine,
                                        constraints=constraints,
                                        placements=self.placements,
                                        **allocate_kwargs)
            self.routes = None
        
        if self.routes is None:
            self.routes = route(vertices_resources=vertices_resources,
                                nets=self._nets,
                                machine=self.machine,
                                constraints=constraints,
                                placements=self.placements,
                                allocations=self.allocations,
                                **allocate_kwargs)
    
    
    def run(self):
        """Run the experiment and return the results."""
        self.place_and_route()
    
    
    def _get_option_value(self, option, group=None, vertex=None):
        """For internal use. Get an option's value for a given group/vertex."""
        values = self._values.get(option, {})
        
        global_value = values[(None, None)]
        group_value = values.get((group, None), global_value)
        vertex_value = values.get((None, vertex), group_value)
        return values.get((group, vertex), vertex_value)
    
    
    def _set_option_value(self, option, value, group=None, vertex=None):
        """For internal use. Set an option's value for a given group/vertex."""
        self._values[option][(group, vertex)] = value
    
    
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
    
    warmup = _Option("warmup")
    duration = _Option("duration")
    cooldown = _Option("cooldown")
    flush_time = _Option("flush_time")
    
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
    
    use_payload = _Option("use_payload")
    
    consume_packets = _Option("consume_packets")
