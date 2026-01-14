/**
 * DAG Explorer Graph Module
 * 
 * Handles Cytoscape.js initialization and core graph operations.
 */

const DAGGraph = (function() {
    'use strict';

    let cy = null;
    let currentLayoutName = DAGConfig.DEFAULTS.layout;

    /**
     * Build Cytoscape style array from config
     * @returns {Array} Cytoscape style definitions
     */
    function buildStyles() {
        return [
            { selector: 'node', style: DAGConfig.STYLES.node },
            { selector: 'edge', style: DAGConfig.STYLES.edge },
            { selector: 'edge.transparent', style: DAGConfig.STYLES.edgeTransparent },
            { selector: 'node:selected', style: DAGConfig.STYLES.nodeSelected },
            { selector: 'node.transparent', style: DAGConfig.STYLES.nodeTransparent },
            { selector: 'edge:selected', style: DAGConfig.STYLES.edgeSelected },
            { selector: '.highlighted', style: DAGConfig.STYLES.highlighted }
        ];
    }

    /**
     * Initialize Cytoscape graph
     * @param {HTMLElement|string} container - Container element or selector
     * @param {Object} data - Graph data with elements
     * @returns {Object} Cytoscape instance
     */
    function initialize(container, data) {
        const containerEl = typeof container === 'string' 
            ? document.getElementById(container) 
            : container;

        cy = cytoscape({
            container: containerEl,
            elements: data.elements || [],
            style: buildStyles(),
            layout: { name: currentLayoutName },
            zoom: data.zoom || 1,
            pan: data.pan || { x: 0, y: 0 },
            zoomingEnabled: data.zoomingEnabled !== undefined ? data.zoomingEnabled : true,
            userZoomingEnabled: data.userZoomingEnabled !== undefined ? data.userZoomingEnabled : true,
            panningEnabled: data.panningEnabled !== undefined ? data.panningEnabled : true,
            userPanningEnabled: data.userPanningEnabled !== undefined ? data.userPanningEnabled : true,
            boxSelectionEnabled: data.boxSelectionEnabled !== undefined ? data.boxSelectionEnabled : true
        });

        return cy;
    }

    /**
     * Get the Cytoscape instance
     * @returns {Object} Cytoscape instance
     */
    function getInstance() {
        return cy;
    }

    /**
     * Apply a layout to the graph
     * @param {Object} layoutOptions - Layout configuration
     * @param {boolean} incremental - Use incremental layout for large graphs
     */
    function applyLayout(layoutOptions, incremental = false) {
        if (!cy) return;

        const options = Object.assign({}, layoutOptions);
        
        // Use incremental layout for large graphs to improve performance
        if (incremental && cy.nodes().length > 100) {
            options.animate = true;
            options.animationDuration = DAGConfig.TIMING.ANIMATION_DURATION;
            options.fit = false;
        }

        const layout = cy.layout(options);
        layout.run();

        // Special handling for breadthfirst layout (invert Y-axis)
        if (options.name === 'breadthfirst') {
            setTimeout(function() {
                cy.batch(function() {
                    cy.nodes().forEach(function(node) {
                        node.position('y', -node.position('y'));
                    });
                });
                cy.fit();
            }, DAGConfig.TIMING.LAYOUT_TIMEOUT);
        }
    }

    /**
     * Change the current layout
     * @param {string} layoutName - Name of the layout
     */
    function changeLayout(layoutName) {
        currentLayoutName = layoutName;
        applyLayout({ name: currentLayoutName });
    }

    /**
     * Center view on a specific node
     * @param {string} nodeId - Node ID to center on
     * @param {number} zoom - Zoom level
     */
    function centerOnNode(nodeId, zoom) {
        if (!cy) return false;

        const node = cy.getElementById(nodeId);
        if (node.length > 0) {
            cy.animate({
                center: { eles: node },
                zoom: zoom || DAGConfig.DEFAULTS.zoom
            }, {
                duration: DAGConfig.TIMING.ANIMATION_DURATION
            });
            return true;
        }
        return false;
    }

    /**
     * Select and center on a random node
     * @param {string} preferredEuid - Preferred starting EUID
     * @param {number} zoom - Zoom level
     */
    function selectAndCenterNode(preferredEuid, zoom) {
        if (!cy) return;

        if (preferredEuid) {
            const startNode = cy.getElementById(preferredEuid);
            if (startNode.length > 0) {
                startNode.select();
                centerOnNode(preferredEuid, zoom);
                return;
            }
        }

        // Fallback to random node
        const nodes = cy.nodes();
        if (nodes.length === 0) return;

        const randomIndex = Math.floor(Math.random() * nodes.length);
        const randomNode = nodes[randomIndex];
        randomNode.select();
        cy.animate({
            center: { eles: randomNode },
            zoom: zoom || DAGConfig.DEFAULTS.zoom
        }, {
            duration: DAGConfig.TIMING.ANIMATION_DURATION
        });
    }

    /**
     * Get all unique btypes from nodes
     * @returns {Set} Set of btype values
     */
    function getBtypes() {
        if (!cy) return new Set();
        const btypes = new Set();
        cy.nodes().forEach(function(node) {
            const btype = node.data('btype');
            if (btype) btypes.add(btype);
        });
        return btypes;
    }

    /**
     * Get all unique b_sub_types from nodes
     * @returns {Array} Sorted array of b_sub_type values
     */
    function getBSubtypes() {
        if (!cy) return [];
        const subtypes = new Set();
        cy.nodes().forEach(function(node) {
            const subtype = node.data('b_sub_type');
            if (subtype) subtypes.add(subtype);
        });
        return Array.from(subtypes).sort();
    }

    // Public API
    return {
        initialize: initialize,
        getInstance: getInstance,
        applyLayout: applyLayout,
        changeLayout: changeLayout,
        centerOnNode: centerOnNode,
        selectAndCenterNode: selectAndCenterNode,
        getBtypes: getBtypes,
        getBSubtypes: getBSubtypes,
        getCurrentLayout: function() { return currentLayoutName; }
    };
})();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DAGGraph;
}

