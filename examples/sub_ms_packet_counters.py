"""This script is designed to be used alongside another SpiNNaker application
in order to measure how bursty the traffic it produces is.

This experiment does not create any flows but (implicitly) uses a core on every
chip which records the values of the router packet counters every 5
microseconds. This data is then read back and aggregated to produce a plot of
global network traffic with sub-milisecond resolution allowing the burstiness
of an application's traffic to be precisely measured.

To use this script, start the script running in its own terminal::

    $ python sub_ms_packet_counters.py hostname

After a short delay "Press enter to sample network activity." will be printed.
Now start your SpiNNaker application running as usual in another terminal. Note
that your application must not use any of the cores this script is using. For
applications based on Rig v0.11.0 and higher, this is generally the case.

To take a snapshot of the network activity within your application, press enter
in the network experiment terminal. To collect the recorded counter values,
press enter again. You may wish to do this after your application has finished
to avoid adding additional network congestion. Once the results are collected
they are plotted on screen.
"""
import sys

# For Python 2 and 3 compatibility
from six.moves import input

from network_tester import Experiment

# Take the hostname of the remote machine from the command line
e = Experiment(sys.argv[1])

# Record the router counters at 5 us intervals (this is about as fast as the
# current version of Network Tester supports). The recording will last 10 ms to
# avoid consuming excesive quantities memory.
e.timestep = 5e-6
e.record_interval = e.timestep
e.duration = 0.001 * 10

# The basic router counters are recorded
e.record_local_multicast = True
e.record_external_multicast = True
e.record_dropped_multicast = True

# To allow the user to trigger recording and result gathering at arbitrary
# points in time, the before_group and before_read_results callbacks are used
# to simply wait for user input.

def before_group(experiment, group):
    print("Press enter to sample network activity.")
    input()

def before_read_results(experiment):
    print("Press enter to download results.")
    input()

# Run the experiment. Note that we must be careful to use an app ID not used by
# the application being tested!
results = e.run(app_id=19,
                before_group=before_group,
                before_read_results=before_read_results)

# Gather the results, in this case we just look at the global totals rather
# than individual chip traffic flows.
totals = results.totals()

# Plot total multicast traffic and dropped traffic against time.
import matplotlib.pyplot as plt

fig, ax1 = plt.subplots()

ax1.plot(totals["time"],
         totals["local_multicast"] + totals["external_multicast"],
         color="g",
         label="Routed MC packets")
ax1.set_ylabel("Routed Packets (per-{} seconds)".format(e.record_interval),
               color="g")
ax1.set_ylim(bottom=0)

ax2 = ax1.twinx()
ax2.plot(totals["time"],
         totals["dropped_multicast"],
         color="r",
         label="Dropped MC packets")
ax2.set_ylabel("Dropped MC Packets (per-{} seconds)".format(e.record_interval),
               color="r")
ax2.set_ylim(bottom=0)

ax1.set_xlabel("Time (s)")
plt.show()
