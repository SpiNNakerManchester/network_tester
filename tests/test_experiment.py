import pytest

from mock import Mock

from network_tester.experiment import Experiment


def test_hostname_or_machine_controler(monkeypatch):
    # If a hostname is passed in, a new MC should be made
    from network_tester import experiment
    mock_mc = Mock()
    monkeypatch.setattr(experiment, "MachineController", mock_mc)
    Experiment("localhost")
    assert mock_mc.called_once_with("localhost")
    mock_mc.reset_mock()
    
    # If an MC is passed in, that should be used
    Experiment(mock_mc)
    assert not mock_mc.called


def test_option_getters_setters():
    """Make sure the internal option get/set API works."""
    e = Experiment(Mock())
    
    with e as group0:
        pass
    with e as group1:
        pass
    node0 = e.new_node()
    node1 = e.new_node()
    
    # Make sure the getters setters use specific values with the correct
    # priority.
    
    # Should get global (default) value
    assert e._get_option_value("timestep") == 0.001
    assert e._get_option_value("timestep", group=group0) == 0.001
    assert e._get_option_value("timestep", node=node0) == 0.001
    assert e._get_option_value("timestep", group=group0, node=node0) == 0.001
    
    # Should be able to change the default value
    e._set_option_value("timestep", 0.1)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 0.1
    assert e._get_option_value("timestep", node=node0) == 0.1
    assert e._get_option_value("timestep", group=group0, node=node0) == 0.1
    
    # Should be able to change the value for a particular node
    e._set_option_value("timestep", 0.5, node=node0)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 0.1
    assert e._get_option_value("timestep", node=node0) == 0.5
    assert e._get_option_value("timestep", group=group0, node=node0) == 0.5
    
    # Should be able to change the value for a particular group (node value
    # should override still)
    e._set_option_value("timestep", 1.0, group=group0)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 1.0
    assert e._get_option_value("timestep", node=node0) == 0.5
    assert e._get_option_value("timestep", group=group0, node=node0) == 0.5
    
    # Should be able to change the value for a particular node-group pair
    e._set_option_value("timestep", 10.0, group=group0, node=node0)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 1.0
    assert e._get_option_value("timestep", node=node0) == 0.5
    assert e._get_option_value("timestep", group=group0, node=node0) == 10.0


def test_option_descriptors():
    """Make sure the option descriptors work."""
    e = Experiment(Mock())
    
    # Defualts should work
    assert e.seed is None
    assert e.probability == 0.0
    
    # Should be able to set
    e.probability = 0.1
    assert e.probability == 0.1
    
    # Should be able to set exceptions for groups
    with e as group0:
        assert e.probability == 0.1
        e.probability = 1.0
        assert e.probability == 1.0
    
    assert e.probability == 0.1
    
    
    # Should be able to set exceptions for nodes
    node0 = e.new_node()
    assert node0.probability == 0.1
    node0.probability = 0.5
    assert node0.probability == 0.5
    assert e.probability == 0.1
    
    # Should be able to set exceptions in groups for nodes
    with e as group1:
        assert e.probability == 0.1
        assert node0.probability == 0.5
        
        # Group probability shouldn't override node probability
        e.probability = 1.0
        assert e.probability == 1.0
        assert node0.probability == 0.5
        
        # Group+node probability should take precidence
        node0.probability = 10.0
        assert e.probability == 1.0
        assert node0.probability == 10.0
    
    # ...but only within the group
    assert e.probability == 0.1
    assert node0.probability == 0.5


def test_non_nestable_groups():
    # Experimental groups must not be allowed to nest
    e = Experiment(Mock())
    
    with e as group0:
        assert e.cur_group is group0
        
        with pytest.raises(Exception):
            with e:
                pass  # pragma: no cover
        
        # Group should not have been changed
        assert e.cur_group is group0


def test_group_labels():
    # Make sure groups can have labels added
    e = Experiment(Mock())
    with e as group0:
        group0.add_label("group", 123)
        group0.add_label("colour", "green")
        
        assert group0._labels == {
            "group": 123,
            "colour": "green",
        }
