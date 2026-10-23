"""
Hermes Control — a desktop control panel for Nous Research's Hermes Agent.

Hermes Agent does the thinking. This app installs it without disturbing
anything else on the machine, keeps it running, exposes every setting it
documents, and gives it a window on Windows, macOS and Linux.

Layout, bottom up:

* :mod:`platforms`  — every operating-system difference, in one file.
* :mod:`cli`        — the only thing that talks to Hermes. No Qt.
* :mod:`confschema` — derives the settings schema from Hermes's own annotated
  config, so the editor is complete for the installed version.
* :mod:`providers`  — the model catalogue, local probing, and the context
  window rule that decides whether a local model can be used at all.
* :mod:`theme`      — design tokens and the stylesheet built from them.
* :mod:`ui`         — Qt. Nothing below this line imports it.
"""

__version__ = "1.6.0"
__all__ = ["__version__"]
