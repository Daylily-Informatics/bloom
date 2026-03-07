from __future__ import annotations

"""
File manager, Dewey UI, and file set utilities.

This module contains legacy Dewey handlers moved out of `main.py` during the
modularization refactor. Handlers are kept behaviorally identical.
"""

import csv
import json
import logging
import os
import random
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.orm.attributes import flag_modified

from bloom_lims.bobjs import BloomFile, BloomFileReference, BloomFileSet, BloomObj
from bloom_lims.bvars import BloomVars
from bloom_lims.db import BLOOMdb3
from bloom_lims.gui.deps import require_auth
from bloom_lims.gui.jinja import templates

try:
    import matplotlib.pyplot as plt
except ModuleNotFoundError:  # pragma: no cover - optional GUI dependency
    plt = None


router = APIRouter()

BVARS = BloomVars()
BASE_DIR = Path("./served_data").resolve()


class FormField(BaseModel):
    name: str
    type: str
    label: str
    required: bool = False
    multiple: bool = False
    options: List[str] = []


def generate_form_fields(template_data: Dict) -> List[FormField]:
    properties = template_data.get("properties", {})
    controlled_properties = template_data.get("controlled_properties", {})
    form_fields = []

    for prop in properties:
        if prop in controlled_properties:
            cp = controlled_properties[prop]
            if cp["type"] == "dependent string":
                form_fields.append(
                    FormField(
                        name=prop,
                        type="select",
                        label=prop.replace("_", " ").capitalize(),
                        options=[],
                    )
                )
            else:
                form_fields.append(
                    FormField(
                        name=prop,
                        type="select",
                        label=prop.replace("_", " ").capitalize(),
                        options=cp.get("enum", []),
                    )
                )
        else:
            form_fields.append(
                FormField(
                    name=prop,
                    type="text",
                    label=prop.replace("_", " ").capitalize(),
                )
            )

    return form_fields


def generate_ui_form_fields(
    ui_form_properties: List[Dict],
    controlled_properties: Dict,
    form_type: str = "create",
    bobject=None,
    category: str = None,
    type_name: str = None,
    subtype: str = None,
    version: str = None,
) -> List[FormField]:
    form_fields = []

    for prop in ui_form_properties:
        property_key = prop["property_key"]
        form_label = prop["form_label"]
        required = prop.get("required", False)
        value_type = prop.get("value_type", "string")

        if property_key in controlled_properties:
            if form_type == "create":
                cp = controlled_properties[property_key]
                if cp["type"] == "dependent string":
                    form_fields.append(
                        FormField(
                            name=property_key,
                            type="select",
                            label=form_label,
                            options=[],
                            required=required,
                        )
                    )
                else:
                    form_fields.append(
                        FormField(
                            name=property_key,
                            type="select",
                            label=form_label,
                            options=cp.get("enum", []),
                            required=required,
                        )
                    )
            else:
                unique_values = sorted(
                    bobject.get_unique_property_values(
                        property_key,
                        category=category,
                        type=type_name,
                        subtype=subtype,
                        version=version,
                    )
                )
                if "" not in unique_values:
                    unique_values.insert(0, "")

                form_fields.append(
                    FormField(
                        name=property_key,
                        type="select",
                        label=form_label,
                        options=unique_values,
                        multiple=True,
                        required=required,
                    )
                )
        elif value_type == "uid-interactive":
            unique_values = sorted(bobject.get_unique_property_values(property_key))
            if "" not in unique_values:
                unique_values.insert(0, "")

            form_fields.append(
                FormField(
                    name=property_key,
                    type="select",
                    label=form_label,
                    options=unique_values,
                    multiple=True,
                    required=required,
                )
            )
        elif value_type == "uid-static":
            unique_values = sorted(bobject.get_unique_property_values(property_key))
            if "" not in unique_values:
                unique_values.insert(0, "")

            form_fields.append(
                FormField(
                    name=property_key,
                    type="select",
                    label=form_label,
                    options=unique_values,
                    multiple=True,
                    required=required,
                )
            )
        else:
            form_fields.append(
                FormField(
                    name=property_key,
                    type="text",
                    label=form_label,
                    required=required,
                )
            )

    return form_fields


