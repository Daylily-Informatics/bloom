from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from bloom_lims.domain.base import BloomObj


class _FakeLineage:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeSession:
    def __init__(self):
        self.added = []
        self.commit_count = 0

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commit_count += 1


def _template(euid, category, type_name, subtype, *, layouts=None):
    return SimpleNamespace(
        euid=euid,
        uid=hash(euid) & 0xFFFF,
        name=euid,
        category=category,
        type=type_name,
        subtype=subtype,
        version="1.0",
        bstatus="active",
        json_addl={"instantiation_layouts": layouts or {}},
        polymorphic_discriminator=f"{category}_template",
    )


def _fake_bloom_obj(templates):
    obj = BloomObj.__new__(BloomObj)
    obj.logger = logging.getLogger("test-template-instantiation")
    obj.session = _FakeSession()
    obj.Base = SimpleNamespace(
        classes=SimpleNamespace(generic_instance_lineage=_FakeLineage)
    )
    obj.domain_code = "Z"
    created = {"count": 0, "instances": {}}
    templates_by_euid = {template.euid: template for template in templates}

    def get_by_euid(euid):
        return templates_by_euid.get(euid) or created["instances"].get(euid)

    def query_template_by_component_v2(
        category=None, type=None, subtype=None, version=None
    ):
        return [
            template
            for template in templates
            if (category is None or template.category == category)
            and (type is None or template.type == type)
            and (subtype is None or template.subtype == subtype)
            and (version is None or template.version == version)
        ]

    def create_instance(template_euid, json_addl_overrides=None):
        template = templates_by_euid[template_euid]
        created["count"] += 1
        instance = SimpleNamespace(
            uid=created["count"],
            euid=f"I-{created['count']}",
            name=(json_addl_overrides or {})
            .get("properties", {})
            .get("name", template.name),
            category=template.category,
            type=template.type,
            subtype=template.subtype,
            version=template.version,
            bstatus=template.bstatus,
            json_addl=json_addl_overrides or {},
            polymorphic_discriminator=f"{template.category}_instance",
        )
        created["instances"][instance.euid] = instance
        return instance

    obj.get_by_euid = get_by_euid
    obj.query_template_by_component_v2 = query_template_by_component_v2
    obj.create_instance = create_instance
    return obj


def test_create_instances_recurses_nested_instantiation_layouts():
    leaf = _template("TPL-LEAF", "content", "material", "leaf")
    mid = _template(
        "TPL-MID",
        "container",
        "well",
        "middle",
        layouts=[
            {
                "relationship_type": "HOLDS_MATERIAL",
                "child_templates": [
                    {
                        "template_code": "content/material/leaf/1.0/",
                        "json_addl": {"properties": {"name": "leaf child"}},
                    }
                ],
            }
        ],
    )
    root = _template(
        "TPL-ROOT",
        "container",
        "plate",
        "nested",
        layouts=[
            {
                "relationship_type": "contains",
                "child_templates": [
                    {
                        "template_code": "container/well/middle/1.0/",
                        "json_addl": {"properties": {"name": "middle child"}},
                    }
                ],
            }
        ],
    )
    obj = _fake_bloom_obj([root, mid, leaf])

    parent_rows, child_rows = obj.create_instances("TPL-ROOT")

    assert len(parent_rows) == 1
    assert len(child_rows) == 2
    assert {child.type for child in child_rows} == {"well", "material"}
    lineages = [row for row in obj.session.added if isinstance(row, _FakeLineage)]
    assert [row.relationship_type for row in lineages] == [
        "HOLDS_MATERIAL",
        "contains",
    ]


def test_create_instances_rejects_template_cycles():
    cyclic = _template(
        "TPL-CYCLE",
        "container",
        "plate",
        "cycle",
        layouts=[
            {
                "relationship_type": "contains",
                "child_templates": [{"template_code": "container/plate/cycle/1.0/"}],
            }
        ],
    )
    obj = _fake_bloom_obj([cyclic])

    with pytest.raises(Exception, match="cycle detected"):
        obj.create_instances("TPL-CYCLE")


def test_create_instances_enforces_object_count_limit():
    child = _template("TPL-CHILD", "container", "well", "child")
    root = _template(
        "TPL-ROOT",
        "container",
        "plate",
        "limited",
        layouts=[
            {
                "relationship_type": "contains",
                "child_templates": [{"template_code": "container/well/child/1.0/"}],
            }
        ],
    )
    obj = _fake_bloom_obj([root, child])

    with pytest.raises(Exception, match="exceeded max object count 1"):
        obj.create_instances("TPL-ROOT", max_instances=1)
