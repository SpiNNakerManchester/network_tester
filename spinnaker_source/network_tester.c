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


network_node_spec_t *network_node_spec;


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
	network_node_spec_t *network_node_spec = spin1_malloc(config_data_length);
	if (!network_node_spec) {
		io_printf(IO_BUF, "ERROR: Could not allocate memory for config data.\n");
		return NULL;
	}
	memcpy(network_node_spec, config_data + 4, config_data_length);
	
	io_printf(IO_BUF, "INFO: This network node has %d traffic nodes.\n",
	          network_node_spec->num_traffic_nodes);
	
	// Make all relative pointers absolute.
	REL_TO_ABS_PTR(network_node_spec->traffic_nodes, network_node_spec);
	
	for (size_t i = 0; i < network_node_spec->num_traffic_nodes; i++) {
		REL_TO_ABS_PTR(network_node_spec->traffic_nodes[i], network_node_spec);
		traffic_node_spec_t *traffic_node_spec =
			network_node_spec->traffic_nodes[i];
		
		io_printf(IO_BUF, "INFO:   Type %d traffic node 0x%08x has %d sources.\n",
		          traffic_node_spec->type,
		          traffic_node_spec->key,
		          traffic_node_spec->num_sources);
		
		REL_TO_ABS_PTR(traffic_node_spec->sources, traffic_node_spec);
		
		for (size_t j = 0; j < traffic_node_spec->num_sources; j++) {
			traffic_node_source_t *traffic_node_source =
				traffic_node_spec->sources + j;
			io_printf(IO_BUF, "INFO:     Source %d Key = 0x%08x.\n",
			          j, traffic_node_source->key);
		}
	}
	
	return network_node_spec;
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
 * @param network_node_spec A pointer to the structure to copy back into SDRAM.
 *                          This pointer is rendered invalid after calling this
 *                          function.
 * @param tag The tag of the SDRAM block to store the configuration data into.
 *            Typically the core number.
 */
void copy_config_to_sdram(network_node_spec_t *network_node_spec, uint tag)
{
	// Make all pointers relative
	for (size_t i = 0; i < network_node_spec->num_traffic_nodes; i++) {
		traffic_node_spec_t *traffic_node_spec =
			network_node_spec->traffic_nodes[i];
		ABS_TO_REL_PTR(traffic_node_spec->sources, traffic_node_spec);
		ABS_TO_REL_PTR(network_node_spec->traffic_nodes[i], network_node_spec);
	}
	ABS_TO_REL_PTR(network_node_spec->traffic_nodes, network_node_spec);
	
	// Copy the config data back into SDRAM
	void *config_data = sark_tag_ptr(tag, 0);
	size_t config_data_length = *((int *)config_data);
	io_printf(IO_BUF, "INFO: Copying %d byte config block back to SDRAM.\n",
	          config_data_length);
	memcpy(config_data + 4, network_node_spec, config_data_length);
}


void c_main(void)
{
	uint core_id = sark_core_id();
	network_node_spec = copy_config_from_sdram(core_id);
	
	//spin1_start(SYNC_NOWAIT);
	spin1_exit(0);
}


