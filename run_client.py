import os
import sys

# S'assure que le répertoire racine du projet et le dossier temporaire PyInstaller sont dans sys.path
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

if hasattr(sys, "_MEIPASS") and sys._MEIPASS not in sys.path:
    sys.path.insert(0, sys._MEIPASS)

from client.gui import main

if __name__ == "__main__":
    main()
