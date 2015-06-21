import sys
import pkg_resources
import struct
import time

from rig.machine_control import MachineController
from rig.routing_table import RoutingTableEntry, Routes


binary = pkg_resources.resource_filename(
    "network_tester", "binaries/network_tester.aplx")

mc = MachineController(sys.argv[1])


with mc.application(0x42):
	num_samples = 1
	num_vals = 2
	commands = [
		0x04, 1250,  # NT_CMD_TIMESTEP 1.25us
		0x10, (1<<16) | (1<<17),  # NT_CMD_RECORD MC sent,received
		0x11, 0,  # NT_CMD_RECORD_INTERVAL: 0
		0x20, 0xFFFFFFFF,  # NT_CMD_PROBABILITY 1
		#0x21, 100, # NT_CMD_BURST_PERIOD 100ms
		#0x22, 50, # NT_CMD_BURST_DUTY 50ms
		#0x31, # NT_CMD_NO_CONSUME
		0x05, 1000,  # NT_CMD_RUN 10ms
		#0x30, # NT_CMD_CONSUME
		0x01, 1, # NT_CMD_SLEEP 1us
		0x02,  # Sync
		0x00, # NT_CMD_EXIT
	]
	
	data = struct.pack("<{}I".format(len(commands)+1), len(commands) * 4, *commands)
	mem = mc.sdram_alloc_as_filelike(max(len(data), 4 + num_samples*num_vals*4), tag=1, x=0, y=0)
	mem.write(data)
	
	# Catch-all route
	entries = [
		RoutingTableEntry(set([Routes.core_1]), 0x00000000, 0x00000000)
	]
	mc.load_routing_table_entries(entries, x=0, y=0)
	
	mc.load_application(binary, {(0, 0): set([1])})
	time.sleep(1.5)
	mc.wait_for_cores_to_reach_state("sync0", 1)
	mc.send_signal("sync0")
	mem.seek(0)
	error_state = struct.unpack("<I", mem.read(4))[0]
	print("Error state: {}".format(error_state))
	print(struct.unpack("<{}I".format(num_samples*num_vals),
	                    mem.read(4*num_samples*num_vals)))
	
	if error_state:
		input("press enter to kill...")
