"""打包版 TTS 模块（AronaAI-TTS.exe）的专用入口。

和源码运行时的 tts_child.py 使用同一套 stdio JSON 协议。由 AronaAI.spec
的第二条流水线构建，主程序通过 ``<exe_dir>/TTS/AronaAI-TTS.exe`` 启动它。

这个包装入口是必需的：PyInstaller 会把入口脚本摊平到
``_internal/<文件名>``，如果直接拿 tts_child.py 当入口，它算出来的
``dirname**3(__file__)`` REPO_ROOT 会指向程序根目录而不是 ``_internal``。
经由 App.tts 导入则仍留在 ``_internal/App/tts/``，REPO_ROOT 就是
``_internal``，运行时路径才对得上。这样也让 PySide6 不进 TTS 包。
约 1GB 的基础模型按需下载到 ``<exe_dir>\\gsv_models``（打包版在
AronaAI.exe 旁，源码运行在 main.py 旁）。
"""

from App.tts.tts_child import run

if __name__ == "__main__":
    run()
