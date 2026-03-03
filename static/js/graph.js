/*
 * BLOOM Graph Viewer - Cytoscape graph client
 * TapDB-derived baseline adapted for Bloom routes and auth model.
 */

let cy = null;
window.cy = null;
let keyboardHandlersInstalled = false;
let controlsBound = false;
let pendingLineageChildId = null;
let neighborhoodAnchorId = null;
let neighborhoodDepth = 1;
let activeNodeActionEuid = null;
const tapTracker = new Map();
const graphConfig = window.BloomGraphConfig || {};
const canEdit = !!graphConfig.canEdit;
const graphPath = graphConfig.graphPath || "/dindex2";

const STORAGE_KEY = "bloom_graph_controls_v1";

const keyState = {
    d: false,
    l: false,
    p: false,
    c: false,
    n: false,
    i: false,
};

const DEFAULT_CONTROL_STATE = {
    layout: "dagre",
    edgeThreshold: 1,
    distance: 0,
    searchQuery: "",
    hiddenBtypes: {},
    mutedSubtypes: {},
};

let controlState = {
    ...DEFAULT_CONTROL_STATE,
    hiddenBtypes: {},
    mutedSubtypes: {},
};

const TAP_SEQUENCE_MS = 700;
const WAVE_STEP_MS = 260;
const WAVE_GLOW_MS = 520;

const cytoscapeStyle = [
    {
        selector: "node",
        style: {
            "background-color": "data(color)",
            "label": "data(id)",
            "color": "#fff",
            "text-valign": "bottom",
            "text-halign": "center",
            "font-size": "11px",
            "font-weight": "bold",
            "text-margin-y": "5px",
            "width": "40px",
            "height": "40px",
            "border-width": "2px",
            "border-color": "#333",
            "text-outline-color": "#000",
            "text-outline-width": "2px",
            "shadow-color": "#000",
            "shadow-opacity": 0.25,
            "shadow-blur": 4,
            "transition-property": "background-color, border-color, border-width, shadow-color, shadow-opacity, shadow-blur, opacity",
            "transition-duration": "420ms",
            "opacity": 1,
        },
    },
    {
        selector: "node:selected",
        style: {
            "border-width": "4px",
            "border-color": "#fff",
            "background-color": "#e74c3c",
        },
    },
    {
        selector: "node.link-anchor",
        style: {
            "border-color": "#ffe47a",
            "border-width": "5px",
            "shadow-color": "#ffe47a",
            "shadow-opacity": 0.95,
            "shadow-blur": 22,
        },
    },
    {
        selector: "node.wave-child",
        style: {
            "background-color": "#ff4fa3",
            "border-color": "#ffd7ea",
            "border-width": "5px",
            "shadow-color": "#ff4fa3",
            "shadow-opacity": 0.9,
            "shadow-blur": 26,
        },
    },
    {
        selector: "node.wave-parent",
        style: {
            "background-color": "#26d9ff",
            "border-color": "#cbf7ff",
            "border-width": "5px",
            "shadow-color": "#26d9ff",
            "shadow-opacity": 0.9,
            "shadow-blur": 26,
        },
    },
    {
        selector: "node.neighborhood-glow",
        style: {
            "border-color": "#f7c948",
            "border-width": "5px",
            "shadow-color": "#f7c948",
            "shadow-opacity": 0.9,
            "shadow-blur": 20,
        },
    },
    {
        selector: "node.search-match",
        style: {
            "border-color": "#8be9fd",
            "border-width": "5px",
            "shadow-color": "#8be9fd",
            "shadow-opacity": 0.8,
            "shadow-blur": 16,
        },
    },
    {
        selector: "node.transparent, edge.transparent",
        style: {
            "opacity": 0.14,
        },
    },
    {
        selector: "node.subtype-muted, edge.subtype-muted",
        style: {
            "opacity": 0.24,
        },
    },
    {
        selector: "edge",
        style: {
            "width": 2,
            "line-color": "#666",
            "curve-style": "bezier",
            "source-arrow-shape": "none",
            "target-arrow-shape": "triangle",
            "target-arrow-fill": "filled",
            "target-arrow-color": "#666",
            "source-endpoint": "outside-to-node",
            "target-endpoint": "outside-to-node",
            "target-distance-from-node": 6,
            "arrow-scale": 1.6,
            "opacity": 1,
        },
    },
    {
        selector: "edge:selected",
        style: {
            "line-color": "#e74c3c",
            "target-arrow-color": "#e74c3c",
            "width": 3,
        },
    },
];

function setStatus(message, level = "") {
    const el = document.getElementById("graph-mode-status");
    if (!el) {
        return;
    }
    el.textContent = message;
    el.className = "";
    if (level) {
        el.classList.add(level);
    }
}

function setDetailsCogsOutput(message, isError = false) {
    const el = document.getElementById("details-cogs-output");
    if (!el) {
        return;
    }
    el.textContent = message || "";
    el.style.color = isError ? "#ffd0d0" : "var(--color-gray-300)";
}

function getNodeBtype(node) {
    return node.data("btype") || node.data("obj_type") || node.data("type") || "unknown";
}

function getNodeSubtype(node) {
    return node.data("b_sub_type") || node.data("subtype") || "unknown";
}

