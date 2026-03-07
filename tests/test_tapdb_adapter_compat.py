from bloom_lims.tapdb_adapter import generic_instance_lineage, generic_template


def test_template_exposes_only_canonical_uid_attribute():
    assert generic_template.uid.property.columns[0].name == "uid"
    assert not hasattr(generic_template, "uuid")


def test_lineage_exposes_only_canonical_uid_fk_attributes():
    assert (
        generic_instance_lineage.parent_instance_uid.property.columns[0].name
        == "parent_instance_uid"
    )
    assert not hasattr(generic_instance_lineage, "parent_instance_uuid")
    assert not hasattr(generic_instance_lineage, "child_instance_uuid")