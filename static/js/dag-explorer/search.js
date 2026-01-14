/**
 * DAG Explorer Search Module
 * 
 * Implements search functionality including fuzzy search across
 * node ID, name, and btype fields.
 */

const DAGSearch = (function() {
    'use strict';

    /**
     * Center the graph on a specific EUID
     * @param {string} euid - The EUID to center on
     * @param {boolean} updateUrl - Whether to update the URL
     */
    function centerOnEuid(euid, updateUrl = true) {
        const cy = DAGGraph.getInstance();
        if (!cy) return false;

        euid = euid || document.getElementById('euidInput').value;
        const node = cy.getElementById(euid);

        if (node.length > 0) {
            if (updateUrl) {
                const newURL = new URL(window.location.href);
                newURL.searchParams.set('globalStartNodeEUID', euid);
                newURL.searchParams.set('globalFilterLevel', '4');
                window.location.href = newURL.toString();
            }
            
            cy.animate({
                center: { eles: node },
                zoom: DAGConfig.DEFAULTS.zoom
            }, {
                duration: DAGConfig.TIMING.ANIMATION_DURATION
            });
            return true;
        } else {
            alert('EUID not found in the DAG.');
            return false;
        }
    }

    /**
     * Perform fuzzy search across node properties
     * @param {string} query - Search query
     * @returns {Array} Array of matching nodes
     */
    function fuzzySearch(query) {
        const cy = DAGGraph.getInstance();
        if (!cy || !query) return [];

        query = query.toLowerCase().trim();
        
        return cy.nodes().filter(function(node) {
            const id = (node.id() || '').toLowerCase();
            const name = (node.data('name') || '').toLowerCase();
            const btype = (node.data('btype') || '').toLowerCase();
            const euid = (node.data('euid') || '').toLowerCase();
            const bSubType = (node.data('b_sub_type') || '').toLowerCase();
            
            return id.includes(query) || 
                   name.includes(query) || 
                   btype.includes(query) ||
                   euid.includes(query) ||
                   bSubType.includes(query);
        });
    }

    /**
     * Search and highlight matching nodes
     * @param {string} query - Search query
     * @returns {number} Number of matches found
     */
    function searchAndHighlight(query) {
        const cy = DAGGraph.getInstance();
        if (!cy) return 0;

        // Remove previous highlights
        cy.nodes().removeClass('search-match');

        if (!query || query.trim() === '') {
            return 0;
        }

        const matches = fuzzySearch(query);
        
        if (matches.length > 0) {
            matches.addClass('search-match');
            
            // Center on first match
            const firstMatch = matches[0];
            cy.animate({
                center: { eles: firstMatch },
                zoom: DAGConfig.DEFAULTS.zoom
            }, {
                duration: DAGConfig.TIMING.ANIMATION_DURATION
            });
        }

        return matches.length;
    }

    /**
     * Get search suggestions based on partial input
     * @param {string} partial - Partial search string
     * @param {number} limit - Maximum number of suggestions
     * @returns {Array} Array of suggestion objects
     */
    function getSuggestions(partial, limit = 10) {
        const cy = DAGGraph.getInstance();
        if (!cy || !partial) return [];

        const matches = fuzzySearch(partial);
        const suggestions = [];

        matches.forEach(function(node) {
            if (suggestions.length >= limit) return;
            suggestions.push({
                id: node.id(),
                euid: node.data('euid'),
                name: node.data('name') || 'Unnamed',
                btype: node.data('btype')
            });
        });

        return suggestions;
    }

    /**
     * Initialize search input with autocomplete-like behavior
     * @param {string} inputId - ID of the search input element
     */
    function initializeSearchInput(inputId) {
        const input = document.getElementById(inputId);
        if (!input) return;

        // Debounced search on input
        const debouncedSearch = DAGUtils.debounce(function(value) {
            const count = searchAndHighlight(value);
            console.log(`Found ${count} matches for "${value}"`);
        }, DAGConfig.TIMING.DEBOUNCE_DELAY);

        input.addEventListener('input', function(e) {
            debouncedSearch(e.target.value);
        });

        input.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                const value = e.target.value.trim();
                if (value) {
                    centerOnEuid(value, true);
                }
            }
        });
    }

    // Public API
    return {
        centerOnEuid: centerOnEuid,
        fuzzySearch: fuzzySearch,
        searchAndHighlight: searchAndHighlight,
        getSuggestions: getSuggestions,
        initializeSearchInput: initializeSearchInput
    };
})();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DAGSearch;
}