def generate_unique_upload_key() -> str:
    color = random.choice(BVARS.pantone_colors)
    invertebrate = random.choice(BVARS.marine_invertebrates)
    number = random.randint(0, 1000000)
    return f"{color.replace(' ','_')}_{invertebrate.replace(' ','_')}_{number}"


@router.get("/dewey", response_class=HTMLResponse)
async def dewey(request: Request, _auth=Depends(require_auth)):
    request.session.pop("form_data", None)

    accordion_states = dict(request.session)
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}
    upload_group_key = generate_unique_upload_key()

    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    f_templates = bobdb.query_template_by_component_v2("file", "file", "generic", "1.0")
    fset_templates = bobdb.query_template_by_component_v2("file", "file_set", "generic", "1.0")

    if not f_templates:
        logging.error("No file template found for file/file/generic/1.0")
        raise HTTPException(
            status_code=500,
            detail=(
                "File template not found: file/file/generic/1.0. "
                "Please run 'bloom init' to seed templates."
            ),
        )
    if len(f_templates) > 1:
        logging.error("Multiple file templates found for file/file/generic/1.0")
        raise HTTPException(
            status_code=500, detail="Multiple file templates found for file/file/generic/1.0"
        )
    if not fset_templates:
        logging.error("No file set template found for file/file_set/generic/1.0")
        raise HTTPException(
            status_code=500,
            detail=(
                "File set template not found: file/file_set/generic/1.0. "
                "Please run 'bloom init' to seed templates."
            ),
        )
    if len(fset_templates) > 1:
        logging.error("Multiple file set templates found for file/file_set/generic/1.0")
        raise HTTPException(
            status_code=500,
            detail="Multiple file set templates found for file/file_set/generic/1.0",
        )

    f_template = f_templates[0]
    ui_form_properties = f_template.json_addl.get("ui_form_properties", [])
    ui_form_fields = generate_ui_form_fields(
        ui_form_properties,
        f_template.json_addl.get("controlled_properties", {}),
        bobject=bobdb,
    )
    ui_form_fields_query = generate_ui_form_fields(
        ui_form_properties,
        f_template.json_addl.get("controlled_properties", {}),
        bobject=bobdb,
        form_type="query",
        category="file",
        type_name="file",
        version=None,
    )

    fset_template = fset_templates[0]
    ui_form_properties_fset = fset_template.json_addl.get("ui_form_properties", [])
    ui_form_fields_fset = generate_ui_form_fields(
        ui_form_properties_fset,
        fset_template.json_addl.get("controlled_properties", {}),
        bobject=bobdb,
    )
    ui_form_fields_query_fset = generate_ui_form_fields(
        ui_form_properties_fset,
        fset_template.json_addl.get("controlled_properties", {}),
        bobject=bobdb,
        form_type="query",
        category="file",
        type_name="file_set",
        version=None,
    )

    template = templates.get_template("modern/dewey.html")
    context = {
        "request": request,
        "accordion_states": accordion_states,
        "style": style,
        "upload_group_key": upload_group_key,
        "udat": user_data,
        "user": user_data,
        "ui_fields": ui_form_fields,
        "ui_search_fields": ui_form_fields_query,
        "controlled_properties": f_template.json_addl.get("controlled_properties", {}),
        "has_ui_form_properties": bool(ui_form_properties),
        "searchable_properties": sorted(f_template.json_addl["properties"].keys()),
        "s3_bucket_prefix": os.environ.get("BLOOM_DEWEY_S3_BUCKET_PREFIX", "NEEDS TO BE SET!") + "0",
        "ui_fields_fset": ui_form_fields_fset,
        "ui_search_fields_fset": ui_form_fields_query_fset,
    }
    return HTMLResponse(content=template.render(context))


