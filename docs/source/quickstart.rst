Quickstart
==========

This quickstart shows the simplest way to run the demo that ships with
this repository and to build the documentation locally.

Prerequisites
-------------
- Python 3.12+ (project was developed with Python 3.12)
- A working virtual environment with project dependencies installed:

.. code-block:: bash

    python -m venv .venv
    source .venv/bin/activate
    pip install pyTermite

Running the demo
----------------
The repository contains a small ``demo.py`` script that demonstrates a basic
workflow for discovering and collecting information from GoPro devices.

From the project root run::

.. code-block:: bash

    python demo.py

Make sure to have any hardware connected and the serials file configured under
``./config/serials.json`` next to the ``demo.py`` script.


Notes
-----
- The demo will attempt to read serial numbers from ``./config/gopro_serials.json``.
- The demo performs real network and hardware I/O; for tests and CI you
  should mock those parts or run the demo on a machine with attached GoPro
  devices.
