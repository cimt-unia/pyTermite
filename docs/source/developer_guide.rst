Developer Guide
================

This developer guide explains how to set up a development environment, run
and test the project, contribute code, and build the documentation.

Repository layout
-----------------
Top-level layout (important files and folders):

- ``src/pytermite/``: Python package containing the application logic.
- ``docs/``: Sphinx documentation sources and generated HTML under
  ``docs/build/html``.
- ``tests/``: pytest test suite for unit tests.
- ``requirements.txt``: runtime dependencies.
- ``dev-requirements.txt``: development dependencies (formatters, linters,
  test helpers, Sphinx).
- ``demo.py``: small demo script that shows a typical usage flow.

Quick setup (recommended)
-------------------------
Create and activate a virtual environment, then install dev dependencies:

.. code-block:: bash

    python -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -e . --group dev


Running the demo
----------------
The demo script demonstrates the functionality of the API. Ensure any hardware is
connected and the serials file is configured under ``./config/serials.json`` next to the ``demo.py`` script.

.. code-block:: bash

    python demo.py


Running tests
-------------
Run the full test suite possibly with coverage reports from the project root via pre-configured tox:

.. code-block:: bash

    tox r -m test [coverage]


To run a single test file or test function, use pytest with filtering:

.. code-block:: bash

    pytest tests/test_utils.py::test_serialize_fallback_object -q


Pre-commit hooks
-----------------
The project uses pre-commit hooks to enforce code quality and consistency. To set up the hooks
locally, run:

.. code-block:: bash

    pre-commit install
    pre-commit install-hooks

You can manually run the hooks on all files with:

.. code-block:: bash

    pre-commit run --all-files

or via tox:

.. code-block:: bash

    tox r -m pre-commit


Linting and formatting
----------------------
You can run linters and formatters as configured in the ``pyproject.toml``.
For example, to run ruff locally without tox:

.. code-block:: bash

    ruff format .
    ruff check .


Type checking
-------------
The project ships type hints and a ``py.typed`` file. Use mypy for static type
checking (install it into your dev environment):

.. code-block:: bash

    mypy .


You can combine type checking with linting and formatting in a single tox run:

.. code-block:: bash

    tox r -m lint


Adding tests
------------
- Place test files in the ``tests/`` directory and name them ``test_*.py``.
- Prefer small, focused unit tests and use fixtures in ``tests/conftest.py``.
- Mock external I/O (network, hardware) to keep tests fast and deterministic.

Example test structure:

- ``tests/test_utils.py`` — pure utility function tests (fast, no IO).
- ``tests/test_commands.py`` — mock HTTP and aiohttp to test command logic.
- ``tests/test_connection.py`` — async connection flows; use pytest-asyncio.


Writing documentation
---------------------
The project uses Sphinx with the ``numpydoc`` extension. Source files live
under ``docs/source``. To build the documentation locally:

.. code-block:: bash

    sphinx-build -b html docs/source docs/build/html

or:

.. code-block:: bash

    sphinx-autobuild docs/source docs/build/html

When documenting code use numpydoc style for docstrings.


Contributing
------------
Follow the project's ``CONTRIBUTING.md`` guidelines. Typical steps for a
feature or bugfix:

1. Fork the repository and create a feature branch.
2. Write tests that reproduce the bug or assert new behaviour.
3. Implement the change, keeping API compatibility where possible.
4. Run the full test suite and linters locally.
5. Open a pull request with a clear description and link to any related
   issues.

Commit message style (Conventional Commits)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
To keep the project history clear and to support automated changelog generation,
please use the Conventional Commits specification for commit messages where
possible. The basic form is::

    <type>[optional scope]: <short description>

Common types include ``feat``, ``fix``, ``docs``, ``style``, ``refactor``,
``test`` and ``chore``. Examples::

    feat(cli): add `--interactive` flag
    fix(connection): handle response timeout when connecting
    docs: update developer guide with testing instructions

Using this convention makes it easier to generate changelogs and to review
history.


Release process
---------------
Releases are automatically built and published to PyPI via GitHub Actions when a new tag is pushed to the ``main`` branch.
To create a new release:

- Bump the version in ``src/pytermite/__init__.py`` under ``__version__``.
- Tag the release in git and create a GitHub release.


Architecture notes
------------------
- ``pytermite.utils``: small, pure helper functions (JSON I/O, serialization,
  URL creation). These are easy to unit test.
- ``pytermite.connection``: discovery and lifecycle management of
  ``WiredConnection`` objects. This module contains async flows and interacts
  with external network discovery helpers (mDNS) and the ``open_gopro`` library.
- ``pytermite.commands``: high-level orchestration commands that operate on
  connected devices (get info, get state, control shutter). These functions
  are central to CLI behavior and are designed to be reused from other
  programs.
- ``pytermite.pytermite``: CLI layer exposing commands via Click and an
  interactive REPL.


Debugging tips
--------------
- Use the tests as a safety net; run a single failing test in verbose mode to
  iterate quickly.
- Add logging via ``structlog`` (used across the project) to get structured
  runtime information. Configure log level in your local environment when
  debugging async flows.

Contact and further help
------------------------
If you need help with the codebase, refer to the ``CONTRIBUTING.md`` and
open issues or pull requests on the repository. For complex hardware-related
problems consider running the demo on a host with attached devices and use
structured logging to capture runtime behavior.