@router.get("/bulk_create_files", response_class=HTMLResponse)
async def bulk_create_files(request: Request, _auth=Depends(require_auth)):
    request.session.pop("form_data", None)

    accordion_states = dict(request.session)
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}

    content = templates.get_template("legacy/bulk_create_files.html").render(
        request=request,
        accordion_states=accordion_states,
        style=style,
        udat=user_data,
        page_title="Bulk Create Files",
    )

    return HTMLResponse(content=content)


@router.post("/create_file")
async def create_file(
    request: Request,
    name: str = Form(...),
    comments: str = Form(""),
    lab_code: str = Form(""),
    file_data: List[UploadFile] = File(""),
    directory: List[UploadFile] = File(""),
    urls: str = Form(""),
    s3_uris: str = Form(""),
    study_id: str = Form(""),
    clinician_id: str = Form(""),
    health_event_id: str = Form(""),
    record_datetime: str = Form(""),
    record_datetime_end: str = Form(""),
    patient_id: str = Form(""),
    upload_group_key: str = Form(""),
    upload_group_key_ifnone: str = Form(""),
    purpose: str = Form(""),
    category: str = Form(""),
    sub_category: str = Form(""),
    sub_category_2: str = Form(""),
    variable: str = Form(""),
    sub_variable: str = Form(""),
    file_tags: str = Form(""),
    import_or_remote: str = Form("import_or_remote"),
    further_metadata: str = Form(""),
):
    user_data = request.session.get("user_data", {})
    controlled_properties = {}

    file_set_name = upload_group_key_ifnone if upload_group_key in [None, "None", ""] else upload_group_key

    if directory and len(directory) > 1000:
        return JSONResponse(
            status_code=400,
            content={"detail": "Too many files. Maximum number of files is 1000."},
        )

    try:
        bfs = BloomFileSet(BLOOMdb3(app_username=request.session.get("user_data", {}).get("email", "na")))
        file_set_metadata = {
            "name": file_set_name,
            "description": "File set created by Dewey file manager",
            "tag": "on-create",
            "comments": "",
        }
        new_file_set = bfs.create_file_set(file_set_metadata=file_set_metadata)

        bfi = BloomFile(BLOOMdb3(app_username=request.session.get("user_data", {}).get("email", "na")))
        file_metadata = {
            "name": name,
            "comments": comments,
            "lab_code": lab_code,
            "clinician_id": clinician_id,
            "health_event_id": health_event_id,
            "record_datetime": record_datetime,
            "record_datetime_end": record_datetime_end,
            "patient_id": patient_id,
            "creating_user": request.session.get("user_data", {}).get("email", "na"),
            "upload_group_key": file_set_name,
            "study_id": study_id,
            "purpose": purpose,
            "category": category,
            "sub_category": sub_category,
            "sub_category_2": sub_category_2,
            "variable": variable,
            "sub_variable": sub_variable,
            "file_tags": file_tags,
            "import_or_remote": import_or_remote,
        }

        if further_metadata:
            file_metadata.update(json.loads(further_metadata))

        results = []

        addl_tags = {"patient_id": patient_id, "study_id": study_id, "clinician_id": clinician_id}

        if file_data:
            for file in file_data:
                if file.filename:
                    try:
                        new_file = bfi.create_file(
                            file_metadata=file_metadata,
                            file_data=file.file,
                            file_name=file.filename,
                            addl_tags=addl_tags,
                        )
                        results.append(
                            {
                                "identifier": new_file.euid,
                                "status": "Success",
                                "original": file.filename if file else url,
                                "current_s3_uri": new_file.json_addl["properties"]["current_s3_uri"],
                            }
                        )
                        bfs.add_files_to_file_set(
                            file_set_euid=new_file_set.euid, file_euids=[new_file.euid]
                        )
                    except Exception as e:
                        results.append(
                            {
                                "identifier": file.filename,
                                "status": f"Failed: {str(e)}",
                                "original": file.filename if file else url,
                            }
                        )

        if urls:
            url_list = urls.split("\n")
            for url in url_list:
                if url.strip():
                    try:
                        new_file = bfi.create_file(
                            file_metadata=file_metadata,
                            url=url.strip(),
                            addl_tags=addl_tags,
                        )
                        results.append(
                            {
                                "identifier": new_file.euid,
                                "status": "Success",
                                "original": url,
                                "current_s3_uri": new_file.json_addl["properties"]["current_s3_uri"],
                            }
                        )
                        bfs.add_files_to_file_set(
                            file_set_euid=new_file_set.euid, file_euids=[new_file.euid]
                        )
                    except Exception as e:
                        results.append({"identifier": url.strip(), "status": f"Failed: {str(e)}"})
        if s3_uris:
            s3_uri_list = s3_uris.split("\n")
            for s3_uri in s3_uri_list:
                if s3_uri.strip():
                    try:
                        new_file = bfi.create_file(
                            file_metadata=file_metadata,
                            s3_uri=s3_uri.strip(),
                            addl_tags=addl_tags,
                        )

                        if type(new_file) == type([]):
                            for nf in new_file:
                                results.append(
                                    {
                                        "identifier": nf.euid,
                                        "status": "Success",
                                        "original": s3_uri,
                                        "current_s3_uri": nf.json_addl["properties"]["current_s3_uri"],
                                    }
                                )
                                bfs.add_files_to_file_set(
                                    file_set_euid=new_file_set.euid, file_euids=[nf.euid]
                                )
                        else:
                            results.append(
                                {
                                    "identifier": new_file.euid,
                                    "status": "Success",
                                    "original": s3_uri,
                                    "current_s3_uri": new_file.json_addl["properties"]["current_s3_uri"],
                                }
                            )
                            bfs.add_files_to_file_set(
                                file_set_euid=new_file_set.euid, file_euids=[new_file.euid]
                            )
                    except Exception as e:
                        results.append(
                            {
                                "identifier": s3_uri.strip(),
                                "status": f"Failed: {str(e)}",
                            }
                        )

        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}
        content = templates.get_template("legacy/create_file_report.html").render(
            request=request, results=results, style=style, udat=user_data
        )

        return HTMLResponse(content=content)

    except ValueError as ve:
        logging.error("Input error: %s", ve)
        return HTMLResponse(content=f"<html><body><h2>{ve}</h2></body></html>", status_code=400)

    except Exception as e:
        logging.error("Error creating file: %s", e)

        accordion_states = dict(request.session)
        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}
        content = templates.get_template("legacy/dewey.html").render(
            request=request,
            error=f"An error occurred: {e}",
            accordion_states=accordion_states,
            style=style,
            controlled_properties=controlled_properties,
            udat=user_data,
        )

        return HTMLResponse(content=content)


