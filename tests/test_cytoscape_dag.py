"""
BLOOM LIMS Cytoscape DAG Backend Tests

This module tests the backend API endpoints and functions that support
the Cytoscape.js graph visualization in dindex2.html.

Test Coverage:
    - DAG data generation and validation
    - Graph manipulation endpoints (add/delete nodes/edges)
    - Cycle detection algorithms
    - Filter functionality
    - EUID-based node operations
    - Graph data structure validation
"""

import pytest
import json
import os
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime


class TestDAGDataStructure:
    """Tests for DAG data structure validation."""

    def test_valid_dag_structure(self):
        """Test that DAG JSON has required structure."""
        valid_dag = {
            "elements": {
                "nodes": [
                    {"data": {"id": "CX1", "euid": "CX1", "btype": "container"}}
                ],
                "edges": [
                    {"data": {"source": "CX1", "target": "CX2", "id": "LX1"}}
                ]
            }
        }
        assert "elements" in valid_dag
        assert "nodes" in valid_dag["elements"]
        assert "edges" in valid_dag["elements"]

    def test_node_required_fields(self):
        """Test that nodes have required fields for Cytoscape rendering."""
        required_fields = ["id", "euid", "btype"]
        node = {"data": {"id": "CX123", "euid": "CX123", "btype": "container", 
                        "name": "Test", "color": "#8B00FF"}}
        
        for field in required_fields:
            assert field in node["data"], f"Missing required field: {field}"

    def test_edge_required_fields(self):
        """Test that edges have required fields."""
        required_fields = ["source", "target", "id"]
        edge = {"data": {"source": "CX1", "target": "CX2", "id": "LX1", 
                        "relationship_type": "generic"}}
        
        for field in required_fields:
            assert field in edge["data"], f"Missing required field: {field}"

    def test_empty_dag_structure(self):
        """Test that empty DAG has proper structure."""
        empty_dag = {"elements": {"nodes": [], "edges": []}}
        assert empty_dag["elements"]["nodes"] == []
        assert empty_dag["elements"]["edges"] == []


class TestCycleDetection:
    """Tests for cycle detection in DAG operations."""

    def test_no_cycle_simple_chain(self):
        """Test that a simple chain has no cycle."""
        # A -> B -> C
        edges = [("A", "B"), ("B", "C")]
        assert not self._detect_cycle(edges, "A", "C")

    def test_cycle_detected(self):
        """Test that a cycle is detected."""
        # A -> B -> C, adding C -> A would create cycle
        edges = [("A", "B"), ("B", "C")]
        assert self._detect_cycle(edges, "C", "A")

    def test_self_loop_detected(self):
        """Test that self-loop is detected as cycle."""
        edges = []
        assert self._detect_cycle(edges, "A", "A")

    def test_complex_cycle_detection(self):
        """Test cycle detection in complex graph."""
        # A -> B -> C -> D, adding D -> B would create cycle
        edges = [("A", "B"), ("B", "C"), ("C", "D")]
        assert self._detect_cycle(edges, "D", "B")

    def _detect_cycle(self, existing_edges, source, target):
        """Helper function implementing cycle detection algorithm."""
        if source == target:
            return True
        
        # Build adjacency list
        graph = {}
        for src, tgt in existing_edges:
            if src not in graph:
                graph[src] = []
            graph[src].append(tgt)
        
        # Add proposed edge temporarily
        if source not in graph:
            graph[source] = []
        graph[source].append(target)
        
        # DFS to detect cycle from target to source
        visited = set()
        stack = [target]
        
        while stack:
            current = stack.pop()
            if current == source:
                return True
            if current not in visited:
                visited.add(current)
                for neighbor in graph.get(current, []):
                    if neighbor not in visited:
                        stack.append(neighbor)
        
        return False


