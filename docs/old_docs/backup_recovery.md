# Backup and Recovery (TapDB-managed)

Bloom no longer implements an in-repo backup subsystem.

## Current Model

- Database backup/restore operations are owned by `daylily-tapdb`.
- Use `tapdb db data backup <env>` and `tapdb db data restore <env>`.
- Bloom does not ship an in-repo backup command.

## Runtime Context

```bash
export AWS_PROFILE=lsmc
export AWS_REGION=us-west-2
export AWS_DEFAULT_REGION=us-west-2
```

## Examples

```bash
python -m daylily_tapdb.cli --config ~/.config/tapdb/bloom/bloom/tapdb-config.yaml --env dev db data backup dev
python -m daylily_tapdb.cli --config ~/.config/tapdb/bloom/bloom/tapdb-config.yaml --env dev db data restore dev
```
