from __future__ import annotations

from bloom_lims import config


def test_get_database_url_preserves_local_postgres_target(monkeypatch) -> None:
    monkeypatch.setattr(
        config,
        "get_tapdb_db_config",
        lambda: {
            "engine_type": "local",
            "host": "localhost",
            "port": "5533",
            "user": "bloom_user",
            "password": "",
            "database": "tapdb_unidbtst_local",
        },
    )

    assert config.get_database_url() == "postgresql://bloom_user@localhost:5533/tapdb_unidbtst_local"


def test_get_database_url_supports_explicit_aurora_hostaddr(monkeypatch) -> None:
    monkeypatch.setattr(
        config,
        "get_tapdb_db_config",
        lambda: {
            "engine_type": "aurora",
            "host": "dayhoff-test.cluster-example.us-west-2.rds.amazonaws.com",
            "hostaddr": "127.0.0.1",
            "port": "15432",
            "user": "bloom_user",
            "password": "secret",
            "database": "tapdb_unidbtst_local",
            "sslrootcert": "/tmp/rds-ca-bundle.pem",
        },
    )

    assert config.get_database_url() == (
        "postgresql://bloom_user:secret@"
        "dayhoff-test.cluster-example.us-west-2.rds.amazonaws.com:15432/tapdb_unidbtst_local"
        "?sslmode=verify-full&sslrootcert=%2Ftmp%2Frds-ca-bundle.pem&hostaddr=127.0.0.1"
    )


def test_get_database_url_supports_direct_aurora_without_hostaddr(monkeypatch) -> None:
    monkeypatch.setattr(
        config,
        "get_tapdb_db_config",
        lambda: {
            "engine_type": "aurora",
            "host": "dayhoff-test.cluster-example.us-west-2.rds.amazonaws.com",
            "port": "5432",
            "user": "bloom_user",
            "password": "secret",
            "database": "tapdb_unidbtst_local",
            "sslrootcert": "/tmp/rds-ca-bundle.pem",
        },
    )

    assert config.get_database_url() == (
        "postgresql://bloom_user:secret@"
        "dayhoff-test.cluster-example.us-west-2.rds.amazonaws.com:5432/tapdb_unidbtst_local"
        "?sslmode=verify-full&sslrootcert=%2Ftmp%2Frds-ca-bundle.pem"
    )
