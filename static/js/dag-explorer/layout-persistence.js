/**
 * DAG Explorer Layout Persistence Module
 * 
 * Handles saving and restoring node positions using localStorage.
 */

const DAGLayoutPersistence = (function() {
    'use strict';

    const STORAGE_PREFIX = 'dagLayout_';

    /**
     * Generate storage key for a specific graph
     * @param {string} startNodeEuid - The starting node EUID
     * @returns {string} Storage key
     */
    function getStorageKey(startNodeEuid) {
        return STORAGE_PREFIX + (startNodeEuid || 'default');
    }

    /**
     * Save current layout positions to localStorage
     * @param {string} startNodeEuid - The starting node EUID for the key
     * @returns {boolean} Success status
     */
    function saveLayoutPositions(startNodeEuid) {
        const cy = DAGGraph.getInstance();
        if (!cy) return false;

        try {
            const positions = {};
            cy.nodes().forEach(function(node) {
                positions[node.id()] = {
                    x: node.position('x'),
                    y: node.position('y')
                };
            });

            const data = {
                positions: positions,
                zoom: cy.zoom(),
                pan: cy.pan(),
                timestamp: Date.now()
            };

            localStorage.setItem(getStorageKey(startNodeEuid), JSON.stringify(data));
            console.log('Layout saved for', startNodeEuid);
            return true;
        } catch (e) {
            console.error('Failed to save layout:', e);
            return false;
        }
    }

    /**
     * Restore layout positions from localStorage
     * @param {string} startNodeEuid - The starting node EUID
     * @returns {boolean} Whether positions were restored
     */
    function restoreLayoutPositions(startNodeEuid) {
        const cy = DAGGraph.getInstance();
        if (!cy) return false;

        try {
            const stored = localStorage.getItem(getStorageKey(startNodeEuid));
            if (!stored) return false;

            const data = JSON.parse(stored);
            if (!data.positions) return false;

            // Check if layout is too old (7 days)
            const maxAge = 7 * 24 * 60 * 60 * 1000; // 7 days in ms
            if (data.timestamp && Date.now() - data.timestamp > maxAge) {
                console.log('Saved layout is too old, ignoring');
                return false;
            }

            cy.batch(function() {
                cy.nodes().forEach(function(node) {
                    const savedPos = data.positions[node.id()];
                    if (savedPos) {
                        node.position(savedPos);
                    }
                });
            });

            // Restore zoom and pan if available
            if (data.zoom) {
                cy.zoom(data.zoom);
            }
            if (data.pan) {
                cy.pan(data.pan);
            }

            console.log('Layout restored for', startNodeEuid);
            return true;
        } catch (e) {
            console.error('Failed to restore layout:', e);
            return false;
        }
    }

    /**
     * Clear saved layout for a specific graph
     * @param {string} startNodeEuid - The starting node EUID
     */
    function clearSavedLayout(startNodeEuid) {
        try {
            localStorage.removeItem(getStorageKey(startNodeEuid));
            console.log('Layout cleared for', startNodeEuid);
        } catch (e) {
            console.error('Failed to clear layout:', e);
        }
    }

    /**
     * Clear all saved layouts
     */
    function clearAllSavedLayouts() {
        try {
            const keysToRemove = [];
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && key.startsWith(STORAGE_PREFIX)) {
                    keysToRemove.push(key);
                }
            }
            keysToRemove.forEach(function(key) {
                localStorage.removeItem(key);
            });
            console.log('Cleared', keysToRemove.length, 'saved layouts');
        } catch (e) {
            console.error('Failed to clear all layouts:', e);
        }
    }

    /**
     * Check if a saved layout exists
     * @param {string} startNodeEuid - The starting node EUID
     * @returns {boolean} Whether a saved layout exists
     */
    function hasSavedLayout(startNodeEuid) {
        try {
            return localStorage.getItem(getStorageKey(startNodeEuid)) !== null;
        } catch (e) {
            return false;
        }
    }

    /**
     * Auto-save layout on graph manipulation
     * Call this to enable automatic saving after node drag
     * @param {string} startNodeEuid - The starting node EUID
     */
    function enableAutoSave(startNodeEuid) {
        const cy = DAGGraph.getInstance();
        if (!cy) return;

        // Save on node drag end
        cy.on('dragfree', 'node', DAGUtils.debounce(function() {
            saveLayoutPositions(startNodeEuid);
        }, 1000));

        // Save on zoom/pan change
        cy.on('viewport', DAGUtils.debounce(function() {
            saveLayoutPositions(startNodeEuid);
        }, 1000));
    }

    // Public API
    return {
        saveLayoutPositions: saveLayoutPositions,
        restoreLayoutPositions: restoreLayoutPositions,
        clearSavedLayout: clearSavedLayout,
        clearAllSavedLayouts: clearAllSavedLayouts,
        hasSavedLayout: hasSavedLayout,
        enableAutoSave: enableAutoSave
    };
})();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DAGLayoutPersistence;
}

