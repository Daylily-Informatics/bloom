-- BLOOM LIMS Prefix Sequences
-- Phase 3 of BLOOM Database Refactor Plan
--
-- These sequences are used by TapDB's EUID generation triggers to create
-- unique identifiers with BLOOM-specific prefixes.
-- Each sequence corresponds to an euid_prefix defined in bloom_lims/config/*/metadata.json.
--
-- Format: <prefix><sequence_number> e.g., BCT1, BCP2, ...

CREATE SEQUENCE IF NOT EXISTS bac_instance_seq;  -- action
CREATE SEQUENCE IF NOT EXISTS bar_instance_seq;  -- actor
CREATE SEQUENCE IF NOT EXISTS bbx_instance_seq;  -- bloom
CREATE SEQUENCE IF NOT EXISTS bc_instance_seq;   -- generic container reserve
CREATE SEQUENCE IF NOT EXISTS bcb_instance_seq;  -- bottle container
CREATE SEQUENCE IF NOT EXISTS bce_instance_seq;  -- flowcell lane container
CREATE SEQUENCE IF NOT EXISTS bcf_instance_seq;  -- flowcell container
CREATE SEQUENCE IF NOT EXISTS bcn_instance_seq;  -- historical container prefix
CREATE SEQUENCE IF NOT EXISTS bcp_instance_seq;  -- plate container
CREATE SEQUENCE IF NOT EXISTS bcr_instance_seq;  -- rack/storage container
CREATE SEQUENCE IF NOT EXISTS bct_instance_seq;  -- tube container
CREATE SEQUENCE IF NOT EXISTS bcw_instance_seq;  -- well container
CREATE SEQUENCE IF NOT EXISTS bd_instance_seq;   -- generic data reserve
CREATE SEQUENCE IF NOT EXISTS bda_instance_seq;  -- library-index assignment data
CREATE SEQUENCE IF NOT EXISTS bdc_instance_seq;  -- custody/location data
CREATE SEQUENCE IF NOT EXISTS bdn_instance_seq;  -- pooling evidence data
CREATE SEQUENCE IF NOT EXISTS bdp_instance_seq;  -- library prep evidence data
CREATE SEQUENCE IF NOT EXISTS bdq_instance_seq;  -- quantification data
CREATE SEQUENCE IF NOT EXISTS bdt_instance_seq;  -- transfer/execution data
CREATE SEQUENCE IF NOT EXISTS bdx_instance_seq;  -- extraction evidence data
CREATE SEQUENCE IF NOT EXISTS bdy_instance_seq;  -- extraction QC evidence data
CREATE SEQUENCE IF NOT EXISTS beq_instance_seq;  -- equipment
CREATE SEQUENCE IF NOT EXISTS bfx_instance_seq;  -- file
CREATE SEQUENCE IF NOT EXISTS bg_instance_seq;   -- generic helper reserve
CREATE SEQUENCE IF NOT EXISTS bgm_instance_seq;  -- generic mapping bundle
CREATE SEQUENCE IF NOT EXISTS bgp_instance_seq;  -- provenance assertion
CREATE SEQUENCE IF NOT EXISTS bgr_instance_seq;  -- registry/meta helper
CREATE SEQUENCE IF NOT EXISTS bgs_instance_seq;  -- state/projection helper
CREATE SEQUENCE IF NOT EXISTS bgt_instance_seq;  -- historical external-object prefix
CREATE SEQUENCE IF NOT EXISTS bgv_instance_seq;  -- validation/helper assertion
CREATE SEQUENCE IF NOT EXISTS bgx_instance_seq;  -- external object mapping
CREATE SEQUENCE IF NOT EXISTS bhe_instance_seq;  -- health_event
CREATE SEQUENCE IF NOT EXISTS bn_instance_seq;   -- generic content reserve
CREATE SEQUENCE IF NOT EXISTS bna_instance_seq;  -- saliva specimen content
CREATE SEQUENCE IF NOT EXISTS bnb_instance_seq;  -- blood specimen/content
CREATE SEQUENCE IF NOT EXISTS bnc_instance_seq;  -- cfDNA content
CREATE SEQUENCE IF NOT EXISTS bnf_instance_seq;  -- FFPE specimen content
CREATE SEQUENCE IF NOT EXISTS bng_instance_seq;  -- gDNA content
CREATE SEQUENCE IF NOT EXISTS bnk_instance_seq;  -- control material content
CREATE SEQUENCE IF NOT EXISTS bnp_instance_seq;  -- sequencing library pool content
CREATE SEQUENCE IF NOT EXISTS bnq_instance_seq;  -- sequencing library content
CREATE SEQUENCE IF NOT EXISTS bnr_instance_seq;  -- reagent content
CREATE SEQUENCE IF NOT EXISTS bns_instance_seq;  -- buccal specimen content
CREATE SEQUENCE IF NOT EXISTS bnx_instance_seq;  -- sequencing index reagent content
CREATE SEQUENCE IF NOT EXISTS br_instance_seq;   -- generic run reserve
CREATE SEQUENCE IF NOT EXISTS brc_instance_seq;  -- Complete Genomics sequencing run
CREATE SEQUENCE IF NOT EXISTS brm_instance_seq;  -- Illumina sequencing run
CREATE SEQUENCE IF NOT EXISTS brn_instance_seq;  -- ONT sequencing run
CREATE SEQUENCE IF NOT EXISTS brp_instance_seq;  -- PacBio sequencing run
CREATE SEQUENCE IF NOT EXISTS brt_instance_seq;  -- Ultima sequencing run
CREATE SEQUENCE IF NOT EXISTS bsj_instance_seq;  -- subject
CREATE SEQUENCE IF NOT EXISTS bwf_instance_seq;  -- workflow
CREATE SEQUENCE IF NOT EXISTS bws_instance_seq;  -- workflow_step