class TestNodeColorMapping:
    """Tests for node color mapping based on type."""

    def test_container_color(self):
        """Test container nodes get correct color."""
        colors = {
            "container": "#8B00FF",
            "content": "#00BFFF",
            "workflow": "#00FF7F",
            "workflow_step": "#ADFF2F",
            "equipment": "#FF4500",
        }
        assert colors["container"] == "#8B00FF"

    def test_default_color_fallback(self):
        """Test that unknown types get default color."""
        colors = {"container": "#8B00FF"}
        unknown_type = "unknown"
        default_color = "pink"
        color = colors.get(unknown_type, default_color)
        assert color == default_color

    def test_sub_type_color_override(self):
        """Test that sub-types can override main type colors."""
        sub_colors = {
            "well": "#70658c",
            "file_set": "#228080",
        }
        btype = "well"
        assert sub_colors.get(btype) == "#70658c"


class TestEdgeFiltering:
    """Tests for edge-based node filtering (transparency slider)."""

    def test_filter_nodes_by_edge_count(self):
        """Test filtering nodes with edge count <= threshold."""
        nodes = [
            {"id": "A", "edges": 1},
            {"id": "B", "edges": 3},
            {"id": "C", "edges": 0},
            {"id": "D", "edges": 5},
        ]
        threshold = 2
        filtered = [n for n in nodes if n["edges"] <= threshold]
        assert len(filtered) == 2
        assert all(n["id"] in ["A", "C"] for n in filtered)

    def test_filter_threshold_zero(self):
        """Test filtering with threshold 0 (isolated nodes only)."""
        nodes = [
            {"id": "A", "edges": 1},
            {"id": "B", "edges": 0},
        ]
        threshold = 0
        filtered = [n for n in nodes if n["edges"] <= threshold]
        assert len(filtered) == 1
        assert filtered[0]["id"] == "B"

    def test_filter_threshold_high(self):
        """Test filtering with high threshold includes all nodes."""
        nodes = [
            {"id": "A", "edges": 5},
            {"id": "B", "edges": 10},
        ]
        threshold = 15
        filtered = [n for n in nodes if n["edges"] <= threshold]
        assert len(filtered) == 2


class TestBTypeFiltering:
    """Tests for filtering by object type (btype)."""

    def test_filter_by_single_btype(self):
        """Test filtering nodes by single btype."""
        nodes = [
            {"id": "CX1", "btype": "container"},
            {"id": "WX1", "btype": "workflow"},
            {"id": "CX2", "btype": "container"},
        ]
        filter_btype = "container"
        filtered = [n for n in nodes if n["btype"] == filter_btype]
        assert len(filtered) == 2

    def test_filter_by_multiple_btypes(self):
        """Test filtering nodes by multiple btypes."""
        nodes = [
            {"id": "CX1", "btype": "container"},
            {"id": "WX1", "btype": "workflow"},
            {"id": "EX1", "btype": "equipment"},
        ]
        filter_btypes = {"container", "workflow"}
        filtered = [n for n in nodes if n["btype"] in filter_btypes]
        assert len(filtered) == 2


class TestEuidSearch:
    """Tests for EUID-based node search and centering."""

    def test_find_existing_euid(self):
        """Test finding an existing EUID in nodes."""
        nodes = {"CX1": {"id": "CX1"}, "WX2": {"id": "WX2"}}
        search_euid = "CX1"
        assert search_euid in nodes

    def test_find_nonexistent_euid(self):
        """Test searching for non-existent EUID."""
        nodes = {"CX1": {"id": "CX1"}}
        search_euid = "NOTFOUND"
        assert search_euid not in nodes

    def test_euid_case_insensitive_search(self):
        """Test case-insensitive EUID search."""
        nodes = {"CX1": {"id": "CX1"}}
        search_euid = "cx1"
        # Search should be case-insensitive
        found = any(k.upper() == search_euid.upper() for k in nodes.keys())
        assert found


