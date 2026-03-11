# pyTermite

<img src="https://raw.githubusercontent.com/cimt-unia/pyTermite/main/branding/logo.png" alt="pyTermite logo" style="width: 40%; display: block; margin-left: auto; margin-right: auto;"/>

<!-- SPHINX-START-HERE -->

[![Project Status: Active – The project has reached a stable, usable state and is being actively developed.](https://www.repostatus.org/badges/latest/active.svg)](https://www.repostatus.org/#active)
[![readthedocs](https://app.readthedocs.org/projects/pytermite/badge/?version=latest)](https://pytermite.readthedocs.io/en/latest/index.html)
[![codecov](https://codecov.io/github/cimt-unia/pyTermite/graph/badge.svg?token=L3NLAHQJDY)](https://codecov.io/github/cimt-unia/pyTermite)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/cimt-unia/pyTermite/main.svg)](https://results.pre-commit.ci/latest/github/cimt-unia/pyTermite/main)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.0-4baaaa.svg)](https://github.com/cimt-unia/pyTermite/blob/main/CODE_OF_CONDUCT.md)

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

## Quick start

If you want to try out pyTermite quickly, you can install it from PyPI and run the demo script from the GitHub repository:

```bash
pip install pyTermite
python -m demo.py
```

Make sure to put the serial numbers of one or multiple connected cameras in a subdirectory `./config/gopro_serials.json` next to `demo.py` before running the script.
Structure of this file is as follows:

```json
{
  "camera_name": "camera_serial_number"
}
```

If you want to contribute or run the latest development version, you can clone the repository and install it locally.
Create a virtual environment, install dependencies and run the demo script:

```bash
git clone https://github.com/cimt-unia/pyTermite.git
cd pyTermite
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

## Running the CLI

After installation, you can use the bundled CLI. Examples:

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

## Testing

Run the test suite with coverage reporting:

```bash
pip install tox --group test
tox r -m test coverage
```

## Documentation

Build the Sphinx documentation locally and open the generated HTML:

```bash
python -m pip install -e . tox --group docs
tox r -m docs
```

or alternatively use `sphinx-autobuild`:

```bash
python -m pip install -e . tox --group docs
sphinx-autobuild docs/source docs/build/html
```

## Contributing

See [`CONTRIBUTING.md`](https://github.com/cimt-unia/pyTermite/blob/main/CONTRIBUTING.md) and the [Developer Guide](https://pytermite.readthedocs.io/en/latest/developer_guide.html) for contribution guidelines and the typical workflow
(pull requests, tests, code style).

## License

This project is licensed under the BSD-3-Clause license (see
[`LICENSE.txt`](https://github.com/cimt-unia/pyTermite/blob/main/LICENSE.txt)).

## Contact

Lukas Behammer — [lukas.behammer@uni-a.de](mailto:lukas.behammer@uni-a.de)
