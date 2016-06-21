"""Top level experiment object."""

import pkg_resources

import time

import logging

import warnings

from collections import OrderedDict

from six import iteritems, itervalues, integer_types

from rig.place_and_route import Cores

from rig.machine_control import MachineController

from rig.netlist import Net as RigNet

from rig.place_and_route import place, allocate, route

from rig.place_and_route.utils import \
    build_machine, build_core_constraints, \
    build_application_map

from rig.routing_table import \
    routing_tree_to_tables, build_routing_table_target_lengths, \
    minimise_tables

from rig.place_and_route.constraints import \
    LocationConstraint

from network_tester.commands import Commands

from network_tester.results import Results

from network_tester.counters import Counters

from network_tester.errors import NetworkTesterError


"""
This logger is used to report the progress of the Experiment.
"""
logger = logging.getLogger(__name__)


class Experiment(object):
    """Defines a network experiment to be run on a SpiNNaker machine.

    An experiment consists of a defined set of SpiNNaker application cores
    (:py:meth:`.new_core`) between which traffic flows (:py:meth:`.new_flow`).

    An experiment is broken up into 'groups' (:py:meth:`.new_group`), during
    which the traffic generators produce packets according to a specified
    traffic pattern. Within each group, metrics, such as packet counts, may be
    recorded. Though the placement of cores and the routing of traffic flows is
    fixed throughout an experiment, the rate and pattern of the generated
    traffic flows can be varied between groups allowing, for example, different
    traffic patterns to be tested.

    When the experiment is :py:meth:`.run`, cores will be loaded with traffic
    generators and the routing tables initialised. When the experiment
    completes, recorded results are read back ready for analysis.
    """

    def __init__(self, hostname_or_machine_controller):
        """Create a new network experiment on a particular SpiNNaker machine.

        Typical usage::

            >>> import sys
            >>> from network_tester import Experiment
            >>> e = Experiment(sys.argv[1])  # Takes hostname as a CLI argument

        The experimental parameters can be set by setting attributes of the
        :py:class:`Experiment` instance like so::

            >>> e = Experiment(...)
            >>> # Set the probability of a packet being generated at the source
            >>> # of each flow every timestep
            >>> e.probability = 1.0

        Parameters
        ----------
        hostname_or_machine_controller : \
                str or :py:class:`rig.machine_control.MachineController`
            The hostname or :py:class:`~rig.machine_control.MachineController`
            of a SpiNNaker machine to run the experiment on.
        """
        if isinstance(hostname_or_machine_controller, str):
            self._mc = MachineController(hostname_or_machine_controller)
        else:
            self._mc = hostname_or_machine_controller

        # A cached reference to the SpiNNaker system info for the machine the
        # experiment will run on. To be accessed via .system_info which
        # automatically fetches the info the first time it is requested.
        self._system_info = None

        # A set of placements, allocations and routes for the
        # traffic-generating/consuming cores.
        self._placements = None
        self._allocations = None
        self._routes = None

        # The experimental group currently being defined. Set and cleared on
        # entry and exit of Group context-managers.
        self._cur_group = None

        # A list of experimental groups which have been defined
        self._groups = []

        # A list of cores in the experiment, in order of creation (this order
        # is preserved in result listings).
        self._cores = []

        # A list of flows in the experiment, in order of creation (this order
        # is preserved in result listings)
        self._flows = []

        # A set of cores added (when required) immediately before placement for
        # the purposes of packet reinjection, one per core. These cores are
        # represented by a _ReinjectionCore.
        self._reinjection_cores = None

        # A set of cores used for the purposes of recording router values. Some
        # of these may not be present in self._cores and are created just after
        # placement in to ensure each chip has at least one core to record
        # router values.  These cores are represented by a Core object.
        self._router_recording_cores = None

        # Holds the value of every option along with any special cases.
        # If a value can have per-node or per-group exceptions it is stored as
        # a dictionary with keys (group, core_or_flow) with the value being
        # defined as below. Otherwise, the value is just stored immediately in
        # the _values dictionary. The list below gives the order of priority
        # for definitions.
        # * (None, None) The global default
        # * (group, None) The default for a particular experimental group
        # * (None, core) The default for a particular core
        # * (None, flow) The default for a particular flow
        # * (group, core) The value for a particular core in a specific group
        # * (group, flow) The value for a particular flow in a specific group
        # {option: value or {(group, core_or_flow): value, ...}, ...}
        self._values = {
            "seed": {(None, None): None},
            "timestep": {(None, None): 0.001},
            "warmup": {(None, None): 0.0},
            "duration": {(None, None): 1.0},
            "cooldown": {(None, None): 0.0},
            "flush_time": {(None, None): 0.01},
            "record_interval": {(None, None): 0.0},
            "probability": {(None, None): 1.0},
            "packets_per_timestep": {(None, None): 1},
            "num_retries": {(None, None): 0},
            "burst_period": {(None, None): 0.0},
            "burst_duty": {(None, None): 0.0},
            "burst_phase": {(None, None): 0.0},
            "use_payload": {(None, None): False},
            "consume_packets": {(None, None): True},
            "router_timeout": {(None, None): None},
            "reinject_packets": {(None, None): False},
        }

        # All counters are global-only options and default to False.
        for counter in Counters:
            if not counter.permanent_counter:
                self._values["record_{}".format(counter.name)] = False

    def new_core(self, chip_x=None, chip_y=None, name=None):
        """Create a new :py:class:`Core`.

        A SpiNNaker application core which can source and sink a number of
        traffic :py:meth:`flows<new_flow>`.

        Example::

            >>> # Create three cores, the first two are placed on chip (0, 0)
            >>> # and final core will be placed automatically onto some
            >>> # available core in the system.
            >>> c0 = e.new_core(0, 0)
            >>> c1 = e.new_core(0, 0)
            >>> c2 = e.new_core()

        The experimental parameters for each core can also be specified
        individually if desired::

            >>> # Traffice flows sourced at core c2 will transmit with 50%
            >>> # probability each timestep
            >>> c2.probability = 0.5

        :ref:`Renamed from new_vertex in v0.2.0. <v0_1_x_upgrade>`

        Parameters
        ----------
        chip_x : int or None
        chip_y : int or None
            If both ``chip_x`` and ``chip_y`` are given, this core will be
            placed on the chip with the specified coordinates. Note: It is not
            possible to place more cores on a specific chip than the chip has
            available.

            If both ``chip_x`` and ``chip_y`` are None (the default), the core
            will be automatically placed on some available chip (see
            :py:meth:`network_tester.Experiment.run`).

            Note that either both must be an integer or both must be None.
        name
            *Optional.* A name for the core. If not specified the core will be
            given a number as its name. This name will be used in results
            tables.

        Returns
        -------
        :py:class:`Core`
            An object representing the core.
        """
        if chip_x is not None and chip_y is not None:
            chip = (chip_x, chip_y)
        elif chip_x is None and chip_y is None:
            chip = None
        else:
            raise ValueError(
                "Either both or neither of chip_x and chip_y may be None.")

        c = Core(self,
                 name if name is not None else len(self._cores),
                 chip)
        self._cores.append(c)

        return c

    def new_vertex(self, name=None, chip=None):
        """Warn users of old code of API incompatibility."""
        raise APIChangedError(
            "e.new_vertex(name, (x, y)) is now "
            "e.new_core(x, y, name)",
            (0, 2, 0)
        )

    def new_flow(self, source, sinks, weight=1.0, name=None):
        """Create a new flow.

        A flow of SpiNNaker packets from one source core to many sink cores.

        For example::

            >>> # A flow with c0 as a source and c1 as a sink.
            >>> f0 = e.new_flow(c0, c1)

            >>> # Another flow with c0 as a source and both c1 and c2 as sinks.
            >>> f1 = e.new_flow(c0, [c1, c2])

        The experimental parameters for each flow can be overridden
        individually if desired. This will take precedence over any values set
        for the source core of the flow.

        For example::

            >>> # Flow f0 will generate a packet in 80% of timesteps
            >>> f0.probability = 0.8

        :ref:`Renamed from new_net in v0.2.0. <v0_1_x_upgrade>`

        Parameters
        ----------
        source : :py:class:`Core`
            The source :py:class:`Core` of the flow. A stream of packets will
            be generated by this core and sent to all sinks.

            Only :py:class:`Core` objects created by this
            :py:class:`Experiment` may be used.
        sinks : :py:class:`Core` or [:py:class:`Core`, ...]
            The sink :py:class:`Core` or list of sink cores for the flow.

            Only :py:class:`Core` objects created by this
            :py:class:`Experiment` may be used.
        weight : float
            *Optional.* A hint for the automatic place and route algorithms
            indicating the relative amount of traffic that may flow through
            this Flow. This number is not used by the traffic generator.
        name
            *Optional.* A name for the flow. If not specified the flow will be
            given a number as its name. This name will be used in results
            tables.

        Returns
        -------
        :py:class:`Flow`
            An object representing the flow.
        """
        if name is None:
            name = len(self._flows)
        f = Flow(self, name, source, sinks, weight)

        self._flows.append(f)
        return f

    def new_net(self, *args, **kwargs):
        """Warn users of old code of API incompatibility."""
        raise APIChangedError(
            "e.new_net(...) is now "
            "e.new_flow(...)",
            (0, 2, 0)
        )

    def new_group(self, name=None):
        """Define a new experimental group.

        The experiment can be divided up into groups where the traffic pattern
        generated (but not the structure of connectivity) varies for each
        group. Results are recorded separately for each group and the network
        is drained of packets between groups.

        The returned :py:class:`Group` object can be used as a context manager
        within which experimental parameters specific to that group may be set,
        including per-core and per-flow parameters. Note that parameters set
        globally for the experiment in particular group do not take precedence
        over per-core or per-flow parameter settings.

        For example::

            >>> with e.new_group():
            ...     # Overrides default probability of sending a packet within
            ...     # the group.
            ...     e.probability = 0.5
            ...     # Overrides the probability for c2 within the group
            ...     c2.probability = 0.25
            ...     # Overrides the probability for f0 within the group
            ...     f0.probability = 0.4

        Parameters
        ----------
        name
            *Optional.* A name for the group. If not specified the group will
            be given a number as its name. This name will be used in results
            tables.

        Returns
        -------
        :py:class:`Group`
            An object representing the group.
        """
        g = Group(self, name if name is not None else len(self._groups))
        self._groups.append(g)
        return g

    def run(self, app_id=0xDB, create_group_if_none_exist=True,
            ignore_deadline_errors=False,
            constraints=None,
            place=place, place_kwargs={},
            allocate=allocate, allocate_kwargs={},
            route=route, route_kwargs={},
            before_load=None, before_group=None, before_read_results=None):
        """Run the experiment on SpiNNaker and return the results.

        Before the experiment is started, any cores whose location was not
        specified are placed automatically on suitable chips and routes are
        generated between them. If fine-grained control is required the
        ``place``, ``allocate`` and ``route`` arguments allow user-defined
        :py:func:`placement <rig.place_and_route.place>`, :py:func:`allocation
        <rig.place_and_route.allocate>` and :py:func:`routing
        <rig.place_and_route.route>` algorithms to be used. The result of these
        processes can be found in the :py:attr:`placements`,
        :py:attr:`allocations` and  :py:attr:`routes` respectively at any time
        after the ``before_load`` callback has been called.

        Following placement, the experimental parameters are loaded onto the
        machine and each experimental group is executed in turn. Results are
        recorded by the machine and are read back at the end of the experiment.

        .. warning::
            Though a global synchronisation barrier is used between the
            execution of each group, the timers in each core may drift out of
            sync during each group's execution. Further, the barrier
            synchronisation does not give any guarantees about how
            closely-synchronised the timers will be at the start of each run.

        :ref:`The place_and_route method was removed in v0.2.0 and its
        functionality merged into this method. <v0_1_x_upgrade>`

        Parameters
        ----------
        app_id : int
            *Optional.* The SpiNNaker application ID to use for the experiment.
        create_group_if_none_exist : bool
            *Optional.* If True (the default), a single group will be
            automatically created if none have been defined with
            :py:meth:`.new_group`. This is the most sensible behaviour for most
            applications.

            If you *really* want to run an experiment with no experimental
            groups (where no traffic will ever be generated and no results
            recorded), you can set this option to False.
        ignore_deadline_errors : bool
            If True, any realtime deadline-missed errors will no longer cause
            this method to raise an exception. Other errors will still cause an
            exception to be raised.

            This option is useful when running experiments which involve
            over-saturating packet sinks or the network in some experimental
            groups.
        constraints : [constraint, ...]
            A list of additional place-and-route constraints to apply.
            In additon to the constraints supplied via this argument, a
            :py:class:`rig.place_and_route.constraints.ReserveResourceConstraint`
            will be added to reserve the monitor processor on every chip and a
            :py:class:`rig.place_and_route.constraints.LocationConstraint` is
            also added for all cores whose chip was explicitly specified (and
            for other special purpose cores such as packet reinjection cores
            and router-register recording cores).
        place : placer
            A :py:func:`Rig-API complaint <rig.place_and_route.place>`
            placement algorithm. This will be used to automatically place any
            cores whose location was not specified.
        place_kwargs : dict
            Additional algorithm-specific keyword arguments to supply to the
            placer.
        allocate : allocator
            A :py:func:`Rig-API complaint <rig.place_and_route.allocate>`
            allocation algorithm.
        allocate_kwargs : dict
            Additional algorithm-specific keyword arguments to supply to the
            allocator.
        route : router
            A :py:func:`Rig-API complaint <rig.place_and_route.route>` route
            algorithm. Used to route all flows in the experiment.
        route_kwargs : dict
            Additional algorithm-specific keyword arguments to supply to the
            router.
        before_load : function or None
            If not None, this function is called before the network tester
            application is loaded onto the machine and after place-and-route
            has been completed. It is called with the :py:class:`Experiment`
            object as its argument. The function may block to postpone the
            loading process as required.
        before_group : function or None
            If not None, this function is called before each experimental group
            is run on the machine. It is called with the :py:class:`Experiment`
            object and :py:class:`Group` as its argument. The function may
            block to postpone the execution of each group as required.
        before_read_results : function or None
            If not None, this function is called after all experimental groups
            have run and before the results are read back from the machine. It
            is called with the :py:class:`Experiment` object as its argument.
            The function may block to postpone the reading of results as
            required.

        Returns
        -------
        :py:class:`Results`
            If no cores reported errors, the experimental results are returned.
            See the :py:class:`Results` object for details.

        Raises
        ------
        NetworkTesterError
            A :py:exc:`NetworkTesterError` is raised if any cores reported an
            error. The most common error is likely to be a 'deadline missed'
            error as a result of the experimental timestep being too short or
            the load on some cores too high in extreme circumstances. Other
            types of error indicate far more severe problems and are probably a
            bug in 'Network Tester'.

            Any results recorded during the run will be included in the
            ``results`` attribute of the exception. See the :py:class:`Results`
            object for details.
        """
        # Sensible default: Create a single experimental group if none defined.
        if create_group_if_none_exist and len(self._groups) == 0:
            self.new_group()

        # Place and route the cores, adding router recording cores and packet
        # reinjection cores.
        self._place_and_route(
            constraints,
            place, place_kwargs,
            allocate, allocate_kwargs,
            route, route_kwargs
        )

        # Get a set of all cores running the network tester binary
        nt_cores = set(self._cores).union(self._router_recording_cores)

        # Assign a unique routing key to each flow
        flow_keys = {flow: num << 8
                     for num, flow in enumerate(self._flows)}

        # Build routing tables from the generated routes
        routing_tables = routing_tree_to_tables(
            self._routes,
            {flow: (key, 0xFFFFFF00) for flow, key in iteritems(flow_keys)})

        # Minimise the routing tables, if required
        target_lengths = build_routing_table_target_lengths(self.system_info)
        routing_tables = minimise_tables(routing_tables, target_lengths)

        network_tester_binary = pkg_resources.resource_filename(
            "network_tester", "binaries/network_tester.aplx")
        reinjector_binary = pkg_resources.resource_filename(
            "network_tester", "binaries/reinjector.aplx")

        # Specify the appropriate binary for all cores.
        nt_application_map = build_application_map(
            {core: network_tester_binary for core in nt_cores},
            self._placements, self._allocations)
        reinjector_application_map = build_application_map(
            {core: reinjector_binary for core in self._reinjection_cores},
            self._placements, self._allocations)

        # Get the set of source and sink flows for each core. Also sets an
        # explicit ordering of the sources/sinks within each.
        # {core: [source_or_sink, ...], ...}
        cores_source_flows = {c: [] for c in nt_cores}
        cores_sink_flows = {c: [] for c in nt_cores}
        for flow in self._flows:
            cores_source_flows[flow.source].append(flow)
            for sink in flow.sinks:
                cores_sink_flows[sink].append(flow)

        # Sort all sink lists by key to allow binary-searching in the
        # network_tester application
        for sink_flows in itervalues(cores_sink_flows):
            sink_flows.sort(key=(lambda f: flow_keys[f]))

        cores_records = self._get_core_record_lookup(
            nt_cores, cores_source_flows, cores_sink_flows)

        # Fill out the set of commands for each core
        logger.info("Generating SpiNNaker configuration data...")
        cores_commands = {
            core: self._construct_core_commands(
                core=core,
                source_flows=cores_source_flows[core],
                sink_flows=cores_sink_flows[core],
                flow_keys=flow_keys,
                records=[cntr for obj, cntr in cores_records[core]],
                router_access_core=core in self._router_recording_cores)
            for core in nt_cores
        }

        # The data size for the results from each core
        total_num_samples = sum(g.num_samples for g in self._groups)
        cores_result_size = {
            core: (
                # The error flag (one word)
                1 +
                # One word per recorded value per sample.
                (total_num_samples * len(cores_records[core]))
            ) * 4
            for core in nt_cores}

        # Call the user-defined pre-load callback...
        if before_load is not None:
            before_load(self)

        cores_result_data = {}

        # Actually load and run the experiment on the machine.
        with self._mc.application(app_id):
            # Allocate SDRAM. This is enough to fit the commands and also any
            # recored results.
            cores_sdram = {}
            logger.info("Allocating SDRAM...")
            for core in nt_cores:
                size = max(
                    # Size of commands (with length prefix)
                    cores_commands[core].size,
                    # Size of results (plus the flags)
                    cores_result_size[core],
                )
                x, y = self._placements[core]
                p = self._allocations[core][Cores].start
                cores_sdram[core] = self._mc.sdram_alloc_as_filelike(
                    size, x=x, y=y, tag=p)

            # Load each core's commands
            logger.info("Loading {} bytes of commands...".format(
                sum(c.size for c in itervalues(cores_commands))))
            for core, sdram in iteritems(cores_sdram):
                sdram.write(cores_commands[core].pack())

            # Load routing tables
            logger.info("Loading routing tables...")
            self._mc.load_routing_tables(routing_tables)

            # Load the packet-reinjection application if used. This must be
            # completed before the main application since it creates a tagged
            # memory allocation.
            if reinjector_application_map:
                logger.info("Loading packet-reinjection application...")
                self._mc.load_application(reinjector_application_map)

            # Load the application
            logger.info("Loading network tester application "
                        "on to {} cores...".format(len(nt_cores)))
            self._mc.load_application(nt_application_map)

            # Run through each experimental group
            next_barrier = "sync0"
            for group_num, group in enumerate(self._groups):
                # Reach the barrier before the run starts
                logger.info("Waiting for barrier...")
                num_at_barrier = self._mc.wait_for_cores_to_reach_state(
                    next_barrier, len(nt_cores), timeout=10.0)
                assert num_at_barrier == len(nt_cores), \
                    "Not all cores reached the barrier " \
                    "before {}.".format(group)

                # Run the user-defined pre-group callback
                if before_group is not None:
                    before_group(self, group)

                # Start the group running
                self._mc.send_signal(next_barrier)
                next_barrier = "sync1" if next_barrier == "sync0" else "sync0"

                # Give the run time to complete
                warmup = self._get_option_value("warmup", group)
                duration = self._get_option_value("duration", group)
                cooldown = self._get_option_value("cooldown", group)
                flush_time = self._get_option_value("flush_time", group)
                total_time = warmup + duration + cooldown + flush_time

                logger.info(
                    "Running group {} ({} of {}) for {} seconds...".format(
                        group.name, group_num + 1, len(self._groups),
                        total_time))
                time.sleep(total_time)

            # Wait for all cores to exit after their final run
            logger.info("Waiting for barrier...")
            num_at_barrier = self._mc.wait_for_cores_to_reach_state(
                "exit", len(nt_cores), timeout=10.0)
            assert num_at_barrier == len(nt_cores), \
                "Not all cores reached the final barrier."

            # Run the user-defined pre-result collection callback
            if before_read_results is not None:
                before_read_results(self)

            # Read recorded data back
            logger.info("Reading back {} bytes of results...".format(
                sum(itervalues(cores_result_size))))
            for core, sdram in iteritems(cores_sdram):
                sdram.seek(0)
                cores_result_data[core] = \
                    sdram.read(cores_result_size[core])

        # Process read results
        results = Results(self, self._cores, self._flows, cores_records,
                          self._router_recording_cores,
                          self._placements, self._routes,
                          cores_result_data, self._groups)
        if any(not e.is_deadline if ignore_deadline_errors else True
               for e in results.errors):
            logger.error(
                "Experiment completed with errors: {}".format(results.errors))
            raise NetworkTesterError(results)
        else:
            logger.info("Experiment completed successfully")
            return results

    def _place_and_route(self,
                         constraints=None,
                         place=place, place_kwargs={},
                         allocate=allocate, allocate_kwargs={},
                         route=route, route_kwargs={}):
        """Place and route the cores and flows in the current experiment.

        If extra control is required over placement and routing of cores and
        flows in an experiment, this method allows additional constraints and
        custom placement, allocation and routing options and algorithms to be
        used.

        The result of placement, allocation and routing can be found in
        :py:attr:`placements`, :py:attr:`allocations` and  :py:attr:`routes`
        respectively.

        This method is called by :py:meth:`.run` if place-and-route has not
        already been called manually. Note that a place-and-route solution is
        invalidated by creating cores and flows and by modifying experimental
        parameters. This function, thus, should be used immediately before
        calling :py:meth:`.run`.

        Parameters
        ----------
        constraints : [constraint, ...]
            A list of additional constraints to apply. A
            :py:class:`rig.place_and_route.constraints.ReserveResourceConstraint`
            will be added to reserve the monitor processor. A
            :py:class:`rig.place_and_route.constraints.LocationConstraint` is
            also added for all cores whose chip was explicitly specified.
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
        vertices_resources = {core: {Cores: 1} for core in
                              self._cores}

        # Generate a Machine object and reserve all in-use cores
        machine = build_machine(self.system_info)
        core_constraints = build_core_constraints(self.system_info)

        constraints = constraints or []
        constraints += core_constraints

        # Force the placements of cores whose positions are pre-defined
        constraints.extend(
            LocationConstraint(core, core.chip)
            for core in self._cores
            if core.chip is not None
        )

        # Add reinjection cores, one per chip, if required
        self._reinjection_cores = set()
        if self._reinjection_used():
            for chip in self.system_info:
                core = _ReinjectionCore()
                vertices_resources[core] = {Cores: 1}
                self._reinjection_cores.add(core)
                constraints += [LocationConstraint(core, chip)]

        # Perform placement as required
        logger.info("Placing cores...")
        self._placements = place(vertices_resources=vertices_resources,
                                 nets=self._flows,
                                 machine=machine,
                                 constraints=constraints,
                                 **place_kwargs)

        # Add router-recording cores to any chips which don't have any cores on
        # them.
        self._router_recording_cores = set()
        if self._any_router_registers_used():
            # A list of chips with a core on it for recording purposes.
            recorded_chips = set()

            # Assign the job of recording/setting router registers to an
            # arbitrary core on every chip which already has cores on it.
            for core, placement in iteritems(self._placements):
                if placement not in recorded_chips and isinstance(core, Core):
                    self._router_recording_cores.add(core)
                    recorded_chips.add(placement)

            # Create a new core to record router values on every chip without a
            # core already available for recording.
            num_extra_cores = 0
            for chip in self.system_info:
                if chip not in recorded_chips:
                    core = Core(self,
                                "router recording core ({}, {})".format(*chip),
                                chip)
                    vertices_resources[core] = {Cores: 1}
                    self._router_recording_cores.add(core)
                    self._placements[core] = core.chip
                    num_extra_cores += 1
            logger.info(
                "{} cores added to record router registers".format(
                    num_extra_cores))

        # Perform allocation
        logger.info("Allocating cores...")
        self._allocations = allocate(vertices_resources=vertices_resources,
                                     nets=self._flows,
                                     machine=machine,
                                     constraints=constraints,
                                     placements=self._placements,
                                     **allocate_kwargs)

        # Perform routing
        logger.info("Routing flows...")
        self._routes = route(vertices_resources=vertices_resources,
                             nets=self._flows,
                             machine=machine,
                             constraints=constraints,
                             placements=self._placements,
                             allocations=self._allocations,
                             **allocate_kwargs)

    def place_and_route(self, *args, **kwargs):
        """Warn users of old code of API incompatibility."""
        raise APIChangedError(
            "e.place_and_route(...) has been merged into"
            "e.run(...)",
            (0, 2, 0)
        )

    @property
    def placements(self):
        """A dictionary {:py:class:`Core`: (x, y), ...}, or None.

        The placements selected for each core, set after calling
        :py:meth:`.run`.

        See also :py:func:`rig.place_and_route.place`.

        :ref:`This attribute was made read-only in v0.2.0. <v0_1_x_upgrade>`
        """
        if self._placements is None:
            raise AttributeError("Placements not available until "
                                 "after calling Experiment.run()")
        else:
            # Filter out cores which were not created by the user.
            return {core: chip for core, chip in iteritems(self._placements)
                    if core in self._cores}

    @placements.setter
    def placements(self, *args, **kwargs):
        """Warn users of old code of API incompatibility."""
        raise APIChangedError(
            "e.placements is read-only, "
            "set Core.chip for all cores instead.",
            (0, 2, 0)
        )

    @property
    def allocations(self):
        """A dictionary {:py:class:`Core`: {resource: slice}, ...} or None.

        Defines the resources allocated to each core. This will include an
        allocation of the :py:class:`~rig.place_and_route.Cores` resource
        representing the core allocated.

        See also :py:func:`rig.place_and_route.allocate`.

        :ref:`This attribute was made read-only in v0.2.0. <v0_1_x_upgrade>`
        """
        if self._allocations is None:
            raise AttributeError("Allocations not available until "
                                 "after calling Experiment.run()")
        else:
            # Filter out cores which were not created by the user.
            return {core: allocation
                    for core, allocation in iteritems(self._allocations)
                    if core in self._cores}

    @allocations.setter
    def allocations(self, *args, **kwargs):
        """Warn users of old code of API incompatibility."""
        raise APIChangedError(
            "e.allocations is read-only, "
            "use custom allocator instead.",
            (0, 2, 0)
        )

    @property
    def routes(self):
        """A dictionary {:py:class:`Flow`: \
        :py:class:`rig.place_and_route.routing_tree.RoutingTree`, ...} or None.

        Defines the route used for each flow.

        See also :py:func:`rig.place_and_route.route`.

        :ref:`This attribute was made read-only in v0.2.0. <v0_1_x_upgrade>`
        """
        if self._routes is None:
            raise AttributeError("Routes not available until "
                                 "after calling Experiment.run()")
        else:
            return self._routes

    @routes.setter
    def routes(self, *args, **kwargs):
        """Warn users of old code of API incompatibility."""
        raise APIChangedError(
            "e.routes is read-only, "
            "use custom router instead.",
            (0, 2, 0)
        )

    def _any_router_registers_used(self):
        """Are any router registers (including reinjection counters) being
        recorded or configured during the experiment?
        """
        return (any(self._get_option_value("record_{}".format(counter.name))
                    for counter in Counters if counter.router_counter) or
                self._get_option_value("router_timeout") is not None or
                any(self._get_option_value("router_timeout", g) is not None
                    for g in self._groups) or
                self._reinjection_used())

    def _reinjection_used(self):
        """Is dropped packet reinjection used (or recorded) in the
        experiment?
        """
        return (any(self._get_option_value("record_{}".format(counter.name))
                    for counter in Counters if counter.reinjector_counter) or
                self._get_option_value("reinject_packets") or
                any(self._get_option_value("reinject_packets", g)
                    for g in self._groups))

    @property
    def system_info(self):
        """The :py:class:`~rig.machine_control.machine_controller.SystemInfo`
        object describing the SpiNNaker system under test.

        This value is fetched from the machine once and cached for all future
        accesses. This value may be modified to influence the place-and-route
        processes.
        """
        if self._system_info is None:
            logger.info("Getting SpiNNaker system information...")
            self._system_info = self._mc.get_system_info()
        return self._system_info

    @system_info.setter
    def system_info(self, value):
        self._system_info = value

    @property
    def machine(self):
        """**Deprecated.** The :py:class:`~rig.place_and_route.Machine` object
        describing the SpiNNaker system under test.

        .. warning::

            This method is now deprecated, users should use
            :py:attr:`.system_info` instead. Also, as of v0.3.0, users should
            *not* modify this object: all changes are now ignored.
        """
        warnings.warn(
            "MachineController.get_machine() is deprecated and changes are "
            "now ignored as of v0.3.0. Use get_system_info() instead.",
            DeprecationWarning)

        return build_machine(self._system_info)

    def _construct_core_commands(self, core, source_flows, sink_flows,
                                 flow_keys, records, router_access_core):
        """For internal use. Produce the Commands for a particular core.

        Parameters
        ----------
        core : :py:class:`.Core`
            The core to pack
        source_flows : [:py:class:`.Flow`, ...]
            The flows which are sourced at this core.
        sink_flows : [:py:class:`.Flow`, ...]
            The flows which are sunk at this core.
        flow_keys : {:py:class:`.Flow`: key, ...}
            A mapping from flow to routing key.
        records : [counter, ...]
            The set of counters this core records
        router_access_core : bool
            Should this core be used to configure router/reinjector
            parameters.
        """
        commands = Commands()

        # Set up the sources and sinks for the core
        commands.num(len(source_flows), len(sink_flows))
        for source_num, source_flow in enumerate(source_flows):
            commands.source_key(source_num, flow_keys[source_flow])
        for sink_num, sink_flow in enumerate(sink_flows):
            commands.sink_key(sink_num, flow_keys[sink_flow])

        # Generate commands for each experimental group
        for group in self._groups:
            # Set general parameters for the group
            commands.seed(self._get_option_value("seed", group))
            commands.timestep(self._get_option_value("timestep", group))
            commands.record_interval(self._get_option_value("record_interval",
                                                            group))

            # Set per-source parameters for the group
            for source_num, source_flow in enumerate(source_flows):
                commands.burst(
                    source_num,
                    self._get_option_value("burst_period", group, source_flow),
                    self._get_option_value("burst_duty", group, source_flow),
                    self._get_option_value("burst_phase", group, source_flow))
                commands.probability(
                    source_num,
                    self._get_option_value("probability", group, source_flow))
                commands.num_retries(
                    source_num,
                    self._get_option_value("num_retries", group, source_flow))
                commands.num_packets(
                    source_num,
                    self._get_option_value("packets_per_timestep",
                                           group, source_flow))
                commands.payload(
                    source_num,
                    self._get_option_value("use_payload",
                                           group,
                                           source_flow))

            # Synchronise before running the group
            commands.barrier()

            # Turn on reinjection as required
            if router_access_core:
                commands.reinject(
                    self._get_option_value("reinject_packets", group))

            # Turn off consumption as required
            commands.consume(
                self._get_option_value("consume_packets", group, core))

            # Set the router timeout
            router_timeout = self._get_option_value("router_timeout", group)
            if router_timeout is not None and router_access_core:
                if isinstance(router_timeout, integer_types):
                    commands.router_timeout(router_timeout)
                else:
                    commands.router_timeout(*router_timeout)

            # Warm up without recording data
            commands.run(self._get_option_value("warmup", group), False)

            # Run the actual experiment and record results (flags are removed
            # for permanent counters since they cannot be not-recorded).
            commands.record(*(c for c in records if not c.permanent_counter))
            commands.run(self._get_option_value("duration", group))

            # Run without recording (briefly) after the experiment to allow for
            # clock skew between cores. Record nothing during cooldown.
            commands.run(self._get_option_value("cooldown", group), False)

            # Restore router timeout, turn consumption back on and reinjection
            # back off after the run
            commands.consume(True)
            if router_timeout is not None and router_access_core:
                commands.router_timeout_restore()
            if router_access_core:
                commands.reinject(False)

            # Drain the network of any remaining packets
            commands.sleep(self._get_option_value("flush_time", group))

        # Finally, terminate
        commands.exit()

        return commands

    def _get_core_record_lookup(self, cores,
                                cores_source_flows, cores_sink_flows):
        """Generates a lookup from core to a list of counters that core
        records.

        Parameters
        ----------
        cores : [:py:class:`.Core`, ...]
        cores_source_flows : {:py:class:`.Core`: [flow, ...], ...}
        cores_sink_flows : {:py:class:`.Core`: [flow, ...], ...}

        Returns
        -------
        cores_records : {core: [(object, counter), ...], ...}
            For each core, gives an ordered-list of the things recorded by that
            core.

            For router counters, object will be a tuple (x, y) indicating which
            chip that counter is responsible for.

            For non-router counters, object will be the Flow associated with
            the counter.
        """
        # Get the set of recorded counters for each core
        # {core: [counter, ...]}
        cores_records = {}
        for core in cores:
            # Start with the permanently-recorded set of counters
            records = [(core, c) for c in Counters if c.permanent_counter]

            # Add any router-counters if this core is recording them
            if core in self._router_recording_cores:
                xy = self._placements[core]
                for counter in Counters:
                    if ((counter.router_counter or
                         counter.reinjector_counter) and
                            self._get_option_value(
                                "record_{}".format(counter.name))):
                        records.append((xy, counter))

            # Add any source counters
            for counter in Counters:
                if (counter.source_counter and
                        self._get_option_value(
                            "record_{}".format(counter.name))):
                    for flow in cores_source_flows[core]:
                        records.append((flow, counter))

            # Add any sink counters
            for counter in Counters:
                if (counter.sink_counter and
                        self._get_option_value(
                            "record_{}".format(counter.name))):
                    for flow in cores_sink_flows[core]:
                        records.append((flow, counter))

            cores_records[core] = records

        return cores_records

    def _get_option_value(self, option, group=None, core_or_flow=None):
        """For internal use. Get an option's value for a given
        group/core/flow."""

        values = self._values[option]
        if isinstance(values, dict):
            if isinstance(core_or_flow, Flow):
                core = core_or_flow.source
                flow = core_or_flow
            else:
                core = core_or_flow

            global_value = values[(None, None)]
            group_value = values.get((group, None), global_value)
            core_value = values.get((None, core), group_value)
            group_core_value = values.get((group, core), core_value)

            if isinstance(core_or_flow, Flow):
                flow_value = values.get((None, flow), group_core_value)
                group_flow_value = values.get((group, flow), flow_value)
                return group_flow_value
            else:
                return group_core_value
        else:
            return values

    def _set_option_value(self, option, value, group=None, core_or_flow=None):
        """For internal use. Set an option's value for a given
        group/core/flow.
        """
        values = self._values[option]
        if isinstance(values, dict):
            values[(group, core_or_flow)] = value
        else:
            if group is not None or core_or_flow is not None:
                raise ValueError(
                    "Cannot set {} option on a group-by-group, "
                    "core-by-core or flow-by-flow basis.".format(option))
            self._values[option] = value

    class _Option(object):
        """A descriptor which provides access to the _values dictionary."""

        def __init__(self, option):
            self.option = option

        def __get__(self, obj, type=None):
            return obj._get_option_value(self.option, obj._cur_group)

        def __set__(self, obj, value):
            return obj._set_option_value(self.option, value, obj._cur_group)

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
    record_external_nearest_neighbour = _Option(
        "record_external_nearest_neighbour")
    record_local_fixed_route = _Option("record_local_fixed_route")
    record_external_fixed_route = _Option("record_external_fixed_route")
    record_dropped_multicast = _Option("record_dropped_multicast")
    record_dropped_p2p = _Option("record_dropped_p2p")
    record_dropped_nearest_neighbour = _Option(
        "record_dropped_nearest_neighbour")
    record_dropped_fixed_route = _Option("record_dropped_fixed_route")
    record_counter12 = _Option("record_counter12")
    record_counter13 = _Option("record_counter13")
    record_counter14 = _Option("record_counter14")
    record_counter15 = _Option("record_counter15")

    record_reinjected = _Option("record_reinjected")
    record_reinject_overflow = _Option("record_reinject_overflow")
    record_reinject_missed = _Option("record_reinject_missed")

    record_sent = _Option("record_sent")
    record_blocked = _Option("record_blocked")
    record_retried = _Option("record_retried")
    record_received = _Option("record_received")

    record_interval = _Option("record_interval")

    burst_period = _Option("burst_period")
    burst_duty = _Option("burst_duty")
    burst_phase = _Option("burst_phase")

    probability = _Option("probability")
    num_retries = _Option("num_retries")
    packets_per_timestep = _Option("packets_per_timestep")
    use_payload = _Option("use_payload")

    consume_packets = _Option("consume_packets")

    router_timeout = _Option("router_timeout")

    reinject_packets = _Option("reinject_packets")


class Core(object):
    """A core in the experiment, created by :py:meth:`Experiment.new_core`.

    A core represents a single core running a traffic generator/consumer and
    logging results.

    See :ref:`core parameters <core-attributes>` and :ref:`flow parameters
    <flow-attributes>` for experimental parameters associated with cores.


    :ref:`Renamed from Vertex in v0.2.0. <v0_1_x_upgrade>`
    """

    def __init__(self, experiment, name, chip=None):
        self._experiment = experiment
        self.name = name
        self.chip = chip

    class _Option(object):
        """A descriptor which provides access to the experiment's _values
        dictionary."""

        def __init__(self, option):
            self.option = option

        def __get__(self, obj, type=None):
            return obj._experiment._get_option_value(
                self.option, obj._experiment._cur_group, obj)

        def __set__(self, obj, value):
            return obj._experiment._set_option_value(
                self.option, value, obj._experiment._cur_group, obj)

    seed = _Option("seed")

    burst_period = _Option("burst_period")
    burst_duty = _Option("burst_duty")
    burst_phase = _Option("burst_phase")

    probability = _Option("probability")
    num_retries = _Option("num_retries")
    packets_per_timestep = _Option("packets_per_timestep")

    use_payload = _Option("use_payload")

    consume_packets = _Option("consume_packets")

    def __repr__(self):
        return "<{} {}>".format(self.__class__.__name__, repr(self.name))


class _ReinjectionCore(object):
    """An object used to represent a packet reinjector core."""


class Flow(RigNet):
    """A flow of traffic between cores, created by
    :py:meth:`Experiment.new_flow`.

    This object inherits its attributes from :py:class:`rig.netlist.Net`.

    See :ref:`flow parameters <flow-attributes>` for experimental parameters
    associated with flows.

    :ref:`Renamed from Net in v0.2.0. <v0_1_x_upgrade>`
    """

    def __init__(self, experiment, name, *args, **kwargs):
        super(Flow, self).__init__(*args, **kwargs)
        self._experiment = experiment
        self.name = name

    class _Option(object):
        """A descriptor which provides access to the experiment's _values
        dictionary."""

        def __init__(self, option):
            self.option = option

        def __get__(self, obj, type=None):
            return obj._experiment._get_option_value(
                self.option, obj._experiment._cur_group, obj)

        def __set__(self, obj, value):
            return obj._experiment._set_option_value(
                self.option, value, obj._experiment._cur_group, obj)

    burst_period = _Option("burst_period")
    burst_duty = _Option("burst_duty")
    burst_phase = _Option("burst_phase")

    probability = _Option("probability")
    num_retries = _Option("num_retries")
    packets_per_timestep = _Option("packets_per_timestep")

    use_payload = _Option("use_payload")

    def __repr__(self):
        return "<{} {}>".format(self.__class__.__name__, repr(self.name))


class Group(object):
    """An experimental group, created by :py:meth:`Experiment.new_group`."""

    def __init__(self, experiment, name):
        self._experiment = experiment
        self.name = name
        self.labels = OrderedDict()

    def add_label(self, name, value):
        """Set the value of a label results column for this group.

        Label columns can be used to give more meaning to each experimental
        group. For example::

            >>> for probability in [0.0, 0.5, 1.0]:
            ...     with e.new_group() as g:
            ...         g.add_label("probability", probability)
            ...         e.probability = probability

        In the example above, all results generated would feature a
        'probability' field with the corresponding value for each group making
        it much easier to plat experimental results.

        Parameters
        ----------
        name : str
            The name of the field.
        value
            The value of the field for this group.
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
        """The number of metric recordings which will be made during the
        execution of this group."""
        duration = self._experiment._get_option_value("duration", self)
        timestep = self._experiment._get_option_value("timestep", self)
        record_interval = \
            self._experiment._get_option_value("record_interval", self)

        run_steps = int(round(duration / timestep))
        interval_steps = int(round(record_interval / timestep))

        if interval_steps == 0:
            return 1
        else:
            return run_steps // interval_steps


class APIChangedError(AttributeError):
    """
    Exception thrown when an old (removed) API is used.
    """

    """
    The base URL of the online documentation.
    """
    DOCUMENTATION_BASE_URL = "http://network-tester.readthedocs.org/en/stable"

    """
    The URL of the documentation page documenting changes introduced in
    specific versions of the API.
    """
    BREAKING_VERSION_DOCUMENTATION_URL = {
        (0, 2, 0): "/upgrading_from_0_1_x.html",
    }

    def __init__(self, message, breaking_version):
        full_message = "{} (Changed in v{}, see {}{})".format(
            message,
            ".".join(map(str, breaking_version)),
            self.DOCUMENTATION_BASE_URL,
            self.BREAKING_VERSION_DOCUMENTATION_URL[breaking_version]
        )
        super(APIChangedError, self).__init__(full_message)
