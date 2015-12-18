#!/usr/bin/env python
"""Measure the throughput of every link in a SpiNNaker system.

Run the script with a booted SpiNNaker system as the argument.

    $ python throughput.py HOSTNAME

This script produces three CSV result files: totals.csv, router_counters.csv
and data.csv. The first two files correspond with the associated network tester
results tables and are provided for machine debugging purposes (e.g. to track
down spurious packet dropping). The final file, data.csv, contains the
comprehensive results of the throughput experiement and can be very large for
bigger systems (e.g. 74 MB for a 24-board system). A heavily-documented R
script, link_throughput.R, is provided which will produce various useful plots
of this data.

Note: In all probability you'll see a very small proportion of realtime
deadlines missed. This is probably OK... Probably...
"""

import sys

import numpy as np

from rig.links import Links
from rig.geometry import spinn5_chip_coord, spinn5_fpga_link

from network_tester import Experiment, to_csv


# Show detailed logging information
import logging
logging.basicConfig(level=logging.DEBUG)

################################################################################
# Experiment definition
################################################################################

# Run the experiment against the machine given on the commandline
e = Experiment(sys.argv[1])

# If some links are dead they will not be included in the experiment.
if list(e.system_info.dead_links()):
    print("WARNING: {} dead links!".format(
        len(list(e.system_info.dead_links()))))

# Number of cores to use on each chip for sending/receiving packets
num_cores = 16

# Create num_cores cores on each chip in the machine.
# {(x, y): [v, ...], ...}
chip_cores = {(x, y): [e.new_core(x, y) for _ in range(num_cores)]
              for x, y in e.system_info}

# For each chip, add flows connecting corresponding cores at the end of each of
# the six links.
# {(x, y, link): [n, ...], ...}
link_flows = {
    (x, y, link): [
        e.new_flow(tx, rx)
        for tx, rx in zip(
            chip_cores.get((x, y), []),
            chip_cores.get(((x + link.to_vector()[0]) % e.system_info.width,
                            (y + link.to_vector()[1]) % e.system_info.height), []))
    ] for x, y, link in e.system_info.links()
}

# Enable the links in sequence such that at any point in time, any pair of
# routers only has a single flow of traffic through it. This means that for
# each direction we send from half the chips and receieve on the other half.
e.packets_per_timestep = 0
for link, alternate_dimension in [(Links.east, 0), (Links.west, 0),
                                  (Links.north, 1), (Links.south, 1),
                                  (Links.north_east, 1), (Links.south_west, 1)]:
    for odd_even in [0, 1]:
        with e.new_group() as g:
            g.add_label("group_link", link.name)
            g.add_label("group_odd_even", odd_even)
            for x, y in e.system_info:
                if (x, y)[alternate_dimension] % 2 == odd_even and \
                        (x, y, link) in e.system_info:
                    for flow in link_flows[(x, y, link)]:
                        flow.packets_per_timestep = 1

# The interval between packets being generated on each core
e.timestep = 2e-6  # 2 microseconds

e.router_timeout = 240

# For each link direction the experiment is split into three parts of equal
# duration:
# 1. Idle: Ensures the network is idle before starting to send packets
# 2. Transmit: Send packets as fast as possible
# 3. Idle: Allow the network to drain (note that we still count packets
#    arriving during this time.
e.duration = 1.0
e.burst_period = e.duration
e.burst_duty = 1.0/3.0
e.burst_phase = 2.0/3.0

# Count the number of packets sent and received
e.record_sent = True
e.record_blocked = True
e.record_received = True

# Also record the router counter values. Note that this isn't strictly
# necessary however this is recorded as a sanity-checking measure: if lots of
# packets are dropped, or any go missing this is a bad thing(TM).
e.record_local_multicast = True
e.record_external_multicast = True
e.record_dropped_multicast = True

# Sanity check; if the parameters above don't generate enough traffic to
# saturate the link, shout!
if (1.0 / e.timestep) * num_cores * 40.0 / 1024.0 / 1024.0 < 300.0:
    print("WARNING: Packet generation rate < 300 MBit/s, links may not saturate")