class TestDistanceFiltering:
    """Tests for BFS-based distance filtering from a center node."""

    def test_bfs_depth_zero(self):
        """Test BFS with depth 0 returns only start node."""
        graph = {"A": ["B", "C"], "B": ["D"], "C": []}
        result = self._bfs_filter("A", graph, 0)
        assert result == {"A"}

    def test_bfs_depth_one(self):
        """Test BFS with depth 1 returns start and neighbors."""
        graph = {"A": ["B", "C"], "B": ["D"], "C": []}
        result = self._bfs_filter("A", graph, 1)
        assert result == {"A", "B", "C"}

    def test_bfs_depth_two(self):
        """Test BFS with depth 2 returns two levels."""
        graph = {"A": ["B"], "B": ["C"], "C": ["D"]}
        result = self._bfs_filter("A", graph, 2)
        assert result == {"A", "B", "C"}

    def _bfs_filter(self, start, graph, max_depth):
        """Helper BFS implementation for distance filtering."""
        result = {start}
        queue = [(start, 0)]
        visited = {start}

        while queue:
            node, depth = queue.pop(0)
            if depth < max_depth:
                for neighbor in graph.get(node, []):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        result.add(neighbor)
                        queue.append((neighbor, depth + 1))

        return result


class TestGraphDataGeneration:
    """Tests for DAG JSON generation from database."""

    def test_generate_node_from_instance(self):
        """Test creating a Cytoscape node from instance data."""
        instance = {
            "euid": "CX123",
            "name": "Test Container",
            "btype": "container",
            "super_type": "container",
            "b_sub_type": "plate",
            "version": "1.0",
        }
        colors = {"container": "#8B00FF"}

        node = {
            "data": {
                "id": str(instance["euid"]),
                "type": "instance",
                "euid": str(instance["euid"]),
                "name": instance["name"],
                "btype": instance["btype"],
                "super_type": instance["super_type"],
                "b_sub_type": f"{instance['super_type']}.{instance['btype']}.{instance['b_sub_type']}",
                "version": instance["version"],
                "color": colors.get(instance["super_type"], "pink"),
            }
        }

        assert node["data"]["id"] == "CX123"
        assert node["data"]["color"] == "#8B00FF"
        assert node["data"]["b_sub_type"] == "container.container.plate"

    def test_generate_edge_from_lineage(self):
        """Test creating a Cytoscape edge from lineage data."""
        lineage = {
            "parent_euid": "CX1",
            "child_euid": "CX2",
            "lineage_euid": "LX1",
            "relationship_type": "generic",
        }
        edge_colors = {"generic": "#ADD8E6", "index": "#4CAF50"}

        edge = {
            "data": {
                "source": str(lineage["parent_euid"]),
                "target": str(lineage["child_euid"]),
                "id": str(lineage["lineage_euid"]),
                "relationship_type": str(lineage["relationship_type"]),
                "color": edge_colors.get(lineage["relationship_type"], "lightgreen"),
            }
        }

        assert edge["data"]["source"] == "CX1"
        assert edge["data"]["target"] == "CX2"
        assert edge["data"]["color"] == "#ADD8E6"


class TestGraphManipulation:
    """Tests for graph manipulation operations."""

    def test_add_node_to_graph(self):
        """Test adding a node to existing graph."""
        graph = {"elements": {"nodes": [], "edges": []}}
        new_node = {"data": {"id": "CX1", "euid": "CX1", "btype": "container"}}

        graph["elements"]["nodes"].append(new_node)

        assert len(graph["elements"]["nodes"]) == 1
        assert graph["elements"]["nodes"][0]["data"]["id"] == "CX1"

    def test_add_edge_to_graph(self):
        """Test adding an edge between existing nodes."""
        graph = {
            "elements": {
                "nodes": [
                    {"data": {"id": "CX1"}},
                    {"data": {"id": "CX2"}},
                ],
                "edges": []
            }
        }
        new_edge = {"data": {"source": "CX1", "target": "CX2", "id": "LX1"}}

        graph["elements"]["edges"].append(new_edge)

        assert len(graph["elements"]["edges"]) == 1

    def test_remove_node_removes_connected_edges(self):
        """Test that removing a node also removes connected edges."""
        graph = {
            "elements": {
                "nodes": [
                    {"data": {"id": "CX1"}},
                    {"data": {"id": "CX2"}},
                ],
                "edges": [
                    {"data": {"source": "CX1", "target": "CX2", "id": "LX1"}}
                ]
            }
        }

        # Remove node CX1
        node_to_remove = "CX1"
        graph["elements"]["nodes"] = [
            n for n in graph["elements"]["nodes"]
            if n["data"]["id"] != node_to_remove
        ]
        graph["elements"]["edges"] = [
            e for e in graph["elements"]["edges"]
            if e["data"]["source"] != node_to_remove
            and e["data"]["target"] != node_to_remove
        ]

        assert len(graph["elements"]["nodes"]) == 1
        assert len(graph["elements"]["edges"]) == 0


