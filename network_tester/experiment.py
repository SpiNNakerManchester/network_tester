"""Top level experiment object."""

import pkg_resources

import time

from collections import OrderedDict

from six import iteritems, itervalues

from rig.machine import Cores

from rig.machine_control import MachineController

from rig.netlist import Net as RigNet

from rig.place_and_route import place, allocate, route

from rig.place_and_route.utils import \
    build_routing_tables, build_application_map

from rig.place_and_route.constraints import ReserveResourceConstraint

from network_tester.commands import Commands

from network_tester.results import Results

from network_tester.counters import Counters

from network_tester.errors import NetworkTesterError


class Group(object):
    """An experimental group."""
    
    def __init__(self, experiment, name):
        self._experiment = experiment
        self.name = name
        self.labels = OrderedDict()
    
    
    def add_label(self, name, value):
        """Set the value of a label column for this group.
        
        Parameters
        ----------
        name : str
            The name of the column
        value
            The value in the column for results in this group.
        """
        self.labels[name] = value
    
    
    def __enter__(self):
        """Define parameters for this experimental group."""
        if self._experiment._cur_group is not None:
            raise Exception("Cannot nest experimental groups.")
        self._experiment._cur_group = self
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        """Completes the definition of this experimental group."""
        self._experiment._cur_group = None
    
    
    def __repr__(self):
        return "<{} {}>".format(self.__class__.__name__, repr(self.name))
    
    
    @property
    def num_samples(self):
        """Returns the number of recorded samples which will be made during
        the running of this group.
        
        Note that this is in terms of *samples* and not in terms of the total
        number of counter values recorded since the values recorded varies from
        vertex to vertex.
        """
        duration = self._experiment._get_option_value("duration", self)
        timestep = self._experiment._get_option_value("timestep", self)
        record_interval = self._experiment._get_option_value("record_interval", self)
        
        run_steps = int(round(duration / timestep))
        interval_steps = int(round(record_interval / timestep))
        
        if interval_steps == 0:
            return 1
        else:
            return run_steps // interval_steps


class Vertex(object):
    """A vertex in the experiment.
    
    A vertex represents a single core running a traffic generator/consumer.
    """
    
    def __init__(self, experiment, name):
        self._experiment = experiment
        self.name = name
    
    
    class _Option(object):
        """A descriptor which provides access to the experiment's _values
        dictionary."""
        
        def __init__(self, option):
            self.option = option
        
        def __get__(self, obj, type=None):
            return obj._experiment._get_option_value(
                self.option, obj._experiment.cur_group, obj)
        
        def __set__(self, obj, value):
            return obj._experiment._set_option_value(
                self.option, value, obj._experiment.cur_group, obj)
    
    seed = _Option("seed")
    
    probability = _Option("probability")
    
    burst_period = _Option("burst_period")
    burst_duty = _Option("burst_duty")
    burst_phase = _Option("burst_phase")
    
    use_payload = _Option("use_payload")
    
    consume_packets = _Option("consume_packets")
    
    def __repr__(self):
        return "<{} {}>".format(self.__class__.__name__, repr(self.name))


