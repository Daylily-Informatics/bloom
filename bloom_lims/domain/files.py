"""
BLOOM LIMS Domain - File Classes

This module contains file-related classes for file attachments,
data files, and file sets.

Extracted from bloom_lims/bobjs.py for better code organization.
"""

import os
import json
import logging
import subprocess
import socket
from datetime import datetime
from pathlib import Path
import urllib.parse

import boto3
import requests
from botocore.exceptions import NoCredentialsError, PartialCredentialsError

from sqlalchemy import desc
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.domain.base import BloomObj
from bloom_lims.domain.utils import get_datetime_string, generate_random_string, _update_recursive

import re

logger = logging.getLogger(__name__)


class BloomFile(BloomObj):
    
    def __init__(self, bdb, bucket_prefix=None, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)
    
        if bucket_prefix is None:
            bucket_prefix = os.environ.get(
                "BLOOM_DEWEY_S3_BUCKET_PREFIX", "set-a-bucket-prefix-in-the-dotenv-file"
            )

        self.bucket_prefix = bucket_prefix
        self.s3_client = boto3.client("s3")

    def _derive_bucket_name(self, euid):
        euid_int = int(re.sub("[^0-9]", "", euid))
        response = self.s3_client.list_buckets()
        buckets = response["Buckets"]
        matching_buckets = [
            bucket["Name"]
            for bucket in buckets
            if bucket["Name"].startswith(self.bucket_prefix)
        ]
        bucket_suffixes = sorted(
            [
                int(re.sub("[^0-9]", "", name.replace(self.bucket_prefix, "")))
                for name in matching_buckets
            ]
        )

        for i in range(len(bucket_suffixes) - 1):
            if bucket_suffixes[i] <= euid_int < bucket_suffixes[i + 1]:
                return f"{self.bucket_prefix}{bucket_suffixes[i]}"

        if euid_int >= bucket_suffixes[-1]:
            return f"{self.bucket_prefix}{bucket_suffixes[-1]}"

        raise Exception("No matching bucket found for the provided EUID.")

    def _determine_s3_key(self, euid, data_file_name):
        bucket_name = self._derive_bucket_name(euid)
        euid_numeric_part = int(re.sub("[^0-9]", "", euid))
        response = self.s3_client.list_objects_v2(
            Bucket=bucket_name, Prefix="", Delimiter="/"
        )

        logging.debug(f"ListObjectsV2 Response: {response}")
        folders = sorted(
            [
                int(content["Prefix"].rstrip("/"))
                for content in response.get("CommonPrefixes", [])
            ]
        )

        if not folders:
            # If no folders are found, create a '0' folder
            self.s3_client.put_object(Bucket=bucket_name, Key="0/")
            folders = [0]

        for i in range(len(folders) - 1):
            if folders[i] <= euid_numeric_part < folders[i + 1]:
                folder_prefix = folders[i]
                break
        else:
            folder_prefix = folders[-1] if euid_numeric_part >= folders[-1] else 0

        logging.debug(f"Determined folder_prefix: {folder_prefix}")
        return f"{folder_prefix}/{euid}.{data_file_name.split('.')[-1]}"

    def DELME_check_s3_key_exists(self, bucket_name, s3_key):
        try:
            self.s3_client.head_object(Bucket=bucket_name, Key=s3_key)
            return True
        except self.s3_client.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            else:
                raise e

    def link_file_to_parent(self, child_euid, parent_euid):
        self.create_generic_instance_lineage_by_euids(child_euid, parent_euid)
        self.session.commit()
        
    def create_file(
        self,
        file_metadata={},
        file_data=None,
        file_name=None,
        url=None,
        full_path_to_file=None,
        s3_uri=None,
        create_locked=False,
        addl_tags={},
    ):
        """
        Create a file or import files from an S3 directory.

        :param file_metadata: Metadata to associate with the file(s).
        :param file_data: File data to upload (binary data).
        :param file_name: Name of the file.
        :param url: URL to fetch the file data.
        :param full_path_to_file: Local path to the file.
        :param s3_uri: S3 URI of the file or directory.
        :param create_locked: Whether to lock the file(s) after creation. Defaults to True.
        :param addl_tags: Additional tags for the file(s).
        :return: Created file object or list of file objects.
        """
        if s3_uri:
            # Detect if S3 URI is a directory
            s3_parsed_uri = re.match(r"s3://([^/]+)/(.+)", s3_uri)
            if not s3_parsed_uri:
                raise ValueError("Invalid s3_uri format. Expected format: s3://bucket_name/prefix")
            
            bucket_name, prefix = s3_parsed_uri.groups()

            try:
                response = self.s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix, Delimiter='/')
                files = response.get('Contents', [])
                
                # If more than one object or the URI ends with '/', treat it as a directory
                if len(files) > 1 or s3_uri.endswith('/'):
                    created_files = []
                    for file in files:
                        file_key = file['Key']
                        
                        # Skip directories
                        if file_key.endswith('/'):
                            continue
                        
                        file_name = file_key.split('/')[-1]
                        current_s3_uri = f"s3://{bucket_name}/{file_key}"
                        
                        # Create individual files for each item in the directory
                        created_file = self.create_file(
                            file_metadata=file_metadata,
                            s3_uri=current_s3_uri,
                            create_locked=create_locked,
                            addl_tags=addl_tags,
                        )
                        created_files.append(created_file)
                    
                    return created_files
                
                # Otherwise, process as a single file
                s3_uri = f"s3://{bucket_name}/{files[0]['Key']}" if files else s3_uri
            
            except Exception as e:
                raise Exception(f"Error detecting file or directory for S3 URI {s3_uri}: {e}")

        # Existing logic for processing a single file
        file_properties = {"properties": file_metadata}
        import_or_remote = file_metadata.get('import_or_remote', 'import')

        # Query for file template with proper error handling
        file_templates = self.query_template_by_component_v2("file", "file", "generic", "1.0")
        if not file_templates:
            raise Exception(
                "File template not found: file/file/generic/1.0. "
                "Please ensure the database is seeded with file templates (run: bloom init)."
            )

        new_file = self.create_instance(
            file_templates[0].euid,
            file_properties,
        )
        self.session.commit()

        new_file.json_addl["properties"]["current_s3_bucket_name"] = (
            self._derive_bucket_name(new_file.euid)
        )
        flag_modified(new_file, "json_addl")
        self.session.commit()

        if file_data or url or full_path_to_file or s3_uri:
            try:
                new_file = self.add_file_data(
                    new_file.euid,
                    file_data,
                    file_name,
                    url,
                    full_path_to_file,
                    s3_uri,
                    addl_tags=addl_tags,
                    import_or_remote=import_or_remote,
                )
            except Exception as e:
                logging.exception(f"Error adding file data: {e}")
                new_file.bstatus = "error adding file data"
                flag_modified(new_file, "json_addl")
                self.session.commit()
                raise Exception(e)
        else:
            logging.warning(f"No data provided for file creation or import skipped: {file_data, url}")
            new_file.bstatus = "awaiting file data"
            self.session.commit()

        if create_locked:
            self.lock_file(new_file.euid)

        return new_file


    def create_file_old(
        self,
        file_metadata={},
        file_data=None,
        file_name=None,
        url=None,
        full_path_to_file=None,
        s3_uri=None,
        create_locked=True,
        addl_tags={},
    ):
        file_properties = {"properties": file_metadata}

        import_or_remote = file_metadata['import_or_remote']

        new_file = self.create_instance(
            self.query_template_by_component_v2("file", "file", "generic", "1.0")[
                0
            ].euid,
            file_properties,
        )
        self.session.commit()

        # Special handling for patient_id
        if (
            "patient_id" in file_metadata
        ):
            patient_id = file_metadata["patient_id"]
            search_criteria = {"properties": {"patient_id": patient_id}}
            existing_euids = self.search_objs_by_addl_metadata(
                search_criteria,
                True,
                category="actor",
                type="generic",
                subtype="patient"
            )

            if existing_euids:
                # Create child relationships to existing objects
                for euid in existing_euids:
                    self.create_generic_instance_lineage_by_euids(euid, new_file.euid)
            else:
                # Create a new actor/generic/patient object
                new_patient = self.create_instance(
                    self.query_template_by_component_v2(
                        "actor", "generic", "patient", "1.0"
                    )[0].euid,
                    {"properties": {"patient_id": patient_id}},
                )
                self.session.commit()
                self.create_generic_instance_lineage_by_euids(
                    new_patient.euid, new_file.euid
                )

        new_file.json_addl["properties"]["current_s3_bucket_name"] = (
            self._derive_bucket_name(new_file.euid)
        )
        flag_modified(new_file, "json_addl")
        self.session.commit()

        if file_data or url or full_path_to_file or s3_uri:
            try:
                new_file = self.add_file_data(
                    new_file.euid, file_data, file_name, url, full_path_to_file, s3_uri, addl_tags=addl_tags, import_or_remote=import_or_remote
                )
            except Exception as e:
                logging.exception(f"Error adding file data: {e}")
                new_file.bstatus = "error adding file data"
                flag_modified(new_file, "json_addl")
                self.session.commit()
                raise Exception(e)
        else:
            logging.warning(f"No data provided for file creation, or import skipped ({import_or_remote}): {file_data, url}")
            new_file.bstatus = "awaiting file data"
            self.session.commit()

        if create_locked:
            self.lock_file(new_file.euid)

        return new_file


    def sanitize_tag(self, value, is_key=False):
        """
        Sanitize the tag key or value to conform to AWS tag requirements by replacing disallowed characters.

        Parameters:
        - value (str): The tag key or value to sanitize.
        - is_key (bool): If True, sanitize as a tag key (128-character limit). 
                        If False, sanitize as a tag value (256-character limit).

        Returns:
        - str: Sanitized tag key or value.
        """
        # AWS tag key or value allowed characters
        allowed_characters_regex = r'[^a-zA-Z0-9 _\.:/=+\-@]'
        
        # Replace disallowed characters with '_'
        sanitized_value = re.sub(allowed_characters_regex, '_', value)
        
        # Trim leading and trailing spaces (not allowed by AWS)
        sanitized_value = sanitized_value.strip()
        
        # Enforce maximum length
        max_length = 128 if is_key else 256
        sanitized_value = sanitized_value[:max_length]
        
        return sanitized_value

    def format_addl_tags(self, add_tags):
        if not isinstance(add_tags, dict):
            raise ValueError("Input must be a dictionary.")

        formatted_tags = []
        for key, value in add_tags.items():
            if not isinstance(value, str):
                raise ValueError(f"Value for key '{key}' must be a string.")
            formatted_tags.append(
                f"{self.sanitize_tag(key)}={self.sanitize_tag(value)}"
            )

        return "&".join(formatted_tags)
    
    def add_file_data(
        self,
        euid,
        file_data=None,
        file_name=None,
        url=None,
        full_path_to_file=None,
        s3_uri=None,
        addl_tags={},
        import_or_remote=None
    ):
        file_instance = self.get_by_euid(euid)
        s3_bucket_name = file_instance.json_addl["properties"]["current_s3_bucket_name"]
        file_properties = {}

        if import_or_remote in ["Remote", "remote"] and (file_data is not None or url is not None or full_path_to_file is not None):
            raise ValueError("Remote file management is only supported with internal S3 URI.")

        addl_tag_string = self.format_addl_tags(addl_tags)
        if len(addl_tag_string) > 0:
            addl_tag_string = f"&{addl_tag_string}"
        
        if file_name is None:
            if url:
                file_name = url.split("/")[-1]
            elif s3_uri:
                file_name = s3_uri.split("/")[-1]
            elif full_path_to_file:
                file_name = Path(full_path_to_file).name
            else:
                raise ValueError(
                    "file_name must be provided if file_data or url is passed without a filename."
                )

        file_suffix = file_name.split(".")[-1]
        s3_key = self._determine_s3_key(euid, file_name)

        # Check if a file with the same EUID already exists in the bucket
        s3_key_path = "/".join(s3_key.split("/")[:-1])
        s3_key_path = s3_key_path + "/" if len(s3_key_path) > 0 else ""


        existing_files = self.s3_client.list_objects_v2(
            Bucket=s3_bucket_name, Prefix=f"{s3_key_path}{euid}."
        )
        if "Contents" in existing_files:
            self.logger.exception(
                f"A file with PREFIX EUID {euid} already exists in bucket {s3_bucket_name} {s3_key_path}."
            )
            raise Exception(
                f"A file with EUID {euid} already exists in bucket {s3_bucket_name} {s3_key_path}."
            )

        if s3_uri:
            # Was just doing this for only remote s3 uris, but am going to leave them be for now
            # Check if a remote file with the same metadata already exists

            search_criteria = {"properties": {"current_s3_uri": s3_uri}}
            existing_euids = self.search_objs_by_addl_metadata(search_criteria, True, category="file", type="file", subtype="generic")
            
            if len(existing_euids) > 0:
                raise Exception(f"Remote file with URI {s3_uri} already exists in the database as {existing_euids}.")

            s3uri_bucket=s3_uri.split("/")[2]
            s3uri_key="/".join(s3_uri.split("/")[3:])
            # Store metadata for the remote file
            file_properties = {
                "remote_s3_uri": s3_uri,
                "original_file_name": file_name,
                "name": file_name,
                "original_file_size_bytes": None,  # Size is unknown for remote files
                "original_file_suffix": file_suffix,
                "original_file_data_type": "s3uri",
                "file_type": file_suffix,
                "current_s3_uri": s3_uri,
                "original_s3_uri": s3_uri,  
                "current_s3_key": s3uri_key,
                "current_s3_bucket_name": s3uri_bucket,
                "import_or_remote": 'remote',
            }
                        # Check if the object has the 'dewey_euid' tag
            try:
                existing_tags = self.s3_client.get_object_tagging(
                    Bucket=s3uri_bucket,
                    Key=s3uri_key
                )

                # Check if 'dewey_euid' is already present in the tags
                for tag in existing_tags.get("TagSet", []):
                    if tag["Key"] == "dewey_euid":
                        raise Exception(f"Object {s3_uri} already has a 'dewey_euid' tag with value {tag['Value']}.")
            except self.s3_client.exceptions.NoSuchKey:
                raise Exception(f"S3 object {s3_uri} does not exist.")
            except Exception as e:
                self.logger.exception(f"Error checking tags for S3 object {s3_uri}: {e}")
                raise Exception(f"Failed to check tags for S3 object: {e}")
            
                    
            # Construct the tags
            tagging = {
                'TagSet': [
                    {'Key': 'dewey_original_file_name', 'Value': self.sanitize_tag(file_name)},
                    {'Key': 'dewey_original_file_path', 'Value': 'N/A'},
                    {'Key': 'dewey_original_file_suffix', 'Value': self.sanitize_tag(file_suffix)},
                    {'Key': 'dewey_euid', 'Value': self.sanitize_tag(euid)},
                ]
            }
                    
            # Apply the tags to the existing object
            try:
                self.s3_client.put_object_tagging(
                    Bucket=s3uri_bucket,
                    Key=s3uri_key,
                    Tagging=tagging
                )
                self.logger.info(f"Tags successfully applied to S3 object {s3_uri}")
            except Exception as e:
                self.logger.exception(f"Error tagging existing S3 object {s3_uri}: {e}\n\n{tagging}")
                raise Exception(f"Failed to tag S3 object: {e}\n{tagging}")

            _update_recursive(file_instance.json_addl["properties"], file_properties)
            flag_modified(file_instance, "json_addl")
            self.session.commit()
            return file_instance

        try:
            if file_data:
                file_data.seek(0)  # Ensure the file pointer is at the beginning
                file_size = len(file_data.read())
                file_data.seek(0)  # Reset the file pointer after reading
                
                try:
                    self.s3_client.put_object(
                        Bucket=s3_bucket_name,
                        Key=s3_key,
                        Body=file_data,
                        Tagging=f"dewey_original_file_name={self.sanitize_tag(file_name)}&dewey_original_file_path=N/A&&dewey_original_file_suffix={self.sanitize_tag(file_suffix)}&dewey_euid={self.sanitize_tag(euid)}{addl_tag_string}"
                    )

                except Exception as e:
                    self.logger.exception(f"Error uploading file data: {e}. Possibly tag related: {self.sanitize_tag(file_name)}, {self.sanitize_tag(str(file_size))}, {self.sanitize_tag(file_suffix)}, {self.sanitize_tag(euid)} ") 
                    raise Exception(e)
                odirectory, ofilename = os.path.split(file_name)

                file_properties = {
                    "current_s3_key": s3_key,
                    "original_file_name": ofilename,
                    "name": file_name,
                    "original_file_path": odirectory,
                    "original_file_size_bytes": file_size,
                    "original_file_suffix": file_suffix,
                    "original_file_data_type": "raw data",
                    "file_type": file_suffix,
                    "current_s3_uri": f"s3://{s3_bucket_name}/{s3_key}",
                    "import_or_remote": import_or_remote,
                }

            elif url:
                response = requests.get(url)
                file_size = len(response.content)
                url_info = url.split("/")[-1]
                file_suffix = url_info.split(".")[-1]
                self.s3_client.put_object(
                    Bucket=s3_bucket_name,
                    Key=s3_key,
                    Body=response.content,
                    Tagging=f"dewey_original_file_name={self.sanitize_tag(url_info)}&dewey_original_url={self.sanitize_tag(url)}&dewey_original_file_suffix={self.sanitize_tag(file_suffix)}&dewey_euid={self.sanitize_tag(euid)}{addl_tag_string}",
                )
                file_properties = {
                    "current_s3_key": s3_key,
                    "original_file_name": url_info,
                    "name": url_info,
                    "original_url": url,
                    "original_file_size_bytes": file_size,
                    "original_file_suffix": file_suffix,
                    "original_file_data_type": "url",
                    "file_type": file_suffix,
                    "current_s3_uri": f"s3://{s3_bucket_name}/{s3_key}",
                    "import_or_remote": import_or_remote,
                }

            elif full_path_to_file:
                with open(full_path_to_file, "rb") as file:
                    file_data = file.read()
                file_size = os.path.getsize(full_path_to_file)
                local_path_info = Path(full_path_to_file)
                local_ip = None
                try:
                    local_ip = socket.gethostbyname(socket.gethostname())
                except socket.gaierror:
                    local_ip = "127.0.0.1"  # Fallback to localhost

                self.s3_client.put_object(
                    Bucket=s3_bucket_name,
                    Key=s3_key,
                    Body=file_data,
                    Tagging=f"dewey_original_file_name={self.sanitize_tag(local_path_info.name)}&dewey_original_file_path={self.sanitize_tag(full_path_to_file)}&dewey_original_file_suffix={self.sanitize_tag(file_suffix)}&dewey_euid={self.sanitize_tag(euid)}{addl_tag_string}",
                )
                file_properties = {
                    "current_s3_key": s3_key,
                    "original_file_name": local_path_info.name,
                    "name": local_path_info.name,
                    "original_file_path": full_path_to_file,
                    "original_local_server_name": socket.gethostname(),
                    "original_server_ip": local_ip,
                    "original_file_size_bytes": file_size,
                    "original_file_suffix": file_suffix,
                    "original_file_data_type": "local file",
                    "file_type": file_suffix,
                    "current_s3_uri": f"s3://{s3_bucket_name}/{s3_key}",
                    "import_or_remote": import_or_remote,
                }

            elif s3_uri in ["deprecate this"]:
                # I do not want to be in the business of moving files around here
                #elif s3_uri:
                # Validate and move the file from the provided s3_uri
                s3_parsed_uri = re.match(r"s3://([^/]+)/(.+)", s3_uri)
                if not s3_parsed_uri:
                    raise ValueError(
                        "Invalid s3_uri format. Expected format: s3://bucket_name/key"
                    )

                source_bucket, source_key = s3_parsed_uri.groups()
                try:
                    self.s3_client.head_object(Bucket=source_bucket, Key=source_key)
                except self.s3_client.exceptions.NoSuchKey:
                    raise ValueError(
                        f"The s3_uri {s3_uri} does not exist or is not accessible with the provided credentials."
                    )

                copy_source = {"Bucket": source_bucket, "Key": source_key}
                self.s3_client.copy(copy_source, s3_bucket_name, s3_key)
                file_size = self.s3_client.head_object(
                    Bucket=s3_bucket_name, Key=s3_key
                )["ContentLength"]

                file_properties = {
                    "current_s3_key": s3_key,
                    "original_file_name": file_name,
                    "name": file_name,
                    "original_s3_uri": s3_uri,
                    "original_file_size_bytes": file_size,
                    "original_file_suffix": file_suffix,
                    "original_file_data_type": "s3_uri",
                    "file_type": file_suffix,
                    "current_s3_uri": f"s3://{s3_bucket_name}/{s3_key}",
                    "import_or_remote": import_or_remote,
                }

                # Delete the old file and create a marker file
                marker_key = f"{source_key}.dewey.{euid}.moved"
                if len(marker_key)  >= 1024:
                    raise Exception(f"Marker key length is too long, >1024chrar : {len(marker_key)},not deleting original file: {source_key}")
                self.s3_client.put_object(
                    Bucket=source_bucket,
                    Key=marker_key,
                    Body=b"",
                    Tagging=f"dewey_import_or_remote={import_or_remote}&dewey_euid={euid}&dewey_original_s3_uri={self.sanitize_tag(s3_uri)}{addl_tag_string}",
                )
                #self.s3_client.delete_object(Bucket=source_bucket, Key=source_key)


            else:
                self.logger.exception("No file data provided.")
                raise ValueError("No file data provided.")

        except Exception as e:
            logging.exception(f"An error occurred while uploading the file: {e}")
            file_instance.bstatus = "error"
            file_instance.json_addl["properties"]["comments"] = (
                str(e) + f" FILENAM == {file_name}"
            )
            flag_modified(file_instance, "json_addl")
            flag_modified(file_instance, "bstatus")
            self.session.flush()
            self.session.commit()
            raise (e)

        _update_recursive(file_instance.json_addl["properties"], file_properties)
        flag_modified(file_instance, "json_addl")
        self.session.commit()

        return file_instance

    def update_file_metadata(self, euid, file_metadata={}):
        file_instance = self.get_by_euid(euid)
        _update_recursive(file_instance.json_addl["properties"], file_metadata)
        flag_modified(file_instance, "json_addl")
        self.session.commit()
        return file_instance

    def get_file_by_euid(self, euid):
        return self.get_by_euid(euid)

    def download_file(
        self,
        euid,
        save_pattern="dewey",
        include_metadata=False,
        save_path="./tmp/",
        delete_if_exists=False,
    ):
        """
        Downloads the S3 file locally with different naming patterns and optionally includes metadata in a YAML file.

        :param euid: EUID of the file to download.
        :param save_pattern: Naming pattern for the saved file. Options: 'dewey', 'orig', 'hybrid'.
        :param include_metadata: Whether to save metadata in a YAML file. Defaults to False.
        :param save_path: Directory where the file will be saved. Defaults to ./tmp/, which will be created if not present.
        :return: Path of the saved file.
        """
        import random
        random.randint(1,99999999)
        save_path = os.path.join(save_path, str(random.randint(1,99999999)))
        os.system(f"mkdir -p {save_path}")
        
        if not os.path.exists(save_path):
            os.makedirs(save_path)
        else:
            self.logger.warn(f"Directory already exists: {save_path}")

        file_instance = self.get_by_euid(euid)
        s3_bucket_name = file_instance.json_addl["properties"]["current_s3_bucket_name"]
        s3_key = file_instance.json_addl["properties"]["current_s3_key"]
        original_file_name = file_instance.json_addl["properties"]["original_file_name"]
        file_suffix = file_instance.json_addl["properties"]["original_file_suffix"]

        if save_pattern == "dewey":
            local_file_name = f"{euid}.{file_suffix}"
        elif save_pattern == "orig":
            local_file_name = original_file_name
            print("WARNING: Using 'orig' pattern may overwrite existing files!")
        elif save_pattern == "hybrid":
            local_file_name = f"{euid}.{original_file_name}"
        else:
            raise ValueError(
                "Invalid save_pattern. Options are: 'dewey', 'orig', 'hybrid'."
            )

        local_file_path = os.path.join(save_path, local_file_name)

        if os.path.exists(local_file_path):
            self.logger.exception(f"File already exists: {local_file_path}")
            if delete_if_exists:
                os.remove(local_file_path)  # Delete the existing file
            else:
                raise Exception(f"File already exists: {local_file_path}")

        # Save metadata as a YAML file if requested
        if include_metadata:
            metadata_file_path = f"{local_file_path}.{euid}.dewey.yaml"
            if os.path.exists(metadata_file_path):
                self.logger.exception(
                    f"Metadata file already exists: {metadata_file_path}"
                )

                if delete_if_exists:
                    os.remove(metadata_file_path)
                else:
                    raise Exception(
                        f"Metadata file already exists: {metadata_file_path}"
                    )

            with open(metadata_file_path, "w") as metadata_file:
                yaml.dump(file_instance.json_addl["properties"], metadata_file)
            print(f"Metadata saved successfully: {metadata_file_path}")

        # Download the file from S3
        try:
            with open(local_file_path, "wb") as file:
                self.s3_client.download_fileobj(s3_bucket_name, s3_key, file)
            print(f"File downloaded successfully: {local_file_path}")
        except Exception as e:
            raise Exception(f"An error occurred while downloading the file: {e}")

        os.system(f"(sleep 2000 && rm -rf {save_path}) &")
        return local_file_path

    def get_s3_uris(self, euids, include_metadata=False):
        """
        Returns a dictionary of EUIDs to arrays containing their corresponding S3 URIs and optionally their metadata.

        :param euids: List of EUIDs to retrieve S3 URIs for.
        :param include_metadata: Boolean indicating whether to include metadata in the result.
        :return: Dictionary with EUID as key and array [S3 URI, metadata] as value.
        """
        euid_to_s3_data = {}

        for euid in euids:
            try:
                file_instance = self.get_by_euid(euid)
                s3_bucket_name = file_instance.json_addl["properties"][
                    "current_s3_bucket_name"
                ]
                s3_key = file_instance.json_addl["properties"]["current_s3_key"]
                s3_uri = f"s3://{s3_bucket_name}/{s3_key}"
                metadata = (
                    file_instance.json_addl["properties"] if include_metadata else None
                )
                euid_to_s3_data[euid] = [s3_uri, metadata]
            except Exception as e:
                self.logger.error(f"Error retrieving S3 URI for EUID {euid}: {e}")
                euid_to_s3_data[euid] = [None, None]  # or handle error as needed

        return euid_to_s3_data

    def delete_file(self, euid):
        # SOFT delete (S3 record is not deleted)

        file_instance = self.get_by_euid(euid)
        # s3_bucket_name = file_instance.json_addl['properties']['current_s3_bucket_name']
        # s3_key = file_instance.json_addl['properties']['current_s3_key']

        try:
            # self.s3_client.delete_object(Bucket=s3_bucket_name, Key=s3_key)
            self.delete_obj(file_instance)
            self.session.commit()
            return True
        except Exception as e:
            self.logger.error(f"Error deleting file {euid}: {e}")
            self.session.rollback()
            return False

    def get_s3_object_stream(self, euid):
        file_instance = self.get_file_by_euid(euid)
        s3_bucket_name = file_instance.json_addl["properties"]["current_s3_bucket_name"]
        s3_key = file_instance.json_addl["properties"]["current_s3_key"]

        try:
            response = self.s3_client.get_object(Bucket=s3_bucket_name, Key=s3_key)
            content_type = response["ContentType"]
            return response["Body"], content_type
        except self.s3_client.exceptions.NoSuchKey:
            raise Exception("File not found")
        except NoCredentialsError:
            raise Exception("Credentials not available")
        except Exception as e:
            raise Exception(e)

    def lock_file(self, euid, lock=True):
        """
        Locks or unlocks the specified S3 file.

        :param euid: EUID of the file to lock/unlock.
        :param lock: Boolean indicating whether to lock (True) or unlock (False) the file. Defaults to True.
        """
        file_instance = self.get_by_euid(euid)
        s3_bucket_name = file_instance.json_addl["properties"]["current_s3_bucket_name"]
        s3_key = file_instance.json_addl["properties"]["current_s3_key"]

        try:
            if lock:                
                self.s3_client.put_object_retention(
                    Bucket=s3_bucket_name,
                    Key=s3_key,
                    Retention={
                        'Mode': 'GOVERNANCE',
                        'RetainUntilDate': (datetime.now() + timedelta(days=36500)).isoformat()
                    }
                )

            return True
        except Exception as e:
            logging.exception(f"An error occurred while {'locking' if lock else 'unlocking'} the file: {e}")
            return False
        
    
    def create_presigned_url(self, 
                             file_euid,  
                             valid_duration=3600, 
                             comments="", status="active", 
                             file_set_euid=None):
        """
        Create a presigned url and create a shared reference to track this.

        :param file_euid: EUID of the file to create a shared reference for.
        :param valid_duration: Duration in seconds for which the reference is valid.
        :param comments: Additional comments for the reference.
        :param status: Status of the reference. Defaults to 'active'.
        :return: Created file reference instance.
        """
        
        # change to allow setting the start_datetime in the future.
        start_datetime = datetime.now(UTC)
        end_datetime = start_datetime + timedelta(seconds=valid_duration)
        
        file_instance = self.get_by_euid(file_euid)
        s3_bucket_name = file_instance.json_addl["properties"]["current_s3_bucket_name"]
        s3_key = file_instance.json_addl["properties"]["current_s3_key"]

        presigned_url = self.s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': s3_bucket_name, 'Key': s3_key},
            ExpiresIn=valid_duration
        )

        file_ref_obj = BloomFileReference(self._bdb)
        file_reference = file_ref_obj.create_file_reference(
            file_euid=file_euid,
            reference_type="presigned",
            valid_duration=valid_duration,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            comments=comments,
            status=status,
            presigned_url=presigned_url,
            file_set_euid=file_set_euid, 
            visibility=None
        )

        return {"file_reference": file_reference, "presigned_url": presigned_url}


    def import_files_from_s3_directory(self, s3_uri, file_metadata={}, create_locked=True):
        """
        Import all files from a specified S3 directory (not recursively).
        
        :param s3_uri: The S3 URI of the directory (e.g., s3://bucket_name/folder/).
        :param file_metadata: Metadata to associate with each imported file.
        :param create_locked: Whether to lock the files upon creation. Defaults to True.
        :return: List of created file objects.
        """
        # Parse S3 URI
        s3_parsed_uri = re.match(r"s3://([^/]+)/(.+)", s3_uri)
        if not s3_parsed_uri:
            raise ValueError("Invalid s3_uri format. Expected format: s3://bucket_name/folder/")
        
        bucket_name, prefix = s3_parsed_uri.groups()
        
        # List objects in the directory
        try:
            response = self.s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix, Delimiter='/')
            files = response.get('Contents', [])
        except Exception as e:
            raise Exception(f"Error listing S3 directory {s3_uri}: {e}")
        
        created_files = []
        for file in files:
            file_key = file['Key']
            
            # Skip directories
            if file_key.endswith('/'):
                continue
            
            file_name = file_key.split('/')[-1]
            current_s3_uri = f"s3://{bucket_name}/{file_key}"
            
            # Add metadata specific to the file
            individual_file_metadata = file_metadata.copy()
            individual_file_metadata['file_name'] = file_name
            
            try:
                # Create and add the file
                created_file = self.create_file(
                    file_metadata=individual_file_metadata,
                    s3_uri=current_s3_uri,
                    create_locked=create_locked
                )
                created_files.append(created_file)
            except Exception as e:
                logging.error(f"Error importing file {current_s3_uri}: {e}")
        
        return created_files




