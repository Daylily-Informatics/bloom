# BLOOM Unified Search V2

BLOOM now uses a unified search service rooted in TapDB-backed access patterns.

## Scope

Search v2 supports mixed record types in one query:

- `instance`
- `template`
- `lineage`
- `audit`

It uses ILIKE + JSON-path filters in phase 1 (no FTS/trigram migrations).

## API

### Query

`POST /api/v1/search/v2/query`

Body (`SearchRequest`):

```json
{
  "query": "sample",
  "record_types": ["instance", "template"],
  "categories": ["file"],
  "page": 1,
  "page_size": 50,
  "sort_by": "timestamp",
  "sort_order": "desc"
}
```

### Export

`POST /api/v1/search/v2/export`

Body (`SearchExportRequest`):

```json
{
  "search": {
    "query": "sample",
    "record_types": ["instance"],
    "page": 1,
    "page_size": 100
  },
  "format": "json",
  "include_metadata": true,
  "max_export_rows": 10000
}
```

Formats:

- `json`
- `tsv`

## Legacy Endpoint Status

Legacy endpoints are still available for compatibility and include deprecation headers:

- `GET /api/v1/search/`
- `GET /api/v1/search/export`

Successor endpoint:

- `POST /api/v1/search/v2/query`

## GUI

`/search` is now backed by search v2 and shows unified/faceted results.

## Dewey Migration

Dewey metadata search forms now post to `/search` and are translated into search v2 filter requests.

Legacy Dewey endpoints are retired:

- `POST /search_files` -> `410 Gone`
- `POST /search_file_sets` -> `410 Gone`

Use `/search` (GUI) or `/api/v1/search/v2/query` (API) instead.
