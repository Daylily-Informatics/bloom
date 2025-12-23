-- BLOOM LIMS Analytics Views Installation Script
-- These views provide standardized metrics for laboratory analytics dashboards
-- Compatible with Metabase, Grafana, Apache Superset, and other BI tools
--
-- Usage: psql -d bloom_lims -f install_views.sql
--
-- Note: These views are designed to be portable across different LIS systems.
-- Adapt the underlying table/column names as needed for your specific LIS.

-- ============================================================================
-- VIEW: v_sample_throughput
-- Purpose: Track sample processing rates over time
-- Key Metrics: Daily sample counts, processing rates, cumulative totals
-- ============================================================================
DROP VIEW IF EXISTS v_sample_throughput CASCADE;
CREATE OR REPLACE VIEW v_sample_throughput AS
SELECT 
    DATE(gi.created_dt) AS processing_date,
    gi.super_type,
    gi.btype AS sample_type,
    gi.b_sub_type AS sample_subtype,
    gi.bstatus AS status,
    COUNT(*) AS sample_count,
    COUNT(*) FILTER (WHERE gi.bstatus = 'complete') AS completed_count,
    COUNT(*) FILTER (WHERE gi.bstatus = 'in_progress') AS in_progress_count,
    COUNT(*) FILTER (WHERE gi.bstatus = 'created') AS pending_count,
    COUNT(*) FILTER (WHERE gi.bstatus = 'failed') AS failed_count,
    ROUND(
        COUNT(*) FILTER (WHERE gi.bstatus = 'complete')::NUMERIC / 
        NULLIF(COUNT(*), 0) * 100, 2
    ) AS completion_rate_pct
FROM generic_instance gi
WHERE gi.is_deleted = FALSE
    AND gi.super_type IN ('content', 'container')
GROUP BY 
    DATE(gi.created_dt),
    gi.super_type,
    gi.btype,
    gi.b_sub_type,
    gi.bstatus
ORDER BY processing_date DESC;

COMMENT ON VIEW v_sample_throughput IS 
'Sample throughput metrics for laboratory analytics. Shows daily processing rates by sample type.';

-- ============================================================================
-- VIEW: v_workflow_bottlenecks  
-- Purpose: Identify workflow queues with backlogs and long wait times
-- Key Metrics: Queue depth, average wait time, oldest item age
-- ============================================================================
DROP VIEW IF EXISTS v_workflow_bottlenecks CASCADE;
CREATE OR REPLACE VIEW v_workflow_bottlenecks AS
WITH workflow_steps AS (
    SELECT 
        gi.uuid,
        gi.euid,
        gi.name,
        gi.btype AS workflow_type,
        gi.b_sub_type AS step_type,
        gi.bstatus AS status,
        gi.created_dt,
        gi.modified_dt,
        EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - gi.created_dt)) / 3600 AS hours_since_created,
        EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - gi.modified_dt)) / 3600 AS hours_since_modified
    FROM generic_instance gi
    WHERE gi.super_type = 'workflow_step'
        AND gi.is_deleted = FALSE
),
queue_items AS (
    SELECT 
        gil.parent_instance_uuid AS workflow_step_uuid,
        COUNT(*) AS items_in_queue,
        MIN(gil.created_dt) AS oldest_item_dt,
        MAX(gil.created_dt) AS newest_item_dt,
        AVG(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - gil.created_dt)) / 3600) AS avg_wait_hours
    FROM generic_instance_lineage gil
    JOIN generic_instance gi ON gil.parent_instance_uuid = gi.uuid
    WHERE gi.super_type = 'workflow_step'
        AND gil.is_deleted = FALSE
    GROUP BY gil.parent_instance_uuid
)
SELECT 
    ws.euid,
    ws.name AS workflow_step_name,
    ws.workflow_type,
    ws.step_type,
    ws.status,
    COALESCE(qi.items_in_queue, 0) AS queue_depth,
    ROUND(COALESCE(qi.avg_wait_hours, 0)::NUMERIC, 2) AS avg_wait_hours,
    qi.oldest_item_dt,
    ROUND(EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - qi.oldest_item_dt)) / 3600, 2) AS oldest_item_age_hours,
    ws.created_dt,
    CASE 
        WHEN COALESCE(qi.items_in_queue, 0) > 50 THEN 'CRITICAL'
        WHEN COALESCE(qi.items_in_queue, 0) > 20 THEN 'WARNING'
        WHEN COALESCE(qi.avg_wait_hours, 0) > 48 THEN 'WARNING'
        ELSE 'NORMAL'
    END AS bottleneck_status