# As in expiring s3 links and so on. Potentially allow sharing of files with hosting protocols like SFTP, etc...

class BloomFileReference(BloomObj):
    
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)


    def create_file_reference(self, file_euid=None, reference_type='presigned', visibility='public', valid_duration=0, start_datetime=None, end_datetime=None, comments="", status="active", presigned_url="", file_set_euid=None, rclone_config={}):
        """
        Create a shared file reference.

        :param file_euid: EUID of the file.
        :param reference_type: Type of reference. 'presigned' or 'rclone http'.
        :param visibility: 'public' or 'controlled'.
        :param valid_duration: Duration in seconds for which the reference is valid.
        :param start_datetime: (Optional) Start datetime for the reference. Defaults to now.
        :param end_datetime: (Optional) End datetime for the reference. Calculated from valid_duration if not provided.
        :param comments: Additional comments for the reference.
        :param status: Status of the reference. Defaults to 'active'.
        :param rclone_config: Configuration for rclone http serve {'port': 8080, 'host': '0.0.0.0', 'user': 'user', 'passwd': 'passwd', 'bucket':'xxx-dewey-0'}.
        :return: Created file reference instance.
        """
        
        start_datetime = start_datetime or datetime.now(UTC)
        end_datetime = end_datetime or (start_datetime + timedelta(seconds=valid_duration))
        
        file_reference_metadata = {
            "status": status,
            "comments": comments,
            "visibility": visibility,
            "reference_type": reference_type,
            "valid_duration": valid_duration,
            "start_datetime": start_datetime.isoformat(),
            "end_datetime": end_datetime.isoformat(),
            "presigned_url": presigned_url,
            "rclone_config": rclone_config
        }
        
        file_reference = self.create_instance(
            self.query_template_by_component_v2(
                "file", "shared_ref", "generic", "1.0"
            )[0].euid,
            {"properties": file_reference_metadata},
        )
        
        if reference_type.startswith('rclone'):
            # Start the rclone http serve

            filter_fn = f"logs/{file_reference.euid}_filter.txt"
            fh = open(filter_fn, "w")

            fs = self.get_by_euid(file_set_euid)
            for x in fs.parent_of_lineages:
                print(x.child_instance.euid)
                fh.write(f"+ {x.child_instance.json_addl['properties']['current_s3_key']}\n")
            fh.write('- *\n')
            fh.close()


            cmd = f"timeout {valid_duration} {reference_type} blms3:{rclone_config['bucket']} --filter-from logs/{file_reference.euid}_filter.txt --addr {rclone_config['host']}:{rclone_config['port']} --user {rclone_config['user']} --pass {rclone_config['passwd']} 2>&1 > logs/{file_reference.euid}_rclone.log &"
            logging.info(f"Starting rclone http serve with command: {cmd}")
            
            file_reference.json_addl['properties']['rclone_cmd'] = cmd
            flag_modified(file_reference, "json_addl")
            
            try:
                # Start the command in the background
                process = subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )

                # Log that the process has started
                logging.info(f"rclone command started with PID: {process.pid}")

                # Optionally, you can wait a moment and then check if the process is still running
                process.communicate(timeout=5)
                if process.poll() is None:
                    logging.info(f"rclone is running successfully in the background.")
                    file_reference.json_addl['properties']['rclone_pid'] = process.pid
                    file_reference.json_addl['properties']['rclone_status'] = 'running'
                    flag_modified(file_reference, "json_addl")
                else:
                    file_reference.json_addl['properties']['rclone_status'] = 'error'
                    flag_modified(file_reference, "json_addl")
                    logging.error(f"rclone command failed to start properly. Error: {process.stderr.read().decode().strip()}")

            except subprocess.TimeoutExpired:
                logging.info(f"rclone command started and is running in the background.")
                file_reference.json_addl['properties']['rclone_pid'] = process.pid
                file_reference.json_addl['properties']['rclone_status'] = 'running bkgrnd'
                flag_modified(file_reference, "json_addl")
            except Exception as e:
                logging.error(f"An error occurred while starting rclone: {str(e)}")
                file_reference.json_addl['properties']['rclone_status'] = 'error'
                flag_modified(file_reference, "json_addl")

            self.session.commit()
            logging.info(f"{cmd} was executed... see logs")

            

            
        if file_euid not in [None]:
            self.create_generic_instance_lineage_by_euids(
                file_euid, file_reference.euid, reference_type
            )
            
        if file_set_euid not in [None]:
            self.create_generic_instance_lineage_by_euids(
                file_set_euid, file_reference.euid, "from_set"
            )



        self.session.commit()
        return file_reference
    

