from setuptools import setup, find_packages
import sys

with open("network_tester/version.py", "r") as f:
    exec(f.read())

requirements = ["rig>=2.0.0,<3.0.0", "numpy>1.6", "six", "enum_compat"]

setup(
    name="network_tester",
    version=__version__,
    packages=find_packages(),
    package_data={'network_tester': ['binaries/*.aplx']},

    # Metadata for PyPi
    url="https://github.com/project-rig/network_tester",
    author="Jonathan Heathcote",
    description="SpiNNaker network experiment library.",
    license="GPLv2",

    # Requirements
    install_requires=requirements,
)