@router.post("/download_file", response_class=HTMLResponse)
async def download_file(
    request: Request,
    euid: str = Form(...),
    download_type: str = Form(...),
    create_metadata_file: str = Form(...),
    ret_json: str = Form(None),
):
    try:
        bfi = BloomFile(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        downloaded_file_path = bfi.download_file(
            euid=euid,
            save_pattern=download_type,
            include_metadata=True if create_metadata_file == "yes" else False,
            save_path="./tmp/",
            delete_if_exists=True,
        )

        if not os.path.exists(downloaded_file_path):
            return HTMLResponse(f"File with EUID {euid} not found.", status_code=404)

        metadata_yaml_path = None
        if create_metadata_file == "yes":
            metadata_yaml_path = downloaded_file_path + "." + euid + ".dewey.yaml"
            if not os.path.exists(metadata_yaml_path):
                return HTMLResponse(f"Metadata file for EUID {euid} not found.", status_code=404)

        if ret_json:
            return JSONResponse(
                content={
                    "file_download_path": downloaded_file_path,
                    "metadata_download_path": metadata_yaml_path,
                }
            )

        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}
        content = templates.get_template("legacy/trigger_downloads.html").render(
            request=request,
            file_download_path=downloaded_file_path,
            metadata_download_path=metadata_yaml_path,
            style=style,
            udat=user_data,
        )

        return HTMLResponse(content=content)

    except Exception as e:
        logging.error("Error downloading file: %s", e)

        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}
        offending_file = str(e).split("/tmp/")[-1]

        content = templates.get_template("legacy/download_error.html").render(
            request=request,
            error=f"An error occurred: {e}",
            style=style,
            udat=user_data,
            offending_file=offending_file,
        )

        return HTMLResponse(content=content)


