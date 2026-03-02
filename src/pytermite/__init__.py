"""pyTermite is a small package to control multiple GoPro cameras via USB connection.

Short Summary
-------------
Provides utilities to discover, connect to and control multiple GoPro devices
connected over USB. The package exposes convenience helpers and a CLI for
interactive use.

Examples
--------
>>> import pytermite
>>> pytermite.get_version()
'0.0.1'
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


def get_version() -> str:
    """
    Return the version of the pyTermite package.

    Returns
    -------
    str
        The version string of the package.
    """
    return __version__
