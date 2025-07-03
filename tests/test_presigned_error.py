import boto3
import requests_mock
from moto import mock_aws
import pytest

from bloom_lims.db import BLOOMdb3
from bloom_lims.bobjs import BloomFile


@pytest.fixture
def s3_bucket():
    with mock_aws():
        s3 = boto3.client('s3', region_name='us-east-1')
        bucket_name = 'daylily-dewey-0'
        s3.create_bucket(Bucket=bucket_name)
        yield bucket_name


@pytest.fixture
def db_session():
    bdb = BLOOMdb3()
    yield bdb


@pytest.fixture
def bloom_file_instance(db_session, s3_bucket):
    return BloomFile(db_session, bucket_prefix="daylily-dewey-")


def test_presigned_url_error_for_non_s3(bloom_file_instance):
    new_file = bloom_file_instance.create_file(
        file_metadata={"description": "Remote", "import_or_remote": "remote"},
        url="http://example.com/test.txt",
    )
    result = bloom_file_instance.create_presigned_url(new_file.euid)
    assert result["presigned_url"] is None
    fx = result["file_reference"]
    props = fx.json_addl["properties"]
    assert props["status"] == "error"
    assert "s3: prefix" in props["comments"]
