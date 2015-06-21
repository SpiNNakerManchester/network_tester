/**
 * SpiNNaker network_tester.
 */

#ifndef NETWORK_TESTER_H
#define NETWORK_TESTER_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#ifndef MIN
#define MIN(a, b) (((a) < (b)) ? (a) : (b))
#endif

#ifndef MAX
#define MAX(a, b) (((a) < (b)) ? (b) : (a))
#endif


#define NT_CMD_EXIT 0x00
#define NT_CMD_SLEEP 0x01
#define NT_CMD_BARRIER 0x02
#define NT_CMD_SEED 0x03
#define NT_CMD_TIMESTEP 0x04
#define NT_CMD_RUN 0x05

#define NT_CMD_RECORD 0x10
#define NT_CMD_RECORD_INTERVAL 0x11

#define NT_CMD_PROBABILITY 0x20
#define NT_CMD_BURST_PERIOD 0x21
#define NT_CMD_BURST_DUTY 0x22
#define NT_CMD_BURST_PHASE 0x23
#define NT_CMD_KEY 0x24
#define NT_CMD_PAYLOAD 0x25
#define NT_CMD_NO_PAYLOAD 0x26

#define NT_CMD_CONSUME 0x30
#define NT_CMD_NO_CONSUME 0x31


#endif