class Net(RigNet):
    """A connection between vertices."""
    
    def __init__(self, experiment, name, *args, **kwargs):
        super(Net, self).__init__(*args, **kwargs)
        self._experiment = experiment
        self.name = name
    
    
    class _Option(object):
        """A descriptor which provides access to the experiment's _values
        dictionary."""
        
        def __init__(self, option):
            self.option = option
        
        def __get__(self, obj, type=None):
            return obj._experiment._get_option_value(
                self.option, obj._experiment.cur_group, obj)
        
        def __set__(self, obj, value):
            return obj._experiment._set_option_value(
                self.option, value, obj._experiment.cur_group, obj)
    
    probability = _Option("probability")
    
    use_payload = _Option("use_payload")
    
    
    def __repr__(self):
        return "<{} {}>".format(self.__class__.__name__, repr(self.name))


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
        # If a value can have per-node or per-group exceptions it is stored as
        # a dictionary with keys (group, vert_or_net) with the value being defined
        # as below. Otherwise, the value is just stored immediately in the
        # _values dictionary. The list below gives the order of priority for
        # definitions.
        # * (None, None) The global default
        # * (group, None) The default for a particular experimental group
        # * (None, vertex) The default for a particular vertex
        # * (None, net) The default for a particular net
        # * (group, vertex) The value for a particular vertex in a specific group
        # * (group, net) The value for a particular net in a specific group
        # {option: value or {(group, vert_or_net): value, ...}, ...}
        self._values = {
            "seed": {(None, None): None},
            "timestep": {(None, None): 0.001},
            "warmup": {(None, None): 1.0},
            "duration": {(None, None): 1.0},
            "cooldown": {(None, None): 0.1},
            "flush_time": {(None, None): 0.01},
            "record_interval": {(None, None): 0.0},
            "probability": {(None, None): 0.0},
            "burst_period": {(None, None): 0.0},
            "burst_duty": {(None, None): 0.0},
            "burst_phase": {(None, None): 0.0},
            "use_payload": {(None, None): False},
            "consume_packets": {(None, None): True},
        }
        
        # All counters are global-only options and default to False.
        for counter in Counters:
            self._values["record_{}".format(counter.name)] = False
    
    
    def new_vertex(self, name=None):
        """Return a new traffic generator/consumer vertex.
        
        Parameters
        ----------
        name
            An arbitrary name to give to the vertex. If not specified, vertices
            are named automatically with a number.
        """
        v = Vertex(self, name if name is not None else len(self._vertices))
        self._vertices.append(v)
        
        # Adding a new vertex invalidates any existing placement solution
        self.placements = None
        
        return v
    
    
    def new_net(self, *args, **kwargs):
        """Return a new net to connect a set of vertices.
        
        Parameters
        ----------
        name
            An arbitrary name to give to the net. If not specified, nets are
            named automatically with a number.
        """
        name = kwargs.pop("name", len(self._nets))
        n = Net(self, name, *args, **kwargs)
        
        # Adding a new net invalidates any routing solution.
        self.routes = None
        
        self._nets.append(n)
        return n
    
    
    def new_group(self, name=None):
        """Define a new experimental group.
        
        Parameters
        ----------
        name
            An arbitrary name to give to the group. If not specified, groups
            are named automatically with a number.
        """
        g = Group(self, name if name is not None else len(self._groups))
        self._groups.append(g)
        return g
    
    
    @property
    def cur_group(self):
        """Get the unique identifier of the experimental group currently being
        defined (or None if no group is being defined)."""
        
        return self._cur_group
    
    
    def _any_router_registers_recorded(self):
        """Are any router registers being recorded?"""
        return any(self._get_option_value("record_{}".format(counter.name))
                   for counter in Counters if counter.router_counter)
    
    
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
    
    
    def _construct_vertex_commands(self, vertex, source_nets, sink_nets,
                                   net_keys, records):
        """For internal use. Produce the Commands for a particular vertex.
        
        Parameters
        ----------
        vertex : :py:class:`.Vertex`
            The vertex to pack
        source_nets : [:py:class:`.Net`, ...]
            The nets which are sourced at this vertex.
        sink_nets : [:py:class:`.Net`, ...]
            The nets which are sunk at this vertex.
        net_keys : {:py:class:`.Net`: key, ...}
            A mapping from net to routing key.
        records : [counter, ...]
            The set of counters this vertex records
        """
        commands = Commands()
        
        # Set up the sources and sinks for the vertex
        commands.num(len(source_nets), len(sink_nets))
        for source_num, source_net in enumerate(source_nets):
            commands.source_key(source_num, net_keys[source_net])
        for sink_num, sink_net in enumerate(sink_nets):
            commands.sink_key(sink_num, net_keys[sink_net])
        
        # Generate commands for each experimental group
        for group in self._groups:
            # Set general parameters for the group
            commands.seed(self._get_option_value("seed", group))
            commands.timestep(self._get_option_value("timestep", group))
            commands.record_interval(self._get_option_value("record_interval", group))
            
            # Set vertex parameters for the group
            commands.burst(
                self._get_option_value("burst_period", group, vertex),
                self._get_option_value("burst_duty", group, vertex),
                self._get_option_value("burst_phase", group, vertex))
            
            # Set source parameters for the group
            for source_num, source_net in enumerate(source_nets):
                commands.probability(
                    source_num,
                    self._get_option_value("probability",
                                           group, 
                                           source_net))
                commands.payload(
                    source_num,
                    self._get_option_value("use_payload",
                                           group, 
                                           source_net))
            
            # Synchronise before running the group
            commands.barrier()
            
            # Turn off consumption at the last possible moment
            commands.consume(
                self._get_option_value("consume_packets", group, vertex))
            
            # warming up without recording data
            commands.record()
            commands.run(self._get_option_value("warmup", group))
            
            # Run the actual experiment and record results
            commands.record(*records)
            commands.run(self._get_option_value("duration", group))
            
            # Run without recording (briefly) after the experiment to allow
            # for clock skew between cores.
            commands.record()  # Record nothing during cooldown
            commands.run(self._get_option_value("cooldown", group))
            
            # Turn consumption back on after the run
            commands.consume(True)
            
            # Drain the network of any remaining packets
            commands.sleep(self._get_option_value("flush_time", group))
        
        # Finally, terminate
        commands.exit()
        
        return commands
    
    
    def _add_router_recording_vertices(self):
        """Adds extra vertices to chips with no other vertices to facilitate
        recording of router counter values, if necessary.
        
        Returns
        -------
        (vertices, router_recording_vertices, placements, allocations, routes)
            vertices is a list containing all vertices (including any added for
            router-recording purposes).
            
            router_recording_vertices is set of vertices which are responsible
            for recording router counters on their core.
            
            placements, allocations and routes are updated sets of placements
            accounting for any new router-recording vertices.
        """
        # Make a local list of vertices, placements and allocations in the
        # model. This may be extended with extra vertices for recording router
        # counter values.
        vertices = self._vertices.copy()
        placements = self.placements.copy()
        allocations = self.allocations.copy()
        routes = self.routes.copy()  # Not actually modified at present
        
        router_recording_vertices = set()
        
        # The set of chips (x, y) which have a core allocated to recording
        # router counters.
        recorded_chips = set()
        
        # If router information is being recorded, a vertex must be assigned on
        # every chip to recording router counters.
        if self._any_router_registers_recorded():
            # Assign the job of recording router values to an arbitrary vertex
            # on every chip which already has vertices on it.
            for vertex, placement in iteritems(self.placements):
                if placement not in recorded_chips:
                    router_recording_vertices.add(vertex)
                    recorded_chips.add(placement)
            
            # If there are chips without any vertices allocated, new
            # router-recording-only vertices must be added.
            for xy in self.machine:
                if xy not in recorded_chips:
                    # Create a new vertex for recording of router data only.
                    vertex = Vertex(self, "router recorder {}, {}".format(*xy))
                    router_recording_vertices.add(vertex)
                    recorded_chips.add(xy)
                    placements[vertex] = xy
                    allocations[vertex] = {Cores: slice(1, 2)}
                    vertices.append(vertex)
        
        return (vertices, router_recording_vertices,
                placements, allocations, routes)
    
    
    def _get_vertex_record_lookup(self, vertices, router_recording_vertices,
                                  placements,
                                  vertices_source_nets, vertices_sink_nets):
        """Generates a lookup from vertex to a list of counters that vertex
        records.
        
        Parameters
        ----------
        vertices : [:py:class:`.Vertex`, ...]
        router_recording_vertices : set([:py:class:`.Vertex`, ...])
        placements : {:py:class:`.Vertex`: (x, y), ...}
        vertices_source_nets : {:py:class:`.Vertex`: [net, ...], ...}
        vertices_sink_nets : {:py:class:`.Vertex`: [net, ...], ...}
        
        Returns
        -------
        vertices_records : {vertex: [(object, counter), ...], ...}
            For each vertex, gives an ordered-list of the things recorded by
            that vertex.
            
            For router counters, object will be a tuple (x, y) indicating which
            chip that counter is responsible for.
            
            For non-router counters, object will be the Net associated with the
            counter.
        """
        # Get the set of recorded counters for each vertex
        # {vertex, [counter, ...]}
        vertices_records = {}
        for vertex in vertices:
            records = []
            
            # Add any router-counters if this vertex is recording them
            if vertex in router_recording_vertices:
                xy = placements[vertex]
                for counter in Counters:
                    if (counter.router_counter and
                            self._get_option_value(
                                "record_{}".format(counter.name))):
                        records.append((xy, counter))
            
            # Add any source counters
            for counter in Counters:
                if (counter.source_counter and
                        self._get_option_value(
                            "record_{}".format(counter.name))):
                    for net in vertices_source_nets[vertex]:
                        records.append((net, counter))
            
            # Add any sink counters
            for counter in Counters:
                if (counter.sink_counter and
                        self._get_option_value(
                            "record_{}".format(counter.name))):
                    for net in vertices_sink_nets[vertex]:
                        records.append((net, counter))
            
            vertices_records[vertex] = records
        
        return vertices_records
    
    
    def run(self, app_id=0x42):
        """Run the experiment and return the results."""
        # Place and route the vertices (if required)
        self.place_and_route()
        
        # Add nodes to unused chips to record router counters (if necessary).
        (vertices, router_recording_vertices,
            placements, allocations, routes) = \
                self._add_router_recording_vertices()
        
        # Assign a unique routing key to each net
        net_keys = {net: num << 8
                    for num, net in enumerate(self._nets)}
        routing_tables = build_routing_tables(
            routes,
            {net: (key, 0xFFFFFF00) for net, key in iteritems(net_keys)})
        
        # Specify the appropriate binary for the network tester vertices.
        binary = pkg_resources.resource_filename(
            "network_tester", "binaries/network_tester.aplx")
        application_map = build_application_map(
            {vertex: binary for vertex in vertices},
            placements, allocations)
        
        # Get the set of source and sink nets for each vertex. Also sets an
        # explicit ordering of the sources/sinks within each.
        # {vertex: [source_or_sink, ...], ...}
        vertices_source_nets = {v: [] for v in vertices}
        vertices_sink_nets = {v: [] for v in vertices}
        for net in self._nets:
            vertices_source_nets[net.source].append(net)
            for sink in net.sinks:
                vertices_sink_nets[sink].append(net)
        
        vertices_records = self._get_vertex_record_lookup(
            vertices, router_recording_vertices, placements,
            vertices_source_nets, vertices_sink_nets)
        
        # Fill out the set of commands for each vertex
        vertices_commands = {
            vertex: self._construct_vertex_commands(
                vertex=vertex,
                source_nets=vertices_source_nets[vertex],
                sink_nets=vertices_sink_nets[vertex],
                net_keys=net_keys,
                records=[cntr for obj, cntr in vertices_records[vertex]])
            for vertex in vertices
        }
        
        # The data size for the results from each vertex
        total_num_samples = sum(g.num_samples for g in self._groups)
        vertices_result_size = {
            vertex: (
                # The error flag (one word)
                1 +
                # One word per recorded value per sample.
                (total_num_samples * len(vertices_records[vertex]))
            ) * 4
            for vertex in vertices}
        
        # The raw result data for each vertex.
        vertices_result_data = {}
        
        # Actually load and run the experiment on the machine.
        with self._mc.application(app_id):
            # Allocate the SDRAM required to allocate each vertex's SDRAM. This is
            # enough to fit the commands and also any recored results.
            samples_per_vertex = sum(g.num_samples for g in self._groups)
            vertices_sdram = {}
            for vertex in vertices:
                size = max(
                    # Size of commands (with length prefix)
                    vertices_commands[vertex].size,
                    # Size of results (plus the flags)
                    vertices_result_size[vertex],
                )
                x, y = placements[vertex]
                p = allocations[vertex][Cores].start
                vertices_sdram[vertex] = self._mc.sdram_alloc_as_filelike(
                    size, x=x, y=y, tag=p)
            
            # Load each vertex's commands
            for vertex, sdram in iteritems(vertices_sdram):
                sdram.write(vertices_commands[vertex].pack())
            
            # Load routing tables
            self._mc.load_routing_tables(routing_tables)
            
            # Load the application
            self._mc.load_application(application_map)
            
            # Run through each experimental group
            next_barrier = "sync0"
            for group in self._groups:
                # Reach the barrier before the run starts
                self._mc.wait_for_cores_to_reach_state(
                    next_barrier, len(vertices))
                self._mc.send_signal(next_barrier)
                next_barrier = "sync1" if next_barrier == "sync0" else "sync0"
                
                # Give the run time to complete
                warmup = self._get_option_value("warmup", group)
                duration = self._get_option_value("duration", group)
                cooldown = self._get_option_value("cooldown", group)
                flush_time = self._get_option_value("flush_time", group)
                time.sleep(warmup + duration + cooldown + flush_time)
            
            # Wait for all cores to exit after their final run
            self._mc.wait_for_cores_to_reach_state("exit", len(vertices))
            
            # Read recorded data back
            for vertex, sdram in iteritems(vertices_sdram):
                sdram.seek(0)
                vertices_result_data[vertex] = \
                    sdram.read(vertices_result_size[vertex])
        
        # Process read results
        results = Results(self, self._vertices, self._nets, vertices_records,
                          router_recording_vertices, placements,
                          vertices_result_data, self._groups)
        if results.errors:
            raise NetworkTesterError(results)
        else:
            return results
    
    
    def _get_option_value(self, option, group=None, vert_or_net=None):
        """For internal use. Get an option's value for a given
        group/vertex/net."""
        
        values = self._values[option]
        if isinstance(values, dict):
            if isinstance(vert_or_net, Net):
                vertex = vert_or_net.source
                net = vert_or_net
            else:
                vertex = vert_or_net
            
            global_value = values[(None, None)]
            group_value = values.get((group, None), global_value)
            vertex_value = values.get((None, vertex), group_value)
            group_vertex_value = values.get((group, vertex), vertex_value)
            
            if isinstance(vert_or_net, Net):
                net_value = values.get((None, net), group_vertex_value)
                group_net_value = values.get((group, net), net_value)
                return group_net_value
            else:
                return group_vertex_value
        else:
            return values
    
    
    def _set_option_value(self, option, value, group=None, vert_or_net=None):
        """For internal use. Set an option's value for a given group/vertex/net."""
        values = self._values[option]
        if isinstance(values, dict):
            values[(group, vert_or_net)] = value
        else:
            if group is not None or vert_or_net is not None:
                raise ValueError(
                    "Cannot set {} option on a group-by-group, "
                    "vertex-by-vertex or net-by-net basis.".format(option))
            self._values[option] = value
    
    
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
