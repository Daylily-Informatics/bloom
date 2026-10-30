# Bloom Lab Actions

All `<persisted-...-euid>` placeholders below must be replaced with actual identifiers returned by the owning service. They are not executable example identities. Existing records must keep their stored EUIDs.

## Overview

Bloom lab actions are a temporary, Bloom-owned operator layer for moving real lab materials through a small number of common wet-lab setup flows:

1. Incoming biospecimen tubes to an extraction plate.
2. Extraction plate wells to a sequencing-library plate.
3. Sequencing libraries to a sequencing-library pool tube.
4. Pool tube plus instrument/run metadata to a sequencing run set.

The implementation is intentionally narrow. It uses existing TapDB generic instances, Bloom templates, and lineage records. It does not revive queue or beta-lab workflow-driving behavior, does not add database tables, and does not attempt to schedule or execute work.

The GUI route is `/lab-actions`. The API route family is `/api/v1/lab-actions/*`.

## Current Template Matrix

The current flow uses the released Bloom template pack, including the generic run-set template.

| Purpose | Semantic template path | Instance prefix | Notes |
|---|---|---:|---|
| Generic run/set object | `set/run-set/generic/1.01` | `BGS` | Released template. Seeded as `category=set`, `type=run-set`, `subtype=generic`, `version=1.01`. Holds named sets, run metadata, members, external members, status, and arbitrary metadata. |
| Extraction plate | `container/plate/fixed-plate-96/1.0` | `BCP` | Existing recursive 96-well plate template. Creates linked well containers. |
| Sequencing-library plate | `container/plate/sequencing-library-plate-96/1.0` | `BCP` | Existing recursive 96-well plate template. Creates linked well containers. |
| Plate well | `container/well/fixed-plate-well/1.0` | `BCW` | Created by recursive plate templates. |
| Pool tube | `container/tube/tube-generic-10ml/1.0` | `BCT` | Existing generic tube template. More specific pool-tube templates can be added later if needed. |
| Incoming specimen contents | `material/specimen/{blood-whole,buccal-swab,saliva}/1.0` | `BNB`, `BNS`, `BNA` | Existing whole-blood, buccal-swab, and saliva specimen templates. Incoming tubes must already hold one material object unless the caller creates/fills the tube first. |
| Extraction well gDNA | `material/sample/gdna/1.0` | `BNG` | Created during extraction mapping. |
| Sequencing-library content | `material/sample/sequencing-library/1.0` | `BNQ` | Created during library plate mapping. |
| Sequencing-library pool content | `material/pool/sequencing-library/1.0` | `BNP` | Created when filling the pool tube. |
| Sequencing index reagent | `material/reagent/sequencing-index/1.0` | `BNX` | Optional; callers may also store an index barcode string directly. |
| gDNA quant data | `data/quantification/gdna/1.0` | `BDQ` | Optional per-well extraction output data. |

No additional templates are required for the current implementation. The seed file stores semantic identity in `category`, `type`, `subtype` and `version`; `instance_prefix` is a separate issuance field. Existing historical prefix/template differences do not authorize regenerating EUIDs or rewriting template semantics. If production operators need separate EUID prefixes or stricter metadata for pool tubes, flowcells, reagent sets, or run kits, add those templates as a separate versioned template-pack change and update this matrix before production rollout.

## Lineage Contract

Lab actions write explicit Bloom lineage records. The key relationship names are:

| Relationship | Source | Target | Meaning |
|---|---|---|---|
| `contains` | Plate | Well container | Recursive plate template child containment. |
| `HOLDS_MATERIAL` | Container | Content/material | Container currently holds the material. |
| `DERIVED_FROM` | Parent content/material | Child content/material | New material was derived from the source material. |
| `extraction_source_container` | Incoming tube | Extraction well | Tube was assigned to this extraction well. |
| `library_source_well` | Extraction well | Library well | Source well mapped to destination library well. |
| `uses_index` | Library content | Index reagent | Library uses this sequencing index reagent. |
| `pooled_from_container` | Source container | Pool tube | Pool tube was filled from this source container. |
| `run_set_member` | Run set | Member EUID | Member belongs to the run set. |
| `run_uses_pool` | Sequencing run set | Pool tube/content | Run set uses this sequencing pool. |
| `run_uses_instrument` | Sequencing run set | Instrument EUID | Run set uses this sequencer/instrument. |
| `run_uses_reagent` | Sequencing run set | Reagent EUID | Run set uses this reagent. |

