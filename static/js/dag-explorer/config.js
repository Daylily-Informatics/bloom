/**
 * DAG Explorer Configuration
 * 
 * Centralized configuration for the Cytoscape.js DAG visualization.
 * This file contains all constants, colors, timing values, and defaults.
 */

const DAGConfig = (function() {
    'use strict';

    // Timing constants (in milliseconds)
    const TIMING = {
        CLICK_RESET_DELAY: 500,          // Time window for multi-click detection
        NODE_FLASH_DURATION: 500,        // Duration of node flash effect
        EDGE_HIGHLIGHT_DURATION: 2000,   // Duration of edge highlight effect
        NEIGHBORHOOD_HIGHLIGHT: 1700,    // Duration of neighborhood highlight
        ANIMATION_DURATION: 200,         // Default animation duration
        DEBOUNCE_DELAY: 300,            // Debounce delay for API calls
        LAYOUT_TIMEOUT: 500,            // Timeout for layout completion
        DOUBLE_CLICK_THRESHOLD: 500     // Time window for double-click detection
    };

    // Node colors by super_type
    const NODE_COLORS = {
        container: '#8B00FF',    // Purple
        content: '#00BFFF',      // Deep Sky Blue
        workflow: '#00FF7F',     // Spring Green
        workflow_step: '#ADFF2F', // Green Yellow
        equipment: '#FF4500',    // Orange Red
        data: '#FFD700',         // Gold
        actor: '#FF69B4',        // Hot Pink
        default: 'pink'          // Fallback color
    };

    // Sub-type specific color overrides
    const SUB_TYPE_COLORS = {
        well: '#70658c',
        file_set: '#228080',
        plate: '#9932CC',
        tube: '#8B008B'
    };

    // Edge colors by relationship type
    const EDGE_COLORS = {
        generic: '#ADD8E6',      // Light Blue
        index: '#4CAF50',        // Green
        parent_child: '#357b95', // Default teal
        default: 'lightgreen'
    };

    // Default values
    const DEFAULTS = {
        filterLevel: 4,
        zoom: 4,
        startNode: 'AY1',
        layout: 'dagre',
        maxLabels: 10,           // Maximum COGS labels on screen
        edgeThreshold: 1         // Default edge filter threshold
    };

    // Cytoscape style definitions
    const STYLES = {
        node: {
            'background-color': function(ele) {
                return ele.data('color') || NODE_COLORS.default;
            },
            'label': 'data(id)',
            'text-valign': 'center',
            'color': '#fff',
            'text-outline-width': 2,
            'text-outline-color': '#666',
            'width': '60px',
            'height': '60px',
            'border-color': '#000',
            'border-width': '2px',
            'font-size': '20px'
        },
        nodeSelected: {
            'background-color': '#030f26',
            'border-color': '#f339f6',
            'border-width': '9px',
            'width': '90px',
            'height': '90px',
            'font-size': '70px'
        },
        nodeTransparent: {
            'opacity': 0.1
        },
        edge: {
            'width': 3,
            'line-color': function(ele) {
                return ele.data('color') || '#357b95';
            },
            'source-arrow-color': '#357b95',
            'target-arrow-color': '#357b95',
            'source-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'control-point-step-size': 40
        },
        edgeSelected: {
            'line-color': '#22b8f0',
            'source-arrow-color': '#357b95',
            'target-arrow-color': '#357b95',
            'width': '6px'
        },
        edgeTransparent: {
            'opacity': 0.1
        },
        highlighted: {
            'background-color': '#61bffc',
            'line-color': '#61bffc',
            'target-arrow-color': '#61bffc',
            'transition-property': 'background-color, line-color, target-arrow-color',
            'transition-duration': '0.5s'
        }
    };

    // Valid keyboard shortcuts
    const VALID_KEYS = ['p', 'c', 'n', 'l'];

    // Available layout options
    const LAYOUTS = ['dagre', 'cose', 'breadthfirst', 'grid', 'circle', 'random', 'concentric'];

    // Public API
    return {
        TIMING: TIMING,
        NODE_COLORS: NODE_COLORS,
        SUB_TYPE_COLORS: SUB_TYPE_COLORS,
        EDGE_COLORS: EDGE_COLORS,
        DEFAULTS: DEFAULTS,
        STYLES: STYLES,
        VALID_KEYS: VALID_KEYS,
        LAYOUTS: LAYOUTS,
        
        // Helper function to get node color
        getNodeColor: function(superType, subType) {
            if (subType && SUB_TYPE_COLORS[subType]) {
                return SUB_TYPE_COLORS[subType];
            }
            return NODE_COLORS[superType] || NODE_COLORS.default;
        },
        
        // Helper function to get edge color
        getEdgeColor: function(relationshipType) {
            return EDGE_COLORS[relationshipType] || EDGE_COLORS.default;
        }
    };
})();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DAGConfig;
}

