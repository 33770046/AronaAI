import json
import os
import subprocess
import sys

from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QProcess,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from qfluentwidgets import qconfig

from App import config as _app_config  # noqa: F401
from .tts_config import get_voice_pack

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CHILD_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_child.py")
_CREATE_NO_WINDOW = 0x08000000
_IDLE_MS = 60_000

# 全局至多一个常驻 TTS 子进程（chat/spine 双引擎共享约束）
_LIVE_ENGINES: list["TTSEngine"] = []


class TTSEngine(QObject):
    playbackFinished = Signal()
    audioError = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._audio_output.setVolume(1.0)
        self._player.setAudioOutput(self._audio_output)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_player_error)

        self._temp_files: list[str] = []

        self._proc: QProcess | None = None
        self._queue: list[dict] = []
        self._outstanding: set[int] = set()
        self._next_id = 0
        self._active_speak_id = 0
        self._warmup_by_id: dict[int, tuple] = {}
        self._warmed_key = None
        self._stdout_buf = ""
        self._error_emitted = False
        self._consec_failures = 0
        self._idle_ms = _IDLE_MS

        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.setInterval(120_000)
        self._watchdog.timeout.connect(self._on_timeout)

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._on_idle)

        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._kill_proc)
        qconfig.ttsEnabled.valueChanged.connect(self._on_tts_enabled_changed)
        _LIVE_ENGINES.append(self)

    def speak(self, text: str, character: str, language: str,
              translate_config=None):
        if not text.strip():
            return

        pack = get_voice_pack(character, language)
        if pack is None:
            return

        self._next_id += 1
        self._active_speak_id = self._next_id
        self._error_emitted = False
        self._enqueue({
            "cmd": "speak",
            "id": self._active_speak_id,
            "text": text,
            "reference_audio": str(pack.reference_audio),
            "reference_text": pack.reference_text,
            "pack_language": pack.language,
            "gpt_model": str(pack.gpt_model),
            "sovits_model": str(pack.sovits_model),
            "translate_config": list(translate_config) if translate_config else None,
            "use_gpu": bool(qconfig.get(qconfig.ttsUseGpu)),
        })

    def warmup(self, character: str, language: str) -> None:
        """Pre-build the TTS child (imports + models) ahead of a likely speak.

        Idempotent: no-op when already warm for the same pack/device, or when
        the engine already has queued work.
        """
        pack = get_voice_pack(character, language)
        if pack is None:
            return
        use_gpu = bool(qconfig.get(qconfig.ttsUseGpu))
        key = (str(pack.gpt_model), str(pack.sovits_model), use_gpu)
        if self._proc is not None and self._warmed_key == key:
            return
        if key in self._warmup_by_id.values():
            return
        if self._queue or self._outstanding:
            return
        self._next_id += 1
        rid = self._next_id
        self._warmup_by_id[rid] = key
        self._enqueue({
            "cmd": "warmup",
            "id": rid,
            "gpt_model": str(pack.gpt_model),
            "sovits_model": str(pack.sovits_model),
            "use_gpu": use_gpu,
        })

    def _enqueue(self, req: dict) -> None:
        self._idle_timer.stop()
        self._queue.append(req)
        self._ensure_proc()

    def _ensure_proc(self) -> None:
        if self._proc is not None:
            state = self._proc.state()
            if state == QProcess.ProcessState.Running:
                self._pump()
                return
            if state == QProcess.ProcessState.Starting:
                return  # started signal will pump
            self._proc = None
        self._reap_idle_others()
        self._start_proc()

    def _reap_idle_others(self) -> None:
        for other in list(_LIVE_ENGINES):
            if other is self or other._proc is None:
                continue
            if other._outstanding or other._queue:
                continue
            other._kill_proc()

    @staticmethod
    def _python_exe() -> str:
        venv = os.path.join(_REPO_ROOT, ".venv", "Scripts", "python.exe")
        if os.path.isfile(venv):
            return venv
        return sys.executable

    def _start_proc(self):
        self._stdout_buf = ""

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        proc.setWorkingDirectory(_REPO_ROOT)
        proc.started.connect(self._on_proc_started)
        proc.readyReadStandardOutput.connect(self._on_proc_stdout)
        proc.readyReadStandardError.connect(self._on_proc_stderr)
        proc.finished.connect(self._on_proc_finished)
        proc.errorOccurred.connect(self._on_proc_error)

        env = [f"{k}={v}" for k, v in os.environ.items()]
        env.append("PYTHONUNBUFFERED=1")
        proc.setEnvironment(env)

        self._proc = proc
        proc.start(self._python_exe(), ["-X", "utf8", _CHILD_SCRIPT])

    def _on_proc_started(self):
        proc = self.sender()
        if proc is not self._proc:
            return
        self._pump()

    def _pump(self) -> None:
        if self._outstanding or not self._queue:
            return
        proc = self._proc
        if proc is None or proc.state() != QProcess.ProcessState.Running:
            return
        req = self._queue.pop(0)
        self._outstanding.add(req.get("id"))
        self._watchdog.start()
        data = (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8")
        proc.write(data)

    def _on_proc_stdout(self):
        proc = self.sender()
        if proc is not self._proc:
            return
        data = bytes(proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._drain_stdout(data)

    def _drain_stdout(self, data: str):
        self._stdout_buf += data
        while "\n" in self._stdout_buf:
            line, self._stdout_buf = self._stdout_buf.split("\n", 1)
            self._handle_line(line.strip())

    def _handle_line(self, line: str):
        if not line:
            return
        try:
            obj = json.loads(line)
        except ValueError:
            return
        if not isinstance(obj, dict):
            return
        event = obj.get("event")
        rid = obj.get("id")
        if event == "result":
            self._on_result(rid, str(obj.get("wav", "")))
        elif event == "ready":
            self._on_ready(rid)
        elif event == "error":
            self._on_child_error(rid, str(obj.get("msg", "TTS child error")))

    def _on_result(self, rid, wav_path: str):
        if rid in self._outstanding:
            self._outstanding.discard(rid)
        self._consec_failures = 0
        if rid != self._active_speak_id:
            # stale result (a newer speak superseded it): discard the file
            if os.path.isfile(wav_path):
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass
        elif not os.path.isfile(wav_path):
            if not self._error_emitted:
                self._error_emitted = True
                self.audioError.emit(f"File not found: {wav_path}")
        else:
            self._temp_files.append(wav_path)
            if len(self._temp_files) > 5:
                old = self._temp_files.pop(0)
                try:
                    os.unlink(old)
                except OSError:
                    pass
            self._player.setSource(QUrl.fromLocalFile(wav_path))
            self._player.play()
        self._advance()

    def _on_ready(self, rid):
        if rid in self._outstanding:
            self._outstanding.discard(rid)
        self._consec_failures = 0
        key = self._warmup_by_id.pop(rid, None)
        if key is not None:
            self._warmed_key = key
        self._advance()

    def _on_child_error(self, rid, msg: str):
        if rid in self._outstanding:
            self._outstanding.discard(rid)
        if rid in self._warmup_by_id:
            # warmup failure: child already dropped its state; the next speak
            # will build again and surface its own error if it fails too
            self._warmup_by_id.pop(rid, None)
        elif rid == self._active_speak_id and not self._error_emitted:
            self._error_emitted = True
            self.audioError.emit(msg)
        self._advance()

    def _advance(self) -> None:
        if self._outstanding:
            return
        if self._queue:
            self._pump()
            return
        self._watchdog.stop()
        self._reap_idle_others()
        self._idle_timer.start(self._idle_ms)

    def _on_proc_stderr(self):
        proc = self.sender()
        if proc is not self._proc:
            return
        data = bytes(proc.readAllStandardError())
        if not data:
            return
        try:
            sys.stderr.buffer.write(data)
            sys.stderr.buffer.flush()
        except Exception:
            pass

    def _on_proc_finished(self, exit_code: int, exit_status):
        proc = self.sender()
        if proc is not self._proc:
            return
        leftover = bytes(proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if leftover:
            self._drain_stdout(leftover)
        if self._stdout_buf.strip():
            self._handle_line(self._stdout_buf.strip())
            self._stdout_buf = ""
        self._watchdog.stop()
        self._idle_timer.stop()
        proc.deleteLater()
        self._proc = None
        lost_active = self._active_speak_id in self._outstanding
        self._outstanding.clear()
        self._warmup_by_id.clear()
        self._warmed_key = None
        if lost_active and not self._error_emitted:
            self._error_emitted = True
            self.audioError.emit(f"TTS 进程异常退出 (code={exit_code})")
        if self._queue:
            self._consec_failures += 1
            if self._consec_failures >= 3:
                dropped_active = self._active_speak_id in {
                    r.get("id") for r in self._queue
                }
                self._queue.clear()
                if dropped_active and not self._error_emitted:
                    self._error_emitted = True
                    self.audioError.emit(f"TTS 进程异常退出 (code={exit_code})")
            else:
                QTimer.singleShot(500, self._ensure_proc)

    def _on_proc_error(self, error):
        proc = self.sender()
        if proc is not self._proc:
            return
        if error != QProcess.ProcessError.FailedToStart:
            return
        queued_ids = {r.get("id") for r in self._queue}
        lost_active = (
            self._active_speak_id in queued_ids
            or self._active_speak_id in self._outstanding
        )
        self._queue.clear()
        self._outstanding.clear()
        self._warmup_by_id.clear()
        self._warmed_key = None
        self._watchdog.stop()
        self._idle_timer.stop()
        proc.deleteLater()
        self._proc = None
        if lost_active and not self._error_emitted:
            self._error_emitted = True
            self.audioError.emit("TTS 子进程启动失败")

    def _on_timeout(self):
        lost_active = self._active_speak_id in self._outstanding
        if lost_active and not self._error_emitted:
            self._error_emitted = True
            self.audioError.emit("TTS 合成超时")
        self._kill_proc()

    def _on_idle(self):
        if self._outstanding or self._queue:
            return
        self._kill_proc()

    def _on_tts_enabled_changed(self, value):
        if not value:
            self._player.stop()
            self._kill_proc()

    def _kill_proc(self):
        self._watchdog.stop()
        self._idle_timer.stop()
        self._queue.clear()
        self._outstanding.clear()
        self._warmup_by_id.clear()
        self._warmed_key = None
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        for signal in (
            proc.started,
            proc.readyReadStandardOutput,
            proc.readyReadStandardError,
            proc.finished,
            proc.errorOccurred,
        ):
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass
        if proc.state() != QProcess.ProcessState.NotRunning:
            pid = proc.processId()
            if pid:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        capture_output=True,
                        creationflags=_CREATE_NO_WINDOW,
                    )
                except OSError:
                    proc.kill()
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.kill()
            proc.waitForFinished(3000)
        proc.deleteLater()

    def _on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.playbackFinished.emit()

    def _on_player_error(self, error, message):
        self.audioError.emit(message)

    def stop_playback(self):
        self._player.stop()

    def stop(self):
        self._kill_proc()
        self._player.stop()
