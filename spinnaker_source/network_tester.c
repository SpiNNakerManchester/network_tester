/**
 * SpiNNaker network_tester kernel.
 */

#include <string.h>

#include "sark.h"
#include "spin1_api.h"

#include "network_tester.h"


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
 * Pointer to the globally used network_node_spec_t used by this node.
 */
static network_node_spec_t *network_node;


/**
 * The timer tick interval in use.
 */
static uint tick_interval;


/**
 * Convert the supplied pointer from a pointer relative to the supplied base
 * pointer to an absolute pointer.
 */
#define REL_TO_ABS_PTR(ptr, base) \
	(ptr) = ((void *)(base)) + ((size_t)(ptr))

/**
 * Copy the configuration loaded into SDRAM into DTCM, converting all pointers
 * into absolute pointers.
 *
 * The `config_data` pointer is updated to point at the DTCM copy of the data.
 *
 * @param tag The tag of the SDRAM block containing the configuration data to be
 *            loaded. Typically the core number.
 * @returns A pointer to the DTCM copy of the config data or NULL on failure.
 */
network_node_spec_t *copy_config_from_sdram(uint tag)
{
	void *config_data = sark_tag_ptr(tag, 0);
	
	// Copy the config data into DTCM, the head of which is the network node
	// config.
	size_t config_data_length = *((int *)config_data);
	io_printf(IO_BUF, "INFO: %d byte config block found.\n",
	          config_data_length);
	network_node_spec_t *network_node = spin1_malloc(config_data_length);
	if (!network_node) {
		io_printf(IO_BUF, "ERROR: Could not allocate memory for config data.\n");
		return NULL;
	}
	memcpy(network_node, config_data + 4, config_data_length);
	
	io_printf(IO_BUF, "INFO: This network node has %d traffic nodes.\n",
	          network_node->num_traffic_nodes);
	
	// Make all relative pointers absolute.
	REL_TO_ABS_PTR(network_node->traffic_nodes, network_node);
	
	for (size_t i = 0; i < network_node->num_traffic_nodes; i++) {
		REL_TO_ABS_PTR(network_node->traffic_nodes[i], network_node);
		traffic_node_spec_t *traffic_node =
			network_node->traffic_nodes[i];
		
		io_printf(IO_BUF, "INFO:   Type %d traffic node 0x%08x has %d sources.\n",
		          traffic_node->type,
		          traffic_node->key,
		          traffic_node->num_sources);
		
		REL_TO_ABS_PTR(traffic_node->sources, traffic_node);
		
		for (size_t j = 0; j < traffic_node->num_sources; j++) {
			traffic_node_source_t *traffic_node_source =
				traffic_node->sources + j;
			io_printf(IO_BUF, "INFO:     Source %d Key = 0x%08x.\n",
			          j, traffic_node_source->key);
		}
	}
	
	return network_node;
}


/**
 * Convert the supplied pointer from an absolute pointer to one relative to the
 * supplied base pointer.
 */
#define ABS_TO_REL_PTR(ptr, base) \
	(ptr) =  (void *)(((size_t)(ptr)) - ((size_t)(base)))

/**
 * Copy the current configuration back into SDRAM from DTCM, converting all
 * pointers into relative pointers.
 *
 * Note: this function must only be used on structures produced by
 * copy_config_from_sdram. (No fields may be added or removed) The structure of
 * the data copied back to SDRAM is guaranteed to match the data loaded, a
 * property used by the host-side software for retrieving data.
 *
 * @param network_node A pointer to the structure to copy back into SDRAM.
 *                     This pointer is rendered invalid after calling this
 *                     function.
 * @param tag The tag of the SDRAM block to store the configuration data into.
 *            Typically the core number.
 */
void copy_config_to_sdram(network_node_spec_t *network_node, uint tag)
{
	// Make all pointers relative
	for (size_t i = 0; i < network_node->num_traffic_nodes; i++) {
		traffic_node_spec_t *traffic_node =
			network_node->traffic_nodes[i];
		ABS_TO_REL_PTR(traffic_node->sources, traffic_node);
		ABS_TO_REL_PTR(network_node->traffic_nodes[i], network_node);
	}
	ABS_TO_REL_PTR(network_node->traffic_nodes, network_node);
	
	// Copy the config data back into SDRAM
	void *config_data = sark_tag_ptr(tag, 0);
	size_t config_data_length = *((int *)config_data);
	io_printf(IO_BUF, "INFO: Copying %d byte config block back to SDRAM.\n",
	          config_data_length);
	memcpy(config_data + 4, network_node, config_data_length);
}


void send_packet(network_node_spec_t *network_node,
                 traffic_node_spec_t *traffic_node)
{
	// Note that sequence numbers start at 1.
	uint key = traffic_node->key |
	           (++(traffic_node->num_sent) & network_node->key_seq_mask);
	spin1_send_mc_packet(key, 0xDEADBEEF, traffic_node->payload);
}


void on_timer_tick(uint tick_num, uint _)
{
	static uint32_t last_time = 0;
	uint32_t time = tick_num * tick_interval;
	
	// Terminate experiment when duration elapses
	if (time >= network_node->duration)
		spin1_exit(0);
	
	// Generate traffic for Bernoulli traffic nodes
	for (int i = 0; i < network_node->num_traffic_nodes; i++) {
		if (network_node->traffic_nodes[i]->type == TN_BERNOULLI) {
			traffic_node_spec_t *traffic_node = network_node->traffic_nodes[i];
			uint32_t period = traffic_node->data.bernoulli.period;
			
			uint32_t node_last_tick = last_time / period;
			uint32_t node_tick = time / period;
			
			if (node_last_tick != node_tick)
				bernoulli_tick(network_node, traffic_node);
		}
	}
	
	last_time = time;
}


void on_mc_packet(uint key, uint payload)
{
	uint32_t seq_num = key & network_node->key_seq_mask;
	key = key & ~network_node->key_seq_mask;
	
	for (int i = 0; i < network_node->num_traffic_nodes; i++) {
		traffic_node_spec_t *traffic_node = network_node->traffic_nodes[i];
		// XXX: Could do a binary search through this list since it is in always
		// given order of key...
		for (int j = 0; j < traffic_node->num_sources; j++) {
			traffic_node_source_t *source = traffic_node->sources + i;
			if (source->key == key) {
				// Record packet arrivals.
				source->num_received++;
				if (seq_num != source->last_seq_num + 1)
					source->num_out_of_order;
				source->last_seq_num = seq_num;
				
				// Generate a packet if this is a relay node.
				if (traffic_node->type == TN_RELAY) {
					send_packet(network_node, traffic_node);
				}
			}
		}
	}
}


void c_main(void)
{
	uint core_id = sark_core_id();
	network_node = copy_config_from_sdram(core_id);
	
	
	// Select the timer tick interval. Default is every 10ms.
	tick_interval = 10000;
	uint bernoulli_tick_interval = get_bernoulli_tick_interval(network_node);
	if (bernoulli_tick_interval)
		tick_interval = MIN(bernoulli_tick_interval, tick_interval);
	spin1_set_timer_tick(tick_interval);
	
	spin1_callback_on(TIMER_TICK, on_timer_tick, 0);
	spin1_callback_on(MC_PACKET_RECEIVED, on_mc_packet, -1);
	spin1_callback_on(MCPL_PACKET_RECEIVED, on_mc_packet, -1);
	
	spin1_start(SYNC_NOWAIT);
}
