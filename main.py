import sys
import jwt
import httpx
import os
import json
import subprocess
from typing import List
from pathlib import Path
import random
import asyncio

import csv
import os
import datetime
import json
import logging
import requests
import shutil

import pandas 

import pandas as pd
import matplotlib.pyplot as plt

from datetime import datetime, timedelta, date

from dotenv import load_dotenv
load_dotenv(override=True)  


# The following three lines allow for dropping embed() in to block and present an IPython shell
from IPython import embed
import nest_asyncio

nest_asyncio.apply()

import difflib

def get_clean_timestamp():
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

os.makedirs("logs", exist_ok=True)

import logging
from logging.handlers import RotatingFileHandler


def setup_logging():
    # uvicorn to capture logs from all libs
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Define the log file name with a timestamp
    log_filename = f"logs/bloomui_{get_clean_timestamp()}.log"

    # Stream handler (to console)
    c_handler = logging.StreamHandler()
    c_handler.setLevel(logging.INFO)

    # File handler (to file, with rotation)
    f_handler = RotatingFileHandler(log_filename, maxBytes=10485760, backupCount=5)
    f_handler.setLevel(logging.INFO)

    # Common log format
    formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(pathname)s:%(lineno)d"
    )
    c_handler.setFormatter(formatter)
    f_handler.setFormatter(formatter)

    # Add handlers to the logger
    logger.addHandler(c_handler)
    logger.addHandler(f_handler)


setup_logging()


from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status,
    Request,
    Response,
    Form,
    Query,
    File,
    UploadFile,
    BackgroundTasks,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyCookie
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from starlette.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import func, text

from jinja2 import Environment, FileSystemLoader
from collections import defaultdict
from datetime import datetime, timedelta

from bloom_lims.db import BLOOMdb3
from bloom_lims.bobjs import (
    BloomObj,
    BloomWorkflow,
    BloomWorkflowStep,
    BloomFile,
    BloomFileSet,
    BloomFileReference
)

from bloom_lims.bvars import BloomVars

BVARS = BloomVars()
BASE_DIR = Path("./served_data").resolve()  # Base directory for serving files

from auth.supabase.connection import create_supabase_client


# Lock to serialize backup and restore operations
db_lock = asyncio.Lock()


# local udata prefernces
UDAT_FILE = "./etc/udat.json"
# Create if not exists
os.makedirs(os.path.dirname(UDAT_FILE), exist_ok=True)
if not os.path.exists(UDAT_FILE):
    with open(UDAT_FILE, "w") as f:
        json.dump({}, f)

# Initialize Jinja2 environment
templates = Environment(loader=FileSystemLoader("templates"))

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/templates", StaticFiles(directory="templates"), name="templates")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/tmp", StaticFiles(directory="tmp"), name="tmp")


# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionMiddleware, secret_key="your-secret-key")

# Serve static files
cookie_scheme = APIKeyCookie(name="session")
SKIP_AUTH = False if len(sys.argv) < 3 else True



@app.get("/list-scripts", response_class=JSONResponse)
async def list_scripts(directory: str = Query(..., description="Directory to search for .js files")):
    """
    List all .js files in the specified directory.

    Args:
        directory (str): The directory to search for .js files.

    Returns:
        JSONResponse: A list of .js file paths.
    """
    try:
        # Resolve the directory path and ensure it exists
        dir_path = Path(directory)
        if not dir_path.is_dir():
            raise HTTPException(status_code=400, detail=f"Invalid directory: {directory}")

        # Ensure the directory has a trailing slash
        normalized_directory = str(dir_path) + "/"

        # Search for .js files and construct file paths with the normalized directory
        js_files = [str(file) for file in dir_path.rglob("*.js")]

        logging.info(f"Found {str(js_files)} .js files in {directory}")
        return JSONResponse(content={"scripts": js_files}, status_code=200)
    except Exception as e:
        logging.error(f"Error listing scripts: {e}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")

class AuthenticationRequiredException(HTTPException):
    def __init__(self, detail: str = "Authentication required"):
        super().__init__(status_code=401, detail=detail)


class MissingSupabaseEnvVarsException(HTTPException):
    def __init__(self, message="The Supabase environment variables are not found."):
        super().__init__(status_code=401, detail=message)


def proc_udat(email):
    with open(UDAT_FILE, "r+") as f:
        user_data = json.load(f)
        if email not in user_data:
            user_data[email] = {"style_css": "static/skins/bloom.css", "email": email}

            f.seek(0)
            json.dump(user_data, f, indent=4)
            f.truncate()

    return user_data[email]


async def DELis_instance(value, type_name):
    return isinstance(value, eval(type_name))


def get_well_color(quant_value):
    # Transition from purple to white
    if quant_value <= 0.5:
        r = int(128 + 127 * (quant_value / 0.5))  # From 128 to 255
        g = int(0 + 255 * (quant_value / 0.5))  # From 0 to 255
        b = int(128 + 127 * (quant_value / 0.5))  # From 128 to 255
    # Transition from white to green
    else:
        r = int(255 - 255 * ((quant_value - 0.5) / 0.5))  # From 255 to 0
        g = 255
        b = int(255 - 255 * ((quant_value - 0.5) / 0.5))  # From 255 to 0

    return f"rgb({r}, {g}, {b})"


def highlight_json_changes(old_json_str, new_json_str):
    try:
        old_json = json.loads(old_json_str)
        new_json = json.loads(new_json_str)
    except json.JSONDecodeError:
        return old_json_str, new_json_str
    
    old_json_formatted = json.dumps(old_json, indent=2)
    new_json_formatted = json.dumps(new_json, indent=2)
    
    diff = difflib.ndiff(old_json_formatted.splitlines(), new_json_formatted.splitlines())
    
    old_json_highlighted = []
    new_json_highlighted = []
    
    for line in diff:
        if line.startswith("- "):
            old_json_highlighted.append(f'<span class="deleted">{line[2:]}</span>')
        elif line.startswith("+ "):
            new_json_highlighted.append(f'<span class="added">{line[2:]}</span>')
        elif line.startswith("  "):
            old_json_highlighted.append(line[2:])
            new_json_highlighted.append(line[2:])
    
    return '\n'.join(old_json_highlighted), '\n'.join(new_json_highlighted)


async def get_relationship_data(obj):
    relationship_data = {}
    for relationship in obj.__mapper__.relationships:
        if relationship.uselist:  # If it's a list of items
            relationship_data[relationship.key] = [
                {
                    "child_instance_euid": (
                        rel_obj.child_instance.euid
                        if hasattr(rel_obj, "child_instance")
                        else []
                    ),
                    "parent_instance_euid": (
                        rel_obj.parent_instance.euid
                        if hasattr(rel_obj, "parent_instance")
                        else []
                    ),
                    "euid": rel_obj.euid,
                    "uuid": rel_obj.uuid,
                    "polymorphic_discriminator": rel_obj.polymorphic_discriminator,
                    "super_type": rel_obj.super_type,
                    "btype": rel_obj.btype,
                    "b_sub_type": rel_obj.b_sub_type,
                    "version": rel_obj.version,
                }
                for rel_obj in getattr(obj, relationship.key)
            ]
        else:  # If it's a single item
            rel_obj = getattr(obj, relationship.key)
            relationship_data[relationship.key] = [
                (
                    {
                        "child_instance_euid": (
                            rel_obj.child_instance.euid
                            if hasattr(rel_obj, "child_instance")
                            else []
                        ),
                        "parent_instance_euid": (
                            rel_obj.parent_instance.euid
                            if hasattr(rel_obj, "parent_instance")
                            else []
                        ),
                        "euid": rel_obj.euid,
                        "uuid": rel_obj.uuid,
                        "polymorphic_discriminator": rel_obj.polymorphic_discriminator,
                        "super_type": rel_obj.super_type,
                        "btype": rel_obj.btype,
                        "b_sub_type": rel_obj.b_sub_type,
                        "version": rel_obj.version,
                    }
                    if rel_obj
                    else {}
                )
            ]
    return relationship_data


def _pg_env():
    env = os.environ.copy()
    env.setdefault("PGHOST", "localhost")
    env.setdefault("PGPORT", "5445")
    env.setdefault("PGUSER", env.get("USER", "bloom"))
    env.setdefault("PGPASSWORD", env.get("PGPASSWORD", "passw0rd"))
    env.setdefault("PGDBNAME", env.get("PGDBNAME", "bloom"))
    return env


def pg_dump_file(out_path: Path):
    env = _pg_env()
    cmd = ["pg_dump", "-Fp", env["PGDBNAME"]]
    with open(out_path, "w") as fh:
        subprocess.run(cmd, stdout=fh, check=True, env=env)


