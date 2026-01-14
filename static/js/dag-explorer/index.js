/**
 * DAG Explorer Main Module
 * 
 * Main entry point that initializes and coordinates all DAG Explorer functionality.
 * 
 * Dependencies (must be loaded in order):
 *   1. config.js
 *   2. utils.js
 *   3. api.js
 *   4. graph.js
 *   5. filters.js
 *   6. events.js
 *   7. search.js
 *   8. layout-persistence.js
 *   9. index.js (this file)
 */

const DAGExplorer = (function() {
    'use strict';

    // Configuration passed from the server
    let globalFilterLevel = DAGConfig.DEFAULTS.filterLevel;
    let globalZoom = DAGConfig.DEFAULTS.zoom;
    let globalStartNodeEUID = DAGConfig.DEFAULTS.startNode;

    /**
     * Initialize the DAG Explorer with server-provided configuration
     * @param {Object} config - Configuration object from server
     */
    function init(config) {
        globalFilterLevel = config.filterLevel || DAGConfig.DEFAULTS.filterLevel;
        globalZoom = config.zoom || DAGConfig.DEFAULTS.zoom;
        globalStartNodeEUID = config.startNodeEUID || DAGConfig.DEFAULTS.startNode;

        // Fetch and initialize the graph
        DAGAPI.fetchDAGData(globalStartNodeEUID, globalFilterLevel)
            .then(function(data) {
                initializeGraph(data);
            })
            .catch(function(error) {
                console.error('Failed to initialize DAG:', error);
                alert('Failed to load DAG data. Please try refreshing the page.');
            });
    }

    /**
     * Initialize the DAG Explorer with embedded data (avoids extra API call)
     * @param {Object} config - Configuration object with embedded data
     */
    function initWithData(config) {
        globalFilterLevel = config.filterLevel || DAGConfig.DEFAULTS.filterLevel;
        globalZoom = config.zoom || DAGConfig.DEFAULTS.zoom;
        globalStartNodeEUID = config.startNodeEUID || DAGConfig.DEFAULTS.startNode;

        // Use embedded data directly
        var data = config.data || { elements: { nodes: [], edges: [] } };

        console.log('Initializing DAG with embedded data:',
            data.elements.nodes.length, 'nodes,',
            data.elements.edges.length, 'edges');

        initializeGraph(data);
    }

    /**
     * Initialize the Cytoscape graph with fetched data
     * @param {Object} data - Graph data from server
     */
    function initializeGraph(data) {
        // Initialize Cytoscape
        DAGGraph.initialize('cy', data);

        // Try to restore saved layout
        const restored = DAGLayoutPersistence.restoreLayoutPositions(globalStartNodeEUID);
        
        if (!restored) {
            // Select and center on start node
            DAGGraph.selectAndCenterNode(globalStartNodeEUID, globalZoom);
        }

        // Initialize filters UI
        initializeFilterUI(data);

        // Initialize event handlers
        DAGEvents.initialize();

        // Initialize search
        DAGSearch.initializeSearchInput('euidInput');

        // Enable auto-save of layout positions
        DAGLayoutPersistence.enableAutoSave(globalStartNodeEUID);

        // Apply initial transparency filter
        const threshold = parseInt(document.getElementById('transparencySlider')?.value || 1);
        DAGFilters.updateNodeTransparency(threshold);
    }

    /**
     * Initialize filter checkboxes and buttons
     * @param {Object} data - Graph data containing elements
     */
    function initializeFilterUI(data) {
        // Get unique btypes
        const btypes = new Set();
        data.elements.nodes.forEach(function(ele) {
            if (ele.data && ele.data.btype) {
                btypes.add(ele.data.btype);
            }
        });

        // Get unique b_sub_types
        const bsubtypes = [...new Set(data.elements.nodes.map(function(ele) {
            return ele.data && ele.data.b_sub_type ? ele.data.b_sub_type : null;
        }).filter(Boolean))].sort();

        // Create b_sub_type buttons
        bsubtypes.forEach(function(bsubtype) {
            const button = $('<button />', {
                id: 'btn_' + bsubtype,
                text: bsubtype,
                class: 'subtype-button'
            });
            $('#bsubtypeButtons').append(button);

            button.click(function() {
                DAGFilters.toggleSubtypeFilter(bsubtype);
                $(this).toggleClass('subtype-button-clicked');
            });
        });

        // Create btype checkboxes
        btypes.forEach(function(btype) {
            const br = $('<span/>');
            const checkbox = $('<input />', { 
                type: 'checkbox', 
                id: 'chk_' + btype, 
                checked: 'checked' 
            });
            const label = $('<label style="font-size: 10px;" />', { 
                'for': 'chk_' + btype 
            }).text(btype);
            
            $('#btypeCheckboxes').append(checkbox).append(label).append(br);

            checkbox.change(function() {
                const checked = $(this).is(':checked');
                DAGFilters.filterByBtype(btype, checked);
            });
        });
    }

    /**
     * Display a COGS value label near a node
     * @param {Object} node - Cytoscape node
     * @param {string} position - 'above' or 'below'
     * @param {string|number} cogsValue - COGS value to display
     */
    function displayCogsValue(node, position, cogsValue) {
        // Remove existing label for this node to prevent accumulation
        $(`.cogs-label[data-node="${node.id()}"]`).remove();

        // Limit total number of labels
        const labels = $('.cogs-value-label');
        if (labels.length >= DAGConfig.DEFAULTS.maxLabels) {
            labels.first().remove();
        }

        const label = $('<div/>', {
            class: 'cogs-label cogs-value-label',
            'data-node': node.id(),
            text: '$' + cogsValue,
            css: {
                position: 'absolute',
                top: position === 'above' 
                    ? (node.renderedPosition().y - 30) + 'px' 
                    : (node.renderedPosition().y + 30) + 'px',
                left: node.renderedPosition().x + 'px',
                color: 'black',
                backgroundColor: position === 'below' ? 'magenta' : 'pink',
                padding: '5px',
                borderRadius: '5px',
                textAlign: 'center'
            }
        });

        $('body').append(label);
    }

    // Expose displayCogsValue globally for events module
    window.displayCogsValue = displayCogsValue;

    // Public API
    return {
        init: init,
        initWithData: initWithData,
        getFilterLevel: function() { return globalFilterLevel; },
        getZoom: function() { return globalZoom; },
        getStartNodeEUID: function() { return globalStartNodeEUID; },
        displayCogsValue: displayCogsValue
    };
})();

// Global functions for backward compatibility with inline HTML handlers
function filterNodes(distance) {
    DAGFilters.handleDistanceFilterChange(distance);
}

function centerOnEuid() {
    DAGSearch.centerOnEuid();
}

function updateNodeTransparency() {
    const threshold = parseInt(document.getElementById('transparencySlider').value);
    DAGFilters.updateNodeTransparency(threshold);
}

function changeLayout(layoutName) {
    DAGGraph.changeLayout(layoutName);
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DAGExplorer;
}

