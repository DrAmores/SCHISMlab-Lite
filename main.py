"""Punto de entrada de la interfaz (tambien lo usan los tests de NiceGUI): python main.py"""
from schismlab.gui.app import *  # noqa: F401,F403  (registra las paginas)
from schismlab.gui.app import main

if __name__ in {"__main__", "__mp_main__"}:
    main()