################################################################################
# Results gathering
################################################################################

# Actually runs the experiment. Unfortunately, *some* realtime deadlines do end
# up being missed but so long as it is only extremely occasional, this
# shouldn't be a big enough fault to warrant crashing!
results = e.run(ignore_deadline_errors=True)

totals = results.totals()
router_counters = results.router_counters()
flow_counters = results.flow_counters()

# Shout if any deadlines are missed; it is up to the user to determine whether
# the quantity of deadlines missed is sufficient to invalidate the results. If
# << 1% of deadlines are missed, this is proabbly fine(!)
if not (totals["deadlines_missed"] == 0).all():
    print("WARNING: {} of {} realtime deadlines missed.".format(
        int(sum(totals["deadlines_missed"])),
        int(len(e.system_info) * num_cores * (e.duration / e.timestep) * 12)
    ))

# Shout if any sent packets didn't arrive (should generally not be the case for
# reasonably generous router timeouts).
missing_packets = int(np.sum(totals["sent"] - totals["received"]))
if missing_packets:
    print("WARNING: {} sent packets did not arrive.".format(
        missing_packets
    ))

# Shout if any sent are dropped by a router (should generally not be the case
# for reasonably generous router timeouts).
dropped_packets = int(np.sum(totals["dropped_multicast"]))
if dropped_packets:
    print("WARNING: {} packets dropped by routers.".format(
        dropped_packets
    ))

# Shout if the number of dropped and non-delivered packets don't match: this
# indicates something seriously weird is happening and should not be possible.
# This has only been observed on quite broken machines...
if missing_packets != dropped_packets:
    print("WARNING: The number of dropped packets does not match "
          "the number sent but which did not arrive.")

# These results are mostly useful when trying to chase up broken machines...
with open("totals.csv", "w") as f:
    f.write(to_csv(totals))
with open("router_counters.csv", "w") as f:
    f.write(to_csv(router_counters))

# We'll now create a new results table which is almost the same as the
# flow_counters results table except it includes a few additional columns
# indicating which links are being used etc. to allow us to seperate out
# results by link or FPGA (if applicable).
data = np.zeros((len(flow_counters),),
                dtype=flow_counters.dtype.descr + [("duration", float),
                                                   ("x", int), ("y", int),
                                                   ("link", object),
                                                   ("board_x", int), ("board_y", int),
                                                   ("fpga_num", object), ("fpga_link_num", object)])

# Add the recorded results
for col in flow_counters.dtype.names:
    data[col] = flow_counters[col]

# A lookup giving the link being tested for each flow.
# {flow: (x, y, link), ...}
flow_links = {}
for (x, y, link), flows in link_flows.items():
    for flow in flows:
        flow_links[flow] = (x, y, link)

# This column just gives the number of seconds the traffic generators actually
# spent generating traffic (and is the same for all recorded data).
data["duration"] = e.duration * e.burst_duty

# Populate the additional results columns
for row in range(len(data)):
    x, y, link = flow_links[data[row]["flow"]]
    
    # The specific link the flow was loading
    data[row]["x"] = x
    data[row]["y"] = y
    data[row]["link"] = link.name
    
    # The coordinates of the (sending) chip with respect to the board it is on
    data[row]["board_x"], data[row]["board_y"] = spinn5_chip_coord(x, y)
    
    # These columns indicate the FPGA link used or are left as None (i.e. NA)
    # when the link a native SpiNNaker link.
    fpga_link = spinn5_fpga_link(x, y, link)
    if fpga_link is None:
        data[row]["fpga_num"] = None
        data[row]["fpga_link_num"] = None
    else:
        data[row]["fpga_num"], data[row]["fpga_link_num"] = fpga_link

# Be warned, this CSV is *very* large (74 MB) for a 24-board system...
with open("data.csv", "w") as f:
    f.write(to_csv(data))

