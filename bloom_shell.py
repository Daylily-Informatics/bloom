#!/usr/bin/env python

from bloom_lims.db import BLOOMdb3
from bloom_lims.bobjs import BloomObj
import sys
import os

bobdb = BloomObj(BLOOMdb3())


from IPython import embed
embed()