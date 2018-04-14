"""Sphinx configuration file for an LSST stack package.

This configuration only affects single-package Sphinx documenation builds.
"""

from documenteer.sphinxconfig.stackconf import build_package_configs
import lsst.display.ds9


_g = globals()
_g.update(build_package_configs(
    project_name='display_ds9',
    version=lsst.display.ds9.version.__version__))
