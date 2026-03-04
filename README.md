# pyTermite

<p align="center">
  <img src="branding/logo.png" alt="pyTermite logo" width="240" />
</p>

[![readthedocs](https://app.readthedocs.org/projects/pytermite/badge/?version=latest)](https://pytermite.readthedocs.io/en/latest/index.html)

[![codecov](https://codecov.io/github/cimt-unia/pyTermite/graph/badge.svg?token=L3NLAHQJDY)](https://codecov.io/github/cimt-unia/pyTermite)

[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/cimt-unia/pyTermite/main.svg)](https://results.pre-commit.ci/latest/github/cimt-unia/pyTermite/main)

pyTermite is a small toolkit that simplifies discovering, connecting to and
controlling a swarm of GoPro cameras over USB and mDNS. It wraps parts of the
`open_gopro` library and provides a convenient CLI and small Python API for
automation and testing.

Key features
- Discover GoPro devices via mDNS/USB
- Connect to multiple cameras concurrently
- Query camera info and runtime state
- Start/stop recording on multiple cameras simultaneously
- Interactive REPL and programmatic API

Quick start
-----------
Create a virtual environment, install dependencies and run the demo script:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python demo.py
```

Running the CLI
---------------
After installation you can use the bundled CLI. Examples::

```bash
# discover devices (waits for mDNS / USB discovery)
pytermite scan --timeout 5

# connect to discovered devices automatically
pytermite connect --auto

# connect using explicit serials
pytermite connect --serials S123,S456

# start recording on connected devices
pytermite record start

# disconnect
pytermite disconnect
```

Testing
-------
Run the test suite with pytest (development dependencies include pytest and
pytest-asyncio):

```bash
python -m pip install -r dev-requirements.txt
pytest -q
```

Documentation
-------------
Build the Sphinx documentation locally and open the generated HTML:

```bash
python -m pip install -r dev-requirements.txt
cd docs
make html
# open docs/build/html/index.html
```

Contributing
------------
See `CONTRIBUTING.md` for contribution guidelines and the typical workflow
(pull requests, tests, code style).

License
-------
This project is licensed under the BSD-3-Clause license (see
`LICENSE.txt`).

Contact
-------
- Lukas Behammer — [lukas.behammer@uni-a.de](mailto:lukas.behammer@uni-a.de)
