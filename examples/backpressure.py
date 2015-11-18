"""In this simple example we attempt to determine how many packets-per-second
must be sent over a SpiNNaker link before back pressure applied by the network
prevents packets being injected."""

import sys

from network_tester import Experiment


e = Experiment(sys.argv[1])

# The traffic generators will step every 5us
e.timestep = 5e-6

# The number of cores to use to send packets on a chip (note that a single core
# cannot saturate a link)
cores_per_chip = 16

# How many packets will be sent by each chip per timestep?
packets_per_timestep = 3

# We'll have a group of cores on one chip sending packets and a corresponding
# set of cores on another chip.
send_cores = [e.new_core(name="s{}".format(n)) for n in range(16)]
recv_cores = [e.new_core(name="r{}".format(n)) for n in range(16)]
for s, r in zip(send_cores, recv_cores):
    # We create multiple flows to allow multiple packets to be sent per
    # timestep since a single flow will send up-to one packet per timestep.
    for _ in range(packets_per_timestep):
        e.new_flow(s, r)

# We will explicitly place the cores on different chips
placements = {c: (0, 0) for c in send_cores}
placements.update({c: (1, 0) for c in recv_cores})
e.placements = placements

# We allow some warmup time to allow the network to reach a stable state before
# recording
e.warmup = 0.05
e.duration = 0.3
e.cooldown = 0.01

# Record the number of packets sent
e.record_sent = True

# During the experiment we'll ramp up the injection rate and see how many
# packets arrive at their destination.
num_steps = 30
for step in range(num_steps):
    with e.new_group() as g:
        e.probability = step / float(num_steps - 1)
        g.add_label("packets_per_second",
                    ((1.0 / e.timestep) *
                     e.probability *
                     cores_per_chip *
                     packets_per_timestep))

results = e.run()

totals = results.totals()

# Scale sent-packet count to packets per-second
totals["sent"] /= e.duration

# Plot with matplotlib
import matplotlib.pyplot as plt
plt.plot(totals["packets_per_second"], totals["sent"])
plt.legend()
plt.xlabel("Offered load (Packets per second)")
plt.ylabel("Accepted load (Packets per second)")
plt.show()
