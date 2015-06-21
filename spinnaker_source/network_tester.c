/**
 * SpiNNaker network_tester kernel.
 */

#include <string.h>
#include <stdbool.h>

#include "sark.h"
#include "spin1_api.h"

#include "network_tester.h"

#define MS_TO_TICKS(ms) ((ms) * ((uint32_t)sv->cpu_clk) * 1000u)
#define US_TO_TICKS(us) ((us) * ((uint32_t)sv->cpu_clk))
#define NS_TO_TICKS(ns) (((ns) * ((uint32_t)sv->cpu_clk)) / 1000u)

// A (sticky) flag which is set to true if something has gone wrong. This
// flag's value should be reported back to the host in whatever manner is
// convenient.
static bool error_occurred = false;

// A bit field which indicates what set of fields is to be recorded.
// Bits 15:0 enable logging of each router diagnostic counter.
// Bit 16 enables logging number of sent packets
// Bit 17 enables logging number of blocked packets due to back pressure
// Bit 24 enables logging number of received packets
static uint32_t to_record;

// The maximum number of values which can be recorded simultaneously (used to
// set the size of the buffer where results are stored)
#define MAX_RECORDABLE_VALUES 19

// The interval at which values will be recorded.
static int32_t record_interval_steps;

// The packet generation timestep
static int32_t timestep_ticks;

// SDRAM location where sufficient storage has been allocated to store all results
static uint32_t *sdram_block;

// SDRAM location where the next results should be stored
static uint32_t *sdram_next_results;

// Probability of a packet being injection each timestep. Probability is scaled
// by (1<<32) with 0xFFFFFFFF being special-cased as "1".
static uint32_t probability;

// Bursting traffic generation. See diagram in command format spec.
static uint32_t burst_period_steps;
static uint32_t burst_duty_steps;
static uint32_t burst_phase_steps;

// The top 24 bits of this value are used as the key of the MC packets which
// will be generated.
static uint32_t key;

// Should generated packets include payloads?
static bool payload;

// Count of packets which have arrived at this core
static uint32_t arrived_count = 0;

// Count of packets which have been sent by this core
static uint32_t sent_count = 0;

// Count of packets which were attempted to be sent but which were blocked by
// back-pressure from the network.
static uint32_t blocked_count = 0;

// This array contains pointers to recordable values for each bit in to_record
// (or NULL for bits without a valid counter).
static uint32_t *counters[32] = {
	// Bits 0-15: router counters
	((uint32_t *)RTR_BASE) + RTR_DGC0,
	((uint32_t *)RTR_BASE) + RTR_DGC1,
	((uint32_t *)RTR_BASE) + RTR_DGC2,
	((uint32_t *)RTR_BASE) + RTR_DGC3,
	((uint32_t *)RTR_BASE) + RTR_DGC4,
	((uint32_t *)RTR_BASE) + RTR_DGC5,
	((uint32_t *)RTR_BASE) + RTR_DGC6,
	((uint32_t *)RTR_BASE) + RTR_DGC7,
	((uint32_t *)RTR_BASE) + RTR_DGC8,
	((uint32_t *)RTR_BASE) + RTR_DGC9,
	((uint32_t *)RTR_BASE) + RTR_DGC10,
	((uint32_t *)RTR_BASE) + RTR_DGC11,
	((uint32_t *)RTR_BASE) + RTR_DGC12,
	((uint32_t *)RTR_BASE) + RTR_DGC13,
	((uint32_t *)RTR_BASE) + RTR_DGC14,
	((uint32_t *)RTR_BASE) + RTR_DGC15,
	// Bit 16: sent packets
	&sent_count,
	// Bit 17: blocked packets
	&blocked_count,
	NULL,
	NULL,
	NULL,
	NULL,
	NULL,
	NULL,
	// Bit 24: blocked packets
	&arrived_count,
	NULL,
	NULL,
	NULL,
	NULL,
	NULL,
	NULL,
	NULL,
};

// This buffer is used to store the last raw counter values recorded. These are
// used to calculate the change in counter values between this recording and
// the next recording. The results are packed consecutively from index zero
// onwards.
static uint32_t last_recorded[MAX_RECORDABLE_VALUES];

// This buffer holds the results currently being copied into SDRAM by DMA.
static uint32_t recorded_value_buffer[MAX_RECORDABLE_VALUES];



// XXX: Will be included as part of next version of SCAMP/SARK
// Get a pointer to a tagged allocation. If the "app_id" parameter is zero
// uses the core's app_id.
void *sark_tag_ptr (uint tag, uint app_id)
{
	if (app_id == 0)
		app_id = sark_vec->app_id;
	
	return (void *) sv->alloc_tag[(app_id << 8) + tag];
}


