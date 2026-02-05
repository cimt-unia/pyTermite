"""
pyTermite is a Python package to control multiple GoPro cameras via USB connection.

It allows users to connect to multiple GoPro devices, retrieve camera information
and status, and start/stop recording on all connected cameras simultaneously.
"""

#  Copyright (c) 2026 by Lukas Behammer
#  University of Augsburg
#  Department of Computer Science
#  Chair of Informatics for Medical Technology
#
#  SPDX-License-Identifier: BSD-3-Clause

__version__ = "0.0.1"
__author__ = "Lukas Behammer"

__all__ = [
    "get_version",
    "connection",
    "commands",
    "utils",
]

import pytermite.commands as commands
import pytermite.connection as connection
import pytermite.utils as utils


def get_version():
    """
    Return the version of the pyTermite package.

    Returns
    -------
    str
        The version string of the package.
    """
    return __version__