function loadPersistedControls() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) {
            return;
        }
        const parsed = JSON.parse(raw);
        controlState = {
            ...DEFAULT_CONTROL_STATE,
            ...parsed,
            hiddenBtypes: { ...(parsed.hiddenBtypes || {}) },
            mutedSubtypes: { ...(parsed.mutedSubtypes || {}) },
        };
    } catch (_err) {
        controlState = {
            ...DEFAULT_CONTROL_STATE,
            hiddenBtypes: {},
            mutedSubtypes: {},
        };
    }
}

function persistControls() {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(controlState));
    } catch (_err) {
        // best effort only
    }
}

function applyControlStateToUI() {
    const layoutEl = document.getElementById("layout-select");
    const transparencyEl = document.getElementById("transparency-slider");
    const distanceEl = document.getElementById("distance-slider");
    const searchEl = document.getElementById("search-query");
    const transparencyDisplay = document.getElementById("transparency-display");
    const distanceDisplay = document.getElementById("distance-display");

    if (layoutEl) {
        layoutEl.value = controlState.layout || DEFAULT_CONTROL_STATE.layout;
    }
    if (transparencyEl) {
        transparencyEl.value = String(controlState.edgeThreshold ?? DEFAULT_CONTROL_STATE.edgeThreshold);
    }
    if (distanceEl) {
        distanceEl.value = String(controlState.distance ?? DEFAULT_CONTROL_STATE.distance);
    }
    if (searchEl) {
        searchEl.value = controlState.searchQuery || "";
    }
    if (transparencyDisplay) {
        transparencyDisplay.textContent = String(controlState.edgeThreshold ?? DEFAULT_CONTROL_STATE.edgeThreshold);
    }
    if (distanceDisplay) {
        distanceDisplay.textContent = String(controlState.distance ?? DEFAULT_CONTROL_STATE.distance);
    }
}

function syncControlStateFromUI() {
    const layoutEl = document.getElementById("layout-select");
    const transparencyEl = document.getElementById("transparency-slider");
    const distanceEl = document.getElementById("distance-slider");
    const searchEl = document.getElementById("search-query");

    if (layoutEl) {
        controlState.layout = layoutEl.value || DEFAULT_CONTROL_STATE.layout;
    }
    if (transparencyEl) {
        controlState.edgeThreshold = Number.parseInt(transparencyEl.value, 10) || 0;
    }
    if (distanceEl) {
        controlState.distance = Number.parseInt(distanceEl.value, 10) || 0;
    }
    if (searchEl) {
        controlState.searchQuery = searchEl.value || "";
    }
}

function bindControlEvents() {
    if (controlsBound) {
        return;
    }
    controlsBound = true;

    const transparencyEl = document.getElementById("transparency-slider");
    const distanceEl = document.getElementById("distance-slider");
    const searchEl = document.getElementById("search-query");
    const findEl = document.getElementById("find-euid");

    if (transparencyEl) {
        transparencyEl.addEventListener("input", () => {
            syncControlStateFromUI();
            applyFiltersAndStyles({ centerSearch: false });
            persistControls();
        });
    }

    if (distanceEl) {
        distanceEl.addEventListener("input", () => {
            syncControlStateFromUI();
            applyFiltersAndStyles({ centerSearch: false });
            persistControls();
        });
    }

    if (searchEl) {
        searchEl.addEventListener("input", () => {
            syncControlStateFromUI();
            applySearch(false);
            persistControls();
        });
        searchEl.addEventListener("keydown", (evt) => {
            if (evt.key === "Enter") {
                evt.preventDefault();
                applySearch(true);
            }
        });
    }

    if (findEl) {
        findEl.addEventListener("keydown", (evt) => {
            if (evt.key === "Enter") {
                evt.preventDefault();
                findAndCenterByEuid();
            }
        });
    }
}

function installKeyboardHandlers() {
    if (keyboardHandlersInstalled) {
        return;
    }
    keyboardHandlersInstalled = true;

    document.addEventListener("keydown", (evt) => {
        const key = (evt.key || "").toLowerCase();
        if (canEdit && key === "d") {
            keyState.d = true;
        }
        if (canEdit && key === "l") {
            keyState.l = true;
            if (!pendingLineageChildId) {
                setStatus("Link mode: hold L and click a child node.", "warn");
            }
        }
        if (key === "p") {
            keyState.p = true;
        }
        if (key === "c") {
            keyState.c = true;
        }
        if (key === "n") {
            keyState.n = true;
        }
        if (key === "i") {
            keyState.i = true;
        }
        if (key === "escape") {
            clearPendingLineageSelection();
            setStatus("Cleared selection.", "warn");
        }
    });

    document.addEventListener("keyup", (evt) => {
        const key = (evt.key || "").toLowerCase();
        if (key === "d") {
            keyState.d = false;
        }
        if (key === "l") {
            keyState.l = false;
        }
        if (key === "p") {
            keyState.p = false;
        }
        if (key === "c") {
            keyState.c = false;
        }
        if (key === "n") {
            keyState.n = false;
        }
        if (key === "i") {
            keyState.i = false;
        }
    });
}

function registerTapSequence(nodeId, button) {
    const key = `${nodeId}|${button}`;
    const now = Date.now();
    const prev = tapTracker.get(key);

    let count = 1;
    if (prev && now - prev.lastTs <= TAP_SEQUENCE_MS) {
        count = prev.count + 1;
    }

    tapTracker.set(key, { count, lastTs: now });

    if (count >= 3) {
        tapTracker.set(key, { count: 0, lastTs: now });
        return true;
    }
    return false;
}

