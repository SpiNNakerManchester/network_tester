"""Result gathering for the network tester application to be run on
SpiNNaker."""

import struct

from six import iteritems


class VertexResults(object):
    """Represents the set of results recorded by a given vertex."""

    def __init__(self, records, groups):
        """Instantiate a result processor.
        
        Parameters
        ----------
        records : set([column_name, ...])
            The set of columns this vertex records.
        groups : [group, ...]
            The list of experimental groups in the experiment.
        """
        self._records = records
        self._groups = groups
        
        self._data = None
    
    
    @property
    def size(self):
        """Get the total size of the packed results, in bytes."""
        return (
            # The error flag (one word)
            1 +
            # One word per recorded value per sample.
            (sum(g.num_samples for g in self._groups) * len(self._records))
        ) * 4
    
    def unpack(self, result_data, format="<"):
        self._data = struct.unpack("{}{}I".format(format, self.size // 4),
                                   result_data)

    
    @property
    def error(self):
        """The final error code of the vertex."""
        return self._data[0]