def pg_restore_file(sql_path: Path):
    env = _pg_env()
    schema = env["PGDBNAME"]
    # Drop the schema matching the DB name to avoid restore conflicts
    logging.info("Dropping schema %s before restore", schema)
    drop_cmd = [
        "psql",
        env["PGDBNAME"],
        "-c",
        f"DROP SCHEMA IF EXISTS {schema} CASCADE; CREATE SCHEMA {schema};",
    ]
    subprocess.run(drop_cmd, check=True, env=env)

    cmd = ["psql", env["PGDBNAME"], "-v", "ON_ERROR_STOP=1"]
    logging.info("Restoring database from %s", sql_path)

    with open(sql_path, "r") as fh:
        try:
            subprocess.run(
                cmd,
                stdin=fh,
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            logging.error("Restore failed: %s", e.stderr.strip())



class RequireAuthException(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=403, detail=detail)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    file_path = os.path.join("static", "favicon.ico")
    return FileResponse(file_path)


@app.exception_handler(AuthenticationRequiredException)
async def authentication_required_exception_handler(
    request: Request, exc: AuthenticationRequiredException
):
    return RedirectResponse(url="/login")


async def require_auth(request: Request):
    

    if os.environ.get("BLOOM_OAUTH", "yes") == "no":
        request.session["user_data"] = {"email": "john@daylilyinformatics.com", "dag_fnv2": ""}
        return request
    
    if (
        os.environ.get("SUPABASE_URL", "NA") == "NA"
        and os.environ.get("SUPABASE_KEY", "NA") == "NA"
    ):
        msg = "SUPABASE_* env variables not not set.  Is your .env file missing?"
        logging.error(msg)

        raise MissingSupabaseEnvVarsException(msg)

    if "user_data" not in request.session:
        raise AuthenticationRequiredException()
    return request.session["user_data"]


@app.exception_handler(RequireAuthException)
async def auth_exception_handler(_request: Request, _exc: RequireAuthException):
    # Redirect the user to the login page
    return RedirectResponse(url="/login")


#
#  The following are the mainpage / index and auth routes for the application
#



@app.get("/index2", response_class=HTMLResponse)
async def index2(request: Request, _=Depends(require_auth)):
    count = request.session.get("count", 0)
    count += 1
    request.session["count"] = count

    template = templates.get_template("index2.html")
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
    context = {"request": request, "style": style, "udat": user_data}

    return HTMLResponse(content=template.render(context), status_code=200)


@app.get("/", response_class=HTMLResponse)
async def read_root(
    request: Request,
):
    count = request.session.get("count", 0)
    count += 1
    request.session["count"] = count

    template = templates.get_template("index.html")
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
    context = {"request": request, "style": style, "udat": user_data}

    return HTMLResponse(content=template.render(context), status_code=200)


@app.get("/login", include_in_schema=False)
async def get_login_page(request: Request):

    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    # Ensure you have this function defined, and it returns the expected style information
    template = templates.get_template("login.html")
    # Pass the 'style' variable in the context
    context = {"request": request, "style": style, "udat": user_data, "supabase_url": os.getenv("SUPABASE_URL", "SUPABASE-URL-NOT-SET") } 
    return HTMLResponse(content=template.render(context))


@app.post("/oauth_callback")
async def oauth_callback(request: Request):
    body = await request.json()
    access_token = body.get("accessToken")

    if not access_token:
        return "No access token provided."
    # Attempt to decode the JWT to get email
    try:
        decoded_token = jwt.decode(access_token, options={"verify_signature": False})
        primary_email = decoded_token.get("email")
    except jwt.DecodeError:
        primary_email = None

    # Fetch user email from GitHub if not present in decoded token
    #if not primary_email:
    #    async with httpx.AsyncClient() as client:
    #        headers = {"Authorization": f"Bearer {access_token}"}
    #        response = await client.get(
    #            "https://api.github.com/user/emails", headers=headers
    #        )
    #        if response.status_code == 200:
    #            emails = response.json()
    #            primary_email = next(
    #                (email["email"] for email in emails if email.get("primary")), None
    #            )
    #        else:
    #            raise HTTPException(
    #                status_code=400, detail="Failed to retrieve user email from GitHub"
    #            )

    # Check if the email domain is allowed
    whitelist_domains = os.getenv("SUPABASE_WHITELIST_DOMAINS", "all")
    if len(whitelist_domains) == 0:
        whitelist_domains = "all"
    if whitelist_domains.lower() != "all":
        allowed_domains = [domain.strip() for domain in whitelist_domains.split(",")]
        user_domain = primary_email.split("@")[1]
        if user_domain not in allowed_domains:
            raise HTTPException(status_code=400, detail="Email domain not allowed")

    request.session["user_data"] = proc_udat(
        primary_email
    )  # {"email": primary_email, "style_css": "static/skins/bloom.css"}

    # Redirect to home page or dashboard
    return RedirectResponse(url="/", status_code=303)


@app.post("/login", include_in_schema=False)
async def login(request: Request, response: Response, email: str = Form(...)):
    # Use a static password for simplicity (not recommended for production)
    password = "notapplicable"
    # Initialize the Supabase client
    supabase = create_supabase_client()

    if not email:
        return JSONResponse(
            content={"message": "Email is required"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    with open(UDAT_FILE, "r+") as f:
        user_data = json.load(f)
        if email not in user_data:
            # The email is not in udat.json, attempt to sign up the user
            auth_response = supabase.auth.sign_up(
                {"email": email, "password": password}
            )
            if "error" in auth_response and auth_response["error"]:
                # Handle signup error
                return JSONResponse(
                    content={"message": auth_response["error"]["message"]},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            else:
                pass  # set below via proc_udat
        else:
            # The email exists in udat.json, attempt to sign in the user
            auth_response = supabase.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            if "error" in auth_response and auth_response["error"]:
                # Handle sign-in error
                return JSONResponse(
                    content={"message": auth_response["error"]["message"]},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

    # Set session cookie after successful authentication, with a 60-minute expiration
    response.set_cookie(
        key="session", value="user_session_token", httponly=True, max_age=3600, path="/"
    )
    request.session["user_data"] = proc_udat(email)
    # Redirect to the root path ("/") after successful login/signup
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    # Add this line at the end of the /login endpoint


@app.get(
    "/logout"
)  # Using a GET request for simplicity, but POST is more secure for logout operations
async def logout(request: Request, response: Response):
    
    try:
        logging.warning(f"Logging out user: Clearing session data:  {request.session}")

        # Initialize the Supabase client
        supabase = create_supabase_client()

        # Get the user's access token
        access_token = request.session.get("user_data", {}).get("access_token")
        if access_token:
            # Call the Supabase sign-out endpoint
            headers = {"Authorization": f"Bearer {access_token}"}
            async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
                logging.debug(f"Logging out user: Calling Supabase logout endpoint")
                logging.debug(f"Supabase URL: {os.environ.get('SUPABASE_URL')}")

                response = await client.post(
                    os.environ.get("SUPABASE_URL", "NA") + "/auth/v1/logout",
                    headers=headers,
                )
                logging.debug(f"Logging out user: Supabase logout response: {response}")
                if response.status_code != 204:
                    logging.error("Failed to log out from Supabase")

        # Clear the session data
        request.session.clear()

        response.delete_cookie("session", path="/")
        logging.info("User session cleared.")
        
        # Debug the session to ensure it's cleared
        logging.warning(f"Session after clearing: {request.session}")


    except Exception as e:
        logging.error(f"Error during logout: {e}")
        return JSONResponse(
            content={"message": "An error occurred during logout: " + str(e)},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Redirect to the homepage
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


#
#  The following are the main routes for the application
#


@app.get("/lims", response_class=HTMLResponse)
async def lims(request: Request, _=Depends(require_auth)):
    count = request.session.get("count", 0)
    count += 1
    request.session["count"] = count

    template = templates.get_template("lims_main.html")
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
    context = {"request": request, "style": style, "udat": user_data}

    return HTMLResponse(content=template.render(context), status_code=200)


@app.get("/assays", response_class=HTMLResponse)
async def assays(request: Request, show_type: str = "all", _auth=Depends(require_auth)):
    # Check if user is logged in
    if (
        "user_data" not in request.session
        or "email" not in request.session["user_data"]
    ):
        # If not logged in, redirect to the login page
        return RedirectResponse(url="/login")

    user_email = request.session["user_data"]["email"]
    user_data = request.session.get("user_data", {})

    # Initialize your database object with the user's email
    bobdb = BloomObj(BLOOMdb3(app_username=user_email))
    ay_ds = {}
    print("\n\n\nAAAAAAAA\n\n\n")
    for i in (
        bobdb.session.query(bobdb.Base.classes.workflow_instance)
        .filter_by(is_deleted=False, is_singleton=True)
        .all()
    ):
        if show_type == "all" or i.json_addl.get("assay_type", "all") == show_type:
            ay_ds[i.euid] = i

    print("\n\n\n\n\nBBBBBB\n\n\n\n")
    assays = []
    ay_dss = {}
    atype = {}

    if show_type == "assay":
        atype["type"] = "Assays"
    elif show_type == "accessioning":
        atype["type"] = "Accessioning"
    else:
        atype["type"] = "All Assays, etc"

    for i in sorted(ay_ds.keys()):
        assays.append(ay_ds[i])
        ay_dss[i] = {
            "Instantaneous COGS": 0
        }  # round(bobdb.get_cost_of_euid_children(i),2)}
        ay_dss[i]["tot"] = 0
        ay_dss[i]["tit_s"] = 0
        ay_dss[i]["tot_fx"] = 0

        for q in ay_ds[i].parent_of_lineages:
            if show_type == "accessioning":
                for fex_tup in bobdb.query_all_fedex_transit_times_by_ay_euid(
                    q.child_instance.euid
                ):
                    try:
                        ay_dss[i]["tit_s"] += float(fex_tup[1])
                        ay_dss[i]["tot_fx"] += 1
                    except Exception as e:
                        print(e)
            wset = ""
            n = q.child_instance.json_addl["properties"]["name"]
            if n.startswith("In"):
                wset = "inprog"
            elif n.startswith("Comple"):
                wset = "complete"
            elif n.startswith("Exception"):
                wset = "exception"
            elif n.startswith("Ready"):
                wset = "avail"
            lins = q.child_instance.parent_of_lineages.all()
            ay_dss[i][wset] = len(lins)
            lctr = 0
            lctr_max = 150
            for llin in lins:
                if lctr > lctr_max:
                    break
                else:
                    ay_dss[i]["Instantaneous COGS"] += round(
                        bobdb.get_cost_of_euid_children(llin.child_instance.euid), 2
                    )
                    ay_dss[i]["tot"] += 1
                lctr += 1

        try:
            ay_dss[i]["avg_d_fx"] = round(
                float(ay_dss[i]["tit_s"])
                / 60.0
                / 60.0
                / 24.0
                / float(ay_dss[i]["tot_fx"]),
                2,
            )
        except Exception as e:
            ay_dss[i]["avg_d_fx"] = "na"

        ay_dss[i]["conv"] = (
            round(
                float(ay_dss[i]["complete"])
                / float(ay_dss[i]["complete"] + ay_dss[i]["exception"]),
                2,
            )
            if ay_dss[i]["complete"] + ay_dss[i]["exception"] > 0
            else "na"
        )
        ay_dss[i]["wsetp"] = (
            round(float(ay_dss[i]["Instantaneous COGS"]) / float(ay_dss[i]["tot"]), 2)
            if ay_dss[i]["tot"] > 0
            else "na"
        )
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    # Rendering the template with the dynamic content
    content = templates.get_template("assay.html").render(
        style=style,
        user_logged_in=True,
        assays_data=ay_ds,
        atype=atype,
        workflow_instances=assays,  # Assuming this is needed based on your template logic
        ay_stats=ay_dss,  # Assuming this is needed based on your template logic
        udat=user_data,
    )

    return HTMLResponse(content=content)


@app.get("/calculate_cogs_children")
async def Acalculate_cogs_children(euid, request: Request, _auth=Depends(require_auth)):
    try:
        bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        cogs_value = round(bobdb.get_cost_of_euid_children(euid), 2)
        return json.dumps({"success": True, "cogs_value": cogs_value})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e)})

@app.post("/query_by_euids", response_class=HTMLResponse)
async def query_by_euids(request: Request, file_euids: str = Form(...)):
    try:
        bfi = BloomFile(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        euid_list = [euid.strip() for euid in file_euids.split("\n") if euid.strip()]

        detailed_results = [bfi.get_by_euid(euid) for euid in euid_list if euid]

        # Create a list of columns for the table
        columns = ["EUID", "Date Created", "Status"]
        if detailed_results and detailed_results[0].json_addl.get("properties"):
            columns += list(detailed_results[0].json_addl["properties"].keys())

        # Prepare the data for the template
        table_data = []
        for result in detailed_results:
            row = {
                "EUID": result.euid,
                "Date Created": result.created_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "Status": result.bstatus,
            }
            for key in columns[3:]:
                row[key] = result.json_addl["properties"].get(key, "N/A")
            table_data.append(row)

        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

        content = templates.get_template("search_results.html").render(
            request=request,
            columns=columns,
            table_data=table_data,
            style=style,
            udat=user_data,
        )
        return HTMLResponse(content=content)

    except Exception as e:
        logging.error(f"Error querying files: {e}", exc_info=True)
        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
        content = templates.get_template("search_error.html").render(
            request=request,
            error=f"An error occurred: {e}",
            style=style,
            udat=user_data,
        )
        return HTMLResponse(content=content)


async def calculate_cogs_parents(euid, request: Request, _auth=Depends(require_auth)):
    try:
        bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]))
        cogs_value = round(bobdb.get_cogs_to_produce_euid(euid), 2)
        return json.dumps({"success": True, "cogs_value": cogs_value})
    except Exception as e:
        return json.dumps({"success": False, "message": str(e)})


@app.get("/set_filter")
async def set_filter(request: Request, _auth=Depends(require_auth), curr_val="off"):
    if curr_val == "off":
        request.session["user_data"]["wf_filter"] = "on"
    else:
        request.session["user_data"]["wf_filter"] = "off"


@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request, _auth=Depends(require_auth), dest="na"):

    os.makedirs(os.path.dirname(UDAT_FILE), exist_ok=True)
    if not os.path.exists(UDAT_FILE):
        with open(UDAT_FILE, "w") as f:
            json.dump({}, f)

    dest_section = {"section": dest}

    user_data = request.session.get("user_data", {})

    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]), cfg_printers=True,cfg_fedex=True)

    # Mock or real printer_info data

    if "print_lab" in user_data:
        bobdb.get_lab_printers(user_data["print_lab"])

    csss = []
    for css in sorted(os.popen("ls -1 static/skins/*css").readlines()):
        csss.append(css.rstrip())

    printer_info = {
        "print_lab": bobdb.printer_labs,
        "printer_name": bobdb.site_printers,
        "label_zpl_style": bobdb.zpl_label_styles,
        "style_css": csss,
    }
    csss = [
        "static/skins/" + os.path.basename(css) for css in csss
    ]  # Get just the file names

    printer_info["style_css"] = csss

    backup_path = user_data.get("db_backup_path", "./db_backups")
    if os.path.isdir(backup_path):
        backup_files = sorted([p.name for p in Path(backup_path).glob("*.sql")], reverse=True)
    else:
        backup_files = []

    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    # Rendering the template with the dynamic content
    content = templates.get_template("admin.html").render(
        style=style,
        user_logged_in=True,
        user_data=user_data,
        printer_info=printer_info,
        dest_section=dest_section,
        backup_path=backup_path,
        backups=backup_files,
        udat=request.session["user_data"],
    )

    return HTMLResponse(content=content)