function clearPendingLineageSelection() {
    if (!pendingLineageChildId || !cy) {
        pendingLineageChildId = null;
        return;
    }
    const node = cy.getElementById(pendingLineageChildId);
    if (node && node.length > 0) {
        node.removeClass("link-anchor");
    }
    pendingLineageChildId = null;
}

function setPendingLineageChild(node) {
    clearPendingLineageSelection();
    pendingLineageChildId = node.id();
    node.addClass("link-anchor");
    setStatus(`Link mode: child ${pendingLineageChildId} selected. Click parent node.`, "warn");
}

function collectWaveLevels(startNode, direction) {
    const levels = [];
    const visited = new Set([startNode.id()]);
    let frontier = cy.collection(startNode);

    while (frontier.length > 0) {
        let next = cy.collection();

        frontier.forEach((node) => {
            const neighbors = direction === "children"
                ? node.incomers("edge").sources()
                : node.outgoers("edge").targets();

            neighbors.forEach((neighbor) => {
                const nid = neighbor.id();
                if (!visited.has(nid)) {
                    visited.add(nid);
                    next = next.add(neighbor);
                }
            });
        });

        if (next.length === 0) {
            break;
        }

        levels.push(next);
        frontier = next;
    }

    return levels;
}

function runWaveFromNode(startNode, direction) {
    if (!cy || !startNode) {
        return;
    }

    const levels = collectWaveLevels(startNode, direction);
    if (levels.length === 0) {
        setStatus(`No ${direction} found for ${startNode.id()}.`, "warn");
        return;
    }

    const className = direction === "children" ? "wave-child" : "wave-parent";
    const colorName = direction === "children" ? "pink" : "aqua";
    setStatus(`Running ${direction} wave (${colorName}) from ${startNode.id()}...`, "ok");

    levels.forEach((nodes, index) => {
        window.setTimeout(() => {
            nodes.addClass(className);
            window.setTimeout(() => {
                nodes.removeClass(className);
            }, WAVE_GLOW_MS);
        }, index * WAVE_STEP_MS);
    });
}

function runNeighborhoodFromNode(node) {
    if (!cy || !node) {
        return;
    }

    if (neighborhoodAnchorId === node.id()) {
        neighborhoodDepth += 1;
    } else {
        neighborhoodAnchorId = node.id();
        neighborhoodDepth = 1;
    }

    let neighborhood = node.closedNeighborhood();
    for (let i = 1; i < neighborhoodDepth; i += 1) {
        neighborhood = neighborhood.union(neighborhood.closedNeighborhood());
    }

    const nodeOnly = neighborhood.nodes();
    nodeOnly.addClass("neighborhood-glow");
    window.setTimeout(() => {
        nodeOnly.removeClass("neighborhood-glow");
    }, 900);

    setStatus(`Neighborhood depth ${neighborhoodDepth} from ${node.id()}.`, "ok");
}

async function deleteGraphObject(ele) {
    if (!canEdit) {
        setStatus("Only admins can delete graph objects.", "warn");
        return;
    }
    const objectId = ele.data("id");
    const typeLabel = ele.isNode() ? "node" : "edge";

    try {
        const response = await fetch(`/api/object/${encodeURIComponent(objectId)}`, {
            method: "DELETE",
            headers: { "Accept": "application/json" },
        });

        let payload = {};
        try {
            payload = await response.json();
        } catch (_err) {
            // Non-JSON response.
        }

        if (!response.ok) {
            throw new Error(payload.detail || payload.message || `Failed to delete ${typeLabel}`);
        }

        if (ele && ele.length > 0) {
            ele.remove();
        }

        refreshLegendFromCurrentGraph();
        applyFiltersAndStyles({ centerSearch: false });
        setStatus(`Deleted ${typeLabel} ${objectId}.`, "ok");
    } catch (error) {
        console.error("Delete failed:", error);
        setStatus(`Delete failed: ${error.message}`, "error");
    }
}

function pickRelationshipType(childId, parentId) {
    const dialog = document.getElementById("relationship-dialog");
    const selectEl = document.getElementById("relationship-type-select");
    const contextEl = document.getElementById("relationship-dialog-context");
    const cancelBtn = document.getElementById("relationship-dialog-cancel");
    const createBtn = document.getElementById("relationship-dialog-create");

    if (!dialog || !selectEl || !cancelBtn || !createBtn || typeof dialog.showModal !== "function") {
        const entered = window.prompt(
            `Relationship type for child ${childId} -> parent ${parentId}:`,
            "generic"
        );
        const trimmed = (entered || "").trim();
        return Promise.resolve(trimmed || null);
    }

    contextEl.textContent = `Child: ${childId} -> Parent: ${parentId}`;
    selectEl.value = "generic";

    return new Promise((resolve) => {
        const cleanup = () => {
            cancelBtn.removeEventListener("click", onCancel);
            createBtn.removeEventListener("click", onCreate);
            dialog.removeEventListener("cancel", onCancel);
        };

        const onCancel = () => {
            cleanup();
            dialog.close();
            resolve(null);
        };

        const onCreate = () => {
            const value = (selectEl.value || "").trim();
            cleanup();
            dialog.close();
            resolve(value || "generic");
        };

        cancelBtn.addEventListener("click", onCancel);
        createBtn.addEventListener("click", onCreate);
        dialog.addEventListener("cancel", onCancel);
        dialog.showModal();
    });
}