FROM workflow_steps ws
LEFT JOIN queue_items qi ON ws.uuid = qi.workflow_step_uuid
WHERE ws.status NOT IN ('complete', 'abandoned')
ORDER BY qi.items_in_queue DESC NULLS LAST, qi.avg_wait_hours DESC NULLS LAST;

COMMENT ON VIEW v_workflow_bottlenecks IS 
'Identifies workflow bottlenecks by analyzing queue depths and wait times.';

-- ============================================================================
-- VIEW: v_equipment_utilization
-- Purpose: Track equipment usage and availability
-- Key Metrics: Usage counts, last used, status distribution
-- ============================================================================
DROP VIEW IF EXISTS v_equipment_utilization CASCADE;
CREATE OR REPLACE VIEW v_equipment_utilization AS
SELECT 
    gi.euid,
    gi.name AS equipment_name,
    gi.btype AS equipment_type,
    gi.b_sub_type AS equipment_model,
    gi.bstatus AS current_status,
    gi.created_dt AS installed_date,
    gi.modified_dt AS last_activity,
    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - gi.modified_dt)) / 3600 AS hours_since_activity,
    (gi.json_addl->>'properties'->>'location')::TEXT AS location,
    (gi.json_addl->>'properties'->>'serial_number')::TEXT AS serial_number,
    COUNT(DISTINCT gil.uuid) AS total_operations,
    COUNT(DISTINCT gil.uuid) FILTER (
        WHERE gil.created_dt > CURRENT_TIMESTAMP - INTERVAL '7 days'
    ) AS operations_last_7_days,
    COUNT(DISTINCT gil.uuid) FILTER (
        WHERE gil.created_dt > CURRENT_TIMESTAMP - INTERVAL '30 days'
    ) AS operations_last_30_days
FROM generic_instance gi
LEFT JOIN generic_instance_lineage gil ON gi.uuid = gil.parent_instance_uuid
WHERE gi.super_type = 'equipment'
    AND gi.is_deleted = FALSE
GROUP BY 
    gi.uuid, gi.euid, gi.name, gi.btype, gi.b_sub_type, 
    gi.bstatus, gi.created_dt, gi.modified_dt, gi.json_addl
ORDER BY operations_last_7_days DESC;

COMMENT ON VIEW v_equipment_utilization IS
'Equipment utilization metrics including usage frequency and current status.';