/**
 * Callback on MC packet arrival. Simply counts the packet.
 */
void on_mc_packet(uint arg0, uint arg1)
{
	arrived_count++;
}


/**
 * Record a single snapshot of the network's activity.
 *
 * If first is 0, no data will be stored in SDRAM but the current counter
 * values will be sampled.
 */
void record(bool first)
{
	int num_results = 0;
	
	// Record router counters.
	for (int counter = 0; counter < 32; counter++) {
		if (to_record & (1u << counter) && counters[counter] != NULL) {
			uint32_t value = *(counters[counter]);
			// Record the change in counter value
			recorded_value_buffer[num_results] = value - last_recorded[num_results];
			
			// Remember the current value to allow changes to be detected
			last_recorded[num_results] = value;
			
			num_results++;
		}
	}
	
	if (!first && num_results > 0) {
		// DMA the results into SDRAM
		if (!spin1_dma_transfer(DMA_WRITE, sdram_next_results, recorded_value_buffer, DMA_WRITE,
		                        num_results * sizeof(uint32_t))) {
			io_printf(IO_BUF, "ERROR: DMA transfer of %d bytes failed.\n",
			          num_results * sizeof(uint32_t));
			error_occurred = true;
		}
		
		// Advance the SDRAM pointer to the next free space
		sdram_next_results += num_results;
	}
}


/**
 * Run the traffic generator for the specified number of samples.
 *
 * Returns true if a timing deadline was missed or false otherwise.
 */
bool run(uint32_t time_left_steps)
{
	// Has the packet generator missed a timing deadline? If so, the stream of
	// packets generated is not correct.
	bool deadline_missed = false;
	
	uint32_t next_timestep_ticks = tc2[TC_COUNT] - timestep_ticks;
	
	// This value counts down until the next recording should be made.
	uint32_t record_elapsed_steps = 0;
	
	// Take an initial sample of any counters being recorded
	record(true);
	
	// Generate traffic in a busy loop to maximise timing accuracy
	while (time_left_steps != 0) {
		// Wait until a timestep has ellapsed. (Note that tc2 is a down-counter).
		uint32_t time_ticks = tc2[TC_COUNT];
		if (time_ticks > next_timestep_ticks)
			continue;
		next_timestep_ticks -= timestep_ticks;
		if (time_ticks <= next_timestep_ticks)
			deadline_missed = true;
		time_left_steps--;
		
		// Only generate packets when in the correct phase if bursting (or all the
		// time if not).
		bool burst;
		if (burst_period_steps != 0) {
			burst = burst_phase_steps < burst_duty_steps;
			
			if (++burst_phase_steps >= burst_period_steps)
				burst_phase_steps = 0;
		} else {
			burst = true;
		}
		
		// Possibly generate a packet
		if (burst) {
			bool generate = (probability == 0xFFFFFFFFu)
			              || (sark_rand() < probability);
			
			if (generate) {
				bool sent = spin1_send_mc_packet(key, 0xDEADBEEF, payload);
				if (sent)
					sent_count++;
				else
					blocked_count++;
			}
		}
		
		// If the recording interval has elapsed, record the state of the network.
		if (record_interval_steps > 0
		    && ++record_elapsed_steps >= record_interval_steps) {
			record_elapsed_steps = 0;
			record(false);
		}
	}
	
	// If only recording a single sample for the whole run (record_interval_steps
	// == 0), take a final recording now.
	if (record_interval_steps == 0)
		record(false);
	
	return deadline_missed;
}


/**
 * The main interpreter loop which interprets commands until a NT_CMD_EXIT is
 * encountered at which point the application is stopped and the function
 * returns.
 */
