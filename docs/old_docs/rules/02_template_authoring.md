# daylily-tapdb Template Authoring Rules

## JSON Template Structure

### Required Top-Level Keys

Every template JSON must include:

```json
{
  "template_name": {
    "version": {
      "properties": {},
      "instantiation_layouts": [],
      "action_groups": {},
      "actions": {}
    }
  }
}
```

### Version Format

Versions must follow semantic versioning: `MAJOR.MINOR`

- `1.0` - Initial version
- `1.1` - Backward-compatible additions
- `2.0` - Breaking changes

### Template Naming

Template names (type) must be:
- Lowercase
- Hyphen-separated for multi-word names
- Descriptive and specific

```
# Good
fixed-plate-96
blood-sample
ngs-library-prep

# Bad
plate1
BloodSample
NGS_Lib
```

---

## Instantiation Layouts

### Layout Structure

```json
{
  "instantiation_layouts": [
    {
      "layout_name": "required-unique-name",
      "layout_string": "category/type/subtype/version/",
      "count": 1,
      "naming_pattern": "{parent_name}_{index}",
      "lineage_type": "contains"
    }
  ]
}
```

### Naming Pattern Variables

| Variable | Description |
|----------|-------------|
| `{parent_name}` | Name of parent instance |
| `{parent_euid}` | EUID of parent instance |
| `{index}` | 1-based index |
| `{index:02d}` | Zero-padded index |
| `{row_letter}` | A-H for 96-well plates |
| `{column_number}` | 1-12 for 96-well plates |

### Lineage Types

Standard lineage types:
- `contains` - Physical containment (plate contains wells)
- `derived_from` - Sample derivation
- `processed_by` - Workflow processing
- `assigned_to` - Actor assignment
- `generic` - Unspecified relationship

---

## Action Definitions

### Action Template Structure

```json
{
  "actions": {
    "action_key": {
      "action_name": "Human Readable Name",
      "method_name": "do_action_method_name",
      "action_enabled": "1",
      "max_executions": "-1",
      "capture_data": "yes",
      "captured_data": {},
      "description": "What this action does"
    }
  }
}
```

### Method Naming

Action methods MUST be prefixed with `do_action_`:

```
do_action_set_status
do_action_print_label
do_action_transfer_sample
```

### Captured Data HTML

Use standard HTML form elements:

```json
{
  "captured_data": {
    "_field_name": "Label: <input type=\"text\" name=\"field_name\" required />",
    "_dropdown": "<select name=\"choice\"><option value=\"a\">A</option></select>",
    "_textarea": "Notes: <textarea name=\"notes\"></textarea>"
  }
}
```

Field keys starting with `_` are rendered as form fields.

### Action Groups

Group related actions:

```json
{
  "action_groups": {
    "primary": ["set_status", "print_label"],
    "secondary": ["add_note", "transfer"],
    "admin": ["delete", "archive"]
  }
}
```

---

## Action Imports

### Import Syntax

```json
{
  "action_imports": {
    "local_action_key": "action/core/action_name/version/"
  }
}
```

### Core Actions Available

| Action | Template Code |
|--------|---------------|
| Set Status | `action/core/set_object_status/1.0/` |
| Print Label | `action/core/print_barcode_label/1.0/` |
| Add Relationships | `action/core/add-relationships/1.0/` |
| Create Subject | `action/core/create-subject-and-anchor/1.0/` |

---

## Properties

### Property Naming

Use snake_case for property keys:

```json
{
  "properties": {
    "sample_type": "blood",
    "collection_date": "",
    "volume_ul": 0
  }
}
```

### Reserved Property Keys

Do not use these as custom properties:
- `uuid`, `euid`, `name`
- `created_dt`, `modified_dt`
- `is_deleted`, `is_singleton`
- `bstatus`, `version`

---

## Metadata Files

### metadata.json Structure

Each category directory must have a metadata.json:

```json
{
  "euid_prefix": "CX",
  "category": "container",
  "description": "Container objects",
  "polymorphic_discriminator": "container_template"
}
```

### EUID Prefix Rules

- 1-5 uppercase letters (typically 2-3)
- Must be unique across all categories
- Must be registered in `EUIDConfig`
- Must have corresponding database sequence

---

*Template Authoring Rules for daylily-tapdb*
