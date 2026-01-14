/**
 * DAG Explorer API Module
 * 
 * Handles all backend API calls with proper error handling and debouncing.
 */

const DAGAPI = (function() {
    'use strict';

    // Track pending requests for cancellation
    let pendingRequests = [];

    /**
     * Make an AJAX request with error handling
     * @param {Object} options - jQuery AJAX options
     * @returns {Promise} Promise resolving to response data
     */
    function request(options) {
        return new Promise((resolve, reject) => {
            const defaults = {
                dataType: 'json',
                timeout: 30000 // 30 second timeout
            };
            
            const ajaxOptions = Object.assign({}, defaults, options, {
                success: function(response) {
                    resolve(response);
                },
                error: function(xhr, status, error) {
                    console.error(`API Error [${options.url}]:`, status, error);
                    reject({
                        status: xhr.status,
                        statusText: status,
                        error: error,
                        response: xhr.responseText
                    });
                }
            });
            
            const xhr = $.ajax(ajaxOptions);
            pendingRequests.push(xhr);
            
            // Clean up completed request
            xhr.always(function() {
                const index = pendingRequests.indexOf(xhr);
                if (index > -1) {
                    pendingRequests.splice(index, 1);
                }
            });
        });
    }

    /**
     * Cancel all pending requests
     */
    function cancelPendingRequests() {
        pendingRequests.forEach(xhr => xhr.abort());
        pendingRequests = [];
    }

    /**
     * Fetch DAG data for a node at specified depth
     * @param {string} euid - Starting node EUID
     * @param {number} depth - Traversal depth
     * @returns {Promise} Promise resolving to graph data
     */
    function fetchDAGData(euid, depth) {
        return request({
            url: '/get_dagv2',
            method: 'GET',
            data: { euid: euid, depth: depth }
        });
    }

    // Debounced version of fetchDAGData
    let debouncedFetchTimeout = null;
    function debouncedFetchDAGData(euid, depth, callback) {
        if (debouncedFetchTimeout) {
            clearTimeout(debouncedFetchTimeout);
        }
        debouncedFetchTimeout = setTimeout(function() {
            fetchDAGData(euid, depth)
                .then(callback)
                .catch(function(error) {
                    console.error('Failed to fetch DAG data:', error);
                });
        }, DAGConfig.TIMING.DEBOUNCE_DELAY);
    }

    /**
     * Get node information
     * @param {string} euid - Node EUID
     * @returns {Promise} Promise resolving to node info
     */
    function getNodeInfo(euid) {
        return request({
            url: '/get_node_info',
            method: 'GET',
            data: { euid: euid }
        });
    }

    /**
     * Get a specific property of a node
     * @param {string} euid - Node EUID
     * @param {string} key - Property key
     * @returns {Promise} Promise resolving to property value
     */
    function getNodeProperty(euid, key) {
        return request({
            url: '/get_node_property',
            method: 'GET',
            data: { euid: euid, key: key }
        });
    }

    /**
     * Calculate COGS for parent nodes
     * @param {string} euid - Node EUID
     * @returns {Promise} Promise resolving to COGS value
     */
    function calculateCogsParents(euid) {
        return request({
            url: '/calculate_cogs_parents',
            method: 'GET',
            data: { euid: euid }
        }).then(function(response) {
            // Handle response that might be a string
            if (typeof response === 'string') {
                return DAGUtils.safeJSONParse(response, { cogs_value: 'N/A' });
            }
            return response;
        });
    }

    /**
     * Calculate COGS for child nodes
     * @param {string} euid - Node EUID
     * @returns {Promise} Promise resolving to COGS value
     */
    function calculateCogsChildren(euid) {
        return request({
            url: '/calculate_cogs_children',
            method: 'GET',
            data: { euid: euid }
        }).then(function(response) {
            if (typeof response === 'string') {
                return DAGUtils.safeJSONParse(response, { cogs_value: 'N/A' });
            }
            return response;
        });
    }

    /**
     * Add a new edge between nodes
     * @param {string} parentUuid - Parent node UUID
     * @param {string} childUuid - Child node UUID
     * @returns {Promise} Promise resolving to new edge data
     */
    function addNewEdge(parentUuid, childUuid) {
        return request({
            url: '/add_new_edge',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ parent_uuid: parentUuid, child_uuid: childUuid })
        });
    }

    /**
     * Delete an object (node or edge)
     * @param {string} euid - Object EUID
     * @returns {Promise} Promise resolving to deletion result
     */
    function deleteObject(euid) {
        return request({
            url: '/delete_object',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ euid: euid })
        });
    }

    /**
     * Update the DAG with new graph data
     * @param {Object} graphData - Cytoscape graph JSON
     * @returns {Promise} Promise resolving to update result
     */
    function updateDAG(graphData) {
        return request({
            url: '/update_dag',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(graphData)
        });
    }

    /**
     * Add a new node
     * @returns {Promise} Promise resolving to new node data
     */
    function addNewNode() {
        return request({
            url: '/add_new_node',
            method: 'GET'
        });
    }

    // Public API
    return {
        request: request,
        cancelPendingRequests: cancelPendingRequests,
        fetchDAGData: fetchDAGData,
        debouncedFetchDAGData: debouncedFetchDAGData,
        getNodeInfo: getNodeInfo,
        getNodeProperty: getNodeProperty,
        calculateCogsParents: calculateCogsParents,
        calculateCogsChildren: calculateCogsChildren,
        addNewEdge: addNewEdge,
        deleteObject: deleteObject,
        updateDAG: updateDAG,
        addNewNode: addNewNode
    };
})();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DAGAPI;
}