# Take a look at this later
@app.post("/update_preference")
async def update_preference(request: Request, auth: dict = Depends(require_auth)):
    # Early return if auth is None or doesn't contain 'email'
    if not auth or "email" not in auth:
        return {
            "status": "error",
            "message": "Authentication failed or user data missing",
        }

    data = await request.json()
    key = data.get("key")
    value = data.get("value")

    if not os.path.exists(UDAT_FILE):
        return {"status": "error", "message": "User data file not found"}

    with open(UDAT_FILE, "r") as f:
        user_data = json.load(f)

    email = request.session.get("user_data", {}).get("email")
    if email in user_data:
        user_data[email][key] = value
        with open(UDAT_FILE, "w") as f:
            json.dump(user_data, f)

        request.session["user_data"][key] = value
        return {"status": "success", "message": "User preference updated"}
    else:
        return {"status": "error", "message": "User not found in user data"}


@app.post("/db_backup")
async def db_backup(request: Request, _auth=Depends(require_auth)):
    backup_path = request.session["user_data"].get("db_backup_path", "./db_backups")
    os.makedirs(backup_path, exist_ok=True)
    outfile = Path(backup_path) / f"backup_{get_clean_timestamp()}.sql"
    async with db_lock:
        await asyncio.to_thread(pg_dump_file, outfile)
    return RedirectResponse(url="/admin?dest=backup", status_code=303)


@app.post("/db_restore")
async def db_restore(request: Request, filename: str = Form(...), _auth=Depends(require_auth)):
    backup_path = request.session["user_data"].get("db_backup_path", "./db_backups")
    target = Path(backup_path) / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    os.makedirs(backup_path, exist_ok=True)
    new_backup = Path(backup_path) / f"pre_restore_{get_clean_timestamp()}.sql"
    async with db_lock:
        await asyncio.to_thread(pg_dump_file, new_backup)
        try:
            await asyncio.to_thread(pg_restore_file, target)
        except Exception as e:
            logging.error("Restore error: %s", e)



@app.get("/queue_details", response_class=HTMLResponse)
async def queue_details(
    request: Request, queue_euid, page=1, _auth=Depends(require_auth)
):
    page = int(page)
    if page < 1:
        page = 1
    per_page = 500  # Items per page
    user_logged_in = True if "user_data" in request.session else False
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    queue = bobdb.get_by_euid(queue_euid)
    qm = []
    for i in queue.parent_of_lineages:
        qm.append(i.child_instance)
    queue_details = queue.sort_by_euid(qm)
    queue_details = queue_details[(page - 1) * per_page : page * per_page]
    pagination = {"next": page + 1, "prev": page - 1, "euid": queue_euid}
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("queue_details.html").render(
        style=style,
        queue=queue,
        queue_details=queue_details,
        pagination=pagination,
        user_logged_in=user_logged_in,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)


