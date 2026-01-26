-- BLOOM LIMS Prefix Sequences
-- Phase 3 of BLOOM Database Refactor Plan
--
-- These sequences are used by TapDB's EUID generation triggers to create
-- unique identifiers with BLOOM-specific prefixes.
-- Each sequence corresponds to an euid_prefix defined in bloom_lims/config/*/metadata.json.
--
-- Format: <prefix><sequence_number> e.g., CX1, CX2, ...

-- Container prefixes
CREATE SEQUENCE IF NOT EXISTS cx_instance_seq;   -- default container
CREATE SEQUENCE IF NOT EXISTS cwx_instance_seq;  -- well

-- Content prefixes
CREATE SEQUENCE IF NOT EXISTS mx_instance_seq;   -- default content
CREATE SEQUENCE IF NOT EXISTS mrx_instance_seq;  -- reagent
CREATE SEQUENCE IF NOT EXISTS mcx_instance_seq;  -- control

-- Equipment prefixes
CREATE SEQUENCE IF NOT EXISTS ex_instance_seq;   -- default equipment

-- Workflow prefixes
CREATE SEQUENCE IF NOT EXISTS wx_instance_seq;   -- default workflow
CREATE SEQUENCE IF NOT EXISTS ay_instance_seq;   -- assay

-- Workflow Step prefixes
CREATE SEQUENCE IF NOT EXISTS wsx_instance_seq;  -- default workflow step
CREATE SEQUENCE IF NOT EXISTS qx_instance_seq;   -- queue

-- Data prefixes
CREATE SEQUENCE IF NOT EXISTS dx_instance_seq;   -- default data

-- Test Requisition prefixes
CREATE SEQUENCE IF NOT EXISTS trx_instance_seq;  -- default test requisition

-- Actor prefixes
CREATE SEQUENCE IF NOT EXISTS ax_instance_seq;   -- default actor

-- Action prefixes
CREATE SEQUENCE IF NOT EXISTS xx_instance_seq;   -- default action

-- File prefixes
CREATE SEQUENCE IF NOT EXISTS fg_instance_seq;   -- default file (generic)
CREATE SEQUENCE IF NOT EXISTS fi_instance_seq;   -- file
CREATE SEQUENCE IF NOT EXISTS fs_instance_seq;   -- file_set
CREATE SEQUENCE IF NOT EXISTS fx_instance_seq;   -- shared_ref

-- Subject prefixes
CREATE SEQUENCE IF NOT EXISTS sx_instance_seq;   -- default subject

-- Health Event prefixes
CREATE SEQUENCE IF NOT EXISTS ev_instance_seq;   -- default health event

-- Generic prefixes
CREATE SEQUENCE IF NOT EXISTS gx_instance_seq;   -- default generic

