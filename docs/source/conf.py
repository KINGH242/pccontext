"""Sphinx configuration for the pccontext documentation."""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath("../.."))

from pccontext import __version__  # noqa: E402

project = "pccontext"
copyright = f"{date.today().year}, Hareem Adderley"
author = "Hareem Adderley"
release = __version__
version = ".".join(__version__.split(".")[:2])

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx.ext.autosectionlabel",
]

autosectionlabel_prefix_document = True

templates_path = ["_templates"]
exclude_patterns = []

# -- Autodoc -----------------------------------------------------------------

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    "member-order": "bysource",
}
autodoc_typehints = "description"
autodoc_class_signature = "separated"

# pccontext imports optional/heavy third-party clients at module scope. Mock the
# ones that are awkward to import in a docs build so autodoc never needs them.
autodoc_mock_imports = ["docker"]

napoleon_google_docstring = True
# Render "Attributes:" blocks as :ivar: fields. Without this, Napoleon emits a
# separate object description per attribute, which collides with the real
# members autodoc documents (e.g. the BlockchainExplorer enum).
napoleon_use_ivar = True
napoleon_numpy_docstring = False

# -- Intersphinx -------------------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pycardano": ("https://pycardano.readthedocs.io/en/latest/", None),
}

# -- HTML output -------------------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_title = f"pccontext {release}"
html_theme_options = {
    "navigation_depth": 3,
    "collapse_navigation": False,
}
