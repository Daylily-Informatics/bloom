"""Bloom lab action orchestration over TapDB objects and lineage."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.domain.base import BloomObj
from bloom_lims.domain.lab_action_spreadsheets import ParsedSheet, parse_workbook
from bloom_lims.domain.v0_graph import attach_bloom_v0_edge, object_evidence
from bloom_lims.integrations.zebra_day import ZebraDayService
from bloom_lims.schemas.lab_actions import (
    ExtractionPlateRequest,
    ExtractionQcAssignment,
    ExtractionQcPlateRequest,
    ExtractionTubeAssignment,
    LabSetMembersRequest,
    LabSetRequest,
    LibraryPlateAssignment,
    PlateWellDataRecord,
    PlateWellDataRequest,
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
EXTRACTION_QC_TEMPLATE_CODE = "data/operation/extraction-qc/1.0/"


def re_split_multi(value: str) -> list[str]:
    return re.split(r"[\n,|;]+", value)


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
                "status": payload.status,
            },
            status=payload.status,
        )
        for member in members:
            if self.bobj.get_by_euid(member) is None:
                continue
            self._create_lineage(instance.euid, member, "run_set_member")
            self._create_lineage(member, instance.euid, "associated_set")
        return instance

    def _well_from_plate_position(self, plate_euid: str, row: str, col: int):
        plate = self._require(plate_euid)
        wells = self._plate_wells(plate)
        position = WellPosition(row=row, col=col).name
        well = wells.get(position)
        if well is None:
            raise ValueError(f"Destination well not found on plate: {position}")
        return well

    def _well_for_data_record(self, record: PlateWellDataRecord):
        if record.well_euid:
            return self._require(record.well_euid)
        return self._well_from_plate_position(record.plate_euid, record.row, record.col)

    def _well_for_qc_assignment(
        self, assignment: ExtractionQcAssignment, source_plate_euid: str | None
    ):
        if assignment.source_well_euid:
            return self._require(assignment.source_well_euid)
        if not source_plate_euid:
            raise ValueError("source_plate_euid is required when assignment uses row/col")
        return self._well_from_plate_position(
            source_plate_euid, assignment.row, assignment.col
        )

    def _create_or_get_qc_plate(self, request: ExtractionQcPlateRequest):
        if request.qc_plate_euid:
            plate = self._require(request.qc_plate_euid)
            if instance_semantic_category(plate) != "container" or plate.type != "plate":
                raise ValueError(f"{request.qc_plate_euid} is not a plate container")
            return plate, []
        plate = self._create_by_code(
            EXTRACTION_PLATE_TEMPLATE_CODE,
            name=request.qc_plate_name or "extraction QC plate",
        )
        return plate, [plate.euid]

    def _all_filled_well_qc_assignments(
        self, source_plate_euid: str
    ) -> list[ExtractionQcAssignment]:
        plate = self._require(source_plate_euid)
        assignments: list[ExtractionQcAssignment] = []
        for name, well in sorted(self._plate_wells(plate).items()):
            if self._lineages_from_parent(well, "HOLDS_MATERIAL"):
                assignments.append(
                    ExtractionQcAssignment(
                        source_well_euid=well.euid,
                        qc_row=name[:1],
                        qc_col=int(name[1:]),
                    )
                )
        if not assignments:
            raise ValueError(f"Source plate {source_plate_euid} has no filled wells")
        return assignments

    def create_lab_set(self, request: LabSetRequest) -> dict[str, Any]:
        run_set = self._create_by_code(
            RUN_SET_TEMPLATE_CODE,
            name=request.name,
            properties={
                "name": request.name,
                "description": request.description or "",
                "members": list(dict.fromkeys(request.members)),
                "external_members": list(dict.fromkeys(request.external_members)),
                "operator": request.operator or "",
                "instrument": request.instrument or "",
                "reagents": request.reagents,
                "machine": request.machine or "",
                "flowcell_barcode": request.flowcell_barcode or "",
                "status": request.status,
                "metadata": request.metadata,
            },
            status=request.status,
        )
        for member in dict.fromkeys(request.members):
            if self.bobj.get_by_euid(member) is not None:
                self._create_lineage(run_set.euid, member, "run_set_member")
                self._create_lineage(member, run_set.euid, "associated_set")
        self.bdb.session.commit()
        return self.get_lab_set(run_set.euid)

    def add_lab_set_members(
        self, set_euid: str, request: LabSetMembersRequest
    ) -> dict[str, Any]:
        run_set = self._require(set_euid)
        props = self._props(run_set)
        members = list(
            dict.fromkeys([*props.get("members", []), *request.members])
        )
        external_members = list(
            dict.fromkeys(
                [*props.get("external_members", []), *request.external_members]
            )
        )
        props["members"] = members
        props["external_members"] = external_members
        self._write_props(run_set, props)
        for member in request.members:
            if self.bobj.get_by_euid(member) is not None:
                self._create_lineage(run_set.euid, member, "run_set_member")
                self._create_lineage(member, run_set.euid, "associated_set")
        self.bdb.session.commit()
        return self.get_lab_set(set_euid)

    def get_lab_set(self, set_euid: str) -> dict[str, Any]:
        run_set = self._require(set_euid)
        props = self._props(run_set)
        return {
            "set_euid": run_set.euid,
            "name": run_set.name,
            "status": run_set.bstatus,
            "properties": props,
            "members": props.get("members", []),
            "external_members": props.get("external_members", []),
        }

    def fill_extraction_qc_plate(
        self, request: ExtractionQcPlateRequest
    ) -> dict[str, Any]:
        assignments = request.assignments or self._all_filled_well_qc_assignments(
            request.source_plate_euid
        )
        if len(assignments) > 96:
            raise ValueError("extraction QC plate can accept at most 96 assignments")
        qc_plate, new_container_euids = self._create_or_get_qc_plate(request)
        qc_wells = self._plate_wells(qc_plate)
        used_qc_positions: set[str] = set()
        mappings: list[dict[str, Any]] = []
        for index, assignment in enumerate(assignments):
            source_well = self._well_for_qc_assignment(
                assignment, request.source_plate_euid
            )
            source_content = self._well_content(source_well)
            if assignment.qc_row is not None and assignment.qc_col is not None:
                qc_position = WellPosition(
                    row=assignment.qc_row, col=assignment.qc_col
                ).name
            else:
                qc_position = WellPosition(
                    row=assignment.row or ROWS[index // 12],
                    col=assignment.col or (index % 12) + 1,
                ).name
            if qc_position in used_qc_positions:
                raise ValueError(f"duplicate QC destination well: {qc_position}")
            used_qc_positions.add(qc_position)
            qc_well = qc_wells.get(qc_position)
            if qc_well is None:
                raise ValueError(f"QC well not found on plate: {qc_position}")
            data = self._create_by_code(
                EXTRACTION_QC_TEMPLATE_CODE,
                name=f"{source_well.euid} extraction QC",
                properties={
                    "source_well_euid": source_well.euid,
                    "source_content_euid": source_content.euid,
                    "qc_plate_euid": qc_plate.euid,
                    "qc_well_euid": qc_well.euid,
                    "qc_well_name": qc_position,
                    "result": assignment.result or "",
                    "status": assignment.status or "recorded",
                    "data": assignment.data,
                },
                status=assignment.status or "recorded",
            )
            self._create_lineage(source_well.euid, qc_well.euid, "qc_source_well")
            self._create_lineage(qc_well.euid, data.euid, "well_associated_data")
            self._create_lineage(source_content.euid, data.euid, "qc_for_material")
            mappings.append(
                {
                    "source_well_euid": source_well.euid,
                    "source_content_euid": source_content.euid,
                    "qc_well_euid": qc_well.euid,
                    "qc_well_name": qc_position,
                    "data_euid": data.euid,
                    "result": assignment.result or "",
                    "status": assignment.status or "recorded",
                }
            )
        run_set = self._run_set(
            requested=request.create_run_set,
            run_set=request.run_set,
            default_name=f"{qc_plate.euid} extraction QC set",
            member_euids=[qc_plate.euid, *[item["data_euid"] for item in mappings]],
        )
        self.bdb.session.commit()
        return {
            "qc_plate_euid": qc_plate.euid,
            "run_set_euid": run_set.euid if run_set is not None else None,
            "new_container_euids": new_container_euids,
            "mappings": mappings,
        }

    def attach_plate_well_data(self, request: PlateWellDataRequest) -> dict[str, Any]:
        mappings: list[dict[str, Any]] = []
        for record in request.records:
            well = self._well_for_data_record(record)
            target = well if record.target == "well" else self._well_content(well)
            data = self._create_by_code(
                request.data_template_code,
                name=record.name or f"{well.euid} associated data",
                properties={
                    "well_euid": well.euid,
                    "target_euid": target.euid,
                    "target_kind": record.target,
                    "data": record.data,
                },
            )
            self._create_lineage(target.euid, data.euid, request.relationship_type)
            mappings.append(
                {
                    "well_euid": well.euid,
                    "target_euid": target.euid,
                    "data_euid": data.euid,
                    "relationship_type": request.relationship_type,
                }
            )
        run_set = self._run_set(
            requested=request.create_run_set,
            run_set=request.run_set,
            default_name="plate well data set",
            member_euids=[item["data_euid"] for item in mappings],
        )
        self.bdb.session.commit()
        return {
            "run_set_euid": run_set.euid if run_set is not None else None,
            "mappings": mappings,
        }

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

    def _split_values(self, value: Any) -> list[str]:
        if value in (None, ""):
            return []
        return [
            token.strip()
            for token in re_split_multi(str(value))
            if token and token.strip()
        ]

    def _row_metadata(self, row: dict[str, Any], *prefixes: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        for key, value in row.items():
            if value in (None, ""):
                continue
            for prefix in prefixes:
                if key.startswith(prefix):
                    metadata[key.removeprefix(prefix)] = value
        return metadata

    def _sheet_action(self, sheet: ParsedSheet) -> str:
        name = sheet.name.strip().lower().replace("-", " ").replace("_", " ")
        headers = set(sheet.headers)
        if name == "csv":
            if {"pool_tube_euid", "flowcell_barcode"} & headers:
                return "seq_run_set"
            if {"input_euid", "input_euids"} & headers:
                return "seq_pool"
            if "source_well_euid" in headers and {"index_barcode", "index_euid"} & headers:
                return "seq_library_plate"
            if {"source_well_euid", "qc_row", "qc_col"} & headers:
                return "extraction_qc"
            if {"well_euid", "data_template_code"} & headers:
                return "plate_well_data"
            if {"set_name", "members", "member_euids"} & headers:
                return "sets"
            if "tube_euid" in headers:
                return "extraction_plate"
        if name in {"extraction plate", "extraction"}:
            return "extraction_plate"
        if name in {"extraction qc", "extractionqc", "extraction qc plate"}:
            return "extraction_qc"
        if name in {"seq library plate", "sequencing library plate", "library plate"}:
            return "seq_library_plate"
        if name in {"seq pool", "sequencing pool", "seq library pool", "pool"}:
            return "seq_pool"
        if name in {"seq run", "seq run set", "sequencing run", "sequencing run set"}:
            return "seq_run_set"
        if name in {"sets", "set", "run sets", "run set"}:
            return "sets"
        if name in {"plate well data", "well data", "annotation"}:
            return "plate_well_data" if name != "annotation" else "container_annotation_preview"
        if name in {"bulk create", "transfer"}:
            return "container_interaction_preview"
        return "unknown"

    def _request_from_extraction_sheet(self, sheet: ParsedSheet) -> ExtractionPlateRequest:
        assignments: list[ExtractionTubeAssignment] = []
        tube_euids: list[str] = []
        plate_name: str | None = None
        for row in sheet.rows:
            tube_euid = str(
                row.get("tube_euid") or row.get("container_euid") or ""
            ).strip()
            if not tube_euid:
                continue
            plate_name = plate_name or str(row.get("plate_name") or "").strip() or None
            row_name = row.get("row") or row.get("well_row") or row.get("child_container_row")
            col_value = row.get("col") or row.get("well_col") or row.get("child_container_column")
            if row_name not in (None, "") or col_value not in (None, ""):
                assignments.append(
                    ExtractionTubeAssignment(
                        tube_euid=tube_euid,
                        row=row_name,
                        col=col_value,
                        quant=self._row_metadata(row, "quant_", "qc_"),
                    )
                )
            else:
                tube_euids.append(tube_euid)
        if assignments:
            return ExtractionPlateRequest(
                mode="directed",
                assignments=assignments,
                plate_name=plate_name or "extraction plate",
            )
        return ExtractionPlateRequest(
            mode="auto",
            tube_euids=tube_euids,
            plate_name=plate_name or "extraction plate",
        )

    def _request_from_qc_sheet(self, sheet: ParsedSheet) -> ExtractionQcPlateRequest:
        source_plate_euid = None
        qc_plate_name = None
        assignments: list[ExtractionQcAssignment] = []
        for row in sheet.rows:
            source_plate_euid = source_plate_euid or str(
                row.get("source_plate_euid") or row.get("plate_euid") or ""
            ).strip() or None
            qc_plate_name = qc_plate_name or str(row.get("qc_plate_name") or "").strip() or None
            assignments.append(
                ExtractionQcAssignment(
                    source_well_euid=str(row.get("source_well_euid") or row.get("well_euid") or "").strip()
                    or None,
                    row=row.get("row") or row.get("well_row"),
                    col=row.get("col") or row.get("well_col"),
                    qc_row=row.get("qc_row") or row.get("target_row"),
                    qc_col=row.get("qc_col") or row.get("target_col"),
                    result=str(row.get("result") or "").strip() or None,
                    status=str(row.get("status") or "").strip() or None,
                    data=self._row_metadata(row, "data_", "qc_", "metric_"),
                )
            )
        return ExtractionQcPlateRequest(
            source_plate_euid=source_plate_euid,
            qc_plate_name=qc_plate_name or "extraction QC plate",
            assignments=assignments,
        )

    def _request_from_library_sheet(self, sheet: ParsedSheet) -> SeqLibraryPlateRequest:
        source_plate_euid = None
        plate_name = None
        assignments: list[LibraryPlateAssignment] = []
        for row in sheet.rows:
            source_plate_euid = source_plate_euid or str(
                row.get("source_plate_euid") or ""
            ).strip() or None
            plate_name = plate_name or str(row.get("plate_name") or "").strip() or None
            source_well_euid = str(row.get("source_well_euid") or row.get("well_euid") or "").strip()
            if source_well_euid:
                assignments.append(
                    LibraryPlateAssignment(
                        source_well_euid=source_well_euid,
                        row=row.get("row") or row.get("well_row"),
                        col=row.get("col") or row.get("well_col"),
                        index_barcode=str(row.get("index_barcode") or "").strip() or None,
                        index_euid=str(row.get("index_euid") or "").strip() or None,
                        data=self._row_metadata(row, "data_", "library_"),
                    )
                )
        if assignments:
            return SeqLibraryPlateRequest(
                mode="directed",
                assignments=assignments,
                plate_name=plate_name or "seq library plate",
            )
        return SeqLibraryPlateRequest(
            mode="plate_1_to_1",
            source_plate_euid=source_plate_euid,
            plate_name=plate_name or "seq library plate",
        )

    def _request_from_pool_sheet(self, sheet: ParsedSheet) -> SeqLibraryPoolRequest:
        input_euids: list[str] = []
        platform = "ILMN"
        pool_tube_euid = None
        pool_name = None
        metadata: dict[str, Any] = {}
        for row in sheet.rows:
            input_euids.extend(
                self._split_values(
                    row.get("input_euid")
                    or row.get("input_euids")
                    or row.get("well_euid")
                    or row.get("tube_euid")
                    or row.get("container_euid")
                    or row.get("content_euid")
                )
            )
            platform = str(row.get("platform") or platform).strip() or platform
            pool_tube_euid = pool_tube_euid or str(row.get("pool_tube_euid") or "").strip() or None
            pool_name = pool_name or str(row.get("pool_name") or "").strip() or None
            metadata.update(self._row_metadata(row, "metadata_", "pool_"))
        return SeqLibraryPoolRequest(
            input_euids=list(dict.fromkeys(input_euids)),
            platform=platform,
            pool_tube_euid=pool_tube_euid,
            pool_name=pool_name or "seq library",
            metadata=metadata,
        )

    def _request_from_run_sheet(self, sheet: ParsedSheet) -> SeqRunSetRequest:
        if not sheet.rows:
            raise ValueError("Seq Run Set sheet has no rows")
        row = sheet.rows[0]
        return SeqRunSetRequest(
            pool_tube_euid=str(row.get("pool_tube_euid") or "").strip(),
            pool_content_euid=str(row.get("pool_content_euid") or "").strip() or None,
            platform=str(row.get("platform") or "ILMN").strip() or "ILMN",
            operator=str(row.get("operator") or "").strip() or None,
            instrument_euid=str(row.get("instrument_euid") or "").strip() or None,
            machine=str(row.get("machine") or "").strip() or None,
            flowcell_barcode=str(row.get("flowcell_barcode") or row.get("flowcell") or "").strip(),
            reagent_euids=self._split_values(row.get("reagent_euids") or row.get("reagents")),
            status=str(row.get("status") or "created").strip() or "created",
            name=str(row.get("name") or "").strip() or None,
            description=str(row.get("description") or "").strip() or None,
            metadata=self._row_metadata(row, "metadata_", "run_"),
        )

    def _request_from_data_sheet(self, sheet: ParsedSheet) -> PlateWellDataRequest:
        records: list[PlateWellDataRecord] = []
        data_template_code = "data/operation/extraction-qc/1.0/"
        relationship_type = "well_associated_data"
        for row in sheet.rows:
            data_template_code = str(
                row.get("data_template_code")
                or row.get("annotation_template_euid")
                or data_template_code
            ).strip()
            relationship_type = str(row.get("relationship_type") or relationship_type).strip()
            records.append(
                PlateWellDataRecord(
                    well_euid=str(row.get("well_euid") or row.get("child_container_euid") or "").strip()
                    or None,
                    plate_euid=str(row.get("plate_euid") or row.get("container_euid") or "").strip()
                    or None,
                    row=row.get("row") or row.get("well_row") or row.get("child_container_row"),
                    col=row.get("col") or row.get("well_col") or row.get("child_container_column"),
                    name=str(row.get("name") or row.get("annotation_name") or "").strip()
                    or None,
                    target="content"
                    if "content"
                    in str(
                        row.get("target")
                        or row.get("annotate_container_child_container_content")
                        or "content"
                    ).strip().lower()
                    else "well",
                    data={
                        **self._row_metadata(row, "data_", "annotation_", "metric_"),
                        **({"value": row.get("annotation_value")} if row.get("annotation_value") not in (None, "") else {}),
                    },
                )
            )
        return PlateWellDataRequest(
            data_template_code=data_template_code,
            relationship_type=relationship_type,
            records=records,
        )

    def _requests_from_sets_sheet(self, sheet: ParsedSheet) -> list[LabSetRequest]:
        requests: list[LabSetRequest] = []
        for row in sheet.rows:
            name = str(row.get("name") or row.get("set_name") or "").strip()
            if not name:
                continue
            requests.append(
                LabSetRequest(
                    name=name,
                    description=str(row.get("description") or "").strip() or None,
                    members=self._split_values(row.get("members") or row.get("member_euids")),
                    external_members=self._split_values(row.get("external_members")),
                    operator=str(row.get("operator") or "").strip() or None,
                    instrument=str(row.get("instrument") or row.get("instrument_euid") or "").strip() or None,
                    reagents=self._split_values(row.get("reagents") or row.get("reagent_euids")),
                    machine=str(row.get("machine") or "").strip() or None,
                    flowcell_barcode=str(row.get("flowcell_barcode") or "").strip() or None,
                    status=str(row.get("status") or "created").strip() or "created",
                    metadata=self._row_metadata(row, "metadata_", "set_"),
                )
            )
        return requests

    def import_spreadsheet(
        self, *, filename: str, data: bytes, dry_run: bool = True
    ) -> dict[str, Any]:
        sheets = parse_workbook(filename, data)
        actions: list[dict[str, Any]] = []
        for sheet in sheets:
            action = self._sheet_action(sheet)
            entry: dict[str, Any] = {
                "sheet": sheet.name,
                "action": action,
                "headers": sheet.headers,
                "row_count": len(sheet.rows),
            }
            if action in {"container_interaction_preview", "container_annotation_preview", "unknown"}:
                entry["preview_rows"] = sheet.rows[:25]
                actions.append(entry)
                continue
            if action == "extraction_plate":
                request = self._request_from_extraction_sheet(sheet)
                entry["request"] = request.model_dump(mode="json")
                if not dry_run:
                    entry["result"] = self.create_extraction_plate(request)
            elif action == "extraction_qc":
                request = self._request_from_qc_sheet(sheet)
                entry["request"] = request.model_dump(mode="json")
                if not dry_run:
                    entry["result"] = self.fill_extraction_qc_plate(request)
            elif action == "seq_library_plate":
                request = self._request_from_library_sheet(sheet)
                entry["request"] = request.model_dump(mode="json")
                if not dry_run:
                    entry["result"] = self.create_seq_library_plate(request)
            elif action == "seq_pool":
                request = self._request_from_pool_sheet(sheet)
                entry["request"] = request.model_dump(mode="json")
                if not dry_run:
                    entry["result"] = self.create_seq_library_pool(request)
            elif action == "seq_run_set":
                request = self._request_from_run_sheet(sheet)
                entry["request"] = request.model_dump(mode="json")
                if not dry_run:
                    entry["result"] = self.create_seq_run_set(request)
            elif action == "plate_well_data":
                request = self._request_from_data_sheet(sheet)
                entry["request"] = request.model_dump(mode="json")
                if not dry_run:
                    entry["result"] = self.attach_plate_well_data(request)
            elif action == "sets":
                requests = self._requests_from_sets_sheet(sheet)
                entry["request"] = [item.model_dump(mode="json") for item in requests]
                if not dry_run:
                    entry["result"] = [self.create_lab_set(item) for item in requests]
            actions.append(entry)
        return {"filename": filename, "dry_run": dry_run, "actions": actions}

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
