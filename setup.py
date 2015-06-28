from setuptools import setup, find_packages
import sys

with open("network_tester/version.py", "r") as f:
    exec(f.read())

setup(
    name="network_tester",
    version=__version__,
    packages=find_packages(),

    # Metadata for PyPi
    author="Jonathan Heathcote",
    description="SpiNNaker network experiment library.",
    license="GPLv2",

    # Requirements
    install_requires=["rig", "numpy>1.6", "six", "enum34"],
)
