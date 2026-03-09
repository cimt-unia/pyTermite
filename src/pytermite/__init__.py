# ruff: noqa: RUF067
"""
`pyTermite` is a small package to control multiple GoPro cameras via USB connection.

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
    "commands",
    "connection",
    "get_version",
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