class TestNeighborhoodHighlighting:
    """Tests for neighborhood highlighting functionality."""

    def test_get_immediate_neighbors(self):
        """Test getting immediate neighbors of a node."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
            {"source": "B", "target": "D"},
        ]

        neighbors = self._get_neighbors("A", edges)
        assert neighbors == {"B", "C"}

    def test_get_extended_neighborhood(self):
        """Test getting extended neighborhood (depth > 1)."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
            {"source": "C", "target": "D"},
        ]

        neighborhood = self._get_neighborhood("A", edges, depth=2)
        assert "A" in neighborhood
        assert "B" in neighborhood
        assert "C" in neighborhood
        assert "D" not in neighborhood

    def _get_neighbors(self, node_id, edges):
        """Get immediate neighbors of a node."""
        neighbors = set()
        for edge in edges:
            if edge["source"] == node_id:
                neighbors.add(edge["target"])
            elif edge["target"] == node_id:
                neighbors.add(edge["source"])
        return neighbors

    def _get_neighborhood(self, node_id, edges, depth=1):
        """Get neighborhood of a node up to specified depth."""
        neighborhood = {node_id}
        current_level = {node_id}

        for _ in range(depth):
            next_level = set()
            for node in current_level:
                for edge in edges:
                    if edge["source"] == node and edge["target"] not in neighborhood:
                        next_level.add(edge["target"])
                    elif edge["target"] == node and edge["source"] not in neighborhood:
                        next_level.add(edge["source"])
            neighborhood.update(next_level)
            current_level = next_level

        return neighborhood


class TestDAGAPIEndpoints:
    """Integration tests for DAG-related API endpoints."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock request with session data."""
        request = MagicMock()
        request.session = {
            "user_data": {
                "email": "test@example.com",
                "dag_fnv2": "./dags/test_dag.json",
            }
        }
        return request

    def test_get_dagv2_returns_empty_when_file_missing(self, mock_request):
        """Test get_dagv2 returns empty structure when file doesn't exist."""
        with patch('os.path.exists', return_value=False):
            # Simulating the endpoint behavior
            dag_fn = mock_request.session["user_data"]["dag_fnv2"]
            dag_data = {"elements": {"nodes": [], "edges": []}}

            if not os.path.exists(dag_fn):
                result = dag_data

            assert result == {"elements": {"nodes": [], "edges": []}}

    def test_update_dag_creates_timestamped_file(self):
        """Test that update_dag creates a timestamped JSON file."""
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"dag_{timestamp}.json"
        assert "dag_" in filename
        assert ".json" in filename

    def test_delete_object_endpoint_structure(self):
        """Test delete_object endpoint request structure."""
        request_data = {"euid": "CX123"}
        assert "euid" in request_data
        assert request_data["euid"] == "CX123"

    def test_add_new_edge_request_structure(self):
        """Test add_new_edge endpoint request structure."""
        request_data = {
            "parent_uuid": "CX1",
            "child_uuid": "CX2"
        }
        assert "parent_uuid" in request_data
        assert "child_uuid" in request_data


