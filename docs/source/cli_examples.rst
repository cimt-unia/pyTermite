CLI Examples
============

Below are some examples of how to use the ``pytermite`` CLI for various operations.

pytermite
~~~~~~~~~
.. code-block:: bash

    # Start the interactive REPL
    pytermite

    # Run a single command without entering the REPL
    pytermite scan

    # Run a command and drop into the REPL
    pytermite -i scan

scan
~~~~
.. code-block:: bash

    # Scan for connected GoPros with a timeout of 5 seconds
    pytermite scan --timeout 5

connect
~~~~~~~
.. code-block:: bash

    # Connect to devices found earlier by `scan` or scan automatically
    pytermite connect --auto

    # Connect to two known serials
    pytermite connect --serials S123,S456

    # Load serials from a JSON file
    pytermite connect --serials-file ./config/serials.json

disconnect
~~~~~~~~~~
.. code-block:: bash

    # Disconnect from all connected cameras
    pytermite disconnect

record
~~~~~~
.. code-block:: bash

    # Start recording on all connected cameras
    pytermite record start

    # Stop recording on all connected cameras
    pytermite record stop
