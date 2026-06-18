"""Bloom lab action orchestration over TapDB objects and lineage."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.domain.base import BloomObj
from bloom_lims.domain.v0_graph import attach_bloom_v0_edge, object_evidence
from bloom_lims.integrations.zebra_day import ZebraDayService
from bloom_lims.schemas.lab_actions import (
    ExtractionPlateRequest,
    ExtractionTubeAssignment,
    LibraryPlateAssignment,
    PrintEuidRequest,
    RunSetInput,
    SeqLibraryPlateRequest,
    SeqLibraryPoolRequest,
    SeqRunSetRequest,
    WellPosition,
)
from bloom_lims.template_identity import instance_semantic_category

ROWS = tuple("ABCDEFGH")
COLS = tuple(range(1, 13))
MAX_EXTRACTION_TUBES = 95
RUN_SET_TEMPLATE_CODE = "set/run-set/generic/1.01/"
EXTRACTION_PLATE_TEMPLATE_CODE = "container/plate/fixed-plate-96/1.0/"
LIBRARY_PLATE_TEMPLATE_CODE = "container/plate/sequencing-library-plate-96/1.0/"
GDNA_TEMPLATE_CODE = "content/sample/gdna/1.0/"
LIBRARY_CONTENT_TEMPLATE_CODE = "content/sample/sequencing-library/1.0/"
POOL_TUBE_TEMPLATE_CODE = "container/tube/tube-generic-10ml/1.0/"
POOL_CONTENT_TEMPLATE_CODE = "content/pool/sequencing-library/1.0/"
GDNA_QUANT_TEMPLATE_CODE = "data/quantification/gdna/1.0/"


@dataclass(frozen=True)
class WellMapping:
    source_container_euid: str
    source_content_euid: str
    well_euid: str
    well_name: str
    output_content_euid: str
    quant_euid: str | None = None


class LabActionsService:
    """Service methods for temporary Bloom wet-lab action flows."""

    def __init__(self, bdb, *, user_id: str | None = None, email: str | None = None):
        self.bdb = bdb
        self.bobj = BloomObj(bdb).set_actor_context(user_id=user_id, email=email)

    def close(self) -> None:
        self.bdb.close()

    def _props(self, instance) -> dict[str, Any]:
        payload = instance.json_addl if isinstance(instance.json_addl, dict) else {}
        props = payload.get("properties")
        return props if isinstance(props, dict) else {}

    def _write_props(self, instance, props: dict[str, Any]) -> None:
        payload = instance.json_addl if isinstance(instance.json_addl, dict) else {}
        payload["properties"] = props
        instance.json_addl = payload
        flag_modified(instance, "json_addl")

    def _require(self, euid: str):
        instance = self.bobj.get_by_euid(euid)
        if instance is None:
            raise ValueError(f"Object not found: {euid}")
        return instance

    def _lineages_from_parent(self, parent, relationship_type: str | None = None):
        lineage_model = self.bdb.Base.classes.generic_instance_lineage
        query = self.bdb.session.query(lineage_model).filter(
            lineage_model.parent_instance_uid == parent.uid,
            lineage_model.is_deleted.is_(False),
        )
        if relationship_type:
            query = query.filter(lineage_model.relationship_type == relationship_type)
        return query.all()

    def _lineages_to_child(self, child, relationship_type: str | None = None):
        lineage_model = self.bdb.Base.classes.generic_instance_lineage
        query = self.bdb.session.query(lineage_model).filter(
            lineage_model.child_instance_uid == child.uid,
            lineage_model.is_deleted.is_(False),
        )
        if relationship_type:
            query = query.filter(lineage_model.relationship_type == relationship_type)
        return query.all()

    def _create_by_code(
        self,
        template_code: str,
        *,
        name: str | None = None,
        properties: dict[str, Any] | None = None,
        status: str | None = None,
    ):
        props = dict(properties or {})
        if name is not None:
            props["name"] = name
        instance = self.bobj.create_instance_by_code(
            template_code, {"json_addl": {"properties": props}}
        )
        if name is not None:
            instance.name = name
        if status is not None:
            instance.bstatus = status
        self._write_props(instance, {**self._props(instance), **props})
        self.bdb.session.flush()
        return instance

    def _create_lineage(
        self,
        parent_euid: str,
        child_euid: str,
        relationship_type: str,
        *,
        edge_type: str | None = None,
        source_role: str = "source",
        target_role: str = "target",
    ):
        lineage = self.bobj.create_generic_instance_lineage_by_euids(
            parent_euid, child_euid, relationship_type=relationship_type
        )
        if edge_type:
            attach_bloom_v0_edge(
                lineage,
                edge_type=edge_type,
                source_euid=parent_euid,
                target_euid=child_euid,
                source_role=source_role,
                target_role=target_role,
                evidence_refs=[
                    object_evidence(parent_euid, role=source_role),
                    object_evidence(child_euid, role=target_role),
                ],
                correlation_id=f"bloom:{relationship_type}:{parent_euid}:{child_euid}",
                causation_id=f"bloom:lab-actions:{relationship_type}",
            )
        return lineage

    def _container_content(self, container) -> Any:
        contents = [
            lineage.child_instance
            for lineage in self._lineages_from_parent(container)
            if instance_semantic_category(lineage.child_instance) == "content"
        ]
        if not contents:
            raise ValueError(f"Container {container.euid} has no content")
        if len(contents) > 1:
            raise ValueError(f"Container {container.euid} has multiple contents")
        return contents[0]

    def _plate_wells(self, plate) -> dict[str, Any]:
        wells: dict[str, Any] = {}
        for lineage in self._lineages_from_parent(plate, "contains"):
            child = lineage.child_instance
            if getattr(child, "type", "") != "well":
                continue
            props = child.json_addl if isinstance(child.json_addl, dict) else {}
            address = props.get("cont_address") or {}
            name = str(address.get("name") or child.name or "").strip().upper()
            if name:
                wells[name] = child
        if not wells:
            raise ValueError(f"Plate {plate.euid} has no linked wells")
        return wells

    def _well_content(self, well):
        return self._container_content(well)

    def _assert_well_empty(self, well) -> None:
        contents = [
            lineage.child_instance
            for lineage in self._lineages_from_parent(well)
            if instance_semantic_category(lineage.child_instance) == "content"
        ]
        if contents:
            raise ValueError(f"Destination well {well.euid} is already filled")

    def _position_names_auto(self, count: int) -> list[str]:
        if count < 1 or count > MAX_EXTRACTION_TUBES:
            raise ValueError(f"auto extraction accepts 1-{MAX_EXTRACTION_TUBES} tubes")
        names = [f"{row}{col}" for row in ROWS for col in COLS]
        return names[:count]

    def _normalize_assignments(
        self, request: ExtractionPlateRequest
    ) -> list[ExtractionTubeAssignment]:
        if request.mode == "auto":
            if len(set(request.tube_euids)) != len(request.tube_euids):
                raise ValueError("duplicate tube_euids are not allowed")
            positions = self._position_names_auto(len(request.tube_euids))
            return [
                ExtractionTubeAssignment(
                    tube_euid=tube_euid,
                    row=position[:1],
                    col=int(position[1:]),
                )
                for tube_euid, position in zip(request.tube_euids, positions)
            ]
        if len({item.tube_euid for item in request.assignments}) != len(
            request.assignments
        ):
            raise ValueError("duplicate assignment tube_euid values are not allowed")
        seen_positions: set[str] = set()
        for item in request.assignments:
            if item.row is None or item.col is None:
                raise ValueError("directed assignments require row and col")
            position = WellPosition(row=item.row, col=item.col).name
            if position in seen_positions:
                raise ValueError(f"duplicate destination well: {position}")
            seen_positions.add(position)
        if len(request.assignments) > MAX_EXTRACTION_TUBES:
            raise ValueError(f"directed extraction accepts at most {MAX_EXTRACTION_TUBES} tubes")
        return request.assignments

    def _create_or_get_extraction_plate(self, request: ExtractionPlateRequest):
        if request.plate_euid:
            plate = self._require(request.plate_euid)
            if instance_semantic_category(plate) != "container" or plate.type != "plate":
                raise ValueError(f"{request.plate_euid} is not a plate container")
            return plate
        return self._create_by_code(
            EXTRACTION_PLATE_TEMPLATE_CODE,
            name=request.plate_name or "extraction plate",
        )

    def _run_set(
        self,
        *,
        requested: bool,
        run_set: RunSetInput | None,
        default_name: str,
        member_euids: list[str],
    ):
        if not requested and run_set is None:
            return None
        payload = run_set or RunSetInput(name=default_name)
        members = list(dict.fromkeys([*payload.members, *member_euids]))
        instance = self._create_by_code(
            RUN_SET_TEMPLATE_CODE,
            name=payload.name or default_name,
            properties={
                "name": payload.name or default_name,
                "description": payload.description or "",
                "members": members,
                "external_members": payload.external_members,
                "metadata": payload.metadata,
                "status": "created",
            },
            status="created",
        )
        for member in members:
            if self.bobj.get_by_euid(member) is None:
                continue
            self._create_lineage(instance.euid, member, "run_set_member")
            self._create_lineage(member, instance.euid, "associated_set")
        return instance

    def create_extraction_plate(self, request: ExtractionPlateRequest) -> dict[str, Any]:
        assignments = self._normalize_assignments(request)
        plate = self._create_or_get_extraction_plate(request)
        wells = self._plate_wells(plate)
        mappings: list[WellMapping] = []
        new_container_euids = [] if request.plate_euid else [plate.euid]

        for assignment in assignments:
            position = WellPosition(row=assignment.row, col=assignment.col).name
            if position not in wells:
                raise ValueError(f"Destination well not found on plate: {position}")
            well = wells[position]
            self._assert_well_empty(well)
            tube = self._require(assignment.tube_euid)
            if instance_semantic_category(tube) != "container":
                raise ValueError(f"{tube.euid} is not a container")
            tube_content = self._container_content(tube)
            gdna = self._create_by_code(
                GDNA_TEMPLATE_CODE,
                name=f"{tube_content.name or tube_content.euid} gDNA",
                properties={
                    "source_tube_euid": tube.euid,
                    "source_content_euid": tube_content.euid,
                    "well_euid": well.euid,
                    "well_name": position,
                    "extraction_plate_euid": plate.euid,
                },
            )
            self._create_lineage(tube.euid, well.euid, "extraction_source_container")
            self._create_lineage(
                well.euid,
                gdna.euid,
                "HOLDS_MATERIAL",
                edge_type="HOLDS_MATERIAL",
                source_role="container",
                target_role="held_material",
            )
            self._create_lineage(
                tube_content.euid,
                gdna.euid,
                "DERIVED_FROM",
                edge_type="DERIVED_FROM",
                source_role="source_material",
                target_role="derived_material",
            )
            quant_euid = None
            if assignment.quant:
                quant = self._create_by_code(
                    GDNA_QUANT_TEMPLATE_CODE,
                    name=f"{gdna.euid} quant",
                    properties={
                        "gdna_euid": gdna.euid,
                        "well_euid": well.euid,
                        **assignment.quant,
                    },
                )
                quant_euid = quant.euid
                self._create_lineage(gdna.euid, quant.euid, "quantifies")
            mappings.append(
                WellMapping(
                    source_container_euid=tube.euid,
                    source_content_euid=tube_content.euid,
                    well_euid=well.euid,
                    well_name=position,
                    output_content_euid=gdna.euid,
                    quant_euid=quant_euid,
                )
            )

        run_set = self._run_set(
            requested=request.create_run_set,
            run_set=request.run_set,
            default_name=f"{plate.euid} extraction set",
            member_euids=[plate.euid, *[item.output_content_euid for item in mappings]],
        )
        self.bdb.session.commit()
        return {
            "plate_euid": plate.euid,
            "run_set_euid": run_set.euid if run_set is not None else None,
            "new_container_euids": new_container_euids,
            "mappings": [item.__dict__ for item in mappings],
        }

    def create_seq_library_plate(self, request: SeqLibraryPlateRequest) -> dict[str, Any]:
        if request.mode == "plate_1_to_1":
            source_plate = self._require(request.source_plate_euid)
            source_wells = self._plate_wells(source_plate)
            assignments = [
                LibraryPlateAssignment(
                    source_well_euid=well.euid,
                    row=name[:1],
                    col=int(name[1:]),
                )
                for name, well in sorted(source_wells.items())
                if self._lineages_from_parent(well, "HOLDS_MATERIAL")
            ]
        else:
            assignments = request.assignments
            for assignment in assignments:
                if assignment.row is None or assignment.col is None:
                    raise ValueError("directed assignments require row and col")

        if not assignments:
            raise ValueError("No source wells were provided or filled")
        plate = self._create_by_code(
            LIBRARY_PLATE_TEMPLATE_CODE,
            name=request.plate_name or "seq library plate",
        )
        dest_wells = self._plate_wells(plate)
        used_destinations: set[str] = set()
        mappings = []
        for assignment in assignments:
            position = WellPosition(row=assignment.row, col=assignment.col).name
            if position in used_destinations:
                raise ValueError(f"duplicate destination well: {position}")
            used_destinations.add(position)
            source_well = self._require(assignment.source_well_euid)
            source_content = self._well_content(source_well)
            dest_well = dest_wells.get(position)
            if dest_well is None:
                raise ValueError(f"Destination well not found on plate: {position}")
            self._assert_well_empty(dest_well)
            library = self._create_by_code(
                LIBRARY_CONTENT_TEMPLATE_CODE,
                name=f"{source_content.name or source_content.euid} seq library",
                properties={
                    "source_well_euid": source_well.euid,
                    "source_content_euid": source_content.euid,
                    "library_plate_euid": plate.euid,
                    "library_well_euid": dest_well.euid,
                    "library_well_name": position,
                    "index_barcode": assignment.index_barcode or "",
                    "index_euid": assignment.index_euid or "",
                    "data": assignment.data,
                },
            )
            self._create_lineage(
                dest_well.euid,
                library.euid,
                "HOLDS_MATERIAL",
                edge_type="HOLDS_MATERIAL",
                source_role="container",
                target_role="held_material",
            )
            self._create_lineage(
                source_content.euid,
                library.euid,
                "DERIVED_FROM",
                edge_type="DERIVED_FROM",
                source_role="source_material",
                target_role="derived_material",
            )
            self._create_lineage(source_well.euid, dest_well.euid, "library_source_well")
            if assignment.index_euid:
                index = self._require(assignment.index_euid)
                self._create_lineage(library.euid, index.euid, "uses_index")
            mappings.append(
                {
                    "source_well_euid": source_well.euid,
                    "source_content_euid": source_content.euid,
                    "library_well_euid": dest_well.euid,
                    "library_content_euid": library.euid,
                    "well_name": position,
                    "index_barcode": assignment.index_barcode or "",
                    "index_euid": assignment.index_euid or "",
                }
            )
        run_set = self._run_set(
            requested=request.create_run_set,
            run_set=request.run_set,
            default_name=f"{plate.euid} library set",
            member_euids=[plate.euid, *[item["library_content_euid"] for item in mappings]],
        )
        self.bdb.session.commit()
        return {
            "plate_euid": plate.euid,
            "run_set_euid": run_set.euid if run_set is not None else None,
            "new_container_euids": [plate.euid],
            "mappings": mappings,
        }

    def _resolve_pool_input(self, euid: str) -> tuple[Any | None, Any]:
        instance = self._require(euid)
        semantic = instance_semantic_category(instance)
        if semantic == "content":
            parents = [
                lineage.parent_instance
                for lineage in self._lineages_to_child(instance)
                if instance_semantic_category(lineage.parent_instance) == "container"
            ]
            return (parents[0] if parents else None), instance
        if semantic == "container":
            return instance, self._container_content(instance)
        raise ValueError(f"{euid} is not a container or content input")

    def create_seq_library_pool(self, request: SeqLibraryPoolRequest) -> dict[str, Any]:
        if len(set(request.input_euids)) != len(request.input_euids):
            raise ValueError("duplicate input_euids are not allowed")
        inputs = [self._resolve_pool_input(euid) for euid in request.input_euids]
        if request.pool_tube_euid:
            pool_tube = self._require(request.pool_tube_euid)
            self._assert_well_empty(pool_tube)
            new_container_euids: list[str] = []
        else:
            pool_tube = self._create_by_code(
                POOL_TUBE_TEMPLATE_CODE,
                name=f"{request.pool_name or request.platform.lower()} pool tube",
            )
            new_container_euids = [pool_tube.euid]
        pool = self._create_by_code(
            POOL_CONTENT_TEMPLATE_CODE,
            name=request.pool_name or f"{request.platform.lower()} sequencing pool",
            properties={
                "platform": request.platform,
                "member_euids": [content.euid for _, content in inputs],
                "metadata": request.metadata,
                "pool_tube_euid": pool_tube.euid,
            },
        )
        self._create_lineage(
            pool_tube.euid,
            pool.euid,
            "HOLDS_MATERIAL",
            edge_type="HOLDS_MATERIAL",
            source_role="container",
            target_role="held_material",
        )
        for container, content in inputs:
            self._create_lineage(
                content.euid,
                pool.euid,
                "DERIVED_FROM",
                edge_type="DERIVED_FROM",
                source_role="source_material",
                target_role="derived_material",
            )
            if container is not None:
                self._create_lineage(container.euid, pool_tube.euid, "pooled_from_container")
        run_set = self._run_set(
            requested=request.create_run_set,
            run_set=request.run_set,
            default_name=f"{pool.euid} pool set",
            member_euids=[pool_tube.euid, pool.euid],
        )
        self.bdb.session.commit()
        return {
            "pool_tube_euid": pool_tube.euid,
            "pool_content_euid": pool.euid,
            "run_set_euid": run_set.euid if run_set is not None else None,
            "new_container_euids": new_container_euids,
            "member_euids": [content.euid for _, content in inputs],
        }

    def create_seq_run_set(self, request: SeqRunSetRequest) -> dict[str, Any]:
        pool_tube = self._require(request.pool_tube_euid)
        pool_content = (
            self._require(request.pool_content_euid)
            if request.pool_content_euid
            else self._container_content(pool_tube)
        )
        props = {
            "name": request.name or f"{request.platform} sequencing run",
            "description": request.description or "",
            "members": [pool_tube.euid, pool_content.euid, *request.reagent_euids],
            "external_members": [],
            "operator": request.operator or "",
            "instrument": request.instrument_euid or "",
            "reagents": request.reagent_euids,
            "machine": request.machine or "",
            "flowcell_barcode": request.flowcell_barcode,
            "status": request.status,
            "platform": request.platform,
            "pool_tube_euid": pool_tube.euid,
            "pool_content_euid": pool_content.euid,
            "metadata": request.metadata,
        }
        run_set = self._create_by_code(
            RUN_SET_TEMPLATE_CODE,
            name=props["name"],
            properties=props,
            status=request.status,
        )
        self._create_lineage(run_set.euid, pool_tube.euid, "run_uses_pool")
        self._create_lineage(run_set.euid, pool_content.euid, "run_uses_pool")
        if request.instrument_euid:
            self._create_lineage(run_set.euid, request.instrument_euid, "run_uses_instrument")
        for reagent_euid in request.reagent_euids:
            self._create_lineage(run_set.euid, reagent_euid, "run_uses_reagent")
        self.bdb.session.commit()
        return {
            "set_euid": run_set.euid,
            "status": run_set.bstatus,
            "platform": request.platform,
            "pool_tube_euid": pool_tube.euid,
            "pool_content_euid": pool_content.euid,
        }

    def plate_mapping_rows(self, plate_euid: str) -> list[dict[str, str]]:
        plate = self._require(plate_euid)
        wells = self._plate_wells(plate)
        rows: list[dict[str, str]] = []
        for well_name, well in sorted(wells.items()):
            row = well_name[:1]
            col = well_name[1:]
            well_contents = [
                lineage.child_instance
                for lineage in self._lineages_from_parent(well)
                if instance_semantic_category(lineage.child_instance) == "content"
            ]
            source_tubes = [
                lineage.parent_instance.euid
                for lineage in self._lineages_to_child(well, "extraction_source_container")
            ]
            for content in well_contents or [None]:
                parent_contents = []
                child_euids = []
                if content is not None:
                    parent_contents = [
                        lineage.parent_instance.euid
                        for lineage in self._lineages_to_child(content)
                    ]
                    child_euids = [
                        lineage.child_instance.euid
                        for lineage in self._lineages_from_parent(content)
                    ]
                rows.append(
                    {
                        "tube_euid": "|".join(source_tubes),
                        "plate_euid": plate.euid,
                        "well_euid": well.euid,
                        "well_row": row,
                        "well_col": col,
                        "well_content_euid": content.euid if content is not None else "",
                        "parent_content_euid": "|".join(parent_contents),
                        "one_degree_parent_euids": "|".join(parent_contents),
                        "one_degree_child_euids": "|".join(child_euids),
                    }
                )
        return rows

    def plate_mapping_csv(self, plate_euid: str) -> str:
        rows = self.plate_mapping_rows(plate_euid)
        output = io.StringIO()
        fieldnames = [
            "tube_euid",
            "plate_euid",
            "well_euid",
            "well_row",
            "well_col",
            "well_content_euid",
            "parent_content_euid",
            "one_degree_parent_euids",
            "one_degree_child_euids",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    def illumina_sample_sheet(self, set_euid: str) -> str:
        run_set = self._require(set_euid)
        props = self._props(run_set)
        platform = str(props.get("platform") or "").strip()
        if platform != "ILMN":
            raise ValueError(
                f"Sample sheet download is only implemented for ILMN, not {platform or 'unknown'}"
            )
        pool_content = self._require(str(props.get("pool_content_euid") or ""))
        library_inputs = [
            lineage.parent_instance
            for lineage in self._lineages_to_child(pool_content, "DERIVED_FROM")
        ]
        data_rows = []
        for library in library_inputs:
            library_props = self._props(library)
            source_gdna = [
                lineage.parent_instance
                for lineage in self._lineages_to_child(library, "DERIVED_FROM")
            ]
            source_material = source_gdna[0] if source_gdna else None
            source_specimen = (
                [
                    lineage.parent_instance
                    for lineage in self._lineages_to_child(source_material, "DERIVED_FROM")
                ][0]
                if source_material is not None
                and self._lineages_to_child(source_material, "DERIVED_FROM")
                else None
            )
            data_rows.append(
                {
                    "Sample_ID": library.euid,
                    "Sample_Name": library.name or library.euid,
                    "index": str(library_props.get("index_barcode") or ""),
                    "Description": json.dumps(
                        {
                            "run_set_euid": run_set.euid,
                            "library_euid": library.euid,
                            "source_gdna_euid": source_material.euid
                            if source_material is not None
                            else "",
                            "source_specimen_content_euid": source_specimen.euid
                            if source_specimen is not None
                            else "",
                        },
                        separators=(",", ":"),
                    ),
                }
            )
        output = io.StringIO()
        output.write("[Header]\n")
        output.write(f"RunSetEUID,{run_set.euid}\n")
        output.write(f"Flowcell,{props.get('flowcell_barcode') or ''}\n")
        output.write(f"Operator,{props.get('operator') or ''}\n")
        output.write("\n[Reads]\n151\n151\n\n[Data]\n")
        writer = csv.DictWriter(
            output, fieldnames=["Sample_ID", "Sample_Name", "index", "Description"]
        )
        writer.writeheader()
        writer.writerows(data_rows)
        return output.getvalue()

    def print_euids(self, request: PrintEuidRequest) -> dict[str, Any]:
        service = ZebraDayService()
        results = []
        for euid in request.euids:
            self._require(euid)
            results.append(
                service.submit_print_job(
                    lab=request.lab,
                    printer_id=request.printer_id,
                    label_zpl_style=request.label_zpl_style,
                    euid=euid,
                    print_n=request.copies,
                )
            )
        return {"printed": len(results), "results": results}