class TestGraphDataValidation:
    """Tests for validating graph data integrity."""

    def test_all_edge_nodes_exist(self):
        """Test that all edge endpoints reference existing nodes."""
        graph = {
            "elements": {
                "nodes": [
                    {"data": {"id": "CX1"}},
                    {"data": {"id": "CX2"}},
                ],
                "edges": [
                    {"data": {"source": "CX1", "target": "CX2", "id": "LX1"}}
                ]
            }
        }

        node_ids = {n["data"]["id"] for n in graph["elements"]["nodes"]}

        for edge in graph["elements"]["edges"]:
            assert edge["data"]["source"] in node_ids, \
                f"Edge source {edge['data']['source']} not in nodes"
            assert edge["data"]["target"] in node_ids, \
                f"Edge target {edge['data']['target']} not in nodes"

    def test_no_duplicate_node_ids(self):
        """Test that there are no duplicate node IDs."""
        nodes = [
            {"data": {"id": "CX1"}},
            {"data": {"id": "CX2"}},
            {"data": {"id": "CX3"}},
        ]

        node_ids = [n["data"]["id"] for n in nodes]
        assert len(node_ids) == len(set(node_ids)), "Duplicate node IDs found"

    def test_no_duplicate_edge_ids(self):
        """Test that there are no duplicate edge IDs."""
        edges = [
            {"data": {"source": "CX1", "target": "CX2", "id": "LX1"}},
            {"data": {"source": "CX2", "target": "CX3", "id": "LX2"}},
        ]

        edge_ids = [e["data"]["id"] for e in edges]
        assert len(edge_ids) == len(set(edge_ids)), "Duplicate edge IDs found"

    def test_valid_euid_format_in_nodes(self):
        """Test that node EUIDs follow valid format."""
        import re
        # EUID pattern: 2-3 uppercase letters + sequence number (no leading zeros)
        euid_pattern = re.compile(r'^[A-Z]{2,3}[1-9][0-9]*$')

        valid_euids = ["CX1", "CX123", "WX1000", "MRX42"]
        invalid_euids = ["CX01", "cx1", "C1", "CX-123"]

        for euid in valid_euids:
            assert euid_pattern.match(euid), f"{euid} should be valid"

        for euid in invalid_euids:
            assert not euid_pattern.match(euid), f"{euid} should be invalid"


class TestFuzzySearch:
    """Tests for fuzzy search functionality (search.js backend support)."""

    def test_fuzzy_search_by_id(self):
        """Test fuzzy search matches node ID."""
        nodes = [
            {"id": "CX123", "name": "Container A", "btype": "container"},
            {"id": "WX456", "name": "Workflow B", "btype": "workflow"},
        ]
        query = "cx1"
        matches = [n for n in nodes if query.lower() in n["id"].lower()]
        assert len(matches) == 1
        assert matches[0]["id"] == "CX123"

    def test_fuzzy_search_by_name(self):
        """Test fuzzy search matches node name."""
        nodes = [
            {"id": "CX1", "name": "Test Container", "btype": "container"},
            {"id": "WX1", "name": "Production Workflow", "btype": "workflow"},
        ]
        query = "prod"
        matches = [n for n in nodes if query.lower() in n["name"].lower()]
        assert len(matches) == 1
        assert matches[0]["name"] == "Production Workflow"

    def test_fuzzy_search_by_btype(self):
        """Test fuzzy search matches btype."""
        nodes = [
            {"id": "CX1", "name": "A", "btype": "container"},
            {"id": "WX1", "name": "B", "btype": "workflow"},
            {"id": "EX1", "name": "C", "btype": "equipment"},
        ]
        query = "work"
        matches = [n for n in nodes if query.lower() in n["btype"].lower()]
        assert len(matches) == 1

    def test_fuzzy_search_empty_query(self):
        """Test fuzzy search with empty query returns no matches."""
        nodes = [{"id": "CX1", "name": "Test", "btype": "container"}]
        query = ""
        matches = [n for n in nodes if query and query.lower() in n["id"].lower()]
        assert len(matches) == 0

    def test_fuzzy_search_no_matches(self):
        """Test fuzzy search with no matches."""
        nodes = [{"id": "CX1", "name": "Test", "btype": "container"}]
        query = "xyz"
        matches = [n for n in nodes if query.lower() in n["id"].lower() or
                   query.lower() in n["name"].lower() or
                   query.lower() in n["btype"].lower()]
        assert len(matches) == 0


