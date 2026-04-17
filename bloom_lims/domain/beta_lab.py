"""Queue-driven beta lab domain services for Bloom."""

from __future__ import annotations

from bloom_lims.bobjs import BloomObj
from bloom_lims.config import get_settings
from bloom_lims.db import BLOOMdb3
from bloom_lims.domain.beta_actions import BloomBetaActionRecorder
from bloom_lims.domain.beta_lab_materials import _BetaLabMaterialsMixin
from bloom_lims.domain.beta_lab_queue import _BetaLabQueueMixin
from bloom_lims.domain.beta_lab_refs import _BetaLabReferenceMixin
from bloom_lims.domain.beta_lab_stages import _BetaLabStagesMixin
from bloom_lims.domain.beta_lab_store import _BetaLabStoreMixin
from bloom_lims.domain.execution_queue import ExecutionQueueService
from bloom_lims.integrations.dewey.client import DeweyArtifactClient


class BetaLabService(
    _BetaLabMaterialsMixin,
    _BetaLabQueueMixin,
    _BetaLabStagesMixin,
    _BetaLabReferenceMixin,
    _BetaLabStoreMixin,
):
    """Implements the queue-centric Bloom beta wet-lab flow."""

    EXTERNAL_REFERENCE_TEMPLATE_CODE = "generic/generic/external_object_link/1.0"
    EXTERNAL_REFERENCE_RELATIONSHIP = "has_external_reference"
    PROCESS_ITEM_REFERENCE_TYPE = "atlas_test_fulfillment_item"
    PATIENT_REFERENCE_TYPE = "atlas_patient"
    TRF_REFERENCE_TYPE = "atlas_trf"
    TEST_REFERENCE_TYPE = "atlas_test"
    TESTKIT_REFERENCE_TYPE = "atlas_testkit"
    SHIPMENT_REFERENCE_TYPE = "atlas_shipment"
    ORGANIZATION_SITE_REFERENCE_TYPE = "atlas_organization_site"
    COLLECTION_EVENT_REFERENCE_TYPE = "atlas_collection_event"
    GENERIC_DATA_TEMPLATE_CODE = "data/generic/generic/1.0"
    BETA_KIND_QUEUE_DEFINITION = "queue_definition"
    BETA_KIND_QUEUE_EVENT = "queue_event"
    BETA_KIND_WORK_ITEM = "beta_work_item"
    BETA_KIND_CLAIM = "beta_claim"
    BETA_KIND_RESERVATION = "beta_reservation"
    BETA_KIND_CONSUMPTION_EVENT = "beta_consumption_event"
    REL_QUEUE_MEMBERSHIP = "beta_queue_membership"
    REL_QUEUE_EVENT = "beta_queue_event"
    REL_QUEUE_EVENT_QUEUE = "beta_queue_event_queue"
    REL_QUEUE_WORK_ITEM = "beta_queue_work_item"
    REL_WORK_ITEM_SUBJECT = "beta_work_item_subject"
    REL_WORK_ITEM_CLAIM = "beta_work_item_claim"
    REL_MATERIAL_RESERVATION = "beta_material_reservation"
    REL_MATERIAL_CONSUMPTION = "beta_material_consumption"
    REL_USED_INSTRUMENT = "beta_used_instrument"
    REL_USED_REAGENT = "beta_used_reagent"
    POOL_TEMPLATE_CODE = "content/pool/generic/1.0"
    POOL_CONTAINER_TEMPLATE_CODE = "container/tube/tube-generic-10ml/1.0"
    LIBRARY_PREP_OUTPUT_TEMPLATE_CODE = "data/wetlab/library_prep_output/1.0"
    LIBRARY_PLATE_TEMPLATE_CODE = "container/plate/fixed-plate-96/1.0"
    EXTRACTION_TEMPLATE_BY_TYPE = {
        "cfdna": "content/sample/cfdna/1.0",
        "gdna": "content/sample/gdna/1.0",
    }
    LIB_PREP_QUEUE_BY_PLATFORM = {
        "ILMN": "ilmn_lib_prep",
        "ONT": "ont_lib_prep",
    }
    SEQ_POOL_QUEUE_BY_PLATFORM = {
        "ILMN": "ilmn_seq_pool",
        "ONT": "ont_seq_pool",
    }
    START_RUN_QUEUE_BY_PLATFORM = {
        "ILMN": "ilmn_start_seq_run",
        "ONT": "ont_start_seq_run",
    }
    CANONICAL_QUEUES = (
        "extraction_prod",
        "extraction_rnd",
        "post_extract_qc",
        "ilmn_lib_prep",
        "ont_lib_prep",
        "ilmn_seq_pool",
        "ont_seq_pool",
        "ilmn_start_seq_run",
        "ont_start_seq_run",
    )
    NEXT_ACTION_BY_QUEUE = {
        "extraction_prod": "create_extraction",
        "extraction_rnd": "create_extraction",
        "post_extract_qc": "record_post_extract_qc",
        "ilmn_lib_prep": "create_library_prep",
        "ont_lib_prep": "create_library_prep",
        "ilmn_seq_pool": "create_pool",
        "ont_seq_pool": "create_pool",
        "ilmn_start_seq_run": "create_run",
        "ont_start_seq_run": "create_run",
    }
    QUEUE_CAPABILITIES = {
        "extraction_prod": ["wetlab.extraction"],
        "extraction_rnd": ["wetlab.extraction"],
        "post_extract_qc": ["wetlab.post_extract_qc"],
        "ilmn_lib_prep": ["wetlab.library_prep", "platform.ILMN"],
        "ont_lib_prep": ["wetlab.library_prep", "platform.ONT"],
        "ilmn_seq_pool": ["wetlab.pooling", "platform.ILMN"],
        "ont_seq_pool": ["wetlab.pooling", "platform.ONT"],
        "ilmn_start_seq_run": ["wetlab.run_start", "platform.ILMN"],
        "ont_start_seq_run": ["wetlab.run_start", "platform.ONT"],
    }

    def __init__(
        self,
        *,
        app_username: str,
        dewey_client: DeweyArtifactClient | None = None,
    ):
        self.bdb = BLOOMdb3(app_username=app_username)
        self.bobj = BloomObj(self.bdb)
        self.action_recorder = BloomBetaActionRecorder(
            self.bdb.session,
            domain_code=self.bdb.domain_code,
        )
        self.execution = ExecutionQueueService(
            app_username=app_username,
            bdb=self.bdb,
        )
        self.dewey_client = (
            dewey_client if dewey_client is not None else self._build_dewey_client()
        )

    def close(self) -> None:
        self.bdb.close()

    @staticmethod
    def _build_dewey_client() -> DeweyArtifactClient | None:
        settings = get_settings()
        if not settings.dewey.enabled:
            return None
        return DeweyArtifactClient(
            base_url=settings.dewey.base_url,
            token=settings.dewey.token,
            timeout_seconds=settings.dewey.timeout_seconds,
            verify_ssl=settings.dewey.verify_ssl,
        )