async function createLineageEdge(childId, parentId, relationshipType) {
    if (!canEdit) {
        setStatus("Only admins can create lineage edges.", "warn");
        return;
    }

    const response = await fetch("/api/lineage", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        body: JSON.stringify({
            child_euid: childId,
            parent_euid: parentId,
            relationship_type: relationshipType || "generic",
        }),
    });

    let payload = {};
    try {
        payload = await response.json();
    } catch (_err) {
        // Non-JSON response.
    }

    if (!response.ok) {
        throw new Error(payload.detail || payload.message || `Failed to create edge (${response.status})`);
    }

    const edgeId = payload.euid || `edge-${Date.now()}`;
    cy.add({
        group: "edges",
        data: {
            id: edgeId,
            source: childId,
            target: parentId,
            relationship_type: relationshipType || "generic",
        },
    });

    refreshLegendFromCurrentGraph();
    applyFiltersAndStyles({ centerSearch: false });
    setStatus(`Created edge ${childId} -> ${parentId} (${relationshipType || "generic"}).`, "ok");
}

function refreshLegendFromCurrentGraph() {
    if (!cy) {
        return;
    }
    const typesInGraph = {};
    cy.nodes().forEach((node) => {
        const data = node.data();
        const category = data.category;
        const color = data.color;
        if (category && color && !typesInGraph[category]) {
            typesInGraph[category] = color;
        }
    });
    updateLegend(typesInGraph);
}

function buildTypeAndSubtypeControls() {
    const typeContainer = document.getElementById("btype-checkboxes");
    const subtypeContainer = document.getElementById("subtype-buttons");

    if (!cy || !typeContainer || !subtypeContainer) {
        return;
    }

    const btypes = Array.from(
        new Set(cy.nodes().map((node) => getNodeBtype(node)).filter(Boolean))
    ).sort((a, b) => a.localeCompare(b));

    const subtypes = Array.from(
        new Set(cy.nodes().map((node) => getNodeSubtype(node)).filter(Boolean))
    ).sort((a, b) => a.localeCompare(b));

    if (btypes.length === 0) {
        typeContainer.innerHTML = "<span style='color: var(--color-gray-400); font-size: 0.78rem;'>No types in graph.</span>";
    } else {
        typeContainer.innerHTML = "";
        btypes.forEach((btype) => {
            if (typeof controlState.hiddenBtypes[btype] === "undefined") {
                controlState.hiddenBtypes[btype] = false;
            }
            const item = document.createElement("label");
            item.className = "type-filter-item";
            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.checked = !controlState.hiddenBtypes[btype];
            checkbox.addEventListener("change", () => {
                controlState.hiddenBtypes[btype] = !checkbox.checked;
                persistControls();
                applyFiltersAndStyles({ centerSearch: false });
            });
            item.appendChild(checkbox);
            item.appendChild(document.createTextNode(btype));
            typeContainer.appendChild(item);
        });
    }

    if (subtypes.length === 0) {
        subtypeContainer.innerHTML = "<span style='color: var(--color-gray-400); font-size: 0.78rem;'>No subtypes in graph.</span>";
    } else {
        subtypeContainer.innerHTML = "";
        subtypes.forEach((subtype) => {
            if (typeof controlState.mutedSubtypes[subtype] === "undefined") {
                controlState.mutedSubtypes[subtype] = false;
            }
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "subtype-chip";
            if (controlState.mutedSubtypes[subtype]) {
                btn.classList.add("active");
            }
            btn.textContent = subtype;
            btn.addEventListener("click", () => {
                controlState.mutedSubtypes[subtype] = !controlState.mutedSubtypes[subtype];
                btn.classList.toggle("active", controlState.mutedSubtypes[subtype]);
                persistControls();
                applyFiltersAndStyles({ centerSearch: false });
            });
            subtypeContainer.appendChild(btn);
        });
    }

    persistControls();
}

function nodeMatchesQuery(node, query) {
    if (!query) {
        return false;
    }
    const q = query.toLowerCase();
    const values = [
        node.id(),
        node.data("name"),
        node.data("euid"),
        node.data("btype"),
        node.data("obj_type"),
        node.data("category"),
        node.data("subtype"),
        node.data("b_sub_type"),
    ];
    return values.some((value) => String(value || "").toLowerCase().includes(q));
}

function getDistanceVisibleNodeIds(distance) {
    if (!cy || distance <= 0) {
        return null;
    }

    let centerNode = cy.$("node:selected").first();
    if (!centerNode || centerNode.length === 0) {
        const startEuid = (document.getElementById("start-euid")?.value || "").trim();
        if (startEuid) {
            centerNode = cy.getElementById(startEuid);
        }
    }
    if (!centerNode || centerNode.length === 0) {
        centerNode = cy.nodes().first();
    }
    if (!centerNode || centerNode.length === 0) {
        return null;
    }

    const visible = new Set([centerNode.id()]);
    cy.elements().bfs({
        roots: centerNode,
        directed: false,
        visit: (v, _e, _u, _i, depth) => {
            if (depth <= distance && v.isNode()) {
                visible.add(v.id());
            }
        },
    });

    return visible;
}

