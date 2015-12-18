"""This network tester script attempts to check the link integrity of every
link in a SpiNNaker system. It is intended to be run repeatedly for long
durations and provides a steady (though not hugely intense) flow of traffic
over all links. The script verifies that all packets sent arrived at their
destinations ensuring that all routers and links are behaving correctly.

The experiment takes two arguments on the commandline::

    $ python link_integrity_test.py hostname duration

The arguments specify the hostname of the machine whose links are to be tested
and the duraton to run the experiment. In practice this script is typically
executed repeatedly for 60-second runs. If the script finds any discrepancies,
it will produce a descriptive error when it terminates, otherwise no output is
produced.
"""

import sys

from network_tester import Experiment


# Take the hostname from the arguments
e = Experiment(sys.argv[1])

# Warn if anything is dead...
if list(e.system_info.dead_links()):
    print("Warning: Some chips are apprently dead: "
          "{}".format(sorted(e.system_info.dead_chips())))
if list(e.system_info.dead_links()):
    print("Warning: Some links are apprently dead: "
          "{}".format(sorted(e.system_info.dead_links())))
    # Try using "dead" links anyway...
    for x, y, link in e.system_info.dead_links():
        e.system_info[(x, y)].working_links.add(link)

# Create a core and flow to test tx/rx for each link
cores = {(x, y, link): e.new_core(x, y)
         for x, y, link in e.system_info.links()}
for (x1, y1, link1), core in cores.items():
    dx, dy = link1.to_vector()
    x2 = (x1 + dx) % e.system_info.width
    y2 = (y1 + dy) % e.system_info.height
    link2 = link1.opposite
    if (x2, y2, link2) in cores:
        e.new_flow(core, cores[(x2, y2, link2)],
                   name=str((x1, y1, link1)))

# Run for a while...
e.duration = float(sys.argv[2])
e.timestep = 1e-5

# Leave 0.1 seconds at the start and end to ensure we see all packets
e.burst_period = e.duration
e.burst_duty = 1.0 - (2.0 / e.duration)
e.burst_phase = 1.0 - (1.0 / e.duration)

# Record both the packet generator/consumer counters and also the router
# dropping counters so that if there is a mismatch between packets sent and
# received it can be checked whether this was due to a router dropping the
# packets or due to some other malfunction.
e.record_sent = True
e.record_received = True
e.record_dropped_multicast = True

results = e.run()

# Report any mismatches in sent/received packet counts
for result in results.flow_totals():
    flow = result["flow"]
    sent = result["sent"]
    received = result["received"]
    if sent != received:
        print("Error: Sent {} and received {} across link {}".format(
            sent, received, flow.name))

# Report any dropped packets
num_dropped = sum(results.totals()["dropped_multicast"])
if num_dropped != 0:
    print("Error: {} packets dropped by a router.".format(num_dropped))
