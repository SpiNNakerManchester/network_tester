import pytest

from mock import Mock

from rig.netlist import Net

from network_tester.experiment import Experiment


def test_hostname_or_machine_controler(monkeypatch):
    # If a hostname is passed in, a new MC should be made
    from network_tester import experiment
    mock_mc = Mock()
    monkeypatch.setattr(experiment, "MachineController", mock_mc)
    Experiment("localhost")
    mock_mc.assert_called_once_with("localhost")
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
    vertex0 = e.new_vertex()
    vertex1 = e.new_vertex()
    
    # Make sure the getters setters use specific values with the correct
    # priority.
    
    # Should get global (default) value
    assert e._get_option_value("timestep") == 0.001
    assert e._get_option_value("timestep", group=group0) == 0.001
    assert e._get_option_value("timestep", vertex=vertex0) == 0.001
    assert e._get_option_value("timestep", group=group0, vertex=vertex0) == 0.001
    
    # Should be able to change the default value
    e._set_option_value("timestep", 0.1)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 0.1
    assert e._get_option_value("timestep", vertex=vertex0) == 0.1
    assert e._get_option_value("timestep", group=group0, vertex=vertex0) == 0.1
    
    # Should be able to change the value for a particular vertex
    e._set_option_value("timestep", 0.5, vertex=vertex0)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 0.1
    assert e._get_option_value("timestep", vertex=vertex0) == 0.5
    assert e._get_option_value("timestep", group=group0, vertex=vertex0) == 0.5
    
    # Should be able to change the value for a particular group (vertex value
    # should override still)
    e._set_option_value("timestep", 1.0, group=group0)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 1.0
    assert e._get_option_value("timestep", vertex=vertex0) == 0.5
    assert e._get_option_value("timestep", group=group0, vertex=vertex0) == 0.5
    
    # Should be able to change the value for a particular vertex-group pair
    e._set_option_value("timestep", 10.0, group=group0, vertex=vertex0)
    assert e._get_option_value("timestep") == 0.1
    assert e._get_option_value("timestep", group=group0) == 1.0
    assert e._get_option_value("timestep", vertex=vertex0) == 0.5
    assert e._get_option_value("timestep", group=group0, vertex=vertex0) == 10.0


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
    
    
    # Should be able to set exceptions for vertices
    vertex0 = e.new_vertex()
    assert vertex0.probability == 0.1
    vertex0.probability = 0.5
    assert vertex0.probability == 0.5
    assert e.probability == 0.1
    
    # Should be able to set exceptions in groups for vertices
    with e as group1:
        assert e.probability == 0.1
        assert vertex0.probability == 0.5
        
        # Group probability shouldn't override vertex probability
        e.probability = 1.0
        assert e.probability == 1.0
        assert vertex0.probability == 0.5
        
        # Group+vertex probability should take precidence
        vertex0.probability = 10.0
        assert e.probability == 1.0
        assert vertex0.probability == 10.0
    
    # ...but only within the group
    assert e.probability == 0.1
    assert vertex0.probability == 0.5


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


def test_new_net():
    # Make sure nets are created and the arguments are those supported by Rig's
    # net construct.
    e = Experiment(Mock())
    
    vertices = [e.new_vertex() for _ in range(10)]
    
    # Arguments should be passed through
    net = e.new_net(vertices[0], vertices[1:])
    assert isinstance(net, Net)
    assert net.source == vertices[0]
    assert net.sinks == vertices[1:]
    assert net.weight == 1.0
    
    # As should kwargs
    net = e.new_net(source=vertices[0], sinks=vertices[9], weight=123)
    assert isinstance(net, Net)
    assert net.source == vertices[0]
    assert net.sinks == [vertices[9]]
    assert net.weight == 123