function applyFiltersAndStyles(options = {}) {
    const { centerSearch = false } = options;
    if (!cy) {
        return [];
    }

    syncControlStateFromUI();

    const edgeThreshold = Math.max(0, Number.parseInt(controlState.edgeThreshold, 10) || 0);
    const distance = Math.max(0, Number.parseInt(controlState.distance, 10) || 0);
    const searchQuery = String(controlState.searchQuery || "").trim();

    const transparencyDisplay = document.getElementById("transparency-display");
    const distanceDisplay = document.getElementById("distance-display");
    if (transparencyDisplay) {
        transparencyDisplay.textContent = String(edgeThreshold);
    }
    if (distanceDisplay) {
        distanceDisplay.textContent = String(distance);
    }

    const distanceVisible = getDistanceVisibleNodeIds(distance);
    const visibleNodeIds = new Set();

    cy.batch(() => {
        cy.nodes().forEach((node) => {
            const btype = getNodeBtype(node);
            const passType = !controlState.hiddenBtypes[btype];
            const passDistance = !distanceVisible || distanceVisible.has(node.id());
            const visible = passType && passDistance;
            node.style("display", visible ? "element" : "none");
            node.removeClass("transparent");
            node.removeClass("subtype-muted");
            node.removeClass("search-match");
            if (visible) {
                visibleNodeIds.add(node.id());
            }
        });

        cy.edges().forEach((edge) => {
            const sourceVisible = visibleNodeIds.has(edge.source().id());
            const targetVisible = visibleNodeIds.has(edge.target().id());
            const visible = sourceVisible && targetVisible;
            edge.style("display", visible ? "element" : "none");
            edge.removeClass("transparent");
            edge.removeClass("subtype-muted");
        });

        cy.nodes().forEach((node) => {
            if (node.style("display") === "none") {
                return;
            }
            const subtype = getNodeSubtype(node);
            if (controlState.mutedSubtypes[subtype]) {
                node.addClass("subtype-muted");
            }
        });

        cy.edges().forEach((edge) => {
            if (edge.style("display") === "none") {
                return;
            }
            if (edge.source().hasClass("subtype-muted") || edge.target().hasClass("subtype-muted")) {
                edge.addClass("subtype-muted");
            }
        });

        cy.nodes().forEach((node) => {
            if (node.style("display") === "none") {
                return;
            }
            const visibleEdges = node.connectedEdges().filter((edge) => edge.style("display") !== "none");
            if (visibleEdges.length <= edgeThreshold) {
                node.addClass("transparent");
                visibleEdges.forEach((edge) => edge.addClass("transparent"));
            }
        });
    });

    const matches = [];
    if (searchQuery) {
        cy.nodes().forEach((node) => {
            if (node.style("display") === "none") {
                return;
            }
            if (nodeMatchesQuery(node, searchQuery)) {
                node.addClass("search-match");
                matches.push(node);
            }
        });
    }

    if (centerSearch) {
        if (searchQuery && matches.length > 0) {
            const firstMatch = matches[0];
            cy.animate({
                center: { eles: firstMatch },
                zoom: Math.max(cy.zoom(), 1.2),
            }, { duration: 280 });
            setStatus(`Search matched ${matches.length} node(s).`, "ok");
        } else if (searchQuery) {
            setStatus(`No nodes matched search: ${searchQuery}`, "warn");
        }
    }

    return matches;
}

function parseJsonLike(text) {
    const trimmed = String(text || "").trim();
    if (!trimmed) {
        return {};
    }

    let parsed;
    try {
        parsed = JSON.parse(trimmed);
    } catch (_err) {
        return { message: trimmed };
    }

    if (typeof parsed === "string") {
        try {
            parsed = JSON.parse(parsed);
        } catch (_err) {
            return { message: parsed };
        }
    }

    return parsed;
}

async function fetchCogsValue(kind, euid) {
    const endpoint = kind === "parents"
        ? `/calculate_cogs_parents?euid=${encodeURIComponent(euid)}`
        : `/calculate_cogs_children?euid=${encodeURIComponent(euid)}`;

    const response = await fetch(endpoint, {
        headers: { "Accept": "application/json" },
    });
    const rawText = await response.text();
    const payload = parseJsonLike(rawText);

    if (!response.ok) {
        throw new Error(payload.detail || payload.message || `COGS request failed (${response.status})`);
    }

    if (payload.success === false) {
        throw new Error(payload.message || "COGS calculation failed");
    }

    if (typeof payload.cogs_value === "undefined") {
        throw new Error(payload.message || "COGS value missing from response");
    }

    return payload.cogs_value;
}

async function runCogsForEuid(kind, euid, options = {}) {
    const { updateDetails = false, updateLegacyDialog = false } = options;
    const label = kind === "parents" ? "COGS to produce" : "COGS of children";

    try {
        setStatus(`Calculating ${label} for ${euid}...`, "ok");
        const cogsValue = await fetchCogsValue(kind, euid);
        const message = `${label}: ${cogsValue}`;
        setStatus(`${euid} ${message}`, "ok");

        if (updateDetails) {
            setDetailsCogsOutput(`${euid} ${message}`);
        }

        if (updateLegacyDialog) {
            const el = document.getElementById("node-action-cogs-output");
            if (el) {
                el.textContent = `${euid} ${message}`;
                el.style.color = "var(--color-gray-300)";
            }
        }
    } catch (error) {
        const errMsg = `${label} failed: ${error.message}`;
        setStatus(errMsg, "error");
        if (updateDetails) {
            setDetailsCogsOutput(errMsg, true);
        }
        if (updateLegacyDialog) {
            const el = document.getElementById("node-action-cogs-output");
            if (el) {
                el.textContent = errMsg;
                el.style.color = "#ffd0d0";
            }
        }
    }
}

