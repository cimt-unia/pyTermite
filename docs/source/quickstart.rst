Quickstart
==========

This quickstart shows the simplest way to run the demo that ships with
this repository and to build the documentation locally.

Prerequisites
-------------
- Python 3.12+ (project was developed with Python 3.12)
- A working virtual environment with project dependencies installed:

  python -m venv .venv
  source .venv/bin/activate
  python -m pip install -r requirements.txt

Running the demo
----------------
The repository contains a small ``demo.py`` script that demonstrates a basic
workflow for discovering and collecting information from GoPro devices.

From the project root run::

    python demo.py

Notes
-----
- The demo will attempt to read serial numbers from ``./config/gopro_serials.json``.
- The demo performs real network and hardware I/O; for tests and CI you
  should mock those parts or run the demo on a machine with attached GoPro
  devices.

Building the documentation locally
----------------------------------
If you want to preview the Sphinx documentation locally, install Sphinx and
build the HTML output::

    python -m pip install -r dev-requirements.txt
    cd docs
    make html

The generated HTML will be available under ``docs/build/html/``.