`HOLDS_MATERIAL` and `DERIVED_FROM` also carry Bloom v0 edge metadata through the existing lineage metadata mechanism.

Run-set membership has one authoritative `run_set_member` edge from the set to
the member. Reverse navigation reads the same edge through its child endpoint;
it must not create an `associated_set` edge back to the set. Reciprocal persisted
edges create a cycle and violate the native DAG contract. Historical reverse
edges require an explicitly approved, audited owner-service repair; deploying
this writer change does not modify existing lineage.

## API Workflows

All GUI actions are API-backed. The GUI should remain a convenience wrapper, not a separate behavior surface.

### 1. Extraction Plate

Auto mode assigns 1-95 tube EUIDs in row-major well order, starting at `A1`.

```bash
curl -sS -X POST "$BLOOM_URL/api/v1/lab-actions/extraction-plates" \
  -H "Authorization: Bearer $BLOOM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "auto",
    "tube_euids": ["<persisted-bct-example1-euid>", "<persisted-bct-example2-euid>"],
    "plate_name": "extraction plate",
    "create_run_set": true
  }'
```

Directed mode lets the caller specify destination wells. It can create a new plate or fill an existing plate:

```json
{
  "mode": "directed",
  "plate_euid": "<persisted-bcp-existing-euid>",
  "assignments": [
    {"tube_euid": "<persisted-bct-example1-euid>", "row": "A", "col": 1},
    {"tube_euid": "<persisted-bct-example2-euid>", "row": "B", "col": 1}
  ]
}
```

The action creates gDNA content in each destination well, links the tube to the well, and links the incoming tube content to the new gDNA content.

### 2. Extraction QC Plate

Extraction QC fills a new or existing QC plate from an extraction plate. If assignments are omitted, Bloom uses every filled source well from the source extraction plate in row-major order. Explicit assignments can name source wells, destination QC wells, result/status, and structured QC data.

```bash
curl -sS -X POST "$BLOOM_URL/api/v1/lab-actions/extraction-qc-plates" \
  -H "Authorization: Bearer $BLOOM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_plate_euid": "<persisted-bcp-extraction-euid>",
    "qc_plate_name": "extraction QC plate",
    "assignments": [
      {
        "source_well_euid": "<persisted-bcw-sourcea1-euid>",
        "qc_row": "A",
        "qc_col": 1,
        "result": "pass",
        "status": "recorded",
        "data": {"concentration_ng_ul": 43.2, "a260_280": 1.83}
      }
    ],
    "create_run_set": true
  }'
```

The action creates `data/operation/extraction-qc/1.0/` records, links source well/content to QC well/data, and rejects requests above the 96-well plate capacity.

### 3. Sequencing-Library Plate

`plate_1_to_1` mode maps every filled extraction well to the same position on a new sequencing-library plate.

```bash
curl -sS -X POST "$BLOOM_URL/api/v1/lab-actions/seq-library-plates" \
  -H "Authorization: Bearer $BLOOM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "plate_1_to_1",
    "source_plate_euid": "<persisted-bcp-extraction-euid>",
    "plate_name": "seq library plate"
  }'
```

Directed mode accepts explicit input wells and output wells. Optional fields include `index_barcode`, `index_euid`, and arbitrary per-well `data`.

### 4. Sequencing-Library Pool Tube

Pools accept input tube EUIDs, well EUIDs, content EUIDs, or existing pool EUIDs. The action creates or fills a pool tube and creates sequencing-library pool content.

```bash
curl -sS -X POST "$BLOOM_URL/api/v1/lab-actions/seq-library-pools" \
  -H "Authorization: Bearer $BLOOM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "input_euids": ["<persisted-bnq-lib1-euid>", "<persisted-bnq-lib2-euid>"],
    "platform": "ILMN",
    "pool_name": "seq library"
  }'
```

Supported platform metadata values are `ILMN`, `ONT`, `Ultima`, `PacBio`, and `CompleteGenomics`.

### 5. Generic Lab Sets

Sets use the `set/run-set/generic/1.01` template for lightweight batch/run grouping. They can hold Bloom EUID members, external EUID/string members, operator/instrument/reagent metadata, status, and arbitrary metadata. Set membership is modeled with lineage and stored properties; it does not drive queues or execution.