def delete_file(file_path: Path):
    try:
        if file_path.exists():
            file_path.unlink()
            logging.info("Deleted file %s", file_path)
    except Exception as e:
        logging.error("Error deleting file %s: %s", file_path, e)


@router.get("/delete_temp_file")
async def delete_temp_file(
    request: Request, filename: str, background_tasks: BackgroundTasks
):
    file_path = Path("./tmp") / filename
    file_path_yaml = Path("./tmp") / f"{filename}.dewey.yaml"

    if file_path.exists():
        background_tasks.add_task(delete_file, file_path)
        background_tasks.add_task(delete_file, file_path_yaml)
    return RedirectResponse(url="/dewey", status_code=303)


@router.post("/search_files", response_class=HTMLResponse)
async def search_files(
    request: Request,
    euid: str = Form(None),
    is_greedy: str = Form("yes"),
    patient_id: List[str] = Form(None),
    clinician_id: List[str] = Form(None),
    record_datetime_start: str = Form(None),
    record_datetime_end: str = Form(None),
    lab_code: List[str] = Form(None),
    purpose: str = Form(None),
    purpose_subtype: str = Form(None),
    category: str = Form(None),
    sub_category: str = Form(None),
    sub_category_2: str = Form(None),
    variable: str = Form(None),
    sub_variable: str = Form(None),
    file_tags: List[str] = Form(None),
    upload_group_key: List[str] = Form(None),
):
    return JSONResponse(
        status_code=410,
        content={
            "detail": (
                "Legacy /search_files endpoint has been removed. "
                "Use GET /search (GUI) or POST /api/v1/search/v2/query."
            )
        },
    )


def create_search_criteria(form_data, fields):
    search_criteria = {}
    for field in fields:
        field_value = form_data.get(field)
        if field_value:
            if isinstance(field_value, list):
                if len(field_value) == 1 and field_value[0] in [".na"]:
                    field_value = ""
                if len(field_value) == 1 and field_value[0] in [""]:
                    continue
                search_criteria[field] = field_value
            else:
                if field_value in [".na"]:
                    field_value = ""
                if field_value in [""]:
                    continue
                search_criteria[field] = field_value
    return search_criteria


