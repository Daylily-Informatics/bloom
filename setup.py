from setuptools import setup, find_packages


def get_version():
    """Get version from bloom_lims._version module."""
    import os
    import re

    # Read version from _version.py without importing (avoids dependency issues)
    version_file = os.path.join(
        os.path.dirname(__file__), "bloom_lims", "_version.py"
    )

    with open(version_file, "r") as f:
        content = f.read()

    # Extract FALLBACK_VERSION as the setup.py version
    # This ensures pip install works offline
    match = re.search(r'FALLBACK_VERSION\s*=\s*["\']([^"\']+)["\']', content)
    if match:
        return match.group(1)

    return "0.0.0"  # Should never happen


setup(
    name="bloom_lims",
    version=get_version(),
    packages=find_packages(),
    install_requires=[
        # Add dependencies here,
        # 'pytest',
    ],
    entry_points={
        "console_scripts": [
            "install-bloom=bloom_lims.thing:main",
            "bloom-backup=bloom_lims.backup.cli:main",
            "bloom=bloom_lims.cli:main",
        ],
    },
)