-- ============================================================================
-- VIEW: v_turnaround_times
-- Purpose: Calculate turnaround times for samples and workflows
-- Key Metrics: Mean TAT, median TAT, percentiles, SLA compliance
-- ============================================================================
DROP VIEW IF EXISTS v_turnaround_times CASCADE;
CREATE OR REPLACE VIEW v_turnaround_times AS
WITH completed_items AS (
    SELECT
        gi.uuid,
        gi.euid,
        gi.super_type,
        gi.btype,
        gi.b_sub_type,
        gi.created_dt AS start_time,
        gi.modified_dt AS end_time,
        EXTRACT(EPOCH FROM (gi.modified_dt - gi.created_dt)) / 3600 AS tat_hours,
        EXTRACT(EPOCH FROM (gi.modified_dt - gi.created_dt)) / 86400 AS tat_days,
        DATE(gi.created_dt) AS start_date
    FROM generic_instance gi
    WHERE gi.bstatus = 'complete'
        AND gi.is_deleted = FALSE
        AND gi.modified_dt > gi.created_dt
)
SELECT
    start_date,
    super_type,
    btype AS item_type,
    b_sub_type AS item_subtype,
    COUNT(*) AS completed_count,
    ROUND(AVG(tat_hours)::NUMERIC, 2) AS mean_tat_hours,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY tat_hours)::NUMERIC, 2) AS median_tat_hours,
    ROUND(MIN(tat_hours)::NUMERIC, 2) AS min_tat_hours,
    ROUND(MAX(tat_hours)::NUMERIC, 2) AS max_tat_hours,
    ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY tat_hours)::NUMERIC, 2) AS p90_tat_hours,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY tat_hours)::NUMERIC, 2) AS p95_tat_hours,
    ROUND(STDDEV(tat_hours)::NUMERIC, 2) AS stddev_tat_hours,
    -- SLA compliance (configurable thresholds)
    COUNT(*) FILTER (WHERE tat_hours <= 24) AS within_24h,
    COUNT(*) FILTER (WHERE tat_hours <= 48) AS within_48h,
    COUNT(*) FILTER (WHERE tat_hours <= 72) AS within_72h,
    ROUND(COUNT(*) FILTER (WHERE tat_hours <= 48)::NUMERIC / NULLIF(COUNT(*), 0) * 100, 2) AS sla_48h_compliance_pct
FROM completed_items
GROUP BY start_date, super_type, btype, b_sub_type
ORDER BY start_date DESC, super_type, btype;

COMMENT ON VIEW v_turnaround_times IS
'Turnaround time analysis with percentiles and SLA compliance metrics.';

-- ============================================================================
-- VIEW: v_audit_activity
-- Purpose: Track user activity from audit logs
-- Key Metrics: Actions per user, peak activity times, operation distribution
-- ============================================================================
DROP VIEW IF EXISTS v_audit_activity CASCADE;
CREATE OR REPLACE VIEW v_audit_activity AS
SELECT
    DATE(al.changed_at) AS activity_date,
    EXTRACT(HOUR FROM al.changed_at) AS activity_hour,
    al.changed_by AS user_id,
    al.operation_type,
    al.rel_table_name AS table_name,
    COUNT(*) AS action_count,
    COUNT(DISTINCT al.rel_table_uuid_fk) AS unique_objects_affected,
    MIN(al.changed_at) AS first_action,
    MAX(al.changed_at) AS last_action
FROM audit_log al
WHERE al.is_deleted = FALSE
GROUP BY
    DATE(al.changed_at),
    EXTRACT(HOUR FROM al.changed_at),
    al.changed_by,
    al.operation_type,
    al.rel_table_name
ORDER BY activity_date DESC, action_count DESC;

COMMENT ON VIEW v_audit_activity IS
'User activity metrics from audit logs for compliance and workload analysis.';

-- ============================================================================
-- VIEW: v_object_counts
-- Purpose: Inventory summary of all objects by type and status
-- Key Metrics: Counts by type, status distribution, growth trends
-- ============================================================================
DROP VIEW IF EXISTS v_object_counts CASCADE;
CREATE OR REPLACE VIEW v_object_counts AS
SELECT
    gi.super_type,
    gi.btype AS object_type,
    gi.b_sub_type AS object_subtype,
    gi.version,
    gi.bstatus AS status,
    COUNT(*) AS total_count,
    COUNT(*) FILTER (WHERE gi.is_deleted = FALSE) AS active_count,
    COUNT(*) FILTER (WHERE gi.is_deleted = TRUE) AS deleted_count,
    COUNT(*) FILTER (WHERE gi.created_dt > CURRENT_TIMESTAMP - INTERVAL '1 day') AS created_last_24h,
    COUNT(*) FILTER (WHERE gi.created_dt > CURRENT_TIMESTAMP - INTERVAL '7 days') AS created_last_7_days,
    COUNT(*) FILTER (WHERE gi.created_dt > CURRENT_TIMESTAMP - INTERVAL '30 days') AS created_last_30_days,
    MIN(gi.created_dt) AS first_created,
    MAX(gi.created_dt) AS last_created,
    MAX(gi.modified_dt) AS last_modified