```bash
curl -sS -X POST "$BLOOM_URL/api/v1/lab-actions/sets" \
  -H "Authorization: Bearer $BLOOM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "extraction reagent set",
    "description": "Reagents, machine, and operator for extraction batch",
    "members": ["<persisted-beq-instrument-euid>"],
    "external_members": ["lot:REAGENT-2026-06-18"],
    "operator": "operator@example.com",
    "status": "created",
    "metadata": {"bench": "SSF"}
  }'
```

Members can be appended later:

```bash
curl -sS -X POST "$BLOOM_URL/api/v1/lab-actions/sets/<persisted-bgs-set-euid>/members" \
  -H "Authorization: Bearer $BLOOM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"members": ["<persisted-bct-tube-euid>"], "external_members": ["vendor-kit:123"]}'
```

### 6. Plate-Well Associated Data

Per-well data can be attached to a well or the well content. This is intentionally generic so operators can capture QC, quantification, or other measurements without introducing a new workflow engine.

```bash
curl -sS -X POST "$BLOOM_URL/api/v1/lab-actions/plate-well-data" \
  -H "Authorization: Bearer $BLOOM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "plate_euid": "<persisted-bcp-extraction-euid>",
    "records": [
      {
        "row": "A",
        "col": 1,
        "data_template_code": "data/quantification/gdna/1.0/",
        "name": "A1 gDNA quant",
        "target": "content",
        "data": {"concentration_ng_ul": 43.2}
      }
    ]
  }'
```

### 7. Sequencing Run Set

Sequencing run setup creates a `set/run-set/generic/1.01` object with pool, operator, instrument, reagent, flowcell, status, and platform metadata.

```bash
curl -sS -X POST "$BLOOM_URL/api/v1/lab-actions/seq-runs" \
  -H "Authorization: Bearer $BLOOM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "pool_tube_euid": "<persisted-bct-pool-euid>",
    "pool_content_euid": "<persisted-bnp-poolcontent-euid>",
    "platform": "ILMN",
    "operator": "operator@example.com",
    "instrument_euid": "<persisted-beq-sequencer-euid>",
    "flowcell_barcode": "FLOWCELL123",
    "status": "created"
  }'
```

Status values are `created`, `running`, `abandoned`, `complete`, and `error`.

### Sample Sheet Download

ILMN sample-sheet download is implemented:

```bash
curl -sS "$BLOOM_URL/api/v1/lab-actions/seq-runs/<persisted-bgs-runset-euid>/samplesheet" \
  -H "Authorization: Bearer $BLOOM_TOKEN" \
  -o SampleSheet.csv
```

The sample sheet includes the run-set EUID and library mappings so OWY can walk back through:

`run set -> pool -> library content -> gDNA content -> incoming specimen content`

Non-ILMN sample-sheet downloads fail explicitly until concrete file formats are specified. There is no fallback manifest.

### Spreadsheet Uploads

Spreadsheet uploads are available at:

```bash
curl -sS -X POST "$BLOOM_URL/api/v1/lab-actions/spreadsheet-import?dry_run=true" \
  -H "Authorization: Bearer $BLOOM_TOKEN" \
  -F "file=@lab-actions.xlsx"
```

Use `dry_run=false` to execute supported sheets after previewing the parsed operations. The parser accepts `.xlsx` and `.csv`; other extensions fail explicitly. The parser normalizes common operator header typos such as `Continer`, `Conteiner`, and `Templae`.

Executable sheet names:

| Sheet | Purpose | Key columns |
|---|---|---|
| `Extraction Plate` | Create or fill extraction plate from incoming tubes. | `tube_euid`, `row`, `col`, `plate_euid`, `plate_name`, `run_set_name`, `print_labels` |
| `Extraction QC` | Fill extraction QC plate from extraction wells. | `source_plate_euid`, `source_well_euid`, `source_row`, `source_col`, `qc_plate_euid`, `qc_plate_name`, `qc_row`, `qc_col`, `result`, `status`, `data` |
| `Seq Library Plate` | Create library plate from extraction wells. | `source_plate_euid`, `source_well_euid`, `source_row`, `source_col`, `output_row`, `output_col`, `index_barcode`, `index_euid`, `data` |
| `Seq Pool` | Create/fill pool tube from wells, tubes, contents, or pools. | `input_euids`, `pool_tube_euid`, `pool_name`, `pool_content_name`, `platform`, `run_set_name`, `print_labels` |
| `Seq Run Set` | Create sequencing run set from a pool and run metadata. | `pool_tube_euid`, `pool_content_euid`, `platform`, `operator`, `instrument_euid`, `flowcell_barcode`, `reagent_euids`, `status`, `metadata` |
| `Sets` | Create generic sets. | `name`, `description`, `members`, `external_members`, `operator`, `instrument`, `reagents`, `machine`, `flowcell_barcode`, `status`, `metadata` |
| `Plate Well Data` | Attach data records to wells or contents. | `plate_euid`, `well_euid`, `row`, `col`, `target`, `data_template_code`, `name`, `data` |

The example workbook family with `Bulk Create`, `Transfer`, and `Annotation` sheets is parsed and previewed as container-interaction evidence. Those sheets are not blindly executed because they can describe broad generic operations; executable lab-action sheets use the specific names above.

### Plate Mapping CSV

Any plate-like container can export a one-degree mapping CSV:

```bash
curl -sS "$BLOOM_URL/api/v1/lab-actions/plates/<persisted-bcp-plate-euid>/mapping.csv" \
  -H "Authorization: Bearer $BLOOM_TOKEN" \
  -o plate_mapping.csv
```

Columns:

- `tube_euid`
- `plate_euid`
- `well_euid`
- `well_row`
- `well_col`
- `well_content_euid`
- `parent_content_euid`
- `one_degree_parent_euids`
- `one_degree_child_euids`

### EUID Barcode Printing

Printing goes through Zebra Day. Tests mock this integration; real printer output requires explicit operator approval.

```bash
curl -sS -X POST "$BLOOM_URL/api/v1/lab-actions/print-euids" \
  -H "Authorization: Bearer $BLOOM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "euids": ["<persisted-bcp-plate-euid>", "<persisted-bct-pool-euid>"],
    "lab": "SSF",
    "printer_id": "printer-id",
    "label_zpl_style": "euid",
    "copies": 1
  }'
```

## Object Create Count

Both object-creation APIs support `count` for creating multiple sibling objects from the same non-recursive, non-singleton template.

Recursive templates, such as 96-well plates, reject `count > 1` because a single plate already expands into many child objects. Create recursive containers one at a time.

## GUI Flow

Open `/lab-actions`.

The wizard has these panels:

1. Extraction Plate.
2. Extraction QC Plate.
3. Sequencing-Library Plate.
4. Sequencing Pool Tube.
5. Sequencing Run Set.
6. EUID Barcode Printing.
7. Generic Set Management.
8. Plate-Well Data.
9. Spreadsheet Upload.

Successful actions populate downstream fields where possible, for example extraction plate EUID into the QC and library plate steps and pool tube/content EUIDs into the run-set step.

## Release and production changes

Use the [working-branch release policy](how-tos.md#publish-a-documentation-release). Documentation changes need no tests, image build, Dayhoff pin update or redeploy. Runtime changes require an explicitly scoped selected-service deployment; do not trigger a full stack deployment or double-release Dayhoff for every edit.

Existing loaded template semantics remain immutable. `set/run-set/generic/1.01` is already part of the released template pack; changing its properties requires a new version. Add required new definitions through an authorized native operation without overwriting historical bindings. Do not run `refresh-templates` against production as a routine release step.

No tests run by default. If the user explicitly requests a specific test scope twice, use the corresponding existing cases; this document does not authorize a suite. Normal deployment acceptance is the requested running service and actual user flow. Real printer jobs or production material creation require explicit scope; do not create lab objects merely to publish documentation.

## Historical Implementation Evidence

The original lab-action implementation ledger is:

`docs/plans/20260618T000000Z_bloom_lab_action_flow_ledger.md`

Local screenshot evidence from the implementation pass:

`output/playwright/bloom_lab_actions/lab_actions_wizard_local.png`

The screenshot is historical local evidence, not current production proof. The accepted Bloom 10 migration and subsequent release boundaries are recorded in [the completed migration ledger](plans/20260911T150553Z_bloom_tapdb_10_1_migration_ledger.md). No new browser run or deployment is required for this documentation update.