@router.post("/create_file_set")
async def create_file_set(
    request: Request,
    name: str = Form(None),
    description: str = Form(None),
    tag: str = Form(None),
    comments: str = Form(None),
    file_euids: str = Form(None),
    ref_type: str = Form("na"),
    duration: float = Form(0),
    bucket: str = Form(""),
    host: str = Form(""),
    port: int = Form(0),
    user: str = Form(""),
    passwd: str = Form(""),
    _auth=Depends(require_auth),
):
    rclone_config = {"bucket": bucket, "host": host, "port": port, "user": user, "passwd": passwd}
    try:
        bf = BloomFile(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        bfs = BloomFileSet(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        bfr = BloomFileReference(BLOOMdb3(app_username=request.session["user_data"]["email"]))

        file_set_metadata = {
            "name": name,
            "description": description,
            "tag": tag,
            "comments": comments,
            "ref_type": ref_type,
            "duration": duration,
            "rclone_config": rclone_config,
            "creating_user": request.session["user_data"]["email"],
        }

        new_file_set = bfs.create_file_set(file_set_metadata=file_set_metadata)

        file_euids_list = [euid.strip() for euid in file_euids.split()]
        bfs.add_files_to_file_set(file_set_euid=new_file_set.euid, file_euids=file_euids_list)

        duration_sec = duration * 24 * 60 * 60

        if ref_type == "presigned_url":
            for f_euid in file_euids_list:
                bf.create_presigned_url(
                    file_euid=f_euid,
                    file_set_euid=new_file_set.euid,
                    valid_duration=duration_sec,
                )
        elif ref_type.startswith("rclone"):
            bfr.create_file_reference(
                reference_type=ref_type,
                valid_duration=duration_sec,
                file_set_euid=new_file_set.euid,
                rclone_config=rclone_config,
            )
        elif ref_type.startswith("na"):
            pass
        else:
            raise ValueError(f"UNSUPPORTED ref_type: {ref_type}")

        return RedirectResponse(url=f"/euid_details?euid={new_file_set.euid}", status_code=303)

    except Exception as e:
        raise (e)


@router.post("/search_file_sets", response_class=HTMLResponse)
async def search_file_sets(
    request: Request,
    name: str = Form(None),
    description: str = Form(None),
    tag: List[str] = Form(None),
    comments: str = Form(None),
    file_euids: str = Form(None),
    is_greedy: str = Form("yes"),
    ref_type: List[str] = Form(None),
    creating_user: List[str] = Form(None),
):
    return JSONResponse(
        status_code=410,
        content={
            "detail": (
                "Legacy /search_file_sets endpoint has been removed. "
                "Use POST /search (GUI Dewey flow) or POST /api/v1/search/v2/query."
            )
        },
    )


@router.get("/visual_report", response_class=HTMLResponse)
async def visual_report(request: Request):
    import base64
    import io

    if plt is None:
        raise HTTPException(status_code=503, detail="matplotlib is required for visual reports")

    file_path = "~/Downloads/dewey_search.tsv"
    data = pd.read_csv(file_path, sep="\t")

    file_types = data["file_type"].value_counts()
    file_sizes = data["original_file_size_bytes"].dropna()
    upload_users = data["upload_ui_user"].value_counts()

    plots = []

    def create_plot(series, title, xlabel, ylabel, plot_type="bar"):
        fig, ax = plt.subplots()
        if plot_type == "bar":
            series.plot(kind="bar", ax=ax)
        elif plot_type == "hist":
            series.plot(kind="hist", ax=ax, bins=30)
        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        figfile = io.BytesIO()
        plt.savefig(figfile, format="png")
        figfile.seek(0)
        return base64.b64encode(figfile.getvalue()).decode("utf8")

    file_types_img = create_plot(file_types, "Distribution of File Types", "File Type", "Count", "bar")
    file_sizes_img = create_plot(
        file_sizes,
        "Distribution of File Sizes",
        "File Size (bytes)",
        "Frequency",
        "hist",
    )
    upload_users_img = create_plot(upload_users, "Files Uploaded by User", "User", "Number of Files", "bar")

    plots.append(file_types_img)
    plots.append(file_sizes_img)
    plots.append(upload_users_img)

    template = templates.get_template("legacy/visual_report.html")
    context = {"request": request, "plots": plots}

    return HTMLResponse(content=template.render(context), status_code=200)


@router.get("/create_instance/{template_euid}", response_class=HTMLResponse)
async def create_instance_form(request: Request, template_euid: str, _auth=Depends(require_auth)):
    bobj = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    template_instance = bobj.get_by_euid(template_euid)
    template_data = template_instance.json_addl

    form_fields = generate_form_fields(template_data)
    ui_form_properties = template_data.get("ui_form_properties", [])
    ui_form_fields = generate_ui_form_fields(
        ui_form_properties, template_data.get("controlled_properties", {})
    )

    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}

    controlled_properties_js = json.dumps(template_data.get("controlled_properties", {}))

    content = templates.get_template("legacy/create_instance_form.html").render(
        request=request,
        fields=form_fields,
        ui_fields=ui_form_fields,
        style=style,
        udat=user_data,
        template_euid=template_euid,
        polymorphic_discriminator=template_instance.polymorphic_discriminator,
        category=template_instance.category,
        type=template_instance.type,
        subtype=template_instance.subtype,
        version=template_instance.version,
        name=template_instance.name,
        controlled_properties=template_data.get("controlled_properties", {}),
        has_ui_form_properties=bool(ui_form_properties),
        controlled_properties_js=controlled_properties_js,
    )
    return HTMLResponse(content=content)


@router.post("/create_instance")
async def create_instance(request: Request, _auth=Depends(require_auth)):
    bobj = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    form_data = await request.form()
    template_euid = form_data["template_euid"]

    jaddl = {"properties": dict(form_data)}
    ni = bobj.create_instance(template_euid, jaddl)

    return RedirectResponse(url=f"/euid_details?euid={ni.euid}", status_code=303)


@router.get("/file_set_urls", response_class=HTMLResponse)
async def file_set_urls(request: Request, fs_euid: str, _auth=Depends(require_auth)):
    try:
        bfs = BloomFileSet(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        bf = BloomFile(BLOOMdb3(app_username=request.session["user_data"]["email"]))

        file_set = bfs.get_by_euid(fs_euid)
        if not file_set:
            raise HTTPException(status_code=404, detail="File set not found.")

        shared_refs = []
        for lineage in file_set.parent_of_lineages:
            if lineage.is_deleted:
                continue
            if lineage.child_instance.type == "shared_ref":
                orig_file = None
                for x in lineage.child_instance.child_of_lineages.all():
                    if x.parent_instance.type == "file":
                        orig_file = x.parent_instance

                shared_refs.append(
                    {
                        "euid": lineage.child_instance.euid,
                        "url": lineage.child_instance.json_addl["properties"].get("presigned_url", "N/A"),
                        "start_datetime": lineage.child_instance.json_addl["properties"].get("start_datetime", "N/A"),
                        "end_datetime": lineage.child_instance.json_addl["properties"].get("end_datetime", "N/A"),
                        "orig_file": orig_file,
                    }
                )

        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}
        context = {
            "request": request,
            "file_set": file_set,
            "shared_refs": shared_refs,
            "style": style,
            "udat": user_data,
        }
        content = templates.get_template("legacy/file_set_urls.html").render(context)
        return HTMLResponse(content=content)

    except Exception as e:
        logging.error("Error fetching file set URLs: %s", e)
        return JSONResponse(
            content={"error": "An error occurred while fetching file set URLs."}, status_code=500
        )


@router.get("/admin_template", response_class=HTMLResponse)
async def get_admin_template(request: Request, euid: str = Query(...)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    obj = bobdb.get_by_euid(euid)

    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")

    controlled_properties = obj.json_addl.get("controlled_properties", {})
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "/static/legacy/skins/bloom.css")}

    template = templates.get_template("legacy/admin_template.html")
    context = {
        "request": request,
        "euid": euid,
        "controlled_properties": json.dumps(controlled_properties, indent=4),
        "udat": user_data,
        "style": style,
    }

    return HTMLResponse(content=template.render(context))


