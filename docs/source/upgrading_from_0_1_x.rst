.. py:module:: network_tester

.. _v0_1_x_upgrade:

Upgrading from Network Tester v0.1.x
====================================

Between the Network Tester v0.1.x and v0.2.x series a number of API and
terminology changes occurred which will break nearly all experiments written
for older versions of Network Tester. This document describes how to modify
your experiment scripts to work with the new network tester API and describes
the terminology changes which occurred. 

At a glance, the API changes are summarised in this table:

===================================================  =============================================================
Old API (v0.1.x)                                     New API
===================================================  =============================================================
``v = e.new_vertex("fred", (1, 2))``                 :py:meth:`c = e.new_core(1, 2, "fred") <Experiment.new_core>`
``n = e.new_net(v0, v1)``                            :py:meth:`f = e.new_flow(c0, c1) <Experiment.new_flow>`
``e.placements = {v0: (1, 2), ...}``                 :py:attr:`c0.chip = (1, 2); ... <Core.chip>`
``e.place_and_route(place=hilbert_place); e.run()``  :py:meth:`e.run(place=hilbert_place) <Experiment.run>`
===================================================  =============================================================

.. note::
    
    The descision to break in API backwards-compatibility between v0.1.x and
    v0.2.x was not taken lightly, despite Network Tester's pre-release state.
    The developer believes the changes made to the API in this release will
    make the library substantially easier to understand, easier to use and also
    considerably more robust. It is unlikely that another major breaking change
    such as this will occur again before the 1.0 release.
    
    To aid users in the transition to v0.2.x the deprecated functions have been
    replaced with stubs which raise a hepful error message linking to this
    documentation.


Terminology Changes
-------------------

Previous versions of Network Tester used the term 'vertex' to refer to an
application core on the machine and 'net' to refer to the flows of traffic
between the cores. In v0.2.x onwards the term 'core' is used in place of vertex
and the term 'flow' in place of net. These changes intend to make it much
clearer what is being done by the API.

The following API name changes have been made to reflect the new terminology:

===========================  ==============================
Old Name (v0.1.x)            New Name
===========================  ==============================
``Experiment.new_vertex()``  :py:meth:`Experiment.new_core`
``Experiment.new_net()``     :py:meth:`Experiment.new_flow`
``Vertex``                   :py:meth:`Core`
``Net``                      :py:meth:`Flow`
===========================  ==============================


Manual Placement Changes
------------------------

The :py:meth:`Experiment.new_core` method's first two arguments are now the
x and y coordinates of the chip the core should be placed on. Previously, the
first argument was the name of the vertex and the chip coordinates were given
as a single argument.

================================  =========================================================
Old Syntax (v0.1.x)               New Syntax
================================  =========================================================
``e.new_vertex("fred", (1, 2))``  :py:meth:`e.new_core(1, 2, "fred") <Experiment.new_core>`
================================  =========================================================

The :py:attr:`Experiment.placements`, :py:attr:`Experiment.allocations` and
:py:attr:`Experiment.routes` properties are now strictly read-only. Manual
placement should be performed by specifying the chip position of each
:py:class:`Core` when it is created or by setting the :py:attr:`Core.chip`
attribute of cores. If greater flexibility is required, you should supply a
rig-compilent :py:func:`~rig.place_and_route.place`,
:py:func:`~rig.place_and_route.allocate` and
:py:func:`~rig.place_and_route.route` function to :py:meth:`Experiment.run`.


Place-and-Route Changes
-----------------------

The place-and-route process now always occurs as part of the
:py:meth:`Experiment.run` method, ``Experiment.place_and_route()`` is no longer
available. The :py:meth:`~Experiment.run` method now accepts all the arguments
the ``place_and_route()`` method used to. This change prevents the accidental
use of stale place-and-route information resulting from changes being made to
the experiment between calling ``place_and_route()`` and
:py:meth:`~Experiment.run`. For example:

===================================================  ======================================================
Old Syntax (v0.1.x)                                  New Syntax
===================================================  ======================================================
``e.place_and_route(place=hilbert_place); e.run()``  :py:meth:`e.run(place=hilbert_place) <Experiment.run>`
===================================================  ======================================================


Reverting to v0.1.x
-------------------

If for some reason this is not possible to modify your experiment script to
support the new Network Tester API, you can revert to the last v0.1.x version
of Network Tester using::

    $ pip install -I "network_tester<0.2.0"

