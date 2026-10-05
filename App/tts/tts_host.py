"""Dedicated entry for the packaged TTS module (AronaAI-TTS.exe).

Hosts the same stdio JSON protocol as the dev-mode tts_child.py script.
Built by AronaAI.spec (second pipeline); the main program starts it via
``<exe_dir>/TTS/AronaAI-TTS.exe``.

This wrapper is load-bearing: PyInstaller flattens the entry script to
``_internal/<basename>``, so a direct tts_child.py entry would make its
``dirname**3(__file__)`` REPO_ROOT resolve to the program root instead of
``_internal``. Imported via App.tts it stays at ``_internal/App/tts/`` with
REPO_ROOT = ``_internal`` (runtime paths, optional manual gsv_models
drop-in). Also keeps PySide6 out of the TTS bundle; the ~1GB pretrained
base models are downloaded on demand into ``<exe_dir>\gsv_models`` (next
to AronaAI.exe; dev: next to main.py) with a console window showing
progress.
"""

from App.tts.tts_child import run

if __name__ == "__main__":
    run()
