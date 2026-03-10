# Zebra Printer Configuration
Bloom relies on [zebra_day](https://github.com/Daylily-Informatics/zebra_day) to administer the lab printer fleet and broker print requests. Please see that repository for printer-specific setup details. The notes below are a Bloom-focused quick reference.


## Printer Setup
* From the venv you are running Bloom from, the `zebra_day` package should be pre-installed.  To start the admin web interface, from your venv, run `zday_start`.  This will start the admin web interface on port 8118 on the machine you are running Bloom from.

### Detect Printers On Your Local Network
_this MUST be done at least once when setting up a new bloom install_ && _done again when adding new printers_
* `zebra_day` can scan the local network (barring firewal rules blocking this) and update the venv printer config file with detected printers. Open the `Scan Network For Zebra Printers` page @ `http://localhost:8118/build_new_printers_config_json`. You IP prefix should be auto detected, else enter the first three sections (ie `192.168.1`). Enter a few character 'Lab Code' (only alphanumeric, no whitespace, etc.), this will be the code under which detected printers are added to the json config. The scan might take a few minutes to complete.

![Printer Scan](./imgs/bc_scan.png)

* The scan will return all detected printers. The `Lab Code` + `Printer Name` will uniquely identify each printer config.  There are several label styles included with `zebra_day`, you may specify a label style with each print request. Make sure the label stock matches the label style. See `zebra_day` docs for more information on label styles. I will use the common `2x1in` label style for the rest of this document. From the `zebra_day` admin web interface, you can print a test label to verify the printer is working.

* The printers visible in the Scan Report will be the printers available in the bloom UI.  NOTE- you may change names of the printers, see the zebra_day docs for more information.

![Printer Test](./imgs/printer_fleet_status.png)


## Label Template Modification
* see zebra_day docs for more information on label templates.

# Printing From Bloom
* Most objects in bloom have basic barcode printing enabled.  You may customize the basic printing ( change what information is printed, how it's printed, the number printed). The default print behavior will print the EUID as a scannable barcode, the EUID as a human readable string, and if possible, the object _user specified_ name (which may be '' if not specifically set).
* Each user session will display the available printers for the lab code, as well as the default label styles. With each print request, these may be set.
* Keep in mind, these interfaces _are not optimized_ for production use. They demonstrate the finest level to which operations can be customized. Production interfaces will likely benefit from rolling up many of these fine steps.