function openNodeActionDialog(nodeData) {
    const dialog = document.getElementById("node-action-dialog");
    if (!dialog) {
        return;
    }

    activeNodeActionEuid = nodeData?.id || null;
    const euidEl = document.getElementById("node-action-euid");
    const nameEl = document.getElementById("node-action-name");
    const cogsEl = document.getElementById("node-action-cogs-output");

    if (euidEl) {
        euidEl.textContent = activeNodeActionEuid || "-";
    }
    if (nameEl) {
        nameEl.textContent = nodeData?.name || "-";
    }
    if (cogsEl) {
        cogsEl.textContent = "";
    }

    if (typeof dialog.showModal === "function") {
        dialog.showModal();
    }
}

function closeNodeActionDialog() {
    const dialog = document.getElementById("node-action-dialog");
    if (dialog && dialog.open) {
        dialog.close();
    }
}

function runLegacyDialogCogs(kind) {
    if (!activeNodeActionEuid) {
        return;
    }
    runCogsForEuid(kind, activeNodeActionEuid, {
        updateDetails: true,
        updateLegacyDialog: true,
    });
}

function openLegacyDialogObject() {
    if (!activeNodeActionEuid) {
        return;
    }
    window.location.href = `/euid_details?euid=${encodeURIComponent(activeNodeActionEuid)}`;
}

function centerLegacyDialogNode() {
    if (!activeNodeActionEuid) {
        return;
    }
    centerOnNode(activeNodeActionEuid);
}

function openHelpDialog() {
    const dialog = document.getElementById("help-dialog");
    if (dialog && typeof dialog.showModal === "function") {
        dialog.showModal();
    }
}

function closeHelpDialog() {
    const dialog = document.getElementById("help-dialog");
    if (dialog && dialog.open) {
        dialog.close();
    }
}

function initCytoscape(container, elements) {
    if (cy) {
        cy.destroy();
    }

    installKeyboardHandlers();
    clearPendingLineageSelection();

    container.addEventListener("contextmenu", (evt) => {
        evt.preventDefault();
    });

    cy = cytoscape({
        container: container,
        elements: elements,
        style: cytoscapeStyle,
        layout: { name: "dagre", rankDir: "BT", nodeSep: 50, rankSep: 80 },
        minZoom: 0.1,
        maxZoom: 3,
        wheelSensitivity: 0.3,
    });
    window.cy = cy;

    cy.on("tap", "node", async function(evt) {
        const node = evt.target;
        showNodeInfo(node.data());

        if (pendingLineageChildId) {
            const childId = pendingLineageChildId;
            const parentId = node.id();

            if (childId === parentId) {
                setStatus("Child and parent cannot be the same node.", "warn");
                clearPendingLineageSelection();
                return;
            }

            const relationshipType = await pickRelationshipType(childId, parentId);
            if (!relationshipType) {
                clearPendingLineageSelection();
                setStatus("Edge creation cancelled.", "warn");
                return;
            }

            try {
                await createLineageEdge(childId, parentId, relationshipType);
            } catch (error) {
                console.error("Edge creation failed:", error);
                setStatus(`Edge creation failed: ${error.message}`, "error");
            } finally {
                clearPendingLineageSelection();
            }
            return;
        }

        if (canEdit && keyState.l) {
            setPendingLineageChild(node);
            return;
        }

        if (keyState.p) {
            runCogsForEuid("parents", node.id(), { updateDetails: true, updateLegacyDialog: false });
            return;
        }

        if (keyState.c) {
            runCogsForEuid("children", node.id(), { updateDetails: true, updateLegacyDialog: false });
            return;
        }

        if (keyState.n) {
            runNeighborhoodFromNode(node);
            return;
        }

        if (keyState.i) {
            openNodeActionDialog(node.data());
            return;
        }

        if (registerTapSequence(node.id(), "left")) {
            runWaveFromNode(node, "children");
        }
    });

    cy.on("cxttap", "node", async function(evt) {
        const node = evt.target;

        if (canEdit && keyState.d) {
            await deleteGraphObject(node);
            return;
        }

        showNodeInfo(node.data());

        if (registerTapSequence(node.id(), "right")) {
            runWaveFromNode(node, "parents");
        }
    });

    cy.on("tap", "edge", function(evt) {
        const edge = evt.target;
        showEdgeInfo(edge.data());
    });

    cy.on("cxttap", "edge", async function(evt) {
        const edge = evt.target;

        if (canEdit && keyState.d) {
            await deleteGraphObject(edge);
            return;
        }

        showEdgeInfo(edge.data());
    });

    cy.on("dbltap", "node", function(evt) {
        const euid = evt.target.data("id");
        window.location.href = "/euid_details?euid=" + encodeURIComponent(euid);
    });

    setStatus("Ready.", "");
    return cy;
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll("\"", "&quot;")
        .replaceAll("'", "&#39;");
}

