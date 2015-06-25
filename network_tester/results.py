"""Result gathering for the network tester application to be run on
SpiNNaker."""

import struct

from six import iteritems, itervalues

import numpy as np

from numpy.lib.recfunctions import flatten_descr

from network_tester.errors import NT_ERR


# A little-endian unsigned 32-bit value type
uint32_le = np.dtype("uint32").newbyteorder("<")


class Results(object):
    """The results of an experiment."""
    
    def __init__(self, experiment, vertices, nets, vertices_records,
                 router_recording_vertices, placements, vertices_result_data, groups):
        """Create a new results container.
        
        Parameters
        ----------
        experiment : [:py:class:`Experiment`, ...]
            The experiment during which the results were recorded.
        vertices : [:py:class:`Vertex`, ...]
            The vertices in the experiment (not including vertices added for
            router-recording purposes).
        nets : [:py:class:`Net`, ...]
            The nets which connect the above vertices.
        vertices_records : {:py:class:`Vertex`: [(object, counter), ...], ...}
            For each vertex gives the ordered list of counters recorded with
            each sample.
            
            For net (source/sink) counters, object is the net object associated
            with that counter.
            
            For router counters, object is a tuple (x, y) indicating the chip
            whose router counter was recorded.
        router_recording_vertices : set([:py:class:`Vertex`, ...])
            Gives the set of vertices which recorded router counter values.
        placements : {:py:class:`Vertex`: (x, y), ...}
            The chip position for each vertex.
        vertices_result_data : {:py:class:`Vertex`: bytes, ...}
            The raw result data read back from each vertex.
        groups : [:py:class:`Group`, ...]
            The list of experimental groups.
        """
        self._experiment = experiment
        self._vertices = vertices
        self._nets = nets
        self._vertices_records = vertices_records
        self._router_recording_vertices = router_recording_vertices
        self._placements = placements
        self._vertices_result_data = vertices_result_data
        self._groups = groups
        
        # Determine the full list of counters recorded throughout the system
        recorded = set()
        for counters in itervalues(self._vertices_records):
            recorded.update(counter for obj, counter in counters)
        self._recorded = sorted(recorded)
        
        # Unpack the errors and data tables from each vertex
        self._vertices_errors = {}
        self._vertices_results = {}
        self.errors = set()
        for vertex, data in iteritems(self._vertices_result_data):
            # Unpack error status
            errors = NT_ERR.from_int(struct.unpack("<I", data[0:4])[0])
            self._vertices_errors[vertex] = errors
            self.errors.update(errors)
            
            # Unpack the data
            results = np.frombuffer(data[4:], dtype=uint32_le).astype(np.uint)
            num_columns = len(self._vertices_records[vertex])
            if num_columns > 0:
                results.shape = (len(results) // num_columns, num_columns)
            self._vertices_results[vertex] = results
        
        # Count the number of samples in the datasets
        self.num_samples = sum(g.num_samples for g in self._groups)
        
        # A full set of group-defined labels
        labels = []
        for group in self._groups:
            for label in group.labels:
                if label not in labels:
                    labels.append(label)
        
        # Create the standard set of columns
        self.common = np.zeros((self.num_samples, ),
                               dtype=[(label, object)
                                      for label in labels] +
                                     [("group", object),
                                      ("time", np.double)])
        row = 0
        for group_num, group in enumerate(self._groups):
            # Work out the sampling interval for the group
            with group:
                sample_period = self._experiment.record_interval
                if sample_period == 0.0:
                    sample_period = self._experiment.duration
            
            # Populate the columns
            for sample_num in range(group.num_samples):
                for label in labels:
                    self.common[row][label] = group.labels.get(label)
                self.common[row]["group"] = group
                self.common[row]["time"] = (sample_num + 1) * sample_period
                row += 1
    
    
    def _make_result_array(self, column_names, rows_per_sample=1):
        """Make a structured array with a row for every sample, all standard
        group/time columns and then the specified set of additional columns for
        counter values. Counter columns are initialised with zeros.
        
        Parameters
        ----------
        column_name : [name or (name, type), ...]
        rows_per_sample : int
            The number of rows in the output to reserve for each sample
            recorded.
        """
        column_names = [(name, np.uint) if isinstance(name, str) else name
                        for name in column_names]
        
        a = np.zeros((self.num_samples * rows_per_sample, ),
                     dtype=list(flatten_descr(self.common.dtype)) +
                           column_names)
        
        # Copy common columns across
        for common_column in self.common.dtype.names:
            for row in range(rows_per_sample):
                a[row::rows_per_sample][common_column] = self.common[common_column]
        
        return a
    
    
    def totals(self):
        """Gives the total counts for all recorded counters."""
        totals = self._make_result_array(c.name for c in self._recorded)
        
        for vertex, records in iteritems(self._vertices_records):
            results = self._vertices_results[vertex]
            for result_column, (obj, counter) in enumerate(records):
                totals[counter.name] += results[:, result_column]
        
        return totals
    
    
    def vertex_totals(self):
        """Gives the counter totals for all nets sourced/sunk by each vertex."""
        num_vertices = len(self._vertices)
        totals = self._make_result_array([("vertex", object)] +
                                         [c.name for c in self._recorded
                                          if c.source_counter or c.sink_counter],
                                         rows_per_sample=num_vertices)
        
        for vertex_num, vertex in enumerate(self._vertices):
            records = self._vertices_records[vertex]
            results = self._vertices_results[vertex]
            totals[vertex_num::num_vertices]["vertex"] = vertex
            for result_column, (obj, counter) in enumerate(records):
                if counter.source_counter or counter.sink_counter:
                    totals[vertex_num::num_vertices][counter.name] += results[:, result_column]
        
        return totals
    
    
    def net_totals(self):
        """Gives the counter totals for each net."""
        num_nets = len(self._nets)
        totals = self._make_result_array([("net", object),
                                          ("fan_out", np.uint)] +
                                         [c.name for c in self._recorded
                                          if c.source_counter or c.sink_counter],
                                         rows_per_sample=num_nets)
        
        for net_num, net in enumerate(self._nets):
            totals[net_num::num_nets]["net"] = net
            totals[net_num::num_nets]["fan_out"] = len(net.sinks)
            for vertex, records in iteritems(self._vertices_records):
                results = self._vertices_results[vertex]
                for result_column, (obj, counter) in enumerate(records):
                    if obj is net and (counter.source_counter or counter.sink_counter):
                        totals[net_num::num_nets][counter.name] += results[:, result_column]
        
        return totals
    
    
    def net_counters(self):
        """Gives the complete counter values for net in the system listing the
        counts for every source/sink pair.
        """
        num_sinks = sum(len(n.sinks) for n in self._nets)
        counts = self._make_result_array([("net", object),
                                          ("fan_out", np.uint),
                                          ("source_vertex", object),
                                          ("sink_vertex", object)] +
                                         [c.name for c in self._recorded
                                          if c.source_counter or c.sink_counter],
                                         rows_per_sample=num_sinks)
        
        pair_num = 0
        for net in self._nets:
            source_vertex = net.source
            source_records = self._vertices_records[source_vertex]
            source_results = self._vertices_results[source_vertex]
            
            for sink_vertex in net.sinks:
                counts[pair_num::num_sinks]["net"] = net
                counts[pair_num::num_sinks]["fan_out"] = len(net.sinks)
                counts[pair_num::num_sinks]["source_vertex"] = source_vertex
                counts[pair_num::num_sinks]["sink_vertex"] = sink_vertex
                
                for source_result_column, (obj, counter) in enumerate(source_records):
                    if obj is net and counter.source_counter:
                        counts[pair_num::num_sinks][counter.name] += source_results[:, source_result_column]
                
                sink_records = self._vertices_records[sink_vertex]
                sink_results = self._vertices_results[sink_vertex]
                
                for sink_result_column, (obj, counter) in enumerate(sink_records):
                    if obj is net and counter.sink_counter:
                        counts[pair_num::num_sinks][counter.name] += sink_results[:, sink_result_column]
                
                pair_num += 1
        
        return counts
    
    
    def router_counters(self):
        """Gives the router counter values for every chip in the system."""
        num_chips = len(self._router_recording_vertices)
        
        totals = self._make_result_array(
            ["x", "y"] + [c.name for c in self._recorded if c.router_counter],
            rows_per_sample=num_chips)
        
        for chip_num, ((y, x), vertex) in enumerate(sorted((self._placements[v][::-1], v)
                                                           for v in self._router_recording_vertices)):
            records = self._vertices_records[vertex]
            results = self._vertices_results[vertex]
            totals[chip_num::num_chips]["x"] = x
            totals[chip_num::num_chips]["y"] = y
            for result_column, (obj, counter) in enumerate(records):
                if counter.router_counter:
                    totals[chip_num::num_chips][counter.name] = results[:, result_column]
        
        return totals
    
    
    def __repr__(self):
        return "<{}{}>".format(self.__class__.__name__,
                               " (errors occurred during experiment)"
                               if self.errors else "")


def to_csv(data, col_sep=",", row_sep="\n", none="NA",
           group_as_name=True, vertex_as_name=True, net_as_name=True):
    """Render a Numpy structured array produced by network tester as a CSV
    complete with headings.
    
    Parameters
    ----------
    data : :py:class:`np.ndarray`   
        A structured array produced by :py:class:`Results`.
    col_sep : str
        The separator between columns in the output. (Default: ',')
    row_sep : str
        The separator between rows in the output. (Default: '\\n')
    none : str
        The string to use to represent :py:class:`None`. (Default: 'NA')
    group_as_name : bool
        If true, the group column will be listed with group names rather than
        the repr() of the :py:class:`Group` object.
    vertex_as_name : bool
        If true, the vertex column will be listed with vertex names rather than
        the repr() of the :py:class:`Vertex` object.
    net_as_name : bool
        If true, the net column will be listed with net names rather than
        the repr() of the :py:class:`Net` object.
    """
    data = data.copy()
    
    out = ""
    
    # Add column headers
    columns = data.dtype.names
    out += col_sep.join(columns) + row_sep

    # Replace groups/vertices/nets with their group name if present
    if "group" in columns and group_as_name:
        data["group"] = [g.name for g in data["group"]]
    if vertex_as_name:
        for vertex_column in ["vertex", "source_vertex", "sink_vertex"]:
            if vertex_column in columns and vertex_as_name:
                data[vertex_column ] = [v.name for v in data[vertex_column]]
    if "net" in columns and net_as_name:
        data["net"] = [n.name for n in data["net"]]

    # Add all data
    for row in data:
        out += col_sep.join(str(value) if value is not None else none
                            for value in row) + row_sep
    
    return(out)
