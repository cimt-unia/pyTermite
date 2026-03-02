CLI overview
============

The command-line interface (CLI) exposes convenience commands to discover,
connect to and control multiple GoPro cameras from the terminal. The main
entry point is provided by the top-level ``pytermite`` commands implemented
in the ``pytermite.py`` module.

Features
--------
- Interactive REPL for repeated commands
- Scan for connected GoPros via USB/mdns
- Connect / disconnect and start/stop recording

Global options
--------------
- ``--interactive, -i``: Keep the process open and drop into the interactive REPL after command execution.
- ``--help, -h``: Show help message and available commands.
- ``--version, -v``: Show the pyTermite version.

Commands
--------
Below is a short description of the primary CLI commands provided by pyTermite. Each command is available when you install the package and run ``pytermite`` from the shell; the examples show the equivalent direct invocation via the module's CLI entry points.

scan
~~~~
Discover GoPro devices connected to the host over USB/mDNS.

Usage::

    pytermite scan [--timeout SECONDS]

Options
- ``--timeout, -t``: Maximum seconds to wait for discovery (default: 10).

Description
- Runs a discovery task that listens for mDNS advertisements and scans the USB bus until the user interrupts (press Enter) or the timeout is reached.
- The discovered serial numbers are cached for subsequent commands in the running process if run interactively, and printed to the console for one-shot usage.

Example::

    pytermite scan --timeout 5

connect
~~~~~~~
Connect to one or more GoPro devices using serial numbers or automatic discovery.

Usage::

    pytermite connect [--auto] [--serials SERIALS] [--serials-file FILE]

Options
- ``--auto``: Automatically discover and connect to all detected devices.
- ``--serials, -s``: Comma-separated serial numbers to connect to (e.g. ``S1,S2``).
- ``--serials-file, -f``: Path to a JSON file containing a mapping of camera names to serial numbers (environment variable: ``PYTERMITE_SERIALS_PATH``).

Description
- Builds WiredConnection objects for the requested serials and attempts to open an async connection to each camera. Successful connections are tracked in the running process and are used by subsequent commands such as ``record``.

Example::

    # Connect to devices found earlier by `scan`
    pytermite connect --auto

    # Connect to two known serials
    pytermite connect --serials S123,S456

    # Load serials from a JSON file
    pytermite connect --serials-file ./config/serials.json

disconnect
~~~~~~~~~~
Disconnect from all currently connected GoPro devices.

Usage::

    pytermite disconnect

Description
- Gracefully closes each active connection and removes them from the in-memory connection cache. If the CLI was started with ``--interactive`` the process will remain running and return to the REPL.

Example::

    pytermite disconnect

record
~~~~~~
Start or stop recording on all currently connected GoPro cameras.

Usage::

    pytermite record start
    pytermite record stop

Description
- Sends a REST ``/shutter/{start|stop}`` call to each connected camera's HTTP endpoint. The command performs the requests concurrently and logs progress.

Example::

    # Start recording on all connected cameras
    pytermite record start

Interactive REPL and convenience notes
-------------------------------------
- Running ``pytermite`` with no subcommand launches an interactive REPL. The REPL supports typing ``help`` to view available commands and ``exit`` or ``quit`` to leave.
- Use the global ``--interactive`` (``-i``) flag with any one-shot command to keep the process open and return to the REPL after the command completes.
- For automation tasks consider using the underlying Python API exposed by the ``pytermite`` package (modules: :mod:`pytermite.connection`, :mod:`pytermite.commands`, :mod:`pytermite.utils`) instead of the CLI.