function prettyJson(value) {
    if (value === undefined) {
        return "{}";
    }
    return JSON.stringify(value === null ? {} : value, null, 2);
}

function topLevelRowValue(key, value) {
    if (value === null || value === undefined || value === "") {
        return "<span style=\"color: var(--color-gray-400);\">-</span>";
    }
    if (key === "json_addl") {
        return "<span style=\"color: var(--color-gray-400);\">See JSON section below</span>";
    }
    if (typeof value === "object") {
        return `<code>${escapeHtml(JSON.stringify(value))}</code>`;
    }
    return escapeHtml(String(value));
}

function renderDetailsPanel({ euid, objectData, graphData, isNode }) {
    const content = document.getElementById("node-info-content");
    if (!content) {
        return;
    }

    const merged = { ...(objectData || {}) };
    if (!Object.prototype.hasOwnProperty.call(merged, "euid")) {
        merged.euid = euid;
    }

    const preferredKeys = [
        "uuid",
        "euid",
        "name",
        "type",
        "obj_type",
        "category",
        "subtype",
        "version",
        "bstatus",
        "source",
        "target",
        "relationship_type",
        "created_dt",
        "modified_dt",
        "json_addl",
    ];
    const remainingKeys = Object.keys(merged)
        .filter((k) => !preferredKeys.includes(k))
        .sort();
    const keys = preferredKeys.filter((k) => Object.prototype.hasOwnProperty.call(merged, k)).concat(remainingKeys);

    const topLevelRows = keys.map((key) => `
        <div class="detail-key">${escapeHtml(key)}</div>
        <div class="detail-value">${topLevelRowValue(key, merged[key])}</div>
    `).join("");

    const rawObjectPayload = objectData || {};
    const graphPayload = graphData || {};
    const jsonPayload = Object.prototype.hasOwnProperty.call(merged, "json_addl")
        ? merged.json_addl
        : {};

    const actions = `
        <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.8rem;">
            <a href="/euid_details?euid=${encodeURIComponent(euid)}" class="btn btn-outline btn-sm">View Details</a>
            ${isNode ? `<button onclick="centerOnNode('${escapeHtml(euid)}')" class="btn btn-outline btn-sm">Center</button>` : ""}
            ${isNode ? `<button onclick="runDetailsCogs('parents', '${escapeHtml(euid)}')" class="btn btn-outline btn-sm">COGS To Produce</button>` : ""}
            ${isNode ? `<button onclick="runDetailsCogs('children', '${escapeHtml(euid)}')" class="btn btn-outline btn-sm">COGS Of Children</button>` : ""}
            ${isNode ? `<button onclick="openNodeActionDialog({ id: '${escapeHtml(euid)}', name: '${escapeHtml(merged.name || "")}'} )" class="btn btn-outline btn-sm">Legacy Actions</button>` : ""}
        </div>
    `;

    content.innerHTML = `
        ${actions}
        <div class="details-section-title">Top-Level Properties</div>
        <div class="details-grid">${topLevelRows || "<span style='color: var(--color-gray-400);'>No properties.</span>"}</div>
        <div class="details-section-title">Raw Object JSON</div>
        <pre class="json-block">${escapeHtml(prettyJson(rawObjectPayload))}</pre>
        <div class="details-section-title">JSON (json_addl)</div>
        <pre class="json-block">${escapeHtml(prettyJson(jsonPayload))}</pre>
        <div class="details-section-title">Graph Payload</div>
        <pre class="json-block">${escapeHtml(prettyJson(graphPayload))}</pre>
    `;
}

async function fetchObjectData(euid) {
    const response = await fetch(`/api/object/${encodeURIComponent(euid)}`, {
        headers: { "Accept": "application/json" },
    });
    if (!response.ok) {
        throw new Error(`Failed to load object details (${response.status})`);
    }
    return response.json();
}

async function showNodeInfo(data) {
    const content = document.getElementById("node-info-content");
    if (content) {
        content.innerHTML = "<p style='color: var(--color-gray-400);'>Loading node details...</p>";
    }
    try {
        const objectData = await fetchObjectData(data.id);
        renderDetailsPanel({
            euid: data.id,
            objectData,
            graphData: data,
            isNode: true,
        });
    } catch (error) {
        console.error("Failed to load node details:", error);
        renderDetailsPanel({
            euid: data.id,
            objectData: {
                euid: data.id,
                name: data.name,
                category: data.category,
                type: data.type,
                subtype: data.subtype,
            },
            graphData: data,
            isNode: true,
        });
        setStatus(`Could not load full node details: ${error.message}`, "warn");
    }
}

async function showEdgeInfo(data) {
    const content = document.getElementById("node-info-content");
    if (content) {
        content.innerHTML = "<p style='color: var(--color-gray-400);'>Loading edge details...</p>";
    }
    try {
        const objectData = await fetchObjectData(data.id);
        renderDetailsPanel({
            euid: data.id,
            objectData,
            graphData: data,
            isNode: false,
        });
    } catch (error) {
        console.error("Failed to load edge details:", error);
        renderDetailsPanel({
            euid: data.id,
            objectData: {
                euid: data.id,
                source: data.source,
                target: data.target,
                relationship_type: data.relationship_type || "related",
            },
            graphData: data,
            isNode: false,
        });
        setStatus(`Could not load full edge details: ${error.message}`, "warn");
    }
}