@app.post("/generic_templates")
async def generic_templates(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    the_templates = (
        bobdb.session.query(bobdb.Base.classes.generic_template)
        .filter_by(is_deleted=False)
        .all()
    )

    # Group templates by super_type
    grouped_templates = {}
    for temp in the_templates:
        if temp.super_type not in grouped_templates:
            grouped_templates[temp.super_type] = []
        grouped_templates[temp.super_type].append(temp)
    return HTMLResponse(grouped_templates)


@app.get("/workflow_summary", response_class=HTMLResponse)
async def workflow_summary(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    workflows = (
        bobdb.session.query(bobdb.Base.classes.workflow_instance)
        .filter_by(is_deleted=False)
        .all()
    )

    workflow_statistics = defaultdict(
        lambda: {
            "status_counts": defaultdict(int),
            "oldest": datetime.max.date(),
            "newest": datetime.min.date(),
        }
    )

    for wf in workflows:
        wf_type = wf.btype
        wf_status = wf.bstatus
        wf_created_dt = wf.created_dt.date()

        stats = workflow_statistics[wf_type]
        stats["status_counts"][wf_status] += 1
        stats["oldest"] = min(stats["oldest"], wf_created_dt)
        stats["newest"] = max(stats["newest"], wf_created_dt)

    workflow_statistics = {k: dict(v) for k, v in workflow_statistics.items()}
    unique_workflow_types = list(workflow_statistics.keys())

    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("workflow_summary.html").render(
        style=style,
        workflows=workflows,
        workflow_statistics=workflow_statistics,
        unique_workflow_types=unique_workflow_types,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)


@app.get("/update_object_name", response_class=HTMLResponse)
async def update_object_name(request: Request, euid, name, _auth=Depends(require_auth)):
    referer = request.headers.get("Referer", "/")
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    obj = bobdb.get_by_euid(euid)
    if obj:
        obj.name = name  # Update the name
        flag_modified(obj, "name")  # Explicitly mark the object as modified
        bobdb.session.commit()  # Commit the changes to the database
    # Return a RedirectResponse to redirect the user
    return RedirectResponse(url=referer, status_code=303)


@app.get("/equipment_overview", response_class=HTMLResponse)
async def equipment_overview(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    # Fetch equipment instances and templates
    equipment_instances = (
        bobdb.session.query(bobdb.Base.classes.equipment_instance)
        .filter_by(is_deleted=False)
        .all()
    )
    equipment_templates = (
        bobdb.session.query(bobdb.Base.classes.equipment_template)
        .filter_by(is_deleted=False)
        .all()
    )
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("equipment_overview.html").render(
        style=style,
        equipment_list=equipment_instances,
        template_list=equipment_templates,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)


async def get_print_labs(_request: Request, _auth=Depends(require_auth)):
    # Replace the following line with the actual logic to retrieve your data
    options = [
        {"value": "option1", "text": "Option 1"},
        {"value": "option2", "text": "Option 2"},
        {"value": "option3", "text": "Option 3"},
        # Add more options as needed
    ]
    return options


@app.get("/reagent_overview", response_class=HTMLResponse)
async def reagent_overview(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    # Fetch equipment instances and templates
    reagent_instances = (
        bobdb.session.query(bobdb.Base.classes.content_instance)
        .filter_by(is_deleted=False, btype="reagent")
        .all()
    )
    reagent_templates = (
        bobdb.session.query(bobdb.Base.classes.content_template)
        .filter_by(is_deleted=False, btype="reagent")
        .all()
    )
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("reagent_overview.html").render(
        style=style,
        instance_list=reagent_instances,
        template_list=reagent_templates,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)


@app.get("/control_overview", response_class=HTMLResponse)
async def control_overview(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    # Fetch equipment instances and templates
    control_instances = (
        bobdb.session.query(bobdb.Base.classes.content_instance)
        .filter_by(is_deleted=False, btype="control")
        .all()
    )
    control_templates = (
        bobdb.session.query(bobdb.Base.classes.content_template)
        .filter_by(is_deleted=False, btype="control")
        .all()
    )
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("control_overview.html").render(
        style=style,
        instance_list=control_instances,
        template_list=control_templates,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)


@app.post("/create_from_template", response_class=HTMLResponse)
@app.get("/create_from_template", response_class=HTMLResponse)
async def create_from_template(
    request: Request, euid: str = None, _auth=Depends(require_auth)
):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    template = bobdb.create_instances(euid)

    if template:
        return RedirectResponse(
            url=f"/euid_details?euid={template[0][0].euid}", status_code=303
        )
    else:
        return RedirectResponse(url="/equipment_overview", status_code=303)


@app.get("/uuid_details", response_class=HTMLResponse)
async def uuid_details(request: Request, uuid: str, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    obj = bobdb.get(uuid)
    return RedirectResponse(url=f"/euid_details?euid={obj.euid}")


@app.get("/vertical_exp", response_class=HTMLResponse)
async def vertical_exp(request: Request, euid=None, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    instance = bobdb.get_by_euid(euid)
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("vertical_exp.html").render(
        style=style, instance=instance, udat=request.session["user_data"]
    )
    return HTMLResponse(content=content)


@app.get("/plate_carosel2", response_class=HTMLResponse)
async def plate_carosel(
    request: Request, plate_euid: str = Query(...), _auth=Depends(require_auth)
):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    # Fetch the main plate and its wells
    main_plate = bobdb.get_by_euid(plate_euid)
    oplt = bobdb.get_by_euid("CX42")
    if not main_plate:
        return "Main plate not found."

    # Example logic to fetch related plates (modify based on your data model)
    related_plates = await get_related_plates(main_plate)
    related_plates.append(main_plate)
    # Render the template with the main plate and related plates data
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("vertical_exp.html").render(
        style=style,
        main_plate=main_plate,
        related_plates=related_plates,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)


@app.get("/get_related_plates", response_class=HTMLResponse)
async def get_related_plates(request: Request, main_plate, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    related_plates = []

    # Fetching ancestor plates through parent_of_lineages
    for parent_lineage in main_plate.parent_of_lineages:
        if parent_lineage.child_instance.btype == "plate":
            related_plates.append(parent_lineage.child_instance)

    # Fetching descendant plates through child_of_lineages
    for child_lineage in main_plate.child_of_lineages:
        if child_lineage.parent_instance.btype == "plate":
            related_plates.append(child_lineage.parent_instance)

    # Remove duplicates from the related_plates list
    related_plates = list({plate.euid: plate for plate in related_plates}.values())

    # Additional logic to calculate rows and columns for each related plate
    for plate in related_plates:
        num_rows = 0
        num_cols = 0
        for lineage in plate.parent_of_lineages:
            if (
                lineage.parent_instance.euid == plate.euid
                and lineage.child_instance.btype == "well"
            ):
                cd = lineage.child_instance.json_addl.get("cont_address", {})
                num_rows = max(num_rows, int(cd.get("row_idx", 0)))
                num_cols = max(num_cols, int(cd.get("col_idx", 0)))
        plate.json_addl["properties"]["num_rows"] = num_rows + 1
        plate.json_addl["properties"]["num_cols"] = num_cols + 1
        flag_modified(plate, "json_addl")

    return related_plates


@app.get("/plate_visualization", response_class=HTMLResponse)
async def plate_visualization(
    request: Request, plate_euid, _auth=Depends(require_auth)
):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    # Fetch the plate and its wells
    plate = bobdb.get_by_euid(plate_euid)

    num_rows = 0
    num_cols = 0

    for i in plate.parent_of_lineages:
        if i.parent_instance.euid == plate.euid and i.child_instance.btype == "well":
            cd = i.child_instance.json_addl["cont_address"]
            if int(cd["row_idx"]) > num_rows:
                num_rows = int(cd["row_idx"])
            if int(cd["col_idx"]) > num_cols:
                num_cols = int(cd["col_idx"])
    plate.json_addl["properties"]["num_rows"] = num_rows + 1
    plate.json_addl["properties"]["num_cols"] = num_cols + 1
    flag_modified(plate, "json_addl")
    bobdb.session.commit()
    if not plate:
        return "Plate not found."
        # Render the template with the plate data
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("plate_display.html").render(
        style=style,
        plate=plate,
        get_well_color=get_well_color,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)

    # What is the correct path for {style.skin.css}?


@app.get("/database_statistics", response_class=HTMLResponse)
async def database_statistics(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    async def get_stats(days):
        cutoff_date = datetime.now() - timedelta(days=days)
        # Assume bobdb.session.query can be awaited; if not, adjust accordingly
        return (
            await bobdb.session.query(
                bobdb.Base.classes.generic_instance.b_sub_type,
                func.count(bobdb.Base.classes.generic_instance.uuid),
            )
            .filter(
                bobdb.Base.classes.generic_instance.created_dt >= cutoff_date,
                bobdb.Base.classes.generic_instance.is_deleted == False,
            )
            .group_by(bobdb.Base.classes.generic_instance.b_sub_type)
            .all()
        )

    stats_1d = await get_stats(1)
    stats_7d = await get_stats(7)
    stats_30d = await get_stats(30)

    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("database_statistics.html").render(
        request=request,
        stats_1d=stats_1d,
        stats_7d=stats_7d,
        stats_30d=stats_30d,
        style=style,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)

@app.post("/save_json_addl_key")
async def save_json_addl_key(request: Request):
    try:
        # Extract JSON data from the request
        data = await request.json()
        euid = data.get("euid")
        json_addl_key = data.get('json_addl_key')        
        json_data = data.get("json_data")

        if not euid or not json_addl_key or not json_data:
            logging.error("EUID, JSON key, or JSON data missing")
            raise HTTPException(status_code=400, detail="EUID, JSON key, or JSON data missing")


        bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        obj = bobdb.get_by_euid(euid)

        if not obj:
            raise HTTPException(status_code=404, detail="Object not found")

        # Update the json_addl['properties']
        obj.json_addl[json_addl_key] = json_data
        flag_modified(obj, "json_addl")
        bobdb.session.commit()

        # Redirect to euid_details page
        return RedirectResponse(url=f"/euid_details?euid={euid}", status_code=303)

    except Exception as e:
        logging.error(f"Error saving JSON properties: {e}")
        raise HTTPException(status_code=500, detail="An error occurred while saving JSON properties")


@app.get("/object_templates_summary", response_class=HTMLResponse)
async def object_templates_summary(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    # Fetch all generic templates
    generic_templates = (
        bobdb.session.query(bobdb.Base.classes.generic_template)
        .filter_by(is_deleted=False)
        .all()
    )

    # Get unique polymorphic_discriminators
    unique_discriminators = sorted(
        set(t.polymorphic_discriminator for t in generic_templates)
    )
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("object_templates_summary.html").render(
        request=request,
        generic_templates=generic_templates,
        unique_discriminators=unique_discriminators,
        style=style,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)

# Quick hack to allow the details page to display deleted items.  Need to rework how the rest of the system juggles this.
@app.get("/euid_details")
async def euid_details(
    request: Request,
    euid: str = Query(..., description="The EUID to fetch details for"),
    _uuid: str = Query(None, description="Optional UUID parameter"),
    is_deleted: bool = Query(False, description="Flag to include deleted items"),
    _auth=Depends(require_auth),
):
    bobdb = BloomObj(
        BLOOMdb3(app_username=request.session["user_data"]["email"]),
        is_deleted=is_deleted,
    )

    try:
    
        # Fetch the object using euid
        obj = bobdb.get_by_euid(euid)
        relationship_data =  get_relationship_data(obj) if obj else {}

        if not obj:
            raise HTTPException(status_code=404, detail="Object not found")

        # Convert the SQLAlchemy object to a dictionary, checking for attribute existence
        obj_dict = {
            column.key: getattr(obj, column.key)
            for column in obj.__table__.columns
            if hasattr(obj, column.key)
        }
        obj_dict["parent_template_euid"] = obj.parent_template.euid if hasattr(obj, "parent_template") else ""  
        audit_logs = bobdb.query_audit_log_by_euid(euid)
        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

        content = templates.get_template("euid_details.html").render(
            request=request,
            object=obj_dict,
            jaddl_prop=obj.json_addl.get("properties", {}),
            jaddl_controlled_prop=obj.json_addl.get("controlled_properties", {}),
            style=style,
            relationships=relationship_data,
            audit_logs=audit_logs,
            oobj=obj,
            udat=request.session["user_data"],
        )
        return HTMLResponse(content=content)

    except Exception as e:
        #if not is_deleted:
        #    # Retry with is_deleted set to True
        #    return await euid_details(
        #        request=request,
        #        euid=euid,
        #        _uuid=_uuid,
        #        is_deleted=True,
        #        _auth=_auth,
        #    )
        #else:
        raise e


@app.get("/un_delete_by_uuid")
async def un_delete_by_uuid(
    request: Request,
    uuid: str = Query(..., description="The UUID to un-delete"),
    euid: str = Query(..., description="The EUID associated with the UUID"),
    _auth=Depends(require_auth),
    is_deleted: bool = True,
):
    try:
        bobdb = BloomObj(
            BLOOMdb3(app_username=request.session["user_data"]["email"]),
            is_deleted=is_deleted,
        )

        # Fetch the object using uuid
        obj = bobdb.get(uuid)
        if not obj:
            raise HTTPException(status_code=404, detail="Object not found")

        # Set the object to not deleted
        obj.is_deleted = False
        bobdb.session.commit()

        logging.info(
            f"Successfully un-deleted object with UUID: {uuid} and EUID: {euid}"
        )
        return RedirectResponse(url=f"/euid_details?euid={euid}", status_code=303)

    except Exception as e:
        logging.error(
            f"Error un-deleting object with UUID: {uuid} and EUID: {euid} - {e}",
            exc_info=True,
        )
        if is_deleted:
            try:
                logging.info(
                    f"Retrying with is_deleted=True for UUID: {uuid} and EUID: {euid}"
                )
                return await un_delete_by_uuid(
                    request, uuid, euid, _auth, is_deleted=False
                )
            except Exception as inner_e:
                logging.error(
                    f"Retry failed for UUID: {uuid} and EUID: {euid} - {inner_e}",
                    exc_info=True,
                )
                raise HTTPException(
                    status_code=404, detail="Object not found after retry"
                )
        else:
            raise HTTPException(status_code=404, detail="Object not found")


@app.get("/bloom_schema_report", response_class=HTMLResponse)
async def bloom_schema_report(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    a_stat = bobdb.query_generic_instance_and_lin_stats()
    b_stats = bobdb.query_generic_template_stats()
    reports = [[a_stat[0]], [a_stat[1]], b_stats]
    nrows = 0
    for i in b_stats:
        nrows += int(i["Total_Templates"])
    for ii in a_stat:
        nrows += int(ii["Total_Instances"])

    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("bloom_schema_report.html").render(
        request=request,
        reports=reports,
        nrows=nrows,
        style=style,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)


@app.get("/delete_by_euid", response_class=HTMLResponse)
def delete_by_euid(request: Request, euid, _auth=Depends(require_auth)):
    referer = request.headers.get("Referer", "/")

    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    bobdb.delete(bobdb.get_by_euid(euid))
    bobdb.session.flush()
    bobdb.session.commit()

    return RedirectResponse(url=referer, status_code=303)


@app.post("/delete_object")
async def delete_object(request: Request, _auth=Depends(require_auth)):
    data = await request.json()
    euid = data.get("euid")
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    bobdb.delete(bobdb.get_by_euid(euid))
    bobdb.session.flush()
    bobdb.session.commit()
    return {
        "status": "success",
        "message": f"Delete object performed for EUID {euid}",
    }


@app.get("/workflow_details", response_class=HTMLResponse)
async def workflow_details(
    request: Request, workflow_euid, _auth=Depends(require_auth)
):
    bwfdb = BloomWorkflow(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    workflow = bwfdb.get_sorted_euid(workflow_euid)
    accordion_states = dict(request.session)
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("workflow_details.html").render(
        request=request,
        workflow=workflow,
        accordion_states=accordion_states,
        style=style,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)


@app.post("/update_accordion_state")
async def update_accordion_state(request: Request, _auth=Depends(require_auth)):
    data = await request.json()
    step_euid = data["step_euid"]
    state = data[
        "state"
    ]  # Assuming 'state' is either 'open' or some other value indicating the accordion's state
    request.session[step_euid] = state
    return {"status": "success"}


@app.post("/workflow_step_action")
async def workflow_step_action(request: Request, _auth=Depends(require_auth)):
    data = await request.json()
    euid = data.get("euid")
    action = data.get("action")
    action_group = data.get("action_group")
    ds = data.get("ds")
    bobdb = BloomWorkflow(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    bo = bobdb.get_by_euid(euid)

    ds["curr_user"] = request.session.get("user_data", "bloomui-user")
    udat = request.session.get("user_data", {})
    ds["lab"] = udat.get("print_lab", "BLOOM")
    ds["printer_name"] = udat.get("printer_name", "")
    ds["label_zpl_style"] = udat.get("label_style", "")
    ds["alt_a"] = udat.get("alt_a", "")
    ds["alt_b"] = udat.get("alt_b", "")
    ds["alt_c"] = udat.get(
        "alt_c",
    )
    ds["alt_d"] = udat.get("alt_d", "")
    ds["alt_e"] = udat.get("alt_e", "")

    if bo.__class__.__name__ == "workflow_instance":
        bwfdb = BloomWorkflow(
            BLOOMdb3(app_username=request.session["user_data"]["email"])
        )
        act = bwfdb.do_action(
            euid, action_ds=ds, action=action, action_group=action_group
        )
    else:
        bwfsdb = BloomWorkflowStep(
            BLOOMdb3(app_username=request.session["user_data"]["email"])
        )
        act = bwfsdb.do_action(
            euid, action_ds=ds, action=action, action_group=action_group
        )

    return {"status": "success", "message": f" {action} performed for EUID {euid}"}


@app.post("/update_obj_json_addl_properties", response_class=HTMLResponse)
async def update_obj_json_addl_properties(
    request: Request,
    obj_euid: str = Form(None),
    _auth=Depends(require_auth),
):
    """Update the json_addl['properties'] field of an object.  Was originally for just wfs...

    Args:
        obj_euid euid(): OBJECT.euid being edited

    Raises:
        Exception: Cherrypy redirect back to referring page
        cherrypy.HTTPRedirect: _description_

    Returns:
        cherrypy.HTTPRedirect: to referrer
    """

    referer = request.headers.get("Referer", "/default_page")

    # Parse form data manually
    form = await request.form()
    properties = {key: value for key, value in form.items() if key != "obj_euid"}

    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    step = bobdb.get_by_euid(obj_euid)

    if step is None:
        print("Step not found")
        return False

    try:
        for key, values in properties.items():
            if key in step.json_addl["properties"]:
                if isinstance(step.json_addl["properties"][key], list):
                    step.json_addl["properties"][key] = (
                        values if isinstance(values, list) else [values]
                    )
                else:
                    step.json_addl["properties"][key] = values
            if key.endswith("[]"):
                key = key[:-2]
                if key in step.json_addl["properties"]:
                    step.json_addl["properties"][key] = (
                        values if isinstance(values, list) else [values]
                    )
                else:
                    step.json_addl["properties"][key] = values

        # Explicitly mark the object as modified if necessary
        flag_modified(step, "json_addl")

        bobdb.session.flush()
        bobdb.session.commit()
        # Optionally, reload the object to confirm changes
        bobdb.session.refresh(step)

    except Exception as e:
        raise Exception("Error updating step properties:", e)

    return RedirectResponse(url=referer, status_code=303)


@app.get("/dagg", response_class=HTMLResponse)
async def dagg(request: Request):
    content = templates.get_template("dag.html").render()
    return HTMLResponse(content=content)


@app.get("/dindex2", response_class=HTMLResponse)
async def dindex2(
    request: Request,
    globalFilterLevel=6,
    globalZoom=0,
    globalStartNodeEUID=None,
    auth=Depends(require_auth),
):
    dag_data = generate_dag_json_from_all_objects_v2(
        request=request, euid=globalStartNodeEUID, depth=globalFilterLevel
    )
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("dindex2.html").render(
        request=request,
        style=style,
        globalFilterLevel=globalFilterLevel,
        globalZoom=globalZoom,
        globalStartNodeEUID=globalStartNodeEUID,
        dag_data=dag_data,
        udat=request.session["user_data"],
    )
    return HTMLResponse(content=content)


def add_new_node(request: Request, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

    new_ci = bobdb.Base.classes.container_instance(name="newthing")
    bobdb.session.add(new_ci)
    bobdb.session.commit()
    return {"euid": new_ci.euid}


@app.get("/get_node_info")
async def get_node_info(request: Request, euid, _auth=Depends(require_auth)):
    bobj = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    node_dat = bobj.get_by_euid(euid)

    if node_dat:
        return {
            "uuid": str(node_dat.uuid),
            "name": node_dat.name,
            "btype": node_dat.btype,
            "euid": node_dat.euid,
            "b_sub_type": node_dat.b_sub_type,
            "status": node_dat.bstatus,
            "json_addl": json.dumps(node_dat.json_addl),
        }
    else:
        return {"error": "Node not found"}

@app.get("/user_audit_logs", response_class=HTMLResponse)
async def user_audit_logs(request: Request, username: str, _auth=Depends(require_auth)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    results = bobdb.query_user_audit_logs(username)
    
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
    
    content = templates.get_template("audit_log_by_user.html").render(
        results=results, username=username, style=style, udat=user_data, request=request, highlight_json_changes=highlight_json_changes

    )
    
    return HTMLResponse(content=content)

@app.get("/user_home", response_class=HTMLResponse)
async def user_home(request: Request):

    user_data = request.session.get("user_data", {})
    session_data = request.session.get("session_data", {})  # Extract session_data from session


    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]), cfg_printers=True,cfg_fedex=True)

    if not user_data:
        return RedirectResponse(url="/login")

    # Directory containing the CSS files
    skins_directory = "static/skins"
    css_files = [f"{skins_directory}/{file}" for file in os.listdir(skins_directory) if file.endswith(".css")]

    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
    dest_section = request.query_params.get("dest_section", {"section": ""})  # Example value

    if "print_lab" in user_data:
        bobdb.get_lab_printers(user_data["print_lab"])
        
    printer_info = {
        "print_lab": bobdb.printer_labs,
        "printer_name": bobdb.site_printers,
        "label_zpl_style": bobdb.zpl_label_styles,
        "style_css": css_files,
    }


    # Fetching version details
    github_tag = subprocess.check_output(["git", "describe", "--tags"]).decode().strip()
    setup_py_version = subprocess.check_output(["python", "setup.py", "--version"]).decode().strip()
    fedex_version = os.popen("pip freeze | grep fedex_tracking_day | cut -d = -f 3").readline().rstrip()  
    zebra_printer_version = os.popen("pip freeze | grep zebra-day | cut -d = -f 3").readline().rstrip()  

    # HARDCODED THE BUCKET PREFIX INT to 0 here and elsewhere using the same pattern.  Reconsider the zero detection (and prob remove it)
    content = templates.get_template("user_home.html").render(
        request=request,
        user_data=user_data,
        session_data=session_data,  # Pass session_data to template
        css_files=css_files,
        style=style,
        dest_section=dest_section,
        whitelisted_domains=" , ".join(os.environ.get("SUPABASE_WHITELIST_DOMAINS", "all").split(",")), 
        s3_bucket_prefix=os.environ.get("BLOOM_DEWEY_S3_BUCKET_PREFIX", "NEEDS TO BE SET!")+"0",
        supabase_url=os.environ.get("SUPABASE_URL", "NEEDS TO BE SET!"),
        printer_info=printer_info,
        github_tag=github_tag,
        setup_py_version=setup_py_version,
        fedex_version=fedex_version,
        zebra_printer_version=zebra_printer_version,
        udat=user_data
    )
    return HTMLResponse(content=content)


def generate_dag_json_from_all_objects_v2(
    request: Request, euid="AY1", depth=6, _auth=Depends(require_auth)
):
    # Default values and setup
    if euid in [None, "", "None"]:
        euid = "AY1"

    bobj = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    last_schema_edit_dt = bobj.get_most_recent_schema_audit_log_entry()

    # Simplify file naming and ensure directory exists
    user_email_sanitized = (
        request.session["user_data"]["email"].replace("@", "_").replace(".", "_")
    )
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    output_dir = "./dags"
    os.makedirs(output_dir, exist_ok=True)  # Ensure the directory exists
    output_file = os.path.join(
        output_dir, f"dag_{user_email_sanitized}_{depth}_{timestamp}_dagv2.json"
    )

    # Check if DAG needs to be regenerated
    schema_mod_dt = request.session.get("schema_mod_dt")
    if (
        schema_mod_dt != last_schema_edit_dt.changed_at.isoformat()
        or not os.path.exists(output_file)
    ):
        print(
            f"Dag WILL BE Regenerated, Schema Has Changed. {output_file} being generated."
        )
    else:
        print(f"Dag Not Regenerated, Schema Has Not Changed. {output_file} unchanged.")
        return

    request.session["schema_mod_dt"] = last_schema_edit_dt.changed_at.isoformat()
    request.session["user_data"]["dag_fnv2"] = output_file

    colors = {
        "container": "#8B00FF",  # Electric Purple
        "content": "#00BFFF",  # Deep Sky Blue
        "workflow": "#00FF7F",  # Spring Green
        "workflow_step": "#ADFF2F",  # Green Yellow
        "equipment": "#FF4500",  # Orange Red
        "object_set": "#FF6347",  # Tomato
        "actor": "#FFD700",  # Gold
        "test_requisition": "#FFA500",  # Orange
        "data": "#FFFF00",  # Yellow
        "generic": "#FF1493",  # Deep Pink
        "action": "#FF8C00",  # Dark Orange
        "file": "#00FF00",  # Lime
    }

    sub_colors = {
        "well": "#70658c",
        "file_set": "#228080",
        "generic": "#008080",
    }

    edge_relationship_type_colors = {"generic": "#ADD8E6", "index": "#4CAF50"}

    # instance_result = []
    instance_result = {}
    lineage_result = {}

    for r in bobj.fetch_graph_data_by_node_depth(euid, depth):
        if r[0] in [None, "", "None"]:
            pass
        else:

            instance = {
                "euid": r[0],
                "name": r[2],
                "btype": r[3],
                "super_type": r[4],
                "b_sub_type": r[5],
                "version": r[6],
            }
            instance_result[r[0]] = instance

            if r[8] in [None, "", "None"]:
                pass
            else:
                lin_edge = {
                    "parent_euid": r[9],
                    "child_euid": r[10],
                    "lineage_euid": r[8],
                    "relationship_type": r[11],
                }
                lineage_result[r[8]] = lin_edge

    # Construct nodes and edges
    nodes = []
    edges = []

    for instance_k in instance_result:
        instance = instance_result[instance_k]
        node = {
            "data": {
                "id": str(instance["euid"]),
                "type": "instance",
                "euid": str(instance["euid"]),
                "name": instance["name"],
                "btype": instance["btype"],
                "super_type": instance["super_type"],
                "b_sub_type": instance["super_type"]
                + "."
                + instance["btype"]
                + "."
                + instance["b_sub_type"],
                "version": instance["version"],
                "color": (
                    colors.get(instance["super_type"], "pink")
                    if instance["btype"] not in ["well", "file_set"]
                    else sub_colors.get(instance["b_sub_type"], "white")
                ),
            }
        }
        nodes.append(node)

    for l_i in lineage_result:
        lineage = lineage_result[l_i]

        edge = {
            "data": {
                "source": str(lineage["parent_euid"]),
                "target": str(lineage["child_euid"]),
                "id": str(lineage["lineage_euid"]),
                "relationship_type": str(lineage["relationship_type"]),
                "color": edge_relationship_type_colors.get(
                    lineage["relationship_type"], "lightgreen"
                ),
            }
        }
        edges.append(edge)

    # Construct JSON structure

    dag_json = {"elements": {"nodes": nodes, "edges": edges}}

    # Write to file
    with open(output_file, "w") as f:
        json.dump(dag_json, f, indent=4)

    print(f"All DAG JSON saved to {output_file}")


def get_dag(request: Request, _auth=Depends(require_auth)):
    dag_fn = request.session["user_data"]["dag_fn"]
    dag_data = {"elements": {"nodes": [], "edges": []}}
    if os.path.exists(dag_fn):
        with open(dag_fn, "r") as f:
            dag_data = json.load(f)
    return dag_data


@app.get("/get_dagv2")
async def get_dagv2(
    request: Request, _euid="AY1", _depth=6, _auth=Depends(require_auth)
):
    dag_fn = request.session["user_data"]["dag_fnv2"]
    # dag_fn = "./dags/j.json"
    dag_data = {"elements": {"nodes": [], "edges": []}}
    if os.path.exists(dag_fn):
        with open(dag_fn, "r") as f:
            dag_data = json.load(f)
    return dag_data


@app.post("/update_dag")
async def update_dag(request: Request, _auth=Depends(require_auth)):
    input_json = await request.json()  # Corrected call to request.json()
    filename = f"dag_{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
    with open(filename, "w") as f:
        json.dump(input_json, f)
    return {"status": "success", "filename": filename}


@app.post("/add_new_edge")
async def add_new_edge(request: Request, _auth=Depends(require_auth)):
    input_data = await request.json()  # Corrected call to request.json()
    parent_euid = input_data["parent_uuid"]
    child_euid = input_data["child_uuid"]
    bobj = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    # Assuming the method returns the new edge object, you might need to adjust this part
    new_edge = bobj.create_generic_instance_lineage_by_euids(parent_euid, child_euid)
    bobj.session.flush()
    bobj.session.commit()
    return {"euid": str(new_edge.euid)}


@app.post("/delete_node")
async def delete_node(request: Request, _auth=Depends(require_auth)):
    input_data = await request.json()
    node_euid = input_data["euid"]
    bobj = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    bobj.delete(euid=node_euid)
    bobj.session.flush()
    bobj.session.commit()

    return {
        "status": "success",
        "message": "Node and associated lineage records deleted successfully.",
    }


@app.post("/delete_edge")
async def delete_edge(request: Request, _auth=Depends(require_auth)):
    input_data = await request.json()
    edge_euid = input_data["euid"]

    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    bobdb.delete(bobdb.get_by_euid(edge_euid))
    bobdb.session.flush()
    bobdb.session.commit()

    return {"status": "success", "message": "Edge deleted successfully."}


## File Manager // Dewey (pull into separate file   )


def generate_unique_upload_key():
    """Return a datestamp for default file set names.

    The datestamp format follows ``YYYYMMDDTHHMMSS`` as required when a
    file set name isn't explicitly provided.
    """
    return datetime.utcnow().strftime("%Y%m%dT%H%M%S")



@app.get("/dewey", response_class=HTMLResponse)
async def dewey(request: Request, _auth=Depends(require_auth)):
    request.session.pop("form_data", None)

    accordion_states = dict(request.session)
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
    upload_group_key = generate_unique_upload_key()

    # Fetch template data for dynamic fields    
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    
    f_templates = bobdb.query_template_by_component_v2("file","file","generic","1.0")
    fset_templates = bobdb.query_template_by_component_v2("file","file_set","generic","1.0")
 
    # these should only be 1
    if len(f_templates) > 1:
        logging.error(f"Multiple file templates found for file/file/generic/1.0")
        raise HTTPException(status_code=500, detail="Multiple file templates found for file/file/generic/1.0")
    if len(fset_templates) > 1:
        logging.error(f"Multiple file set templates found for file/file_set/generic/1.0")
        raise HTTPException(status_code=500, detail="Multiple file set templates found for file/file_set/generic/1.0")
    
    f_template = f_templates[0]
    ui_form_properties = f_template.json_addl.get("ui_form_properties", [])
    ui_form_fields = generate_ui_form_fields(ui_form_properties, f_template.json_addl.get("controlled_properties", {}),  bobject=bobdb)
    ui_form_fields_query = generate_ui_form_fields(ui_form_properties, f_template.json_addl.get("controlled_properties", {}),  bobject=bobdb, form_type="query", super_type="file", btype="file", version=None)

    
    fset_template = fset_templates[0]
    ui_form_properties_fset = fset_template.json_addl.get("ui_form_properties", [])
    ui_form_fields_fset = generate_ui_form_fields(ui_form_properties_fset, fset_template.json_addl.get("controlled_properties", {}),  bobject=bobdb)
    ui_form_fields_query_fset = generate_ui_form_fields(ui_form_properties_fset, fset_template.json_addl.get("controlled_properties", {}),  bobject=bobdb, form_type="query", super_type="file", btype="file_set", version=None)


    content = templates.get_template("dewey.html").render(
        request=request,
        accordion_states=accordion_states,
        style=style,
        upload_group_key=upload_group_key,
        udat=user_data,
        ui_fields=ui_form_fields,
        ui_search_fields=ui_form_fields_query,
        controlled_properties=f_template.json_addl.get("controlled_properties", {}),
        has_ui_form_properties=bool(ui_form_properties),
        searchable_properties=sorted(f_template.json_addl['properties'].keys()),   
        s3_bucket_prefix=os.environ.get("BLOOM_DEWEY_S3_BUCKET_PREFIX", "NEEDS TO BE SET!")+"0",
        ui_fields_fset=ui_form_fields_fset,
        ui_search_fields_fset=ui_form_fields_query_fset,
    )

    return HTMLResponse(content=content)



@app.get("/bulk_create_files", response_class=HTMLResponse)
async def bulk_create_files(request: Request, _auth=Depends(require_auth)):
    request.session.pop("form_data", None)

    accordion_states = dict(request.session)
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

    content = templates.get_template("bulk_create_files.html").render(
        request=request,
        accordion_states=accordion_states,
        style=style,
        udat=user_data,
        page_title="Bulk Create Files",
    )

    return HTMLResponse(content=content)


@app.get("/dewey0_DELETEME", response_class=HTMLResponse)
async def dewey0(request: Request, _auth=Depends(require_auth)):
    request.session.pop("form_data", None)

    accordion_states = dict(request.session)
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
    upload_group_key = generate_unique_upload_key()
    content = templates.get_template("dewey.html").render(
        request=request,
        accordion_states=accordion_states,
        style=style,
        upload_group_key=upload_group_key,
        udat=user_data,
    )

    return HTMLResponse(content=content)


@app.post("/create_file")
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
    controlled_properties = {}  # Or fetch from relevant source

    file_set_name = upload_group_key_ifnone if upload_group_key in [None,'None',""] else upload_group_key 

    if directory and len(directory) > 1000:
        return JSONResponse(
            status_code=400,
            content={"detail": "Too many files. Maximum number of files is 1000."},
        )
        raise
    
    try:
     
        # Creating a file set to tag all the files uploaded in the same batch together.
        bfs = BloomFileSet(BLOOMdb3(app_username=request.session.get("user_data",{}).get("email","na")))
        file_set_metadata = {
            "name": file_set_name,
            "description": "File set created by Dewey file manager",
            "tag": "on-create",
            "comments": "",
        }
        # Create the file set
        new_file_set = bfs.create_file_set(file_set_metadata=file_set_metadata)
        
        bfi = BloomFile(BLOOMdb3(app_username=request.session.get("user_data",{}).get("email","na")))
        file_metadata = {
            "name": name,
            "comments": comments,
            "lab_code": lab_code,
            "clinician_id": clinician_id,
            "health_event_id": health_event_id,
            "record_datetime": record_datetime,
            "record_datetime_end": record_datetime_end,
            "patient_id": patient_id,
            "creating_user": request.session.get("user_data",{}).get("email","na"),
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
                if file.filename:  # Ensure that there is a valid filename
                    try:
                        local_meta = dict(file_metadata)
                        local_meta["import_or_remote"] = "Import"
                        new_file = bfi.create_file(
                            file_metadata=local_meta,
                            file_data=file.file,
                            file_name=file.filename,
                            addl_tags=addl_tags,
                        )
                        results.append(
                            {
                                "identifier": new_file.euid,
                                "status": "Success",
                                "original": file.filename if file else url,
                                "current_s3_uri": new_file.json_addl["properties"][
                                    "current_s3_uri"
                                ],
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
                else:
                    logging.warning(f"Skipping file with no filename: {file}")

        if directory:
            directory_files = [
                file for file in directory if not file.filename.startswith(".")
            ]

            for file in directory_files:

                if (
                    len(file.filename) > 0
                    and len(file.filename.lstrip(".").lstrip("/").split("/")) < 3
                ):
                    try:
                        local_meta = dict(file_metadata)
                        local_meta["import_or_remote"] = "Import"
                        new_file = bfi.create_file(
                            file_metadata=local_meta,
                            file_data=file.file,
                            file_name=file.filename,
                            addl_tags=addl_tags,
                        )
                        results.append(
                            {
                                "identifier": new_file.euid,
                                "status": "Success",
                                "original": file.filename if file else url,
                                "current_s3_uri": new_file.json_addl["properties"][
                                    "current_s3_uri"
                                ],
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
                            file_metadata=file_metadata, url=url.strip(),addl_tags=addl_tags,
                        )
                        results.append(
                            {
                                "identifier": new_file.euid,
                                "status": "Success",
                                "original": url,
                                "current_s3_uri": new_file.json_addl["properties"][
                                    "current_s3_uri"
                                ],
                            }
                        )
                        bfs.add_files_to_file_set(
                            file_set_euid=new_file_set.euid, file_euids=[new_file.euid]
                        )  
                    except Exception as e:
                        results.append(
                            {"identifier": url.strip(), "status": f"Failed: {str(e)}"}
                        )
        if s3_uris:
            s3_uri_list = s3_uris.split("\n")
            for s3_uri in s3_uri_list:
                if s3_uri.strip():
                    try:
                        new_file = bfi.create_file(
                            file_metadata=file_metadata, s3_uri=s3_uri.strip(), addl_tags=addl_tags,
                        )

                        if type(new_file) == type([]):
                            for nf in new_file:
                                results.append(
                                    {
                                        "identifier": nf.euid,
                                        "status": "Success",
                                        "original": s3_uri,
                                        "current_s3_uri": nf.json_addl["properties"][
                                            "current_s3_uri"
                                        ],
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
                                    "current_s3_uri": new_file.json_addl["properties"][
                                        "current_s3_uri"
                                    ],
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

        # Render the report
        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
        content = templates.get_template("create_file_report.html").render(
            request=request,
            results=results,
            style=style,
            udat=user_data,
            file_set_euid=new_file_set.euid,
            file_set_name=file_set_name,
        )

        return HTMLResponse(content=content)

    except ValueError as ve:
        logging.error(f"Input error: {ve}")
        return HTMLResponse(
            content=f"<html><body><h2>{ve}</h2></body></html>", status_code=400
        )

    except Exception as e:
        logging.error(f"Error creating file: {e}")

        accordion_states = dict(request.session)
        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
        content = templates.get_template("dewey.html").render(
            request=request,
            error=f"An error occurred: {e}",
            accordion_states=accordion_states,
            style=style,
            controlled_properties=controlled_properties,
            udat=user_data,
        )

        return HTMLResponse(content=content)


@app.post("/download_file", response_class=HTMLResponse)
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

        # Ensure the file exists
        if not os.path.exists(downloaded_file_path):
            return HTMLResponse(f"File with EUID {euid} not found.", status_code=404)

        metadata_yaml_path = None
        if create_metadata_file == "yes":
            metadata_yaml_path = downloaded_file_path + "." + euid + ".dewey.yaml"
            if not os.path.exists(metadata_yaml_path):
                return HTMLResponse(
                    f"Metadata file for EUID {euid} not found.", status_code=404
                )

        if ret_json:
            return JSONResponse(
                content={
                    "file_download_path": downloaded_file_path,
                    "metadata_download_path": metadata_yaml_path,
                }
            )

        # Render the template with download paths
        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
        content = templates.get_template("trigger_downloads.html").render(
            request=request,
            file_download_path=downloaded_file_path,
            metadata_download_path=metadata_yaml_path,
            style=style,
            udat=user_data,
        )

        return HTMLResponse(content=content)

    except Exception as e:
        logging.error(f"Error downloading file: {e}")

        # Render the error page with a link to delete the offending temp files
        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
        offending_file = str(e).split("/tmp/")[-1]

        content = templates.get_template("download_error.html").render(
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
            logging.info(f"Deleted file {file_path}")
    except Exception as e:
        logging.error(f"Error deleting file {file_path}: {e}")


@app.get("/delete_temp_file")
async def delete_temp_file(
    request: Request, filename: str, background_tasks: BackgroundTasks
):
    file_path = Path("./tmp") / filename
    file_path_yaml = Path("./tmp") / f"{filename}.dewey.yaml"

    if file_path.exists():
        background_tasks.add_task(delete_file, file_path)
        background_tasks.add_task(delete_file, file_path_yaml)
    return RedirectResponse(url="/dewey", status_code=303)

@app.post("/search_files", response_class=HTMLResponse)
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
    study_id: List[str] = Form(None),
    comments: str = Form(None),
    created_datetime_start: str = Form(None),
    created_datetime_end: str = Form(None),
    creating_user: List[str] = Form(None),
):
    
    form_data = {
    "euid": euid,
    "patient_id": patient_id,
    "clinician_id": clinician_id,
    "lab_code": lab_code,
    "purpose": purpose,
    "purpose_subtype": purpose_subtype,
    "category": category,
    "sub_category": sub_category,
    "sub_category_2": sub_category_2,
    "study_id": study_id,
    "comments": comments,
    "creating_user": creating_user,
    }
    
    search_fields = [
        "euid", "patient_id", "clinician_id", "lab_code", "purpose", "purpose_subtype", 
        "category", "sub_category", "sub_category_2", "study_id", "comments", "creating_user"
    ]
    
    search_criteria = create_search_criteria(form_data, search_fields)
        
    if record_datetime_start or record_datetime_end:
        search_criteria["record_datetime"] = {
            "start": record_datetime_start,
            "end": record_datetime_end
        }

    greedy = is_greedy == "yes"

    try:
        bfi = BloomFile(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))

        # Prepare additional filters for created_datetime and record_datetime
        query = bfi.session.query(bfi.Base.classes.generic_instance)

        if created_datetime_start:
            query = query.filter(
                bfi.Base.classes.generic_instance.created_dt >= datetime.strptime(created_datetime_start, "%Y-%m-%d")
            )
        if created_datetime_end:
            query = query.filter(
                bfi.Base.classes.generic_instance.created_dt <= datetime.strptime(created_datetime_end, "%Y-%m-%d")
            )

        if record_datetime_start or record_datetime_end:
            record_datetime_filter = {}
            if record_datetime_start:
                record_datetime_filter["start"] = datetime.strptime(record_datetime_start, "%Y-%m-%d")
            if record_datetime_end:
                record_datetime_filter["end"] = datetime.strptime(record_datetime_end, "%Y-%m-%d")
            search_criteria["record_datetime"] = record_datetime_filter

        euid_results = bfi.search_objs_by_addl_metadata(
            {'properties':search_criteria}, greedy, "file", super_type="file"
        )

        if created_datetime_start or created_datetime_end:
            euid_results = [result.euid for result in query.filter(
                bfi.Base.classes.generic_instance.euid.in_(euid_results)
            ).all()]

        # Fetch details for each EUID
        detailed_results = [bfi.get_by_euid(euid) for euid in euid_results]

        # Create a list of columns for the table
        columns = ["EUID", "Date Created", "Status"]
        if detailed_results and detailed_results[0].json_addl.get("properties"):
            columns += list(detailed_results[0].json_addl["properties"].keys())

        # Prepare the data for the template
        table_data = []
        for result in detailed_results:
            row = {
                "EUID": result.euid,
                "Date Created": result.created_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "Status": result.bstatus,
            }
            for key in columns[3:]:
                try:
                    row[key] = result.json_addl["properties"].get(key, "N/A")
                except Exception as e:
                    pass
            table_data.append(row)

        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
        fset_templates = bobdb.query_template_by_component_v2("file","file_set","generic","1.0")
  
        fset_template = fset_templates[0]
        ui_form_properties_fset = fset_template.json_addl.get("ui_form_properties", [])
        ui_form_fields_fset = generate_ui_form_fields(ui_form_properties_fset, fset_template.json_addl.get("controlled_properties", {}),  bobject=bobdb)
        ui_form_fields_query_fset = generate_ui_form_fields(ui_form_properties_fset, fset_template.json_addl.get("controlled_properties", {}),  bobject=bobdb, form_type="query", super_type="file", btype="file_set", version=None)

        content = templates.get_template("search_results.html").render(
            request=request,
            columns=columns,
            table_data=table_data,
            n_results=len(table_data),
            s3_bucket_prefix=os.environ.get("BLOOM_DEWEY_S3_BUCKET_PREFIX", "NEEDS TO BE SET!")+"0",
            style=style,
            udat=user_data,
            ui_fields_fset=ui_form_fields_fset,
            ui_search_fields_fset=ui_form_fields_query_fset,
        )
        return HTMLResponse(content=content)

    except Exception as e:
        logging.error(f"Error searching files: {e}", exc_info=True)
        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
        content = templates.get_template("search_error.html").render(
            request=request,
            error=f"An error occurred: {e}",
            style=style,
            udat=user_data,
        )
        return HTMLResponse(content=content)


@app.get("/get_node_property")
async def get_node_property(request: Request, euid: str, key: str):
    bo = BloomObj(BLOOMdb3(app_username=""))

    try:
        boi = bo.get_by_euid(euid)
        if boi is None:
            return JSONResponse({"error": "Node not found"}, status_code=404)

        property_value = boi.json_addl.get("properties", {}).get(
            key, "Property Not Found"
        )
        return JSONResponse({key: property_value})
    except Exception as e:
        logging.error(f"Error retrieving node property: {e}")
        return JSONResponse(
            {"error": f"Error retrieving node property: {e}"}, status_code=500
        )


@app.post("/create_file_set")
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
    passwd: str = Form("") 
):        
    rclone_config = {
                "bucket": bucket,
                "host": host,
                "port": port,
                "user": user,
                "passwd": passwd
            }
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

        # Create the file set
        new_file_set = bfs.create_file_set(file_set_metadata=file_set_metadata)

        # Add files to the file set
        file_euids_list = [euid.strip() for euid in file_euids.split()]
        bfs.add_files_to_file_set(
            file_set_euid=new_file_set.euid, file_euids=file_euids_list
        )
        
        # where in duration is days
        duration_sec = duration * 24 * 60 * 60
        
        if ref_type == "presigned_url":
            for f_euid in file_euids_list:            
                bf.create_presigned_url(file_euid=f_euid, file_set_euid=new_file_set.euid, 
                                         valid_duration=duration_sec
                                         )
        elif ref_type.startswith('rclone'):
            bfr.create_file_reference(reference_type=ref_type,valid_duration=duration_sec,file_set_euid=new_file_set.euid, rclone_config=rclone_config)
        elif ref_type.startswith("na"):
            pass
        else:
            raise ValueError(f"UNSUPPORTED ref_type: {ref_type}")
        

        return RedirectResponse(
            url=f"/euid_details?euid={new_file_set.euid}", status_code=303
        )

    except Exception as e:
        raise (e)
    
    
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


# The following is very redundant to the file_search and <s>probably</s> should be refactored
@app.post("/search_file_sets", response_class=HTMLResponse)
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

    form_data = {
            "name": name,
            "description": description,
            "tag": tag,
            "comments": comments,
            "file_euids": file_euids,
            "ref_type": ref_type,
            "creating_user": creating_user,
        }

    search_fields = ["name", "description", "tag", "comments", "ref_type", "creating_user"]
    search_criteria = create_search_criteria(form_data, search_fields)

    greedy = is_greedy == "yes"

    try:
        bfs = BloomFileSet(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        file_sets = bfs.search_objs_by_addl_metadata(
            {'properties':search_criteria}, greedy, "file_set", super_type="file"
        )

        # Fetch details for each EUID
        detailed_results = [bfs.get_by_euid(euid) for euid in file_sets]

        # Create a list of columns for the table
        columns = ["EUID", "Date Created", "Status"]
        if detailed_results and detailed_results[0].json_addl.get("properties"):
            columns += list(detailed_results[0].json_addl["properties"].keys())
        columns.append("File EUIDs")
        # Prepare the data for the template
        table_data = []
        for result in detailed_results:
            row = {
                "EUID": result.euid,
                "Date Created": result.created_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "Status": result.bstatus,
            }
            for key in columns[3:]:
                row[key] = result.json_addl["properties"].get(key, "N/A")
            file_euids = [
                elem.child_instance.euid for elem in result.parent_of_lineages.all()
            ]
            euid_links = [
                f'<a href="euid_details?euid={euid}">{euid}</a>' for euid in file_euids
            ]
            row["File EUIDs"] = euid_links
            table_data.append(row)

        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}

        num_results = len(table_data)
        content = templates.get_template("file_set_search_results.html").render(
            request=request,
            table_data=table_data,
            columns=columns,
            style=style,
            udat=user_data,
            num_results=num_results,
        )
        return HTMLResponse(content=content)

    except Exception as e:
        logging.error(f"Error searching file sets: {e}")
        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
        content = templates.get_template("search_error.html").render(
            request=request,
            error=f"An error occurred: {e}",
            style=style,
            udat=user_data,
        )
        return HTMLResponse(content=content)


@app.get("/visual_report", response_class=HTMLResponse)
async def visual_report(request: Request):
    import io
    import base64

    # Read the TSV file
    file_path = "~/Downloads/dewey_search.tsv"
    data = pd.read_csv(file_path, sep="\t")

    # Analyze the Data
    file_types = data["file_type"].value_counts()
    file_sizes = data["original_file_size_bytes"].dropna()
    upload_users = data["upload_ui_user"].value_counts()

    # Generate Visualizations
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

    file_types_img = create_plot(
        file_types, "Distribution of File Types", "File Type", "Count", "bar"
    )
    file_sizes_img = create_plot(
        file_sizes,
        "Distribution of File Sizes",
        "File Size (bytes)",
        "Frequency",
        "hist",
    )
    upload_users_img = create_plot(
        upload_users, "Files Uploaded by User", "User", "Number of Files", "bar"
    )

    plots.append(file_types_img)
    plots.append(file_sizes_img)
    plots.append(upload_users_img)

    # Render the HTML template with the plots
    template = templates.get_template("visual_report.html")
    context = {"request": request, "plots": plots}

    return HTMLResponse(content=template.render(context), status_code=200)

### 
#  INSTANCE INSTANTIATION FORMS !!!
###

from typing import List, Dict
from pydantic import BaseModel

class FormField(BaseModel):
    name: str
    type: str
    label: str
    required: bool = False
    multiple: bool = False
    options: List[str] = []

@app.get("/create_instance/{template_euid}", response_class=HTMLResponse)
async def create_instance_form(request: Request, template_euid: str):
    bobj = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    
    template_instance = bobj.get_by_euid(template_euid)
    template_data = template_instance.json_addl
    
    form_fields = generate_form_fields(template_data)
    ui_form_properties = template_data.get("ui_form_properties", [])
    ui_form_fields = generate_ui_form_fields(ui_form_properties, template_data.get("controlled_properties", {}))
    
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
    
    controlled_properties_js = json.dumps(template_data.get("controlled_properties", {}))
    
    content = templates.get_template("create_instance_form.html").render(
        request=request,
        fields=form_fields,
        ui_fields=ui_form_fields,
        style=style,
        udat=user_data,
        template_euid=template_euid,
        polymorphic_discriminator=template_instance.polymorphic_discriminator,
        super_type=template_instance.super_type,
        btype=template_instance.btype,
        b_sub_type=template_instance.b_sub_type,
        version=template_instance.version,
        name=template_instance.name,
        controlled_properties=template_data.get("controlled_properties", {}),
        has_ui_form_properties=bool(ui_form_properties),
        controlled_properties_js=controlled_properties_js
    )
    return HTMLResponse(content=content)

def generate_form_fields(template_data: Dict) -> List[FormField]:
    properties = template_data.get("properties", {})
    controlled_properties = template_data.get("controlled_properties", {})
    form_fields = []

    for prop in properties:
        if prop in controlled_properties:
            cp = controlled_properties[prop]
            if cp["type"] == "dependent string":
                form_fields.append(FormField(
                    name=prop,
                    type="select",
                    label=prop.replace("_", " ").capitalize(),
                    options=[]
                ))
            else:
                form_fields.append(FormField(
                    name=prop,
                    type="select",
                    label=prop.replace("_", " ").capitalize(),
                    options=cp.get("enum", [])
                ))
        else:
            form_fields.append(FormField(
                name=prop,
                type="text",
                label=prop.replace("_", " ").capitalize()
            ))

    return form_fields



def generate_ui_form_fields(ui_form_properties: List[Dict], controlled_properties: Dict,  form_type: str = 'create',  bobject=None, super_type: str = None, btype: str = None, b_type: str = None, b_sub_type: str = None, version: str = None  ) -> List[FormField]:
    form_fields = []

    for prop in ui_form_properties:
        property_key = prop["property_key"]
        form_label = prop["form_label"]
        required=prop.get("required", False)
        value_type = prop.get("value_type", "string")

        if property_key in controlled_properties:
            if form_type == 'create':
                cp = controlled_properties[property_key]
                if cp["type"] == "dependent string":
                    form_fields.append(FormField(
                        name=property_key,
                        type="select",
                        label=form_label,
                        options=[], 
                        required=required
                    ))
                else:
                    form_fields.append(FormField(
                        name=property_key,
                        type="select",
                        label=form_label,
                        options=cp.get("enum", []),
                        required=required
                    ))
            else:
                unique_values = sorted(bobject.get_unique_property_values(property_key, super_type=super_type, btype=btype, b_sub_type=b_sub_type, version=version))
                if '' not in unique_values:
                    unique_values.insert(0, '')
        
                form_fields.append(FormField(
                    name=property_key,
                    type="select",
                    label=form_label,
                    options=unique_values,
                    multiple=True,
                    required=required
                ))
        elif value_type == "uid-interactive":
            unique_values = sorted(bobject.get_unique_property_values(property_key))
            if '' not in unique_values:
                unique_values.insert(0, '')
    
            form_fields.append(FormField(
                name=property_key,
                type="select",
                label=form_label,
                options=unique_values,
                multiple=True,
                required=required
            ))
        elif value_type == "uid-static":
            unique_values = sorted(bobject.get_unique_property_values(property_key))
            if '' not in unique_values:
                unique_values.insert(0, '')
                
            form_fields.append(FormField(
                        name=property_key,
                        type="select",
                        label=form_label,
                        options=unique_values,
                        multiple=True,
                        required=required
                    ))
        else:
            form_fields.append(FormField(
                name=property_key,
                type="text",
                label=form_label,
                required=required
            ))
            

    return form_fields


@app.post("/create_instance")
async def create_instance(request: Request):
    bobj = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    form_data = await request.form()
    #form_data_dict = form_data._dict
    template_euid = form_data['template_euid']
    #del form_data_dict['template_euid']

    jaddl = {'properties': dict(form_data)}
    ni = bobj.create_instance(template_euid, jaddl)

    return RedirectResponse(
        url=f"/euid_details?euid={ni.euid}", status_code=303
    )

@app.get("/file_set_urls", response_class=HTMLResponse)
async def file_set_urls(request: Request, fs_euid: str, _auth=Depends(require_auth)):
    try:
        bfs = BloomFileSet(BLOOMdb3(app_username=request.session["user_data"]["email"]))
        bf = BloomFile(BLOOMdb3(app_username=request.session["user_data"]["email"]))

        file_set = bfs.get_by_euid(fs_euid)
        if not file_set:
            raise HTTPException(status_code=404, detail="File set not found.")

        # Fetch all shared references where the file set is a parent
        shared_refs = []
        for lineage in file_set.parent_of_lineages:
            if lineage.child_instance.btype == 'shared_ref':
 
                orig_file = None
                for x in lineage.child_instance.child_of_lineages.all():
                    if x.parent_instance.btype == 'file':
                        orig_file = x.parent_instance                
                        
                shared_refs.append({
                    "euid": lineage.child_instance.euid,
                    "url": lineage.child_instance.json_addl['properties'].get("presigned_url", "N/A"),
                    "start_datetime": lineage.child_instance.json_addl['properties'].get("start_datetime", "N/A"),
                    "end_datetime": lineage.child_instance.json_addl['properties'].get("end_datetime", "N/A"),
                    "orig_file": orig_file
                })

        # Render the HTML template
        user_data = request.session.get("user_data", {})
        style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
        context = {
            "request": request,
            "file_set": file_set,
            "shared_refs": shared_refs,
            "style": style,
            "udat": user_data,
        }
        content = templates.get_template("file_set_urls.html").render(context)
        return HTMLResponse(content=content)

    except Exception as e:
        logging.error(f"Error fetching file set URLs: {e}")
        return JSONResponse(
            content={"error": "An error occurred while fetching file set URLs."},
            status_code=500
        )


@app.get("/admin_template", response_class=HTMLResponse)
async def get_admin_template(request: Request, euid: str = Query(...)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    obj = bobdb.get_by_euid(euid)
    
    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")

    controlled_properties = obj.json_addl.get("controlled_properties", {})
    user_data = request.session.get("user_data", {})
    style = {"skin_css": user_data.get("style_css", "static/skins/bloom.css")}
    
    template = templates.get_template("admin_template.html")
    context = {
        "request": request,
        "euid": euid,
        "controlled_properties": json.dumps(controlled_properties, indent=4),
        "udat":  user_data,
        "style":style
    }

    return HTMLResponse(content=template.render(context))

@app.post("/admin_template", response_class=HTMLResponse)
async def post_admin_template(request: Request, euid: str = Form(...), controlled_properties: str = Form(...)):
    bobdb = BloomObj(BLOOMdb3(app_username=request.session["user_data"]["email"]))
    obj = bobdb.get_by_euid(euid)

    if not obj:
        raise HTTPException(status_code=404, detail="Object not found")

    try:
        obj.json_addl['controlled_properties'] = json.loads(controlled_properties)
        flag_modified(obj, "json_addl")
        bobdb.session.commit()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return RedirectResponse(url=f"/admin_template?euid={euid}", status_code=303)



@app.get("/serve_endpoint/{file_path:path}", response_class=HTMLResponse)
async def serve_files(file_path: str, request: Request, auth=Depends(require_auth)):
    print('YYYYYYYYY',file_path)
    
    #file_path = "/"+ file_path.replace('//','/').lstrip('/').rstrip('/').lstrip('/') 
    #if file_path == "" or file_path =="//":
    #    file_path="/"

    if file_path.startswith('/'):
        file_path = file_path.lstrip('/')

    if  file_path in [None,"","/"]:
        file_path = ""
    print('RRRRR',file_path)

        
    requested_path = BASE_DIR / file_path
    print('xxxxxx', BASE_DIR, file_path, requested_path)
    logging.info(f"Requested path: {requested_path}")
    
    if not requested_path.exists():
        logging.error(f"File or directory not found: {requested_path}")
        raise HTTPException(status_code=404, detail="File or directory not found")

    full_path = requested_path.resolve()

    if full_path.is_dir():
        return directory_listing(full_path, file_path)
    elif full_path.is_file():
        if full_path.suffix == '.html':
            with open(full_path, 'r') as f:
                content = f.read()
            return HTMLResponse(content=content)
        return FileResponse(full_path, media_type="application/octet-stream", filename=full_path.name)

    raise HTTPException(status_code=404, detail="File or directory not found")


def directory_listing(directory: Path, file_path: str) -> HTMLResponse:
    """
    Generate an HTML response listing the contents of a directory with alphabetical ordering.
    """

    parent_path = file_path + "/../.."
    
    # Alphabetical sort for directories and files
    items = sorted(directory.iterdir(), key=lambda x: x.name.lower())

    files = []
    for item in items:
        if item.is_dir():
            files.append(
                f"<li><a href='/serve_endpoint/{file_path.lstrip('/')}/{item.name}/'>{item.name}/</a></li>"
            )
        else:
            files.append(
                f"<li><a href='/serve_endpoint/{file_path.lstrip('/')}/{item.name}'>{item.name}</a></li>"
            )
    print('PPPPPP', str(parent_path))
    html_content = f"""
    <h2>Directory listing for: {directory.name}</h2>
    <ul>
        <li><a href="/serve_endpoint/{parent_path.lstrip('/')}">.. (parent directory)</a></li>
        {''.join(files)}
    </ul>
    """
    return HTMLResponse(content=html_content)

# Middleware for checking authentication
@app.get("/protected_content", response_class=HTMLResponse)
async def protected_content(request: Request, auth=Depends(require_auth)):
    """
    Example of an endpoint requiring authentication.
    Once authenticated, users can access protected resources.
    """
    content = "You are authenticated and can access protected resources."
    return HTMLResponse(content=content)

client = TestClient(app)  # Create a test client for programmatic requests

@app.post("/bulk_create_files_from_tsv")
async def bulk_create_files_from_tsv(request: Request, file: UploadFile = File(...)):
    temp_dir = Path("temp_bulk_create")
    temp_dir.mkdir(exist_ok=True)

    # Save uploaded TSV locally
    tsv_path = temp_dir / file.filename
    with open(tsv_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Read and validate the TSV
    rows = []
    try:
        with open(tsv_path, "r") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        if not rows:
            return {"status": "error", "message": "The TSV file is empty."}

        # Validate required columns
        required_columns = [
            "name", "comments", "lab_code", "urls", "s3_uris", "study_id",
            "clinician_id", "record_datetime", "record_datetime_end", "patient_id",
            "purpose", "category", "sub_category", "sub_category_2", "variable",
            "sub_variable", "file_tags", "upload_key"
        ]

        for column in required_columns:
            if column not in rows[0]:
                return {"status": "error", "message": f"Missing required column: {column}"}
        
        
        logging.info("Pre-checks passed. Processing the TSV...")
    except Exception as e:
        return {"status": "error", "message": f"Failed to process TSV: {e}"}

    # Process rows and hit create_file
    results = []
    for i, row in enumerate(rows):
        num_files = 0
        num_success = 0
        num_failed = 0
        messages = []

        # Determine the number of files to create
        urls = row.get("urls", "").split(",") if row.get("urls") else []
        s3_uris = row.get("s3_uris", "").split(",") if row.get("s3_uris") else []
        num_files = len(urls) + len(s3_uris)

        try:
            # Simulate a POST request to create_file
            #from IPython import embed; embed()
            response = client.post("/create_file", data=row)
            logging.info(f"Row {i + 1}: {response.json()} ... {response.status_code}")
            if response.status_code in [200,307]:
                num_success += 1
                messages.append("File created successfully.")
            else:
                num_failed += 1
                messages.append(response.json().get("detail", "Unknown error"))
        except Exception as e:
            num_failed += 1
            messages.append(str(e))

        # Append the result
        results.append({
            "row": i + 1,
            "num_files_to_create": num_files,
            "num_success": num_success,
            "num_failed": num_failed,
            "create_message": "; ".join(messages),
            "datetime_finished": datetime.now().isoformat()
        })

    # Append results to TSV and save as .fin.tsv
    fin_tsv_path = tsv_path.with_suffix(".fin.tsv")
    
    with open(fin_tsv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) + [ "row",
            "num_files_to_create", "num_success", "num_failed", "create_message", "datetime_finished"
        ], delimiter="\t")
        writer.writeheader()
        for row, result in zip(rows, results):
            writer.writerow({**row, **result})

    return FileResponse(fin_tsv_path, media_type="text/tab-separated-values")