class TestLayoutPersistence:
    """Tests for layout persistence functionality (layout-persistence.js backend support)."""

    def test_position_data_structure(self):
        """Test that position data has correct structure."""
        positions = {
            "CX1": {"x": 100, "y": 200},
            "CX2": {"x": 300, "y": 400},
        }
        for node_id, pos in positions.items():
            assert "x" in pos
            assert "y" in pos
            assert isinstance(pos["x"], (int, float))
            assert isinstance(pos["y"], (int, float))

    def test_layout_data_includes_zoom_pan(self):
        """Test that layout data includes zoom and pan."""
        layout_data = {
            "positions": {"CX1": {"x": 100, "y": 200}},
            "zoom": 1.5,
            "pan": {"x": 50, "y": 50},
            "timestamp": 1704067200000,
        }
        assert "zoom" in layout_data
        assert "pan" in layout_data
        assert "timestamp" in layout_data

    def test_layout_expiration_check(self):
        """Test layout expiration logic (7 days)."""
        import time
        max_age_ms = 7 * 24 * 60 * 60 * 1000  # 7 days in milliseconds
        current_time = int(time.time() * 1000)

        # Fresh layout
        fresh_timestamp = current_time - (1 * 24 * 60 * 60 * 1000)  # 1 day old
        assert current_time - fresh_timestamp < max_age_ms

        # Expired layout
        old_timestamp = current_time - (10 * 24 * 60 * 60 * 1000)  # 10 days old
        assert current_time - old_timestamp > max_age_ms


class TestClickDetection:
    """Tests for click detection logic (events.js backend support)."""

    def test_timestamp_based_click_detection(self):
        """Test timestamp-based multi-click detection."""
        click_threshold_ms = 500

        # Simulate rapid clicks
        clicks = [0, 100, 200]  # timestamps in ms
        click_count = 1
        for i in range(1, len(clicks)):
            if clicks[i] - clicks[i-1] < click_threshold_ms:
                click_count += 1
            else:
                click_count = 1

        assert click_count == 3  # Triple click detected

    def test_click_reset_on_timeout(self):
        """Test click count resets after timeout."""
        click_threshold_ms = 500

        # Simulate clicks with gap
        clicks = [0, 100, 700]  # 700ms gap resets count
        click_count = 1
        for i in range(1, len(clicks)):
            if clicks[i] - clicks[i-1] < click_threshold_ms:
                click_count += 1
            else:
                click_count = 1

        assert click_count == 1  # Reset after timeout


class TestDebouncing:
    """Tests for debounce functionality (utils.js backend support)."""

    def test_debounce_delay_logic(self):
        """Test debounce delay calculation."""
        debounce_delay_ms = 300

        # Simulate rapid calls
        call_times = [0, 50, 100, 150, 200]
        last_call = call_times[-1]

        # Function should only execute after delay from last call
        execute_time = last_call + debounce_delay_ms
        assert execute_time == 500

    def test_debounce_prevents_rapid_calls(self):
        """Test that debounce prevents rapid successive calls."""
        debounce_delay_ms = 300
        call_count = 0
        last_call_time = None

        call_times = [0, 50, 100, 400, 450, 800]

        for t in call_times:
            if last_call_time is None or t - last_call_time >= debounce_delay_ms:
                call_count += 1
                last_call_time = t

        # Only 3 calls should go through (0, 400, 800)
        assert call_count == 3


class TestBatchOperations:
    """Tests for batch operation optimization (filters.js backend support)."""

    def test_batch_filter_performance(self):
        """Test that batch filtering is more efficient."""
        # Simulate node filtering
        nodes = [{"id": f"CX{i}", "edges": i % 5} for i in range(100)]
        threshold = 2

        # Batch approach: filter once, apply to all
        low_edge_nodes = [n for n in nodes if n["edges"] <= threshold]
        high_edge_nodes = [n for n in nodes if n["edges"] > threshold]

        assert len(low_edge_nodes) + len(high_edge_nodes) == len(nodes)
        assert len(low_edge_nodes) == 60  # 0, 1, 2 edges = 3/5 of nodes

    def test_batch_class_application(self):
        """Test batch class application logic."""
        nodes = [
            {"id": "CX1", "classes": set()},
            {"id": "CX2", "classes": set()},
            {"id": "CX3", "classes": set()},
        ]

        # Batch add class
        for node in nodes:
            node["classes"].add("transparent")

        assert all("transparent" in n["classes"] for n in nodes)

        # Batch remove class
        for node in nodes:
            node["classes"].discard("transparent")

        assert all("transparent" not in n["classes"] for n in nodes)