function runDetailsCogs(kind, euid) {
    runCogsForEuid(kind, euid, { updateDetails: true, updateLegacyDialog: false });
}

function centerOnNode(nodeId) {
    if (!cy) {
        return;
    }
    const node = cy.getElementById(nodeId);
    if (node.length > 0) {
        cy.animate({ center: { eles: node }, zoom: Math.max(cy.zoom(), 1.45) }, { duration: 300 });
        node.select();
    }
}

function applyLayout(shouldPersist = true) {
    if (!cy) {
        return;
    }

    const layoutName = document.getElementById("layout-select").value;
    const layoutOptions = {
        dagre: { name: "dagre", rankDir: "BT", nodeSep: 50, rankSep: 80 },
        cose: { name: "cose", animate: true, animationDuration: 500 },
        breadthfirst: { name: "breadthfirst", directed: true, spacingFactor: 1.5 },
        circle: { name: "circle" },
        grid: { name: "grid" },
    };

    controlState.layout = layoutName;
    if (shouldPersist) {
        persistControls();
    }

    cy.layout(layoutOptions[layoutName] || { name: layoutName }).run();
}

function applySearch(center = true) {
    syncControlStateFromUI();
    persistControls();
    return applyFiltersAndStyles({ centerSearch: center });
}

function findAndCenterByEuid(explicitEuid = "") {
    if (!cy) {
        return false;
    }
    const inputEl = document.getElementById("find-euid");
    const value = (explicitEuid || inputEl?.value || "").trim();
    if (!value) {
        setStatus("Enter an EUID to find.", "warn");
        return false;
    }

    const node = cy.getElementById(value);
    if (!node || node.length === 0 || node.style("display") === "none") {
        setStatus(`EUID not found in current graph view: ${value}`, "warn");
        return false;
    }

    centerOnNode(value);
    setStatus(`Centered on ${value}.`, "ok");
    return true;
}

async function loadGraph() {
    syncControlStateFromUI();
    persistControls();

    const startEuid = (document.getElementById("start-euid")?.value || "").trim();
    const depth = document.getElementById("depth")?.value || "4";

    const container = document.getElementById("cy");
    container.innerHTML = "<div class='loading'>Loading graph data...</div>";

    try {
        let url = "/api/graph/data?depth=" + encodeURIComponent(depth);
        if (startEuid) {
            url += "&start_euid=" + encodeURIComponent(startEuid);
        }

        const response = await fetch(url, { headers: { "Accept": "application/json" } });
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Failed to load graph data");
        }

        if (!data.elements || !Array.isArray(data.elements.nodes) || data.elements.nodes.length === 0) {
            container.innerHTML = "<div class='loading'>No data found for this start node/depth.</div>";
            updateLegend({});
            setStatus("No graph data found for this query.", "warn");
            return;
        }

        container.innerHTML = "";
        initCytoscape(container, data.elements);

        const typesInGraph = {};
        data.elements.nodes.forEach((node) => {
            const category = node.data.category;
            const color = node.data.color;
            if (category && !typesInGraph[category]) {
                typesInGraph[category] = color;
            }
        });
        updateLegend(typesInGraph);

        buildTypeAndSubtypeControls();
        applyControlStateToUI();
        applyLayout(false);
        applyFiltersAndStyles({ centerSearch: !!controlState.searchQuery });

        const newUrl = `${graphPath}?start_euid=${encodeURIComponent(startEuid)}&depth=${encodeURIComponent(depth)}`;
        window.history.replaceState({}, "", newUrl);
        setStatus("Graph loaded.", "ok");
    } catch (error) {
        console.error("Error loading graph:", error);
        container.innerHTML = `<div class='loading'>Error loading graph: ${escapeHtml(error.message)}</div>`;
        updateLegend({});
        setStatus(`Load failed: ${error.message}`, "error");
    }
}

function updateLegend(typesInGraph) {
    const legendContainer = document.getElementById("legend-items");
    if (!legendContainer) {
        return;
    }

    if (Object.keys(typesInGraph).length === 0) {
        legendContainer.innerHTML = "<span style='color: var(--color-gray-400); font-size: 0.85rem;'>No nodes in graph</span>";
        return;
    }

    const sortedTypes = Object.keys(typesInGraph).sort();
    legendContainer.innerHTML = sortedTypes.map((type) => `
        <div class="legend-item">
            <div class="legend-color" style="background:${typesInGraph[type]}"></div>
            ${escapeHtml(type)}
        </div>
    `).join("");
}

function initGraphPage() {
    loadPersistedControls();
    applyControlStateToUI();
    bindControlEvents();
    loadGraph();
}

window.initGraphPage = initGraphPage;
window.loadGraph = loadGraph;
window.applyLayout = applyLayout;
window.applySearch = applySearch;
window.findAndCenterByEuid = findAndCenterByEuid;
window.centerOnNode = centerOnNode;
window.runDetailsCogs = runDetailsCogs;
window.openNodeActionDialog = openNodeActionDialog;
window.closeNodeActionDialog = closeNodeActionDialog;
window.runLegacyDialogCogs = runLegacyDialogCogs;
window.openLegacyDialogObject = openLegacyDialogObject;
window.centerLegacyDialogNode = centerLegacyDialogNode;
window.openHelpDialog = openHelpDialog;
window.closeHelpDialog = closeHelpDialog;
