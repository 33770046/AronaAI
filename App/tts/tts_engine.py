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
from .tts_config import get_voice_pack, detect_gpu_support

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CHILD_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_child.py")
_CREATE_NO_WINDOW = 0x08000000
_IDLE_MS = 60_000

# 全局至多一个常驻 TTS 子进程（chat/spine 双引擎共享约束）
_LIVE_ENGINES: list["TTSEngine"] = []

# 启动期基础模型预取（~1GB 下载）：全局单飞，防止两个子进程并发下载
_PREFETCH_ACTIVE = False
_PREFETCH_OWNER = None
_PREFETCH_RID = 0


def _models_target_dir() -> str:
    """下载目标文件夹：exe 旁（打包）/ main.py 旁（dev），统一交给子进程环境变量。"""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "gsv_models")
    return os.path.join(_REPO_ROOT, "gsv_models")


def _migrate_legacy_cache() -> None:
    """旧版缓存 ~/.cache/gsv -> 目标文件夹（尽力而为：跨盘/占用/无权限则跳过）。"""
    target = _models_target_dir()
    cache = os.path.join(os.path.expanduser("~"), ".cache", "gsv")
    if os.path.isdir(target) or not os.path.isdir(cache):
        return
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.rename(cache, target)
    except OSError:
        pass


def _pretrained_missing() -> bool:
    """与 App/tts/tts_child.py::_models_missing 一致的 4 项检查。"""
    _migrate_legacy_cache()
    target = _models_target_dir()
    cache = os.path.join(os.path.expanduser("~"), ".cache", "gsv")
    for path in (target, cache):
        if os.path.isdir(path):
            return not (
                os.path.isdir(os.path.join(path, "chinese-hubert-base"))
                and os.path.isdir(os.path.join(path, "g2p"))
                and os.path.isdir(os.path.join(path, "sv"))
                and os.path.isfile(os.path.join(
                    path, "chinese-roberta-wwm-ext-large",
                    "cnroberta_int8_dynamic.onnx"))
            )
    return True


def _jp_langpack_missing() -> bool:
    """日文字典是否还没下载。

    对应 tts_child._ensure_jp_langpack 的两个标记文件。只做路径检查，
    引擎不导入 torch。
    """
    root = (os.path.dirname(sys.executable)
            if getattr(sys, "frozen", False) else _REPO_ROOT)
    jp = os.path.join(root, "langpacks", "jp")
    return not (
        os.path.isfile(os.path.join(jp, "openjtalk-dict", "sys.dic"))
        and os.path.isfile(os.path.join(jp, "sudachi", "system.dic"))
    )


def _settle_prefetch() -> None:
    """预取结束（成功/失败/进程退出）→ 放行其他引擎排队的请求。"""
    global _PREFETCH_ACTIVE, _PREFETCH_OWNER, _PREFETCH_RID
    if not _PREFETCH_ACTIVE:
        return
    _PREFETCH_ACTIVE = False
    _PREFETCH_OWNER = None
    _PREFETCH_RID = 0
    app = QCoreApplication.instance()
    if app is not None and QCoreApplication.closingDown():
        return  # 正在退出：不再拉起新子进程
    for eng in list(_LIVE_ENGINES):
        if eng._queue:
            eng._ensure_proc()


