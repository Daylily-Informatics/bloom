/**
 * DAG Explorer Utility Functions
 * 
 * Common utility functions used across the DAG Explorer application.
 */

const DAGUtils = (function() {
    'use strict';

    /**
     * Create a debounced version of a function
     * @param {Function} func - Function to debounce
     * @param {number} wait - Milliseconds to wait
     * @returns {Function} Debounced function
     */
    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func.apply(this, args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    /**
     * Create a throttled version of a function
     * @param {Function} func - Function to throttle
     * @param {number} limit - Minimum milliseconds between calls
     * @returns {Function} Throttled function
     */
    function throttle(func, limit) {
        let inThrottle;
        return function executedFunction(...args) {
            if (!inThrottle) {
                func.apply(this, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }

    /**
     * Safe JSON parse with error handling
     * @param {string} jsonString - JSON string to parse
     * @param {*} defaultValue - Default value if parsing fails
     * @returns {*} Parsed value or default
     */
    function safeJSONParse(jsonString, defaultValue = null) {
        try {
            return JSON.parse(jsonString);
        } catch (e) {
            console.error('JSON parse error:', e);
            return defaultValue;
        }
    }

    /**
     * Check if a value is a valid EUID format
     * @param {string} euid - EUID to validate
     * @returns {boolean} True if valid
     */
    function isValidEuid(euid) {
        if (!euid || typeof euid !== 'string') return false;
        // EUID pattern: 2-3 uppercase letters + sequence number (no leading zeros)
        const euidPattern = /^[A-Z]{2,3}[1-9][0-9]*$/;
        return euidPattern.test(euid);
    }

    /**
     * Generate a unique ID
     * @returns {string} Unique identifier
     */
    function generateUniqueId() {
        return 'id_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    /**
     * Event handler registry for cleanup
     */
    const eventHandlers = [];

    /**
     * Register an event handler for later cleanup
     * @param {jQuery|Element} element - Element to attach handler to
     * @param {string} event - Event name
     * @param {Function} handler - Event handler function
     */
    function registerHandler(element, event, handler) {
        $(element).on(event, handler);
        eventHandlers.push({ element, event, handler });
    }

    /**
     * Clean up all registered event handlers
     */
    function cleanupHandlers() {
        eventHandlers.forEach(({ element, event, handler }) => {
            $(element).off(event, handler);
        });
        eventHandlers.length = 0;
    }

    /**
     * Multi-click detector with timestamp-based detection
     * Replaces setTimeout-based approach to fix race conditions
     */
    function createClickDetector(clickWindow = 500) {
        const clickData = new Map();
        
        return {
            /**
             * Record a click and return the current count
             * @param {string} id - Unique identifier for the element
             * @returns {number} Current click count within window
             */
            recordClick: function(id) {
                const now = Date.now();
                const data = clickData.get(id) || { count: 0, lastTime: 0 };
                
                // Reset if outside click window
                if (now - data.lastTime > clickWindow) {
                    data.count = 0;
                }
                
                data.count++;
                data.lastTime = now;
                clickData.set(id, data);
                
                return data.count;
            },
            
            /**
             * Reset click count for an element
             * @param {string} id - Element identifier
             */
            reset: function(id) {
                clickData.delete(id);
            },
            
            /**
             * Clear all click data
             */
            clear: function() {
                clickData.clear();
            }
        };
    }

    /**
     * Fuzzy search implementation
     * @param {string} query - Search query
     * @param {string} target - Target string to search in
     * @returns {boolean} True if match found
     */
    function fuzzyMatch(query, target) {
        if (!query || !target) return false;
        query = query.toLowerCase();
        target = target.toLowerCase();
        return target.includes(query);
    }

    // Public API
    return {
        debounce: debounce,
        throttle: throttle,
        safeJSONParse: safeJSONParse,
        isValidEuid: isValidEuid,
        generateUniqueId: generateUniqueId,
        registerHandler: registerHandler,
        cleanupHandlers: cleanupHandlers,
        createClickDetector: createClickDetector,
        fuzzyMatch: fuzzyMatch
    };
})();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DAGUtils;
}

