import pytest

from mock import Mock

from network_tester.results import VertexResults

from network_tester.experiment import Experiment

class TestVertexResults(object):
    
    def test_size(self):
        # Make sure size computations for results are correct
        
        # No recordings and no groups means just the error flag
        assert VertexResults(set(), []).size == 4
        
        # Some recordings and no groups means just the error flag
        assert VertexResults(set(["sent"]), []).size == 4
        
        # Some groups and no recordings means just the error flag
        e = Experiment(Mock())
        group0 = e.new_group()
        assert VertexResults(set(), [group0]).size == 4
        
        # Some groups and recordings means the error flag plus that data
        e = Experiment(Mock())
        group1 = e.new_group()
        assert VertexResults(set(["sent", "blocked"]), [group0, group1]).size \
            == 4 + 8 + 8
    
    def test_error(self):
        # Make sure the error value is unpacked successfully
        r = VertexResults(set(), [])
        r.unpack(b"\x01\0\0\0")
        assert r.error == 1



