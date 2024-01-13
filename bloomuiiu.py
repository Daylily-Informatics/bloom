import os
import sys
import json
from datetime import datetime
from sqlalchemy.orm.attributes import flag_modified
from datetime import datetime, timedelta

from sqlalchemy import func
import cherrypy

from jinja2 import Environment, FileSystemLoader

from bloom_lims.bdb import BLOOMdb3
from bloom_lims.bdb import BloomObj, BloomWorkflow, BloomWorkflowStep

from collections import defaultdict

SKIP_AUTH = False if len(sys.argv) < 3 else True


def is_instance(value, type_name):
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


def get_relationship_data(obj):
    relationship_data = {}
    for relationship in obj.__mapper__.relationships:
        if relationship.uselist:  # If it's a list of items
            relationship_data[relationship.key] = [
                {
                    "child_instance_euid": rel_obj.child_instance.euid
                    if hasattr(rel_obj, "child_instance")
                    else [],
                    "parent_instance_euid": rel_obj.parent_instance.euid
                    if hasattr(rel_obj, "parent_instance")
                    else [],
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
                {
                    "child_instance_euid": rel_obj.child_instance.euid
                    if hasattr(rel_obj, "child_instance")
                    else [],
                    "parent_instance_euid": rel_obj.parent_instance.euid
                    if hasattr(rel_obj, "parent_instance")
                    else [],
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
            ]
    return relationship_data


def require_auth(redirect_url="/login"):
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            # Check if user is authenticated
            if 'user_data' not in cherrypy.session:
                # Not authenticated, redirect to login page
                raise cherrypy.HTTPRedirect(redirect_url)
            else:
                # Authenticated, proceed to the requested page
                return func(self, *args, **kwargs)
        return wrapper
    return decorator

class WorkflowService(object):
    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader("templates")
        )  # Assuming you have HTML templates in a 'templates' directory
        self.env.globals["get_well_color"] = get_well_color
        self.env.filters["is_instance"] = is_instance

    @cherrypy.expose
    def index(self):
        user_logged_in = True if 'user_data' in cherrypy.session else False
        template = self.env.get_template("index.html")
        return template.render( style=self.get_root_style(), user_logged_in=user_logged_in)


    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def assays(self, show_type='all'):
        user_logged_in = True if 'user_data' in cherrypy.session else False
        template = self.env.get_template("assay.html")
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        ay_ds = {}
        for i in (
            bobdb.session.query(bobdb.Base.classes.workflow_instance)
            .filter_by(is_deleted=False,is_singleton=True)
            .all()
        ):
            if show_type == 'all' or i.json_addl.get('assay_type','all') == show_type:
                ay_ds[i.euid] = i

        assays = []
        ay_dss = {}
        atype={}

        if show_type == 'assay':
            atype['type'] = 'Assays'
        elif show_type == 'accessioning':
            atype['type'] = 'Accessioning'
        else:
            atype['type'] = 'All Assays, etc'

        for i in sorted(ay_ds.keys()):
            assays.append(ay_ds[i])
            ay_dss[i] = {"Instantaneous COGS" : round(bobdb.get_cost_of_euid_children(i),2)}
            ay_dss[i]['tot'] = 0
            ay_dss[i]['tit_s'] = 0
            ay_dss[i]['tot_fx'] = 0

            for q in ay_ds[i].parent_of_lineages:
                for c in q.child_instance.parent_of_lineages:
                    for cc in c.child_instance.parent_of_lineages:
                        if cc.child_instance.name == "package:generic:1.0":
                            try:
                                ay_dss[i]['tit_s'] += int(cc.child_instance.json_addl['properties']['fedex_tracking_data'][0]['Transit_Time_sec'])
                                ay_dss[i]['tot_fx'] += 1
                            except Exception as e:
                                pass
                try:
                    ay_dss[i]['avg_d_fx'] = float(ay_dss[i]['tit_s'])/60.0/60.0/24.0 / float(ay_dss[i]['tot_fx'])
                except Exception as e:
                    ay_dss[i]['avg_d_fx'] = 'na'
                wset = ''
                n = q.child_instance.json_addl['properties']['name']
                if n.startswith('In'):
                    wset = 'inprog'
                elif n.startswith('Comple'):
                    wset = 'complete'
                elif n.startswith('Exception'):
                    wset = 'exception'
                elif n.startswith('Ready'):
                    wset = 'avail'
                ay_dss[i][wset]=len(q.child_instance.parent_of_lineages)
                ay_dss[i]['tot'] += len(q.child_instance.parent_of_lineages)
            ay_dss[i]['conv'] = float(ay_dss[i]['complete']) / float( ay_dss[i]['complete'] + ay_dss[i]['exception']) if ay_dss[i]['complete'] + ay_dss[i]['exception'] > 0 else 'na'  
            ay_dss[i]['wsetp'] = float(ay_dss[i]["Instantaneous COGS"]) / float(ay_dss[i]['tot']) if ay_dss[i]['tot'] > 0 else 'na'
                
        return template.render( style=self.get_root_style(), workflow_instances=assays, ay_stats=ay_dss, atype=atype)


    @cherrypy.expose
    def logout(self):
        # Check if a user is currently logged in
        if 'user' in cherrypy.session:
            # Clear the session data to log out the user
            cherrypy.session.pop('user_data', None)
            cherrypy.session.pop('user', None)
            cherrypy.lib.sessions.expire()  # Optionally, expire the session cookie

        # Redirect the user to the login page or another appropriate page after logging out
        raise cherrypy.HTTPRedirect('/')


    @cherrypy.expose
    def login(self, email=None, password=None):
        user_data_file = './etc/udat.json'
        user_data = {}

        if email in [None] or password in [None]:
            if SKIP_AUTH:
                email="skip@auth.ai"
                password="na"
            else:
                # Show the login page
                template = self.env.get_template("login.html")
                return template.render(style=self.get_root_style())
        
        # Load or create user data
        if not os.path.exists(user_data_file):
            print(f"User data file not found in {user_data_file}, creating empty file...")
            os.system(f"mkdir -p etc && echo '{{}}' > {user_data_file}")

        with open(user_data_file, 'r') as f:
            user_data = json.load(f)
        
        if email and email not in user_data:
            # New user, create entry
            user_data[email] = {'style_css': 'static/skins/bloom.css'}
            with open(user_data_file, 'w') as f:
                json.dump(user_data, f)

        # Set user session
        cherrypy.session['user_data'] = user_data.get(email, {})
        cherrypy.session['user_data']['wf_filter'] = 'off'
        cherrypy.session['user'] = email
        # Redirect to a different page or render a success message
        raise cherrypy.HTTPRedirect('/')
    
    
    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def calculate_cogs_children(self, euid):
        try:
            bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
            cogs_value =round(bobdb.get_cost_of_euid_children(euid),2)
            return json.dumps({"success": True, "cogs_value": cogs_value})
        except Exception as e:
            cherrypy.log("Error in calculate_cogs_children: ", traceback=True)
            return json.dumps({"success": False, "message": str(e)})
    
    
    
    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def calculate_cogs_parents(self, euid):
        try:
            bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
            cogs_value = round(bobdb.get_cogs_to_produce_euid(euid),2)
            return json.dumps({"success": True, "cogs_value": cogs_value})
        except Exception as e:
            cherrypy.log("Error in calculate_cogs_parents: ", traceback=True)
            return json.dumps({"success": False, "message": str(e)})
    
    
    
    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def set_filter(self, curr_val='off'):
        if curr_val == 'off':
            cherrypy.session['user_data']['wf_filter'] = 'on'
        else:
            cherrypy.session['user_data']['wf_filter'] = 'off'

    
    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def admin(self,dest='na'):
        dest_section = {'section':dest}
        template = self.env.get_template("admin.html")

        # Assuming user_data is stored in the CherryPy session
        user_data = cherrypy.session.get('user_data', {})

        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        
        
         # Mock or real printer_info data

        if 'print_lab' in user_data:
            bobdb.get_lab_printers(user_data['print_lab'])

        csss = []
        for css in sorted(os.popen('ls -1 static/skins/*css').readlines()):
            csss.append(css.rstrip())
            
        printer_info = {
            'print_lab': bobdb.printer_labs,
            'printer_name': bobdb.site_printers,
            'label_zpl_style': bobdb.zpl_label_styles,
            'style_css': csss
        }

        # Render the template with user data and printer info
        return template.render(style=self.get_root_style(),user_data=user_data, printer_info=printer_info, dest_section=dest_section)

    @cherrypy.expose
    def get_root_style(self):   
        rs_obj = {"skin_css": 'static/skins/bloom.css'}
        try:
            user_data = cherrypy.session.get('user_data', {})
            rs_obj = {"skin_css": user_data.get('style_css', 'static/skins/bloom.css')}
        except Exception as e:
            pass

        return rs_obj
        
    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    @require_auth(redirect_url="/login")
    def update_preference(self):
        # Retrieve data sent from the AJAX call
        data = cherrypy.request.json
        key = data.get('key')
        value = data.get('value')
        
        # Load existing user data from the file
        user_data_file = './etc/udat.json'
        if os.path.exists(user_data_file):
            with open(user_data_file, 'r') as f:
                user_data = json.load(f)
        else:
            return {'status': 'error', 'message': 'User data file not found'}

        # Update the user data in memory
        email = cherrypy.session.get('user')
        if email in user_data:
            user_data[email][key] = value
        else:
            return {'status': 'error', 'message': 'User not found in user data'}

        # Write updated user data back to the file
        with open(user_data_file, 'w') as f:
            json.dump(user_data, f)

        # Update the user session dictionary
        cherrypy.session['user_data'] = user_data[email]
        
        return {'status': 'success', 'message': 'User preference updated'}

    
    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def generic_templates(self):
        template = self.env.get_template("generic_templates.html")
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        templates = (
            bobdb.session.query(bobdb.Base.classes.generic_template)
            .filter_by(is_deleted=False)
            .all()
        )

        # Group templates by super_type
        grouped_templates = {}
        for temp in templates:
            if temp.super_type not in grouped_templates:
                grouped_templates[temp.super_type] = []
            grouped_templates[temp.super_type].append(temp)
        return template.render(style=self.get_root_style(),grouped_templates=grouped_templates)

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def workflow_summary(self):
        template = self.env.get_template("workflow_summary.html")
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        workflows = (
            bobdb.session.query(bobdb.Base.classes.workflow_instance)
            .filter_by(is_deleted=False)
            .all()
        )
        accordion_states = dict(cherrypy.session)

        # Initialize statistics dictionary
        workflow_statistics = defaultdict(
            lambda: {
                "status_counts": defaultdict(int),
                "oldest": datetime.max.date(),  # Convert to datetime.date
                "newest": datetime.min.date(),  # Convert to datetime.date
            }
        )

        # Iterate through each workflow to compute statistics
        for wf in workflows:
            wf_type = wf.btype
            wf_status = wf.bstatus

            wf_created_dt = (
                wf.created_dt.date()
            )  # Ensure this is a datetime.date object

            workflow_statistics[wf_type]["status_counts"][wf_status] += 1
            workflow_statistics[wf_type]["oldest"] = min(
                workflow_statistics[wf_type]["oldest"], wf_created_dt
            )
            workflow_statistics[wf_type]["newest"] = max(
                workflow_statistics[wf_type]["newest"], wf_created_dt
            )

        # Convert defaultdict to regular dict for Jinja2 compatibility
        workflow_statistics = {k: dict(v) for k, v in workflow_statistics.items()}
        unique_workflow_types = workflow_statistics.keys()

        # Convert defaultdict to regular dict for Jinja2 compatibility
        workflow_statistics = {k: dict(v) for k, v in workflow_statistics.items()}

        return template.render(style=self.get_root_style(),
            workflows=workflows,
            workflow_statistics=workflow_statistics,
            unique_workflow_types=unique_workflow_types,
        )

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def update_object_name(self, euid, name):
        referer = cherrypy.request.headers.get("Referer", "/default_page")
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        obj = bobdb.get_by_euid(euid)
        if obj:
            obj.name = name  # Update the name
            flag_modified(obj, "name")  # Explicitly mark the object as modified
            bobdb.session.commit()  # Commit the changes to the database
        # Redirect back to the details page or show a confirmation
        raise cherrypy.HTTPRedirect(referer)

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def equipment_overview(self):
        template = self.env.get_template("equipment_overview.html")
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))

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

        # Render the template with the fetched data
        return template.render(style=self.get_root_style(),
            equipment_list=equipment_instances, template_list=equipment_templates
        )


    @cherrypy.expose
    @cherrypy.tools.json_out()
    @require_auth(redirect_url="/login")
    def get_print_labs(self):
        # Replace the following line with the actual logic to retrieve your data
        options = [
            {"value": "option1", "text": "Option 1"},
            {"value": "option2", "text": "Option 2"},
            {"value": "option3", "text": "Option 3"},
            # Add more options as needed
        ]
        return options
    

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def reagent_overview(self):
        template = self.env.get_template("reagent_overview.html")
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))

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
        # Render the template with the fetched data
        return template.render(style=self.get_root_style(),
            instance_list=reagent_instances, template_list=reagent_templates
        )

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def control_overview(self):
        template = self.env.get_template("control_overview.html")
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))

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
        # Render the template with the fetched data
        return template.render(style=self.get_root_style(),
            instance_list=control_instances, template_list=control_templates
        )

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def create_from_template(self, euid):
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        template = bobdb.create_instances(euid)
        raise cherrypy.HTTPRedirect("/euid_details?euid=" + str(template[0][0].euid))

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def uuid_details(self, uuid):
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        # Fetch the object using uuid
        obj = bobdb.get(uuid)
        raise cherrypy.HTTPRedirect("/euid_details?euid=" + str(obj.euid))

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def vertical_exp(self, euid=None):
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        instance = bobdb.get_by_euid(euid)
        template = self.env.get_template("vertical_exp.html")
        return template.render(style=self.get_root_style(),instance=instance)

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def plate_carosel(self, plate_euid):
        template = self.env.get_template("plate_carosel2.html")
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))

        # Fetch the main plate and its wells
        main_plate = bobdb.get_by_euid(plate_euid)
        oplt = bobdb.get_by_euid("CX42")
        if not main_plate:
            return "Main plate not found."

        # Example logic to fetch related plates (modify based on your data model)
        related_plates = self.get_related_plates(main_plate)
        related_plates.append(main_plate)
        # Render the template with the main plate and related plates data
        return template.render(style=self.get_root_style(),main_plate=main_plate, related_plates=related_plates)


    def get_related_plates(self, main_plate):
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
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

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def plate_visualization(self, plate_euid):
        template = self.env.get_template("plate_display.html")
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        # Fetch the plate and its wells
        plate = bobdb.get_by_euid(plate_euid)

        num_rows = 0
        num_cols = 0

        for i in plate.parent_of_lineages:
            if (
                i.parent_instance.euid == plate.euid
                and i.child_instance.btype == "well"
            ):
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
        return template.render(style=self.get_root_style(),plate=plate)

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def database_statistics(self):
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))

        def get_stats(days):
            cutoff_date = datetime.now() - timedelta(days=days)
            return (
                bobdb.session.query(
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

        stats_1d = get_stats(1)
        stats_7d = get_stats(7)
        stats_30d = get_stats(30)

        return self.env.get_template("database_statistics.html").render(style=self.get_root_style(),
            stats_1d=stats_1d, stats_7d=stats_7d, stats_30d=stats_30d
        )

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def object_templates_summary(self):
        template = self.env.get_template("object_templates_summary.html")
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))

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

        return template.render(style=self.get_root_style(),
            generic_templates=generic_templates,
            unique_discriminators=unique_discriminators,
        )

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def euid_details(self, euid, uuid=None):
        template = self.env.get_template("euid_details.html")
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))

        # Fetch the object using euid
        obj = bobdb.get_by_euid(euid)
        relationship_data = get_relationship_data(obj) if obj else {}

        # Convert the SQLAlchemy object to a dictionary, checking for attribute existence
        obj_dict = {
            column.key: getattr(obj, column.key)
            for column in obj.__table__.columns
            if hasattr(obj, column.key)
        }
        obj_dict['parent_template_euid'] = obj.parent_template.euid if hasattr(obj, 'parent_template') else ""
        audit_logs = bobdb.query_audit_log_by_euid(euid)
        # Pass the dictionary to the template
        return template.render(style=self.get_root_style(),
            object=obj_dict,
            relationships=relationship_data,
            audit_logs=audit_logs,
            oobj=obj,
        )

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def un_delete_by_uuid(self, uuid=None, euid=None):
        referer = cherrypy.request.headers.get("Referer", "/default_page")

        if uuid == None or euid == None:
            return (
                f"Error: uuid or euid not provided && both are required. {uuid} {euid}"
            )

        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        del_obj = bobdb.get(uuid)
        del_obj.is_deleted = False
        bobdb.session.flush()
        bobdb.session.commit()

        raise cherrypy.HTTPRedirect(referer)

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def toggle_state(self, euid):
        referer = cherrypy.request.headers.get("Referer", "/default_page")

        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        obj = bobdb.get_by_euid(euid)
        obj.bstate = "active" if obj.bstate == "inactive" else "inactive"
        flag_modified(obj, "bstate")
        bobdb.session.flush()
        bobdb.session.commit()

        raise cherrypy.HTTPRedirect(referer)

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def delete_by_euid(self, euid):
        referer = cherrypy.request.headers.get("Referer", "/default_page")

        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        bobdb.delete(bobdb.get_by_euid(euid))
        bobdb.session.flush()
        bobdb.session.commit()

        raise cherrypy.HTTPRedirect(referer)

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    @require_auth(redirect_url="/login")
    def delete_object(self):
        data = cherrypy.request.json
        euid = data.get("euid")
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))

        bobdb.delete(bobdb.get_by_euid(euid))
        bobdb.session.flush()
        bobdb.session.commit()

        return {
            "status": "success",
            "message": f"Delete object performed for EUID {euid}",
        }

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def workflow_details(self, workflow_euid):
        bwfdb = BloomWorkflow(BLOOMdb3(app_username=cherrypy.session['user']))
        template = self.env.get_template("workflow_details.html")
        workflow = bwfdb.get_sorted_euid(workflow_euid)
        accordion_states = dict(cherrypy.session)
        return template.render(style=self.get_root_style(),workflow=workflow, accordion_states=accordion_states, udat=cherrypy.session['user_data'])

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @require_auth(redirect_url="/login")
    def update_accordion_state(self):
        data = cherrypy.request.json
        step_euid = data["step_euid"]
        state = data["state"]  # 'open
        cherrypy.session[step_euid] = state
        return {"status": "success"}


    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    @require_auth(redirect_url="/login")
    def workflow_step_action(self):
        data = cherrypy.request.json
        euid = data.get("euid")
        action = data.get("action")
        action_group = data.get("action_group")
        ds = data.get("ds")
        bobdb = BloomWorkflow(BLOOMdb3(app_username=cherrypy.session['user']))
        bo = bobdb.get_by_euid(euid)


        ds["curr_user"] = cherrypy.session.get("user", "bloomui-user")
        udat = cherrypy.session.get("user_data",{}  )
        ds['lab'] = udat.get("print_lab", "BLOOM")
        ds['printer_name'] = udat.get("printer_name","")
        ds['label_zpl_style'] = udat.get("label_style","")
        ds['alt_a'] = udat.get("alt_a","")
        ds['alt_b'] = udat.get("alt_b","")
        ds['alt_c'] = udat.get("alt_c",)
        ds['alt_d'] = udat.get("alt_d","")   
        ds['alt_e'] = udat.get("alt_e","")                                     
                                     
        if bo.__class__.__name__ == "workflow_instance":
            bwfdb = BloomWorkflow(BLOOMdb3(app_username=cherrypy.session['user']))
            act = bwfdb.do_action(
                euid, action_ds=ds, action=action, action_group=action_group
            )
        else:
            bwfsdb = BloomWorkflowStep(BLOOMdb3(app_username=cherrypy.session['user']))
            act = bwfsdb.do_action(
                euid, action_ds=ds, action=action, action_group=action_group
            )

        return {"status": "success", "message": f" {action} performed for EUID {euid}"}

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def update_obj_json_addl_properties(self, obj_euid, **properties):
        """Update the json_addl['properties'] field of an object.  Was originally for just wfs...

        Args:
            obj_euid euid(): OBJECT.euid being edited

        Raises:
            Exception: Cherrypy redirect back to referring page
            cherrypy.HTTPRedirect: _description_

        Returns:
            cherrypy.HTTPRedirect: to referrer
        """
        referer = cherrypy.request.headers.get("Referer", "/default_page")

        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
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

        raise cherrypy.HTTPRedirect(referer)

    @cherrypy.expose
    @require_auth(redirect_url="/login")
    def dindex(self, globalFilterLevel=0, globalZoom=0, globalStartNodeEUID=None):
        self.generate_dag_json_from_all_objects()

        # Load your template
        tmpl = self.env.get_template("dindex.html")

        # Render the template with parameters
        return tmpl.render(style=self.get_root_style(),
            globalFilterLevel=globalFilterLevel,
            globalZoom=globalZoom,
            globalStartNodeEUID=globalStartNodeEUID,
        )

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def add_new_node(self):
        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))

        new_ci = bobdb.Base.classes.container_instance(name="newthing")
        bobdb.session.add(new_ci)
        bobdb.session.commit()
        return {"euid": new_ci.euid}

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def get_node_info(self, euid):
        BO = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        node_dat = BO.get_by_euid(euid)

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

    @cherrypy.expose
    @cherrypy.tools.json_out()
    @require_auth(redirect_url="/login")
    def generate_dag_json_from_all_objects(self, output_file="dag.json"):
        # Define colors for each TABLECLASS_instance
        BO = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))           
        last_schema_edit_dt = BO.get_most_recent_schema_audit_log_entry()

        if (
            "schema_mod_dt" not in cherrypy.session
            or cherrypy.session["schema_mod_dt"] != last_schema_edit_dt.changed_at
        ):
            print(
                f"Dag WILL BE Regenerated, Schema Has Changed. {output_file} being generated."
            )
        else:
            print(
                f"Dag Not Regenerated, Schema Has Not Changed. {output_file} unchanged."
            )
            return
        cherrypy.session["schema_mod_dt"] = last_schema_edit_dt.changed_at

        colors = {
            "container_instance": "#372568",
            "content_instance": "#4560D5",
            "workflow_instance": "#2CB6F0",
            "workflow_step_instance": "#93FE45",
            "equipment_instance": "#7B0403",
            "object_set_instance": "#FE9B2D",
            "actor_instance": "#FEDC45",
            "test_requisition_instance": "#FDDC45",
            "data_instance": "#FCDC45",
            "generic_instance": "pink",
            "action_instance": "#FEDC25",
        }
        sub_colors = {"well": "#70658c"}

        # Collect all instances and lineages from different tables
        instances = []
        lineages = []
        for table_class_name, color in colors.items():
            if hasattr(BO.Base.classes, table_class_name):
                table_class = getattr(BO.Base.classes, table_class_name)
                instances.extend(
                    BO.session.query(table_class).filter_by(is_deleted=False).all()
                )
                lineage_class_name = table_class_name + "_lineage"
                if hasattr(BO.Base.classes, lineage_class_name):
                    lineage_class = getattr(BO.Base.classes, lineage_class_name)
                    lineages.extend(
                        BO.session.query(lineage_class)
                        .filter_by(is_deleted=False)
                        .all()
                    )

        lineages.extend(
            BO.session.query(BO.Base.classes.generic_instance_lineage)
            .filter_by(is_deleted=False)
            .all()
        )

        # Construct nodes and edges
        nodes = []
        edges = []

        for instance in instances:
            classn = (
                str(instance.__class__).split(".")[-1].replace(">", "").replace("'", "")
            )

            node = {
                "data": {
                    "id": instance.euid,
                    "type": "instance",
                    "euid": instance.euid,
                    "name": instance.name,
                    "btype": instance.super_type,
                    "super_type": instance.super_type,
                    "b_sub_type": instance.super_type
                    + "."
                    + instance.btype
                    + "."
                    + instance.b_sub_type,
                    "version": instance.version,
                    "color": colors[classn]
                    if instance.btype != "well"
                    else sub_colors["well"],
                },
                "position": {"x": 0, "y": 0},
                "group": "nodes",
            }

            nodes.append(node)

            if hasattr(instance, "in_container") and len(instance.in_container) > 0:
                for container in instance.in_container:
                    edge = {
                        "data": {
                            "source": instance.euid,
                            "target": container.euid,
                            "id": f"{container.euid}_{instance.euid}",
                        },
                        "group": "edges",
                    }
                    edges.append(edge)

            if hasattr(instance, "in_workflow"):
                if instance.in_workflow not in [None]:
                    wf = instance.in_workflow
                    edge = {
                        "data": {
                            "source": wf.euid,
                            "target": instance.euid,
                            "id": f"{wf.euid}_{instance.euid}",
                        },
                        "group": "edges",
                    }
                    edges.append(edge)

        for lineage in lineages:
            if (
                not BO.get(lineage.child_instance_uuid).is_deleted
                and not BO.get(lineage.parent_instance_uuid).is_deleted
            ):
                edge = {
                    "data": {
                        "source": BO.get(lineage.parent_instance_uuid).euid,
                        "target": BO.get(lineage.child_instance_uuid).euid,
                        "id": lineage.euid,
                    },
                    "group": "edges",
                }
                edges.append(edge)
            else:
                pass
        # Construct JSON structure
        dag_json = {
            "elements": {"nodes": nodes, "edges": edges},
            "style": [
                {
                    "selector": "node",
                    "style": {"background-color": "data(color)", "label": "data(name)"},
                },
                {
                    "selector": "edge",
                    "style": {
                        "width": "3px",
                        "line-color": "rgb(204,204,204)",
                        "source-arrow-color": "rgb(204,204,204)",
                        "source-arrow-shape": "triangle",
                        "curve-style": "bezier",
                        "control-point-step-size": "40px",
                    },
                },
            ],
            "data": {},
            "zoomingEnabled": True,
            "userZoomingEnabled": True,
            "zoom": 1.8745865634962724,
            "minZoom": 1e-50,
            "maxZoom": 1e50,
            "panningEnabled": True,
            "userPanningEnabled": True,
            "pan": {"x": 180.7595665772659, "y": 52.4950387619553},
            "boxSelectionEnabled": True,
            "renderer": {"name": "canvas"},
        }

        # Write to file
        with open(output_file, "w") as f:
            json.dump(dag_json, f, indent=4)

        print(f"All DAG JSON saved to {output_file}")

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def get_dag(self):
        dag_data = {"elements": {"nodes": [], "edges": []}}
        if os.path.exists("dag.json"):
            with open("dag.json", "r") as f:
                dag_data = json.load(f)

        return dag_data

    @cherrypy.expose
    @cherrypy.tools.json_in()
    def update_dag(self):
        input_json = cherrypy.request.json
        filename = "dag_{}.json".format(datetime.now().strftime("%Y%m%d%H%M%S"))
        with open(filename, "w") as f:
            json.dump(input_json, f)
        return {"status": "success", "filename": filename}

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def add_new_edge(self):
        BO = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        input_data = cherrypy.request.json
        parent_euid = input_data["parent_uuid"]
        child_euid = input_data["child_uuid"]
        ### I THINK THESE ARE BACKWARDS... trying to flip them
        BO.create_generic_instance_lineage_by_euids(parent_euid, child_euid)

        return {"euid": str(new_edge.euid)}

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def delete_node(self):
        input_data = cherrypy.request.json
        node_euid = input_data["euid"]
        BO = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        BO.delete(euid=node_euid)
        BO.session.flush()
        BO.session.commit()

        return {
            "status": "success",
            "message": "Node and associated lineage records deleted successfully.",
        }

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def delete_edge(self):
        input_data = cherrypy.request.json
        edge_euid = input_data["euid"]

        bobdb = BloomObj(BLOOMdb3(app_username=cherrypy.session['user']))
        bobdb.delete(bobdb.get_by_euid(edge_euid))
        bobdb.session.flush()
        bobdb.session.commit()

        return {"status": "success", "message": "Edge deleted successfully."}


if __name__ == "__main__":
    root_server_dir = os.path.abspath(sys.argv[1])

    cherrypy.config.update(
        {
            "tools.staticdir.on": True,
            "tools.staticdir.dir": root_server_dir,
            "server.socket_host": "0.0.0.0",
            "server.socket_port": 8080,
            "server.thread_pool": 20,
            "server.socket_queue_size": 50,
            "tools.sessions.on": True,
            "tools.sessions.timeout": 66,  # Session timeout in minutes
        }
    )

    cherrypy.quickstart(WorkflowService(), "/")