def test_machine(monkeypatch):
    # Make sure lazy-loading of the machine works
    mock_machine = Mock()
    mock_mc = Mock()
    mock_mc.get_machine.return_value = mock_machine
    e = Experiment(mock_mc)
    
    # First time the machine should be fetched
    assert not mock_mc.get_machine.called
    assert e.machine is mock_machine
    assert mock_mc.get_machine.called
    mock_mc.get_machine.reset_mock()
    
    # Next time it shouldn't
    assert e.machine is mock_machine
    assert not mock_mc.get_machine.called
    
    # It shouldn't if set manually either...
    mock_machine2 = Mock()
    e.machine = mock_machine2
    assert e.machine is mock_machine2
    assert not mock_mc.get_machine.called
    
    # It should if reset manually
    e.machine = None
    assert e.machine is mock_machine
    assert mock_mc.get_machine.called


@pytest.mark.parametrize("router_register",
    [
        "local_multicast",
        "external_multicast",
        "local_p2p",
        "external_p2p",
        "local_nearest_neighbour",
        "external_nearest_neighbour",
        "local_fixed_route",
        "external_fixed_route",
        "dropped_multicast",
        "dropped_p2p",
        "dropped_nearest_neighbour",
        "dropped_fixed_route",
        "counter12",
        "counter13",
        "counter14",
        "counter15",
    ])
def test_any_router_registers_recorded(router_register):
    # Should return true if any router register is set to be recorded
    e = Experiment(Mock())
    
    # Should not be true by default
    assert not e._any_router_registers_recorded()
    
    # Should be true when any register enabled 
    setattr(e, "record_{}".format(router_register), True)
    assert e._any_router_registers_recorded()
    
    with e as group:
        # Should also be true within a group
        assert e._any_router_registers_recorded(group)
        
        # Should be able to override within the group
        setattr(e, "record_{}".format(router_register), False)
        assert not e._any_router_registers_recorded(group)
        assert e._any_router_registers_recorded()
    
    # Should be unaffected outside the group
    assert e._any_router_registers_recorded()
    
    # But not when disabled again
    setattr(e, "record_{}".format(router_register), False)
    assert not e._any_router_registers_recorded()


def test_place_and_route():
    mock_mc = Mock()
    mock_place = Mock()
    mock_allocate = Mock()
    mock_route = Mock()
    
    e = Experiment(mock_mc)
    
    # Initially should call all functions
    e.place_and_route(place=mock_place,
                      allocate=mock_allocate,
                      route=mock_route)
    assert mock_place.called
    assert mock_allocate.called
    assert mock_route.called
    mock_place.reset_mock()
    mock_allocate.reset_mock()
    mock_route.reset_mock()
    
    # Called again, nothing should be called
    e.place_and_route(place=mock_place,
                      allocate=mock_allocate,
                      route=mock_route)
    assert not mock_place.called
    assert not mock_allocate.called
    assert not mock_route.called
    
    # Setting the placements should cause others to run
    e.placements = None
    e.place_and_route(place=mock_place,
                      allocate=mock_allocate,
                      route=mock_route)
    assert mock_place.called
    assert mock_allocate.called
    assert mock_route.called
    mock_place.reset_mock()
    mock_allocate.reset_mock()
    mock_route.reset_mock()
    
    # Setting the allocations should cause allocation and routing
    e.allocations = None
    e.place_and_route(place=mock_place,
                      allocate=mock_allocate,
                      route=mock_route)
    assert not mock_place.called
    assert mock_allocate.called
    assert mock_route.called
    mock_allocate.reset_mock()
    mock_route.reset_mock()
    
    # Setting the routes should just cause routing to run
    e.routes = None
    e.place_and_route(place=mock_place,
                      allocate=mock_allocate,
                      route=mock_route)
    assert not mock_place.called
    assert not mock_allocate.called
    assert mock_route.called
    mock_route.reset_mock()
    
    # Creating a vertex should reset everything
    vertex = e.new_vertex()
    e.place_and_route(place=mock_place,
                      allocate=mock_allocate,
                      route=mock_route)
    assert mock_place.called
    assert mock_allocate.called
    assert mock_route.called
    mock_place.reset_mock()
    mock_allocate.reset_mock()
    mock_route.reset_mock()
    
    # Creating a net should reset the routes
    e.new_net(vertex, vertex)
    e.place_and_route(place=mock_place,
                      allocate=mock_allocate,
                      route=mock_route)
    assert not mock_place.called
    assert not mock_allocate.called
    assert mock_route.called
    mock_route.reset_mock()