@router.post("/admin_template", response_class=HTMLResponse)
async def post_admin_template(
    request: Request,
    euid: str = Form(...),
    controlled_properties: str = Form(...),
):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    obj = bobdb.get_by_euid(euid)

    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")

    try:
        obj.json_addl["controlled_properties"] = json.loads(controlled_properties)
        flag_modified(obj, "json_addl")
        bobdb.session.commit()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return RedirectResponse(url=f"/admin_template?euid={euid}", status_code=303)


@router.get("/serve_endpoint/{file_path:path}", response_class=HTMLResponse)
async def serve_files(file_path: str, request: Request, auth=Depends(require_auth)):
    print("YYYYYYYYY", file_path)

    if file_path.startswith("/"):
        file_path = file_path.lstrip("/")

    if file_path in [None, "", "/"]:
        file_path = ""
    print("RRRRR", file_path)

    requested_path = BASE_DIR / file_path
    print("xxxxxx", BASE_DIR, file_path, requested_path)
    logging.info("Requested path: %s", requested_path)

    if not requested_path.exists():
        logging.error("File or directory not found: %s", requested_path)
        raise HTTPException(status_code=404, detail="File or directory not found")

    full_path = requested_path.resolve()

    if full_path.is_dir():
        return directory_listing(full_path, file_path)
    if full_path.is_file():
        if full_path.suffix == ".html":
            with open(full_path, "r") as f:
                content = f.read()
            return HTMLResponse(content=content)
        return FileResponse(full_path, media_type="application/octet-stream", filename=full_path.name)

    raise HTTPException(status_code=404, detail="File or directory not found")


