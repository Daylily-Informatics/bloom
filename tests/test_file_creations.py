import sys
import os
import pytest
import boto3
import requests_mock
from moto import mock_aws
from pathlib import Path
from sqlalchemy.orm import sessionmaker

from bloom_lims.db import BLOOMdb3
from bloom_lims.bobjs import BloomWorkflow, BloomFile

from io import BytesIO



@pytest.fixture
def s3_bucket():
    with mock_aws():
        s3 = boto3.client('s3', region_name='us-east-1')
        bucket_name = 'daylily-dewey-0'
        s3.create_bucket(Bucket=bucket_name)
        yield bucket_name

@pytest.fixture
def db_session():
    bdb=BLOOMdb3()    
    yield bdb

@pytest.fixture
def bloom_file_instance(db_session, s3_bucket):
    return BloomFile(db_session, bucket_prefix="daylily-dewey-")

def test_create_file_no_data(bloom_file_instance):
    new_file = bloom_file_instance.create_file(file_metadata={"description": "No data test"})
    assert new_file is not None
    assert new_file.json_addl['properties']['description'] == "No data test"
    assert new_file.json_addl['properties']['current_s3_bucket_name'] == "daylily-dewey-0"
    
def test_create_file_with_data(bloom_file_instance):
    data_path = Path("tests/test_pdf.pdf")
    with open(data_path, "rb") as f:
        file_data = BytesIO(f.read())

    file_name = data_path.name
    new_file = bloom_file_instance.create_file(
        file_metadata={"description": "Data test"},
        file_data=file_data,
        file_name=file_name
    )

    assert new_file is not None
    assert new_file.json_addl['properties']['description'] == "Data test"
    assert new_file.json_addl['properties']['original_file_size_bytes'] == file_data.getbuffer().nbytes

def test_create_file_with_local_path(bloom_file_instance):
    fn = "tests/test_png.png"
    data_path = Path(fn)
    new_file = bloom_file_instance.create_file(file_metadata={"description": "Local path test"}, full_path_to_file=fn)
    assert new_file is not None
    assert new_file.json_addl['properties']['description'] == "Local path test"
    assert new_file.json_addl['properties']['original_file_size_bytes'] == os.path.getsize(fn)


def test_create_file_with_url(bloom_file_instance):
    url = "https://github.com/Daylily-Informatics/bloom/blob/20240603b/tests/test_png.png"
    with requests_mock.Mocker() as m:
        m.get(url, content=b"test content")
        new_file = bloom_file_instance.create_file(file_metadata={"description": "URL test"}, url=url)
        assert new_file is not None
        assert new_file.json_addl['properties']['description'] == "URL test"
        assert new_file.json_addl['properties']['original_file_size_bytes'] == len(b"test content")

if __name__ == "__main__":
    pytest.main()
