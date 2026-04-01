-- BLOOM LIMS Prefix Sequences
-- Phase 3 of BLOOM Database Refactor Plan
--
-- These sequences are used by TapDB's EUID generation triggers to create
-- unique identifiers with BLOOM-specific prefixes.
-- Each sequence corresponds to an euid_prefix defined in bloom_lims/config/*/metadata.json.
--
-- Format: <prefix><sequence_number> e.g., BCN1, BCN2, ...

CREATE SEQUENCE IF NOT EXISTS bac_instance_seq;  -- action
CREATE SEQUENCE IF NOT EXISTS bar_instance_seq;  -- actor
CREATE SEQUENCE IF NOT EXISTS bbl_instance_seq;  -- bloom
CREATE SEQUENCE IF NOT EXISTS bcn_instance_seq;  -- container
CREATE SEQUENCE IF NOT EXISTS bct_instance_seq;  -- content
CREATE SEQUENCE IF NOT EXISTS bdt_instance_seq;  -- data
CREATE SEQUENCE IF NOT EXISTS beq_instance_seq;  -- equipment
CREATE SEQUENCE IF NOT EXISTS bfl_instance_seq;  -- file
CREATE SEQUENCE IF NOT EXISTS bhe_instance_seq;  -- health_event
CREATE SEQUENCE IF NOT EXISTS bsj_instance_seq;  -- subject
CREATE SEQUENCE IF NOT EXISTS btr_instance_seq;  -- test_requisition
CREATE SEQUENCE IF NOT EXISTS bwf_instance_seq;  -- workflow
CREATE SEQUENCE IF NOT EXISTS bws_instance_seq;  -- workflow_step
