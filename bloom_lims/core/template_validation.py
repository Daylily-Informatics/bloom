"""
BLOOM LIMS Template Validation Suite

Provides automated validation for JSON templates including:
- Schema compliance checking
- Action reference validation
- Circular dependency detection
- Version compatibility verification

Usage:
    from bloom_lims.core.template_validation import TemplateValidator
    
    validator = TemplateValidator()
    result = validator.validate_all()
    
    if result.errors:
        print(f"Found {len(result.errors)} errors")
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from bloom_lims.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of template validation."""
    valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    templates_checked: int = 0
    files_checked: int = 0


@dataclass
class TemplateDefinition:
    """Parsed template definition."""
    file_path: Path
    category: str
    type: str
    subtype: str
    version: str
    data: Dict[str, Any]
    action_imports: Dict[str, Any] = field(default_factory=dict)
    instantiation_layouts: List[Any] = field(default_factory=list)


class TemplateValidator:
    """
    Validates BLOOM LIMS JSON template files.
    
    Performs comprehensive validation including schema checks,
    reference validation, and dependency analysis.
    """
    
    # Valid super types
    VALID_SUPER_TYPES = {
        "workflow", "workflow_step", "container", "content",
        "equipment", "data", "test_requisition", "actor",
        "action", "file", "health_event", "generic"
    }
    
    # Required fields for different template types
    REQUIRED_FIELDS = {
        "action": ["action_template"],
        "workflow": ["action_imports"],
        "workflow_step": ["action_imports"],
    }
    
    # Template reference pattern
    REFERENCE_PATTERN = re.compile(
        r"^([a-z_]+)/([a-z0-9_\-*]+)/([a-z0-9_\-*]+)/([0-9.*]+)/?$"
    )
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize validator.
        
        Args:
            config_path: Path to config directory (defaults to bloom_lims/config)
        """
        self._settings = get_settings()
        
        if config_path is None:
            self._config_path = Path(__file__).parent.parent / "config"
        else:
            self._config_path = config_path
        
        self._templates: Dict[str, TemplateDefinition] = {}
        self._action_references: Set[str] = set()
    
    def validate_all(self) -> ValidationResult:
        """
        Validate all templates in the config directory.
        
        Returns:
            ValidationResult with errors and warnings
        """
        result = ValidationResult()
        
        if not self._config_path.exists():
            result.valid = False
            result.errors.append(f"Config directory not found: {self._config_path}")
            return result
        
        # First pass: Load and parse all templates
        self._load_templates(result)
        
        # Second pass: Validate references
        self._validate_references(result)
        
        # Third pass: Check for circular dependencies
        self._check_circular_dependencies(result)
        
        result.valid = len(result.errors) == 0
        return result
    
    def _load_templates(self, result: ValidationResult) -> None:
        """Load and parse all template files."""
        for json_file in self._config_path.rglob("*.json"):
            if json_file.name == "metadata.json":
                continue
            
            result.files_checked += 1
            
            try:
                with open(json_file) as f:
                    data = json.load(f)

                # Determine category from directory structure
                relative_path = json_file.relative_to(self._config_path)
                category = relative_path.parts[0] if relative_path.parts else "generic"

                for type_name, versions in data.items():
                    if not isinstance(versions, dict):
                        result.errors.append(
                            f"{json_file}: '{type_name}' must be a dict of versions"
                        )
                        continue

                    for version, template_data in versions.items():
                        result.templates_checked += 1

                        self._validate_template_structure(
                            json_file, category, type_name, version,
                            template_data, result
                        )
                        
            except json.JSONDecodeError as e:
                result.errors.append(f"{json_file}: Invalid JSON - {e}")
            except Exception as e:
                result.errors.append(f"{json_file}: Error loading - {e}")

    def _validate_template_structure(
        self,
        file_path: Path,
        category: str,
        type_name: str,
        version: str,
        data: Dict[str, Any],
        result: ValidationResult
    ) -> None:
        """Validate individual template structure."""
        template_id = f"{category}/{type_name}/{version}"

        # Check if template data is a dict
        if not isinstance(data, dict):
            result.errors.append(f"{file_path}: {template_id} must be a dictionary")
            return

        # Store template for reference checking
        subtype = type_name  # In the file structure, type contains the subtype
        template = TemplateDefinition(
            file_path=file_path,
            category=category,
            type=type_name,
            subtype=subtype,
            version=version,
            data=data,
            action_imports=data.get("action_imports", {}),
            instantiation_layouts=data.get("instantiation_layouts", []),
        )
        self._templates[template_id] = template

        # Check required fields for specific types
        if category in self.REQUIRED_FIELDS:
            for field in self.REQUIRED_FIELDS[category]:
                if field not in data:
                    result.warnings.append(
                        f"{file_path}: {template_id} missing recommended field '{field}'"
                    )

        # Validate singleton value
        if "singleton" in data:
            singleton = data["singleton"]
            if singleton not in ["0", "1", 0, 1, "true", "false", True, False]:
                result.warnings.append(
                    f"{file_path}: {template_id} singleton value '{singleton}' is non-standard"
                )

        # Validate action_imports structure
        if "action_imports" in data:
            self._validate_action_imports(
                file_path, template_id, data["action_imports"], result
            )

        # Validate instantiation_layouts structure
        if "instantiation_layouts" in data:
            self._validate_instantiation_layouts(
                file_path, template_id, data["instantiation_layouts"], result
            )

    def _validate_action_imports(
        self,
        file_path: Path,
        template_id: str,
        action_imports: Dict[str, Any],
        result: ValidationResult
    ) -> None:
        """Validate action_imports structure."""
        if not isinstance(action_imports, dict):
            result.errors.append(
                f"{file_path}: {template_id} action_imports must be a dictionary"
            )
            return

        for group_name, group_data in action_imports.items():
            if not isinstance(group_data, dict):
                result.errors.append(
                    f"{file_path}: {template_id} action group '{group_name}' must be a dict"
                )
                continue

            # Validate required group fields
            if "actions" not in group_data:
                result.warnings.append(
                    f"{file_path}: {template_id} group '{group_name}' missing 'actions'"
                )
                continue

            # Track action references for later validation
            for action_ref in group_data.get("actions", {}).keys():
                self._action_references.add(action_ref.strip("/"))

    def _validate_instantiation_layouts(
        self,
        file_path: Path,
        template_id: str,
        layouts: List[Any],
        result: ValidationResult
    ) -> None:
        """Validate instantiation_layouts structure."""
        if not isinstance(layouts, list):
            result.errors.append(
                f"{file_path}: {template_id} instantiation_layouts must be a list"
            )
            return

        for row_idx, row in enumerate(layouts):
            if not isinstance(row, list):
                result.warnings.append(
                    f"{file_path}: {template_id} layout row {row_idx} should be a list"
                )

    def _validate_references(self, result: ValidationResult) -> None:
        """Validate all cross-references between templates."""
        for ref in self._action_references:
            if not self._is_valid_reference(ref):
                result.warnings.append(f"Action reference '{ref}' may be invalid pattern")

    def _is_valid_reference(self, ref: str) -> bool:
        """Check if a template reference is valid."""
        return self.REFERENCE_PATTERN.match(ref) is not None

    def _check_circular_dependencies(self, result: ValidationResult) -> None:
        """Check for circular dependencies in template relationships."""
        # Build dependency graph from instantiation_layouts
        dependencies: Dict[str, Set[str]] = {}

        for template_id, template in self._templates.items():
            deps = set()
            for row in template.instantiation_layouts:
                if isinstance(row, list):
                    for item in row:
                        if isinstance(item, dict):
                            deps.update(item.keys())
            dependencies[template_id] = deps

        # Check for cycles using DFS
        visited = set()
        path = set()

        def has_cycle(node: str) -> bool:
            if node in path:
                return True
            if node in visited:
                return False

            visited.add(node)
            path.add(node)

            for dep in dependencies.get(node, set()):
                if has_cycle(dep):
                    return True

            path.remove(node)
            return False

        for template_id in dependencies:
            path.clear()
            if has_cycle(template_id):
                result.errors.append(
                    f"Circular dependency detected involving {template_id}"
                )