class BloomFileSet(BloomObj):
    def __init__(self, bdb, is_deleted=False, cfg_printers=False, cfg_fedex=False):
        super().__init__(bdb,is_deleted=is_deleted, cfg_printers=cfg_printers, cfg_fedex=cfg_fedex)

    def create_file_set(self, file_uids=[], file_set_metadata={}):
        file_set = self.create_instance(
            self.query_template_by_component_v2("file", "file_set", "generic", "1.0")[
                0
            ].euid,
            {"properties": file_set_metadata},
        )
        self.session.commit()

        return file_set

    def add_files_to_file_set(self, file_set_euid, file_euids=[]):
        file_set = self.get_by_euid(file_set_euid)
        for file_euid in file_euids:
            self.create_generic_instance_lineage_by_euids(file_set_euid, file_euid)
        self.session.commit()
        return file_set

    def get_file_set_by_euid(self, euid):
        return self.get_by_euid(euid)

    def remove_files_from_file_set(self, file_set_euid, file_euids=[]):
        file_set = self.get_by_euid(file_set_euid)

        # delete the lineage for each file to this file set
        for file_euid in file_euids:
            for i in file_set.child_of_lineages:
                if i.child_instance.euid == file_euid:
                    self.delete_obj(i)

        self.session.commit()
        return file_set

    def search_file_sets_by_metadata(self, search_criteria, greedy=True):
        """
        Search for file sets based on additional metadata.

        :param search_criteria: Dictionary containing the metadata to search for.
        :param greedy: Boolean indicating whether to perform a greedy search (matching any criteria) or not (matching all criteria).
        :return: List of EUIDs of matching file sets.
        """

        query = self.session.query(self.Base.classes.file_instance)

        if greedy:
            # Greedy search: matching any of the provided search keys
            or_conditions = []
            for key, value in search_criteria.items():
                if key == "file_metadata":
                    key = "properties"
                    logging.warning(
                        "The key 'file_metadata' is being treated as 'properties'."
                    )

                # Create conditions for JSONB key-value pairs
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        jsonb_filter = {key: {sub_key: sub_value}}
                        or_conditions.append(
                            self.Base.classes.file_set_instance.json_addl.op("@>")(
                                jsonb_filter
                            )
                        )
                else:
                    jsonb_filter = {key: value}
                    or_conditions.append(
                        self.Base.classes.file_set_instance.json_addl.op("@>")(
                            jsonb_filter
                        )
                    )

            if or_conditions:
                query = query.filter(or_(*or_conditions))
        else:
            # Non-greedy search: matching all specified search terms
            and_conditions = []
            for key, value in search_criteria.items():
                if key == "file_metadata":
                    key = "properties"
                    logging.warning(
                        "The key 'file_metadata' is being treated as 'properties'."
                    )

                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        jsonb_filter = {key: {sub_key: sub_value}}
                        and_conditions.append(
                            self.Base.classes.file_set_instance.json_addl.op("@>")(
                                jsonb_filter
                            )
                        )
                else:
                    jsonb_filter = {key: value}
                    and_conditions.append(
                        self.Base.classes.file_set_instance.json_addl.op("@>")(
                            jsonb_filter
                        )
                    )

            if and_conditions:
                query = query.filter(and_(*and_conditions))

        logging.info(f"Generated SQL: {str(query.statement)}")

        results = query.all()
        return [result.euid for result in results]
 


__all__ = [
    "BloomFile",
    "BloomFileReference",
    "BloomFileSet",
]