void interpreter_main(uint commands_ptr, uint arg1)
{
	uint32_t *commands = (uint32_t *)commands_ptr;
	
	io_printf(IO_BUF, "INFO: Starting main loop with first command at 0x%08x\n",
	          commands);
	
	while (1) {
		switch (*commands) {
			default:
				error_occurred = true;
				io_printf(IO_BUF, "ERROR: Unrecognised command '0x%02x' at 0x%08x\n",
				          *commands, commands);
				// Fall through to NT_CMD_EXIT
			
			case NT_CMD_EXIT:
				sdram_block[0] = error_occurred;
				io_printf(IO_BUF, "INFO: network_tester exiting with status %s\n",
				          error_occurred ? "ERROR" : "OK");
				spin1_exit((int)error_occurred);
				return;
			
			case NT_CMD_SLEEP:
				commands++;
				spin1_delay_us(*(commands++));
				break;
			
			case NT_CMD_BARRIER:
				commands++;
				event_wait();
				break;
			
			case NT_CMD_SEED:
				commands++;
				sark_srand(*(commands++));
				break;
			
			case NT_CMD_TIMESTEP:
				commands++;
				timestep_ticks = (int32_t)NS_TO_TICKS(*(commands++));
				break;
			
			case NT_CMD_RUN:
				commands++;
				if (run(*(commands++))) {
					io_printf(IO_BUF, "ERROR: Timing deadline(s) missed during run\n");
					error_occurred = true;
				}
				break;
			
			case NT_CMD_RECORD:
				commands++;
				to_record = *(commands++);
				break;
			
			case NT_CMD_RECORD_INTERVAL:
				commands++;
				record_interval_steps = *(commands++);
				break;
			
			case NT_CMD_PROBABILITY:
				commands++;
				probability = *(commands++);
				break;
			
			case NT_CMD_BURST_PERIOD:
				commands++;
				burst_period_steps = *(commands++);
				break;
			
			case NT_CMD_BURST_DUTY:
				commands++;
				burst_duty_steps = *(commands++);
				break;
			
			case NT_CMD_BURST_PHASE:
				commands++;
				burst_phase_steps = *(commands++);
				break;
			
			case NT_CMD_KEY:
				commands++;
				key = *(commands++);
				break;
			
			case NT_CMD_PAYLOAD:
				commands++;
				payload = true;
				break;
			
			case NT_CMD_NO_PAYLOAD:
				commands++;
				payload = false;
				break;
			
			case NT_CMD_CONSUME:
				commands++;
				// Enables the interrupt on packet arrival
				vic[VIC_ENABLE] = 1 << CC_RDY_INT;
				break;
			
			case NT_CMD_NO_CONSUME:
				commands++;
				// Disables the interrupt on packet arrival causing the packets to
				// back-up in the network.
				vic[VIC_DISABLE] = 1 << CC_RDY_INT;
				break;
		}
	}
}

void c_main(void)
{
	// Work out CPU position
	uint32_t xy = spin1_get_chip_id();
	uint32_t x = (xy >> 8) | 0xFF;
	uint32_t y = (xy >> 0) | 0xFF;
	uint32_t p = spin1_get_core_id();
	
	// Set default parameters
	to_record = 0x00000000; // Nothing
	record_interval_steps = 0;
	timestep_ticks = US_TO_TICKS(100);
	probability = 0xFFFFFFFF; // 100%
	burst_period_steps = 0; // Not bursty
	burst_duty_steps = 0; // No ticks on
	burst_phase_steps = 0; // Default: all aligned
	key = (x << 24) | (y << 16) | (p << 8); // Default: XYP
	payload = false; // Default: no payloads
	
	// Accept MC packets
	spin1_callback_on(MC_PACKET_RECEIVED, on_mc_packet, -1);
	spin1_callback_on(MCPL_PACKET_RECEIVED, on_mc_packet, -1);
	
	// Load the commands loaded into SDRAM by the host. The commands are prefixed
	// with a 32-bit integer giving the number of bytes worth of commands.
	sdram_block = (uint32_t *)sark_tag_ptr(p, 0);
	sdram_next_results = sdram_block + 1;
	uint32_t commands_length = sdram_block[0];
	uint32_t *commands = spin1_malloc(commands_length);
	if (commands == NULL) {
		io_printf(IO_BUF, "ERROR: Failed to alloc %d bytes.\n", commands_length);
		return;
	}
	spin1_memcpy(commands, sdram_block + 1, commands_length);
	io_printf(IO_BUF, "INFO: Copied %d bytes of commands from SDRAM...\n", commands_length);
	
	// Start the command interpreter as soon as the API starts
	spin1_schedule_callback(interpreter_main, (uint)commands, 0, 1);
	
	// Start timer 2 running at the CPU clock frequency, this is used for timing
	// packet generation.
	tc2[TC_CONTROL] = ( 1 << 7  // E: Enable the timer
	                  | 0 << 6  // M: Mode = Free-running
	                  | 0 << 5  // I: Interrupt disabled
	                  | 0 << 2  // Pre: Divide clock by 1
	                  | 1 << 1  // S: 32-bit mode
	                  | 0 << 0  // O: Wrapping mode, not one-shot
	                  );
	
	io_printf(IO_BUF, "INFO: spin1_start\n");
	
	spin1_start(SYNC_NOWAIT);
}
