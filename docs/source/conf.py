# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'pyTermite'
copyright = '2026, Lukas Behammer'
author = 'Lukas Behammer'

with open("../../src/pytermite/__init__.py") as f:
    setup_lines = f.readlines()
version = "vUndefined"
for line in setup_lines:
    if line.startswith("__version__"):
        version = line.split('"')[1]
        break

release = version


# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.coverage",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.autosummary",
    "numpydoc",
    "sphinxcontrib.email",
    "sphinx_copybutton",
]

exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'pydata_sphinx_theme'
html_favicon = '../../branding/logo.png'
html_title = f"{project} v{release}"
html_baseurl = os.environ.get("READTHEDOCS_CANONICAL_URL", "/")
html_logo = "../../branding/logo.png"
html_theme_options = {
    "icon_links": [
        {
            # Label for this link
            "name": "GitHub",
            # URL where the link will redirect
            "url": "https://github.com/cimt-unia/pyTermite",  # required
            # Icon class (if "type": "fontawesome"), or path to local image (if "type": "local")
            "icon": "fa-brands fa-square-github",
            # The type of image to be used (see below for details)
            "type": "fontawesome",
        }
   ]
}


# -- Options for Autodoc -----------------------------------------------------
autodoc_member_order = "groupwise"
autodoc_default_options = {
    "members": None,
}


# -- Options for Napoleon -----------------------------------------------------
napoleon_google_docstring = False
napoleon_use_admonition_for_notes = True


# -- Options for Coverage -----------------------------------------------------
coverage_modules = ["pytermite"]
coverage_statistics_to_stdout = True