FROM generic_instance gi
GROUP BY
    gi.super_type,
    gi.btype,
    gi.b_sub_type,
    gi.version,
    gi.bstatus
ORDER BY total_count DESC;

COMMENT ON VIEW v_object_counts IS
'Inventory summary showing object counts by type, subtype, and status.';

-- ============================================================================
-- VIEW: v_daily_summary
-- Purpose: High-level daily summary for executive dashboards
-- Key Metrics: Total activity, completion rates, system health
-- ============================================================================
DROP VIEW IF EXISTS v_daily_summary CASCADE;
CREATE OR REPLACE VIEW v_daily_summary AS
WITH daily_instances AS (
    SELECT
        DATE(created_dt) AS summary_date,
        COUNT(*) AS instances_created,
        COUNT(*) FILTER (WHERE bstatus = 'complete') AS instances_completed,
        COUNT(*) FILTER (WHERE bstatus = 'failed') AS instances_failed,
        COUNT(DISTINCT super_type) AS distinct_super_types,
        COUNT(DISTINCT btype) AS distinct_types
    FROM generic_instance
    WHERE is_deleted = FALSE
    GROUP BY DATE(created_dt)
),
daily_lineages AS (
    SELECT
        DATE(created_dt) AS summary_date,
        COUNT(*) AS lineages_created
    FROM generic_instance_lineage
    WHERE is_deleted = FALSE
    GROUP BY DATE(created_dt)
),
daily_audit AS (
    SELECT
        DATE(changed_at) AS summary_date,
        COUNT(*) AS audit_entries,
        COUNT(DISTINCT changed_by) AS active_users,
        COUNT(*) FILTER (WHERE operation_type = 'INSERT') AS inserts,
        COUNT(*) FILTER (WHERE operation_type = 'UPDATE') AS updates,
        COUNT(*) FILTER (WHERE operation_type = 'DELETE') AS deletes
    FROM audit_log
    GROUP BY DATE(changed_at)
)
SELECT
    COALESCE(di.summary_date, dl.summary_date, da.summary_date) AS summary_date,
    COALESCE(di.instances_created, 0) AS instances_created,
    COALESCE(di.instances_completed, 0) AS instances_completed,
    COALESCE(di.instances_failed, 0) AS instances_failed,
    COALESCE(dl.lineages_created, 0) AS relationships_created,
    COALESCE(da.audit_entries, 0) AS total_operations,
    COALESCE(da.active_users, 0) AS active_users,
    COALESCE(da.inserts, 0) AS insert_operations,
    COALESCE(da.updates, 0) AS update_operations,
    COALESCE(da.deletes, 0) AS delete_operations,
    CASE
        WHEN COALESCE(di.instances_failed, 0) > 10 THEN 'ALERT'
        WHEN COALESCE(di.instances_failed, 0) > 5 THEN 'WARNING'
        ELSE 'NORMAL'
    END AS health_status
FROM daily_instances di
FULL OUTER JOIN daily_lineages dl ON di.summary_date = dl.summary_date
FULL OUTER JOIN daily_audit da ON COALESCE(di.summary_date, dl.summary_date) = da.summary_date
ORDER BY summary_date DESC;

COMMENT ON VIEW v_daily_summary IS
'Daily executive summary with key operational metrics and health indicators.';

-- ============================================================================
-- Grant read access to analytics user (if exists)
-- Uncomment and modify for your environment
-- ============================================================================
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO analytics_user;
-- GRANT SELECT ON v_sample_throughput, v_workflow_bottlenecks, v_equipment_utilization,
--                 v_turnaround_times, v_audit_activity, v_object_counts, v_daily_summary
--                 TO analytics_user;

-- Print success message
DO $$
BEGIN
    RAISE NOTICE 'BLOOM Analytics views installed successfully!';
    RAISE NOTICE 'Views created: v_sample_throughput, v_workflow_bottlenecks, v_equipment_utilization,';
    RAISE NOTICE '              v_turnaround_times, v_audit_activity, v_object_counts, v_daily_summary';
END $$;

