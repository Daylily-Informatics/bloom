/**
 * DAG Explorer Events Module
 * 
 * Handles all event binding and interaction logic.
 */

const DAGEvents = (function() {
    'use strict';

    // State variables
    let keyHeld = null;
    let selectedChildNode = null;
    let lastClickedNode = null;
    let neighborhoodDepth = 1;
    let lastEdgeClicked = null;
    let lastEdgeClickTime = 0;

    // Click detector for multi-click handling (fixes race condition)
    const nodeClickDetector = DAGUtils.createClickDetector(DAGConfig.TIMING.CLICK_RESET_DELAY);
    const nodeRightClickDetector = DAGUtils.createClickDetector(DAGConfig.TIMING.CLICK_RESET_DELAY);

    /**
     * Initialize all event handlers
     */
    function initialize() {
        initializeKeyboardHandlers();
        initializeCytoscapeEvents();
        initializeUIEvents();
    }

    /**
     * Set up keyboard event handlers
     */
    function initializeKeyboardHandlers() {
        // Consolidated keydown handler for all valid keys
        $(document).keydown(function(e) {
            if (DAGConfig.VALID_KEYS.includes(e.key)) {
                keyHeld = e.key;
            }
        });

        // Consolidated keyup handler
        $(document).keyup(function(e) {
            if (DAGConfig.VALID_KEYS.includes(e.key)) {
                keyHeld = null;
                
                // Reset selected child node when 'l' key is released
                if (e.key === 'l' && selectedChildNode) {
                    selectedChildNode.style('background-color', '');
                    selectedChildNode = null;
                }
            }
        });
    }

    /**
     * Set up Cytoscape graph events
     */
    function initializeCytoscapeEvents() {
        const cy = DAGGraph.getInstance();
        if (!cy) return;

        // Background tap handler
        cy.on('tap', function(event) {
            if (event.target === cy) {
                $('#node-info').hide();
                nodeClickDetector.clear();
                
                if (selectedChildNode) {
                    selectedChildNode.style('background-color', '');
                    selectedChildNode = null;
                }
            }
        });

        // Node tap handler with timestamp-based multi-click detection
        cy.on('tap', 'node', handleNodeTap);

        // Node right-click handler (for deletion)
        cy.on('cxttap', 'node', handleNodeRightClick);

        // Edge right-click handler (for deletion)
        cy.on('cxttap', 'edge', handleEdgeRightClick);

        // Edge add handler (for cycle detection)
        cy.on('add', 'edge', handleEdgeAdd);
    }

    /**
     * Handle node tap events (click)
     * Uses timestamp-based detection to fix race condition
     */
    function handleNodeTap(evt) {
        evt.originalEvent.stopPropagation();
        
        const cy = DAGGraph.getInstance();
        const node = evt.target;
        const euid = node.data('euid');
        const nodeId = node.id();

        // Use timestamp-based click detection (fixes race condition)
        const clickCount = nodeClickDetector.recordClick(nodeId);

        // Handle triple click - show dialog
        if (clickCount === 3) {
            handleTripleClick(node, evt);
            nodeClickDetector.reset(nodeId);
            return;
        }

        // Handle 'n' key held - neighborhood highlighting
        if (keyHeld === 'n') {
            handleNeighborhoodHighlight(node);
        }

        // Handle COGS calculation (p or c key held)
        if (clickCount >= 1 && (keyHeld === 'p' || keyHeld === 'c')) {
            handleCogsCalculation(node, euid, keyHeld);
        }

        // Handle 'l' key held - edge creation
        if (keyHeld === 'l') {
            handleEdgeCreation(node, cy);
        } else {
            // Default: show node info
            handleNodeInfo(node, euid);
        }
    }

    /**
     * Handle triple-click on node - show dialog
     */
    function handleTripleClick(node, evt) {
        const nodeData = node.data();
        const dialog = $('#nodeDialog');
        const euid = nodeData.euid;

        // Clear previous COGS values
        $('#actionAOutput').text('');
        $('#actionBOutput').text('');

        // Set dialog content
        dialog.find('#nodeEuid span').text(nodeData.euid);
        dialog.find('#nodeName span').text(nodeData.name);
        dialog.find('#actionALink').attr('href', '/calculate_cogs_parents?euid=' + nodeData.euid);
        dialog.find('#actionBLink').attr('href', '/calculate_cogs_children?euid=' + nodeData.euid);
        dialog.find('#euidInfoLink').attr('href', '/euid_details?euid=' + nodeData.euid);

        // Fetch node name
        DAGAPI.getNodeProperty(euid, 'name')
            .then(function(response) {
                const nodeName = response.name || 'Unknown Name';
                dialog.find('#nodeName span').text(nodeName);
                dialog.css({ top: evt.renderedPosition.y, left: evt.renderedPosition.x }).show();
            })
            .catch(function() {
                dialog.find('#nodeName span').text('Unknown Name');
                dialog.css({ top: evt.renderedPosition.y, left: evt.renderedPosition.x }).show();
            });
    }

    /**
     * Handle neighborhood highlighting when 'n' key is held
     */
    function handleNeighborhoodHighlight(node) {
        if (lastClickedNode && lastClickedNode.id() === node.id()) {
            neighborhoodDepth++;
        } else {
            neighborhoodDepth = 1;
        }
        lastClickedNode = node;

        let neighborhood = node.closedNeighborhood();
        for (let i = 1; i < neighborhoodDepth; i++) {
            neighborhood = neighborhood.union(neighborhood.closedNeighborhood());
        }
        neighborhood.addClass('highlighted');
        
        setTimeout(function() {
            neighborhood.removeClass('highlighted');
        }, DAGConfig.TIMING.NEIGHBORHOOD_HIGHLIGHT);
    }

    /**
     * Handle COGS calculation display
     */
    function handleCogsCalculation(node, euid, key) {
        const position = key === 'p' ? 'above' : 'below';
        const apiCall = key === 'p' ? DAGAPI.calculateCogsParents : DAGAPI.calculateCogsChildren;

        apiCall(euid)
            .then(function(response) {
                displayCogsValue(node, position, response.cogs_value || 'N/A');
            })
            .catch(function(error) {
                console.error('COGS calculation failed:', error);
                displayCogsValue(node, position, 'Error');
            });
    }

    /**
     * Handle edge creation when 'l' key is held
     */
    function handleEdgeCreation(node, cy) {
        if (!selectedChildNode) {
            selectedChildNode = node;
            node.style('background-color', 'red');
        } else {
            // Create edge from parent (current node) to child (selected)
            node.style('background-color', 'red');
            setTimeout(function() {
                node.style('background-color', '');
            }, DAGConfig.TIMING.NODE_FLASH_DURATION);

            const newEdge = cy.add({
                group: 'edges',
                data: { target: selectedChildNode.id(), source: node.id() },
                style: { 'line-color': 'aqua' }
            });

            setTimeout(function() {
                newEdge.style('line-color', '');
            }, DAGConfig.TIMING.EDGE_HIGHLIGHT_DURATION);

            selectedChildNode.style('background-color', '');
            selectedChildNode = null;
        }
    }

    /**
     * Handle node info display
     */
    function handleNodeInfo(node, euid) {
        if (node.isNode()) {
            DAGAPI.getNodeInfo(euid)
                .then(function(data) {
                    if (!data.error) {
                        const jsonAddl = DAGUtils.safeJSONParse(data.json_addl, {});
                        const name = jsonAddl?.properties?.name || 'N/A';
                        const content = 'EUID: ' + data.euid + ' // ' + name + ' // ' +
                            data.uuid + ' ( ' + data.btype + ':::' + data.b_sub_type + ' ) <br>' +
                            'Name: ' + name + ' ( ' + data.status + ' )<br>json_addl: ' + data.json_addl;
                        $('#node-info').html(content).show();
                    } else {
                        $('#node-info').html('Node information not found').show();
                    }
                })
                .catch(function(error) {
                    console.error('Failed to get node info:', error);
                    $('#node-info').html('Error loading node information').show();
                });
        }
    }

    /**
     * Handle node right-click (for deletion)
     */
    function handleNodeRightClick(evt) {
        const cy = DAGGraph.getInstance();
        const node = evt.target;
        const nodeId = node.id();

        const clickCount = nodeRightClickDetector.recordClick(nodeId);

        if (clickCount === 3) {
            cy.remove(node);
            DAGAPI.deleteObject(node.data('euid'))
                .then(function(response) {
                    console.log('Node deletion successful:', response);
                })
                .catch(function(error) {
                    console.error('Error deleting node:', error);
                });
            nodeRightClickDetector.reset(nodeId);
        }
    }

    /**
     * Handle edge right-click (for deletion)
     * Uses timestamp-based double-click detection
     */
    function handleEdgeRightClick(evt) {
        const cy = DAGGraph.getInstance();
        const edge = evt.target;
        const edgeUuid = edge.data('id');
        const currentTime = Date.now();

        // Use longer threshold for better double-click detection
        if (lastEdgeClicked === edge &&
            currentTime - lastEdgeClickTime < DAGConfig.TIMING.DOUBLE_CLICK_THRESHOLD) {
            cy.remove(edge);
            DAGAPI.deleteObject(edgeUuid)
                .then(function(response) {
                    console.log('Edge deletion successful:', response);
                })
                .catch(function(error) {
                    console.error('Error deleting edge:', error);
                });
            lastEdgeClicked = null;
        } else {
            lastEdgeClicked = edge;
            lastEdgeClickTime = currentTime;
        }
    }

    /**
     * Handle new edge addition (cycle detection)
     */
    function handleEdgeAdd(event) {
        const cy = DAGGraph.getInstance();
        const edge = event.target;
        const sourceNodeUuid = edge.data('source');
        const targetNodeUuid = edge.data('target');

        if (doesCreateCycle(sourceNodeUuid, targetNodeUuid)) {
            cy.remove(edge);
            alert("Cannot create edge. It would result in a cycle.");
        } else {
            DAGAPI.addNewEdge(sourceNodeUuid, targetNodeUuid)
                .then(function(response) {
                    edge.data('euid', response.euid);
                })
                .catch(function(error) {
                    console.error('Error adding new edge:', error);
                });
        }
    }

    /**
     * Check if adding an edge would create a cycle
     */
    function doesCreateCycle(sourceId, targetId) {
        const cy = DAGGraph.getInstance();
        let visited = new Set();
        let stack = [targetId];

        while (stack.length > 0) {
            let current = stack.pop();

            if (current === sourceId) {
                return true;
            }

            if (!visited.has(current)) {
                visited.add(current);
                let neighbors = cy.nodes('#' + current).outgoers('node');
                neighbors.forEach(function(node) {
                    if (!visited.has(node.id())) {
                        stack.push(node.id());
                    }
                });
            }
        }

        return false;
    }

    /**
     * Initialize UI button event handlers
     */
    function initializeUIEvents() {
        // Close dialog button
        $('#closeDialogButton').on('click', function() {
            $('#nodeDialog').hide();
            $('#actionAOutput').text('');
            $('#actionBOutput').text('');
        });

        // Make connection button
        $('#makeConnectionButton').click(function() {
            const cy = DAGGraph.getInstance();
            const parentNodeId = $('#parent-node').val();
            const childNodeId = $('#child-node').val();

            if (cy.getElementById(parentNodeId).length && cy.getElementById(childNodeId).length) {
                cy.add({
                    group: 'edges',
                    data: { source: parentNodeId, target: childNodeId }
                });
                DAGGraph.applyLayout({ name: DAGGraph.getCurrentLayout() });
            } else {
                alert('One or both node IDs do not exist.');
            }
        });

        // Add node button
        $('#addNodeButton').click(function() {
            const cy = DAGGraph.getInstance();
            DAGAPI.addNewNode()
                .then(function(response) {
                    cy.add({
                        group: 'nodes',
                        data: { id: response.euid, type: 'child', euid: response.euid, name: 'New Node', btype: '' },
                        position: { x: 100, y: 100 }
                    });
                    DAGGraph.applyLayout({ name: DAGGraph.getCurrentLayout() });
                    console.log('Added new node:', response.euid);
                })
                .catch(function(error) {
                    console.error('Error adding new node:', error);
                });
        });

        // Save button
        $('#saveButton').click(function() {
            const cy = DAGGraph.getInstance();
            DAGAPI.updateDAG(cy.json())
                .then(function() {
                    alert("DAG updated!");
                })
                .catch(function(error) {
                    console.error('Error saving DAG:', error);
                    alert("Failed to save DAG");
                });
        });

        // COGS link handlers
        $('#actionALink').click(function(event) {
            event.preventDefault();
            const euid = $('#nodeEuid span').text();
            DAGAPI.calculateCogsParents(euid)
                .then(function(response) {
                    $('#actionAOutput').text(response.cogs_value || 'N/A');
                })
                .catch(function() {
                    $('#actionAOutput').text('Error');
                });
        });

        $('#actionBLink').click(function(event) {
            event.preventDefault();
            const euid = $('#nodeEuid span').text();
            DAGAPI.calculateCogsChildren(euid)
                .then(function(response) {
                    $('#actionBOutput').text(response.cogs_value || 'N/A');
                })
                .catch(function() {
                    $('#actionBOutput').text('Error');
                });
        });

        // Remove COGS labels on document click
        $(document).on('click', function() {
            $('.cogs-value-label').remove();
        });

        // Help modal handlers
        initializeHelpModal();
    }

    /**
     * Initialize help modal
     */
    function initializeHelpModal() {
        const modal = document.getElementById("helpModal");
        const btn = document.getElementById("helpBtn");
        const span = document.getElementsByClassName("closeBtn")[0];

        if (btn) {
            btn.onclick = function() {
                modal.style.display = "block";
            };
        }

        if (span) {
            span.onclick = function() {
                modal.style.display = "none";
            };
        }

        window.onclick = function(event) {
            if (event.target === modal) {
                modal.style.display = "none";
            }
        };
    }

    // Public API
    return {
        initialize: initialize,
        getKeyHeld: function() { return keyHeld; },
        getSelectedChildNode: function() { return selectedChildNode; },
        setSelectedChildNode: function(node) { selectedChildNode = node; },
        doesCreateCycle: doesCreateCycle
    };
})();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DAGEvents;
}

