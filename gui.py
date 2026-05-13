#!/usr/bin/env python3
"""gui.py — Interfaccia grafica per gravi-signal-ml.

Fornisce un'interfaccia utente minimalista basata su Gooey,
avvolgendo la CLI esistente senza modificarla direttamente.
"""

from gooey import Gooey
from main import main as cli_main

@Gooey(
    program_name="gravi-signal-ml",
    clear_before_run=True,
    show_restart_button=False
)
def main():
    """Entry point della GUI che richiama il main originale."""
    cli_main()

if __name__ == "__main__":
    main()