def directory_listing(directory: Path, file_path: str) -> HTMLResponse:
    parent_path = file_path + "/../.."

    items = sorted(directory.iterdir(), key=lambda x: x.name.lower())

    files = []
    for item in items:
        if item.is_dir():
            files.append(f"<li><a href=\"/serve_endpoint/{file_path}/{item.name}/\">{item.name}/</a></li>")
        else:
            files.append(f"<li><a href=\"/serve_endpoint/{file_path}/{item.name}\">{item.name}</a></li>")
    print("PPPPPP", str(parent_path))
    html_content = f"""
    <h2>Directory listing for: {directory.name}</h2>
    <ul>
        <li><a href="/serve_endpoint/{parent_path.lstrip('/')}">.. (parent directory)</a></li>
        {''.join(files)}
    </ul>
    """
    return HTMLResponse(content=html_content)


@router.get("/protected_content", response_class=HTMLResponse)
async def protected_content(request: Request, auth=Depends(require_auth)):
    content = "You are authenticated and can access protected resources."
    return HTMLResponse(content=content)


@router.post("/bulk_create_files_from_tsv")
async def bulk_create_files_from_tsv(request: Request, file: UploadFile = File(...)):
    temp_dir = Path("temp_bulk_create")
    temp_dir.mkdir(exist_ok=True)

    tsv_path = temp_dir / file.filename
    with open(tsv_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    rows = []
    try:
        with open(tsv_path, "r") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        if not rows:
            return {"status": "error", "message": "The TSV file is empty."}

        required_columns = [
            "name",
            "comments",
            "lab_code",
            "urls",
            "s3_uris",
            "study_id",
            "clinician_id",
            "record_datetime",
            "record_datetime_end",
            "patient_id",
            "purpose",
            "category",
            "sub_category",
            "sub_category_2",
            "variable",
            "sub_variable",
            "file_tags",
            "upload_key",
        ]

        for column in required_columns:
            if column not in rows[0]:
                return {"status": "error", "message": f"Missing required column: {column}"}

        logging.info("Pre-checks passed. Processing the TSV...")
    except Exception as e:
        return {"status": "error", "message": f"Failed to process TSV: {e}"}

    results = []

    # Preserve the original behavior that uses an internal TestClient to hit /create_file.
    # This is intentionally not performance-optimized, because it is a legacy path.
    from bloom_lims.app import create_app

    client = TestClient(create_app())

    for i, row in enumerate(rows):
        num_files = 0
        num_success = 0
        num_failed = 0
        messages = []

        urls = row.get("urls", "").split(",") if row.get("urls") else []
        s3_uris = row.get("s3_uris", "").split(",") if row.get("s3_uris") else []
        num_files = len(urls) + len(s3_uris)

        try:
            response = client.post("/create_file", data=row)
            logging.info("Row %s: %s ... %s", i + 1, response.json(), response.status_code)
            if response.status_code in [200, 307]:
                num_success += 1
                messages.append("File created successfully.")
            else:
                num_failed += 1
                messages.append(response.json().get("detail", "Unknown error"))
        except Exception as e:
            num_failed += 1
            messages.append(str(e))

        results.append(
            {
                "row": i + 1,
                "num_files_to_create": num_files,
                "num_success": num_success,
                "num_failed": num_failed,
                "create_message": "; ".join(messages),
                "datetime_finished": datetime.now().isoformat(),
            }
        )

    fin_tsv_path = tsv_path.with_suffix(".fin.tsv")

    with open(fin_tsv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(rows[0].keys())
            + [
                "row",
                "num_files_to_create",
                "num_success",
                "num_failed",
                "create_message",
                "datetime_finished",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        for row, result in zip(rows, results):
            writer.writerow({**row, **result})

    return FileResponse(fin_tsv_path, media_type="text/tab-separated-values")
