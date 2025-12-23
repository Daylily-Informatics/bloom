# BLOOM Analytics Dashboard Integration

This directory contains a loosely-coupled analytics solution for BLOOM LIMS and other Laboratory Information Systems (LIS). The integration uses **Metabase**, an open-source business intelligence tool, connected directly to the PostgreSQL database.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   BLOOM LIMS    │────▶│   PostgreSQL    │◀────│    Metabase     │
│   (FastAPI)     │     │   Database      │     │   (Analytics)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌─────────────────┐
                        │   SQL Views     │
                        │  (Analytics)    │
                        └─────────────────┘
```

## Why Metabase?

| Feature | Benefit for Labs |
|---------|------------------|
| Open Source (AGPL) | Free, no vendor lock-in |
| PostgreSQL Native | Direct connection to BLOOM database |
| Visual Query Builder | Non-technical users can create reports |
| Embeddable | Dashboard embedding in BLOOM UI |
| Alerting | Automated notifications for thresholds |
| API | Programmatic access to dashboards |

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Start Metabase with Docker
cd analytics/metabase
docker-compose up -d

# Access Metabase at http://localhost:3000
```

### Option 2: Standalone JAR

```bash
# Download and run Metabase
./analytics/metabase/run_metabase.sh
```

### Option 3: Conda Environment

```bash
# If using conda, Metabase can run alongside BLOOM
conda activate BLOOM
./analytics/metabase/run_metabase.sh
```

## Configuration

### Environment Variables

Add to your `.env` file:

```bash
# Metabase Configuration
METABASE_PORT=3000
METABASE_DB_TYPE=postgres
METABASE_DB_HOST=localhost
METABASE_DB_PORT=5432
METABASE_DB_NAME=bloom_lims
METABASE_DB_USER=bloom_user
METABASE_DB_PASS=your_password

# Optional: Embed dashboards in BLOOM
METABASE_EMBED_SECRET=your-embed-secret-key
```

## SQL Views for Analytics

The `sql_views/` directory contains PostgreSQL views optimized for analytics:

| View | Purpose | Key Metrics |
|------|---------|-------------|
| `v_sample_throughput` | Sample processing rates | Samples/day, TAT |
| `v_workflow_bottlenecks` | Queue analysis | Wait times, backlogs |
| `v_equipment_utilization` | Equipment usage | Utilization %, downtime |
| `v_turnaround_times` | TAT analysis | Mean, median, percentiles |
| `v_audit_activity` | User activity | Actions/user, peak times |
| `v_object_counts` | Inventory | Counts by type/status |

### Installing Views

```bash
# Run the analytics views installation script
psql -d bloom_lims -f analytics/sql_views/install_views.sql
```

## Sample Dashboards

Pre-built dashboard configurations are in `dashboards/`:

1. **Operations Overview** - Daily sample counts, active workflows
2. **Turnaround Time Monitor** - TAT trends, SLA compliance
3. **Equipment Dashboard** - Utilization, maintenance schedules
4. **Quality Metrics** - Error rates, reprocessing trends
5. **User Activity** - Audit logs, action summaries

## Portability to Other LIS

This analytics solution is designed to be portable:

1. **Standardized Views**: SQL views use common LIS terminology
2. **Configurable Mappings**: `config/lis_mappings.yaml` maps BLOOM fields to standard names
3. **API Abstraction**: Dashboard definitions reference abstract metrics
4. **Documentation**: Each view includes comments for adaptation

### Adapting for Another LIS

1. Copy `analytics/` directory to your LIS project
2. Edit `config/lis_mappings.yaml` to map your schema
3. Modify SQL views to match your database structure
4. Import dashboard configurations into Metabase

## Security Considerations

- Metabase connects read-only to the database (recommended)
- Use a dedicated database user with SELECT-only permissions
- Enable HTTPS for production deployments
- Configure Metabase authentication (LDAP, SSO, etc.)

## Directory Structure

```
analytics/
├── README.md                 # This file
├── metabase/
│   ├── docker-compose.yml    # Docker deployment
│   ├── run_metabase.sh       # Standalone runner
│   └── metabase.db/          # Metabase config (gitignored)
├── dashboards/
│   ├── operations_overview.json
│   ├── turnaround_times.json
│   └── equipment_utilization.json
├── sql_views/
│   ├── install_views.sql     # Main installation script
│   ├── v_sample_throughput.sql
│   ├── v_workflow_bottlenecks.sql
│   └── ...
└── config/
    └── lis_mappings.yaml     # LIS field mappings
```

## Troubleshooting

### Metabase can't connect to PostgreSQL
- Ensure PostgreSQL is running: `pg_isready`
- Check connection settings in Metabase admin
- Verify firewall allows connection on port 5432

### Views not showing data
- Run `SELECT * FROM v_sample_throughput LIMIT 5;` to test
- Check that BLOOM has data in the database
- Verify view permissions for Metabase user

## License

This analytics integration is released under the same MIT license as BLOOM LIMS.

