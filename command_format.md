Network Tester Command Format
=============================

The network test program loaded on to each core is fed a simple command
sequence from the host which it will execute to determine what to do. The
sequence is made up of instructions which start with a 32-bit integer
indicating what operation to carry out. Each instruction type may then be
followed by a certain number of values.

All values are little endian and all instructions must be 32-bit word aligned.

In this version of the specification, all commands have a number in the range
0-255.

Upon reading an unrecognised instruction number, the interpreter should halt
and report an error.

System commands
---------------

### 0x00: `NT_CMD_EXIT`

    +------------------+
    | 0x00             |
    +------------------+
          1 word

Terminate immediately and stop executing instructions.

### 0x01: `NT_CMD_SLEEP`

    +------------------+------------------+
    | 0x01             | usec             |
    +------------------+------------------+
          1 word             1 word

Sit idle (and don't execute any further instructions for usec microseconds.

### 0x02: `NT_CMD_BARRIER`

    +------------------+
    | 0x02             |
    +------------------+
          1 word

Block idle waiting for a SYNC0 or SYNC1 barrier. Calls to this will alternate
between the two SYNC types, starting with SYNC0.

### 0x03: `NT_CMD_SEED`

    +------------------+------------------+
    | 0x03             | seed             |
    +------------------+------------------+
          1 word             1 word

Seed the random number generator with the specified seed.

### 0x04: `NT_CMD_TIMESTEP`

    +------------------+------------------+
    | 0x20             | timestep_ns      |
    +------------------+------------------+
          1 word             1 word

How many nanoseconds should a timestep last? All further timing parameters will
be in terms of this unit.

### 0x05: `NT_CMD_RUN`

    +------------------+------------------+
    | 0x04             | steps            |
    +------------------+------------------+
          1 word             1 word

Run the traffic generator for the specified number of timesteps.

Result recording commands
-------------------------

### 0x10: `NT_CMD_RECORD`

    +------------------+-------------------+
    | 0x10             | to_record         |
    +------------------+-------------------+
          1 word              1 word

Enable or disable the recording of particular values during a run.

`to_record` is a bitmap with the following bits:

* `cnt[15:0]` each bit corresponds with a SpiNNaker router diagnostic counter
* `cnt[16]` number of sent packets
* `cnt[17]` number of blocked packets (e.g. not sent due to back-pressure)
* `cnt[24]` number of received MC packets

### 0x11: `NT_CMD_RECORD_INTERVAL`

    +------------------+------------------+
    | 0x11             | interval_steps   |
    +------------------+------------------+
          1 word             1 word

While the simulation is running, how frequently should results be recorded?
`interval_usec` gives the interval between samples in timesteps. The first
snapshot will be made at the moment the run begins.

A value of 0 will result in a value being recorded at the start and end of the
run only.



Packet generation commands
--------------------------

### 0x20: `NT_CMD_PROBABILITY`

    +------------------+------------------+
    | 0x21             | probability      |
    +------------------+------------------+
          1 word             1 word

The probability of a packet being generated each timestep. The probability of
transmission is calculated as `probability`/(1<<32).

Special case: If probability is set to 0xFFFFFFFF then the probability of
transmission is set to one.

### 0x21-0x23: `NT_CMD_BURST_PERIOD`, `NT_CMD_BURST_DUTY`, `NT_CMD_BURST_PHASE`

    +------------------+------------------+
    | 0x22             | period_steps     |
    +------------------+------------------+
    +------------------+------------------+
    | 0x23             | duty_steps       |
    +------------------+------------------+
    +------------------+------------------+
    | 0x24             | phase_steps      |
    +------------------+------------------+
          1 word             1 word

To enable the simulation of bursting traffic, traffic generation can be
controlled with a particular duty cycle like so:

                                   period_steps
                        |------------------------------|
                              duty_steps
                             |-------|
                       phase_steps   |
                        |----|
                        .                              .
    send packets        .    +-------+                 .
                        .    |       |                 .
                        .    |       |                 .
      no packets  ...---.----+       +-----------------.---...
                        .                              .
                        .                              .

Special case: a `period_steps` of 0 disables this feature.

### 0x24: `NT_CMD_KEY`

    +------------------+------------------+
    | 0x25             | key              |
    +------------------+------------------+
          1 word             1 word

Sets the top 24 bits of the MC packet key to use for generated packets. The
bottom 8 bits of the key supplied are ignored. The lower 8 bits are sent with
incrementing values to allow for (most) packet mis-orderings to be detected at
the receiver.

### 0x25: `NT_CMD_PAYLOAD`

    +------------------+
    | 0x26             |
    +------------------+
          1 word

Enables the sending of MC packets with payloads.

### 0x26: `NT_CMD_NO_PAYLOAD`

    +------------------+
    | 0x27             |
    +------------------+
          1 word

Disables the sending of MC packets with payloads.


Packet consumption commands
---------------------------

### 0x30: `NT_CMD_CONSUME`

    +------------------+
    | 0x30             |
    +------------------+
          1 word

Enable the consumption of packets from the network. Note that this also enables
the consumption of packets when not in `NT_CMD_CONSUME` though packets arriving
during these times will not be recorded.

### 0x31: `NT_CMD_NO_CONSUME`

    +------------------+
    | 0x31             |
    +------------------+
          1 word

Disable the consumption of packets from the network. Note that this also
prevents the consumption of packets when not in `NT_CMD_CONSUME`.

Note that it is strongly advised that after a period of non-consumption,
consumption be re-enabled and a short sleep performed to drain the network
before exiting or syncing.