class TTSEngine(QObject):
    playbackFinished = Signal()
    audioError = Signal(str)
    # (百分比 0-100，None 表示进度未知；文案；是否结束)
    downloadProgress = Signal(object, str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._audio_output.setVolume(1.0)
        self._player.setAudioOutput(self._audio_output)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_player_error)

        self._temp_files: list[str] = []
        self._play_queue: list[str] = []
        self._speak_started = False
        self._speak_complete = True
        self._playback_stopped = False

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
        if qconfig.get(qconfig.ttsEnabled):
            self.prefetch_models()

    def speak(self, text: str, character: str, language: str,
              translate_config=None):
        if not text.strip():
            return

        pack = get_voice_pack(character, language)
        if pack is None:
            # 不要静默失败：缺语音包时要能看出是这里的问题，而不是"没声音"
            if not self._error_emitted:
                self._error_emitted = True
                self.audioError.emit(
                    f"未找到语音包：角色 {character} / 语言 {language}。"
                    f"请确认 Assets/TTS/{character}_{language.upper()} 下含 "
                    f".ckpt、.pth 与 reference/*.ogg，且 config.ini 已登记。")
            return

        self._next_id += 1
        self._active_speak_id = self._next_id
        self._error_emitted = False
        self._play_queue.clear()
        self._speak_started = False
        self._speak_complete = False
        self._playback_stopped = False
        self._enqueue({
            "cmd": "speak",
            "id": self._active_speak_id,
            "text": text,
            "stream": self._stream_enabled(),
            "reference_audio": str(pack.reference_audio),
            "reference_text": pack.reference_text,
            "pack_language": pack.language,
            "gpt_model": str(pack.gpt_model),
            "sovits_model": str(pack.sovits_model),
            "translate_config": list(translate_config) if translate_config else None,
            "use_gpu": bool(qconfig.get(qconfig.ttsUseGpu)),
        })

    def warmup(self, character: str, language: str) -> None:
        """在大概率要说话之前，先把 TTS 子进程（导入 + 模型）热起来。

        幂等：同一语音包/设备已经热好，或引擎已有排队任务时，什么都不做。
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
        if _PREFETCH_ACTIVE and self is not _PREFETCH_OWNER:
            # 模型下载期间不另起子进程（防并发下载），
            # 由 _settle_prefetch 在预取结束后放行
            return
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
        if getattr(sys, "frozen", False):
            # 打包版：TTS 运行时独立放在主 exe 旁边的 TTS 文件夹里，
            # 删掉这个文件夹就等于卸载该模块
            tts_exe = os.path.join(
                os.path.dirname(sys.executable), "TTS", "AronaAI-TTS.exe")
            if not os.path.isfile(tts_exe):
                self._fail_spawn(
                    "TTS module not found (TTS/AronaAI-TTS.exe). "
                    "Unpack the TTS package into the AronaAI folder to "
                    "enable speech.")
                return

        self._stdout_buf = ""

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        proc.setWorkingDirectory(_REPO_ROOT)
        proc.started.connect(self._on_proc_started)
        proc.readyReadStandardOutput.connect(self._on_proc_stdout)
        proc.finished.connect(self._on_proc_finished)
        proc.errorOccurred.connect(self._on_proc_error)

        env = [f"{k}={v}" for k, v in os.environ.items()]
        env.append("PYTHONUNBUFFERED=1")
        env.append(f"ARONA_GSV_MODELS={_models_target_dir()}")
        proc.setEnvironment(env)

        self._proc = proc
        if getattr(sys, "frozen", False):
            proc.start(tts_exe, [])
        else:
            proc.start(self._python_exe(), ["-X", "utf8", _CHILD_SCRIPT])

    def _fail_spawn(self, message: str) -> None:
        """子进程起不来（缺少模块）：清掉待办并报一次明确的错，
        而不是让请求永远排在队列里没人管。
        """
        self._proc = None
        self._queue.clear()
        self._outstanding.clear()
        self._warmup_by_id.clear()
        self._watchdog.stop()
        if not self._error_emitted:
            self._error_emitted = True
            self.audioError.emit(message)
        self._advance()
        _settle_prefetch()

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
        # 一个请求可能触发首次下载，耗时远超空闲看门狗：基础模型约 1GB，
        # 首次日文合成还要下约 300MB 字典，两者互不相干。任一情况都要放宽，
        # 否则下载中途被杀，说话就悄无声息地没结果。
        self._watchdog.setInterval(
            1_800_000 if self._req_may_download(req) else 120_000)
        self._watchdog.start()
        data = (json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8")
        proc.write(data)

    def _req_may_download(self, req: dict) -> bool:
        """这个请求是否会触发首次下载。"""
        if req.get("cmd") == "prefetch":
            # 预取可能重下基础模型，要求日文时还会接着下日文字典（约 100MB）
            return _pretrained_missing() or bool(req.get("want_jp"))
        if _pretrained_missing():
            return True
        # 日文合成时字典若仍缺（预取失败或被跳过）会下载一次
        # open_jtalk + sudachidict；其它语言跳过检查，保持正常的 120 秒上限
        if req.get("pack_language") != "jp":
            return False
        try:
            return _jp_langpack_missing()
        except Exception:
            return True  # 判断不了就放宽，宁可等久一点

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
            self._on_result(rid, str(obj.get("wav", "")),
                            bool(obj.get("stream")), bool(obj.get("last")))
        elif event == "ready":
            self._on_ready(rid)
        elif event == "progress":
            self._on_progress(obj)
        elif event == "error":
            self._on_child_error(rid, str(obj.get("msg", "TTS child error")))

    def _on_progress(self, obj: dict):
        """把子进程的下载进度转发给界面。

        pct 为 0-100，None 表示进度未知。done=True 表示下载结束，可以收起进度条。
        """
        raw = obj.get("pct")
        try:
            pct = None if raw is None else max(0.0, min(100.0, float(raw)))
        except (TypeError, ValueError):
            pct = None
        label = str(obj.get("label") or "")
        self.downloadProgress.emit(pct, label, bool(obj.get("done")))

    def _on_result(self, rid, wav_path: str, streaming: bool = False,
                   last: bool = False):
        done = not streaming or last
        if done and rid in self._outstanding:
            self._outstanding.discard(rid)
        self._consec_failures = 0
        if rid != self._active_speak_id:
            # 过期结果（已被更新的 speak 取代）：把文件删掉
            if os.path.isfile(wav_path):
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass
        else:
            if done:
                self._speak_complete = True
            if not os.path.isfile(wav_path):
                if not self._error_emitted:
                    self._error_emitted = True
                    self.audioError.emit(f"File not found: {wav_path}")
            elif self._playback_stopped:
                if os.path.isfile(wav_path):
                    try:
                        os.unlink(wav_path)
                    except OSError:
                        pass
            else:
                self._play_queue.append(wav_path)
                self._temp_files.append(wav_path)
                self._prune_temp_files()
                if not self._speak_started:
                    self._speak_started = True
                    self._player.stop()
                    self._play_next()
                elif (self._player.playbackState()
                        != QMediaPlayer.PlaybackState.PlayingState):
                    self._play_next()
        self._advance()

    def _play_next(self) -> None:
        if not self._play_queue:
            return
        path = self._play_queue.pop(0)
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()

    def _prune_temp_files(self) -> None:
        while len(self._temp_files) > 5:
            current = self._player.source().toLocalFile()
            protected = set(self._play_queue)
            if current:
                protected.add(current)
            removable = next(
                (f for f in self._temp_files if f not in protected), None)
            if removable is None:
                break
            self._temp_files.remove(removable)
            try:
                os.unlink(removable)
            except OSError:
                pass

    def _reset_playback(self) -> None:
        self._play_queue.clear()
        self._playback_stopped = True
        self._player.stop()

    def _on_ready(self, rid):
        if rid in self._outstanding:
            self._outstanding.discard(rid)
        self._consec_failures = 0
        key = self._warmup_by_id.pop(rid, None)
        if key is not None:
            self._warmed_key = key
        self._advance()
        if _PREFETCH_ACTIVE and self is _PREFETCH_OWNER and rid == _PREFETCH_RID:
            _settle_prefetch()

    def _on_child_error(self, rid, msg: str):
        if rid in self._outstanding:
            self._outstanding.discard(rid)
        is_prefetch = (
            _PREFETCH_ACTIVE and self is _PREFETCH_OWNER
            and rid == _PREFETCH_RID)
        if rid in self._warmup_by_id:
            # warmup 失败：child 已经清掉自己的状态，下次 speak 会重建，
            # 真有问题会在那时报出来
            self._warmup_by_id.pop(rid, None)
        elif rid == self._active_speak_id and not self._error_emitted:
            self._error_emitted = True
            self.audioError.emit(msg)
        self._advance()
        if is_prefetch:
            _settle_prefetch()

    def _advance(self) -> None:
        if self._outstanding:
            return
        if self._queue:
            self._pump()
            return
        self._watchdog.stop()
        self._reap_idle_others()
        self._idle_timer.start(self._idle_ms)

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
        _settle_prefetch()

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
        _settle_prefetch()

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
            self._reset_playback()
            self._kill_proc()
        else:
            self.prefetch_models()

    def prefetch_models(self) -> None:
        """开启语音/启动时预取 ~1GB 基础模型（全局单飞）。

        基础模型下完后子进程会接着下日文字典（当前语音语言为日文时）。
        所以「模型已在、字典缺」也要进预取，否则日文只能等首次合成时才补。
        """
        global _PREFETCH_ACTIVE, _PREFETCH_OWNER, _PREFETCH_RID
        if _PREFETCH_ACTIVE:
            return
        want_jp = self._wants_jp()
        if not _pretrained_missing() and not (want_jp and _jp_langpack_missing()):
            return
        for eng in _LIVE_ENGINES:
            if eng._proc is not None or eng._queue or eng._outstanding:
                return  # 有引擎忙：交给其 _build_tts 兜底路径
        _PREFETCH_ACTIVE = True
        _PREFETCH_OWNER = self
        self._next_id += 1
        _PREFETCH_RID = self._next_id
        # 宿主知道用户选的语言，子进程不知道（那边没有 Qt），
        # 只在真的用日文时才要求下载字典
        self._enqueue({"cmd": "prefetch", "id": _PREFETCH_RID,
                       "want_jp": want_jp})

    @staticmethod
    def _wants_jp() -> bool:
        try:
            return qconfig.get(qconfig.voiceLang) == "jp"
        except Exception:
            return False

    @staticmethod
    def _stream_enabled() -> bool:
        """是否边合成边播放（第 N 段在播时合成第 N+1 段）。

        按设备分别取值，因为取舍不同：GPU 合成够快，流式能有效掩盖延迟；
        CPU 每段耗时很长，流式送来的片段太晚，听起来会断断续续。

        设备判断偏保守：只有 GPU 开关打开**且**检测到 CUDA 版 torch 才算
        GPU，因为显存不足或没有 CUDA 时子进程会静默退回 CPU。
        """

        def _cpu_choice() -> bool:
            try:
                return bool(qconfig.get(qconfig.ttsStreamCpu))
            except Exception:
                return False

        def _gpu_choice() -> bool:
            try:
                return bool(qconfig.get(qconfig.ttsStreamGpu))
            except Exception:
                return True

        try:
            use_gpu = bool(qconfig.get(qconfig.ttsUseGpu))
        except Exception:
            use_gpu = False
        if use_gpu:
            try:
                gpu_ok, _ = detect_gpu_support()
            except Exception:
                gpu_ok = False
            # 开关是开的，但子进程实际会跑在 CPU 上，那就按 CPU 的选择来
            return _gpu_choice() if gpu_ok else _cpu_choice()
        return _cpu_choice()

    def _kill_proc(self):
        self._watchdog.stop()
        self._idle_timer.stop()
        self._queue.clear()
        self._outstanding.clear()
        self._warmup_by_id.clear()
        self._warmed_key = None
        proc = self._proc
        if proc is None:
            _settle_prefetch()
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
        _settle_prefetch()

    def _on_media_status(self, status):
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        if self._play_queue:
            self._play_next()
        elif self._speak_complete:
            self.playbackFinished.emit()

    def _on_player_error(self, error, message):
        self.audioError.emit(message)

    def stop_playback(self):
        self._reset_playback()

    def stop(self):
        self._kill_proc()
        self._reset_playback()
