"""Only explicit local configuration; no DB bootstrap or broad test fixtures."""
import os

os.environ["BLOOM_DEPLOYMENT_CODE"] = "accession-unit"
from tests.support.runtime import ensure_test_runtime_environment

ensure_test_runtime_environment()
