/**
 * DAG Explorer Filters Module
 * 
 * Handles node filtering by edge count, btype, distance, and transparency.
 */

const DAGFilters = (function() {
    'use strict';

    /**
     * Update node transparency based on edge count threshold
     * Uses batch operations for performance optimization
     * @param {number} threshold - Maximum edge count for transparency
     */
    function updateNodeTransparency(threshold) {
        const cy = DAGGraph.getInstance();
        if (!cy) return;

        // Update display
        const display = document.getElementById('transparencyDisplay');
        if (display) {
            display.innerText = threshold;
        }

        // Use batch operations for better performance
        cy.batch(function() {
            // Pre-calculate edge counts
            const lowEdgeNodes = cy.nodes().filter(function(node) {
                return node.connectedEdges().length <= threshold;
            });
            const highEdgeNodes = cy.nodes().subtract(lowEdgeNodes);

            // Apply classes in batch
            lowEdgeNodes.addClass('transparent');
            lowEdgeNodes.connectedEdges().addClass('transparent');
            
            highEdgeNodes.removeClass('transparent');
            highEdgeNodes.connectedEdges().removeClass('transparent');
        });
    }

    /**
     * Filter nodes by btype (show/hide)
     * @param {string} btype - The btype to filter
     * @param {boolean} visible - Whether to show or hide
     */
    function filterByBtype(btype, visible) {
        const cy = DAGGraph.getInstance();
        if (!cy) return;

        const opacity = visible ? '1' : '0.1';
        cy.elements().filter(function(ele) {
            return ele.data('btype') === btype;
        }).style('opacity', opacity);
    }

    /**
     * Filter nodes by b_sub_type (toggle transparency)
     * @param {string} subtype - The b_sub_type to filter
     */
    function toggleSubtypeFilter(subtype) {
        const cy = DAGGraph.getInstance();
        if (!cy) return;

        const elements = cy.elements().filter('[b_sub_type = "' + subtype + '"]');
        const currentOpacity = elements.style('opacity');
        const newOpacity = currentOpacity === '0.1' ? '1' : '0.1';
        elements.style('opacity', newOpacity);
    }

    /**
     * Filter nodes based on distance from a center node using BFS
     * @param {number} distance - Maximum distance from center
     * @param {string} centerNodeId - ID of the center node
     */
    function filterByDistance(distance, centerNodeId) {
        const cy = DAGGraph.getInstance();
        if (!cy) return;

        // Update display
        const display = document.getElementById('distanceDisplay');
        if (display) {
            display.innerText = distance;
        }

        // If distance is 0, show all nodes
        if (parseInt(distance) === 0) {
            cy.elements().style('display', 'element');
            return;
        }

        // Hide all elements first
        cy.elements().style('display', 'none');

        // Use BFS to find nodes within distance
        cy.elements().bfs({
            roots: '#' + centerNodeId,
            visit: function(v, e, u, i, depth) {
                if (depth <= parseInt(distance)) {
                    v.style('display', 'element');
                    if (e) e.style('display', 'element');
                }
            },
            directed: false
        });

        // Always show the center node and immediate neighborhood
        cy.$('#' + centerNodeId).closedNeighborhood().style('display', 'element');
    }

    /**
     * Adjust graph display based on distance without page reload
     * @param {number} distance - Filter distance
     * @param {string} nodeId - Center node ID
     */
    function adjustGraphBasedOnDistance(distance, nodeId) {
        filterByDistance(distance, nodeId);
    }

    /**
     * Handle distance filter change with URL update
     * @param {number} distance - New distance value
     */
    function handleDistanceFilterChange(distance) {
        const cy = DAGGraph.getInstance();
        if (!cy) return;

        document.getElementById('distanceDisplay').innerText = distance;

        const selectedNodeId = cy.$('node:selected').id() || DAGExplorer.getStartNodeEUID();
        
        // Check if URL needs updating
        const currentURL = new URL(window.location.href);
        const currentDistance = currentURL.searchParams.get('globalFilterLevel');
        const currentEUID = currentURL.searchParams.get('globalStartNodeEUID');

        if (currentDistance !== distance.toString() || currentEUID !== selectedNodeId) {
            currentURL.searchParams.set('globalFilterLevel', distance);
            currentURL.searchParams.set('globalStartNodeEUID', selectedNodeId);
            window.location.href = currentURL.toString();
        } else {
            // Adjust locally without page reload
            adjustGraphBasedOnDistance(distance, selectedNodeId);
        }
    }

    // Public API
    return {
        updateNodeTransparency: updateNodeTransparency,
        filterByBtype: filterByBtype,
        toggleSubtypeFilter: toggleSubtypeFilter,
        filterByDistance: filterByDistance,
        adjustGraphBasedOnDistance: adjustGraphBasedOnDistance,
        handleDistanceFilterChange: handleDistanceFilterChange
    };
})();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DAGFilters;
}

