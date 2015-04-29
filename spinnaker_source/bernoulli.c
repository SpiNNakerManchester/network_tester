/**
 * SpiNNaker network_tester kernel: Bernoulli traffic generator.
 */

#include "sark.h"
#include "spin1_api.h"

#include "network_tester.h"


uint get_bernoulli_tick_interval(network_node_spec_t *network_node)
{
	uint interval = -1;
	for (size_t i = 0; i < network_node->num_traffic_nodes; i++) {
		if (network_node->traffic_nodes[i]->type == TN_BERNOULLI &&
		    (network_node->traffic_nodes[i]->data.bernoulli.period < interval ||
		     interval == -1)) {
			interval = network_node->traffic_nodes[i]->data.bernoulli.period;
		}
	}
	
	return interval;
}


void bernoulli_tick(network_node_spec_t *network_node,
                    traffic_node_spec_t *traffic_node) {
	// Sanity check...
	if (traffic_node->type != TN_BERNOULLI)
		return;
	
	// Possibly generate a packet
	if (spin1_rand() < (uint)(traffic_node->data.bernoulli.probability *
	                          (double)(-1u))) {
		send_packet(network_node, traffic_node);
	}
}
