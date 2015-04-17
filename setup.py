from setuptools import setup, find_packages
import sys

setup(
    name="network_tester",
    version="0.0.1-dev",
    packages=find_packages(),

    # Metadata for PyPi
    author="Jonathan Heathcote",
    description="SpiNNaker network experiment generator.",
    license="GPLv2",

    # Requirements
    install_requires=["six", "rig"],
    tests_require=["pytest>=2.6", "pytest-cov", "mock"],
)
