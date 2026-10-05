import gc
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TRANSLATE_EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts-translate")


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _clean_text(text: str) -> str:
    text = re.sub(r'[^\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af'
                  r'a-zA-Z0-9\s，。！？、；：\u201c\u201d\u2018\u2019（）【】《》—…\.\,\!\?\;\:\'\"\(\)\[\]\-]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _translate_zh_to_jp(text: str, api_key: str, base_url: str, model: str) -> str:
    try:
        url = f"{base_url.rstrip('/')}/chat/completions"
        translate_model = "deepseek-chat" if "deepseek" in model else model
        payload = {
            "model": translate_model,
            "messages": [
                {"role": "system", "content": "你是翻译器。将中文翻译成日文，只输出翻译结果，不要解释。"},
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,
            "max_tokens": 256,
            "stream": False,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        msg = result["choices"][0]["message"]
        content = (msg.get("content") or "").strip()
        return content if content else text
    except Exception:
        return text


def _ref_cache_dir() -> str:
    return os.path.join(REPO_ROOT, "tts_cache", "ref_cache")


def _ref_cache_path(key) -> str:
    digest = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()
    return os.path.join(_ref_cache_dir(), f"{digest}.pt")


def _ref_cache_get(key):
    try:
        path = _ref_cache_path(key)
        if not os.path.isfile(path):
            return None
        import torch
        entry = torch.load(path, map_location="cpu", weights_only=False)
        if not isinstance(entry, dict) or entry.get("key") != key:
            return None
        prompt = entry.get("prompt")
        spk = entry.get("spk")
        if not isinstance(prompt, dict) or not isinstance(spk, dict) or not prompt or not spk:
            return None
        _log(f"[TTS] Ref cache loaded: {path}")
        return {"prompt": prompt, "spk": spk}
    except Exception as e:
        _log(f"[TTS] Ref cache load failed: {e}")
        return None


def _ref_cache_put(key, tts):
    try:
        prompt = dict(tts.prompt_audio_cache)
        spk = dict(tts.spk_audio_cache)
        if not prompt or not spk:
            return
        entry = {"key": key, "prompt": prompt, "spk": spk}
        path = _ref_cache_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import torch
        tmp_path = path + ".tmp"
        torch.save(entry, tmp_path)
        os.replace(tmp_path, path)
        _log(f"[TTS] Ref cache saved: {path}")
    except Exception as e:
        _log(f"[TTS] Ref cache save failed: {e}")


def _decide_device(want_gpu: bool) -> str:
    if not want_gpu:
        return "cpu"
    try:
        import torch
        if not torch.cuda.is_available():
            _log("[TTS] GPU requested but torch has no CUDA support -> CPU")
            return "cpu"
        free, total = torch.cuda.mem_get_info()
    except Exception as e:
        _log(f"[TTS] GPU probe failed: {e} -> CPU")
        return "cpu"
    try:
        min_mb = int(os.environ.get("TTS_MIN_FREE_VRAM_MB", "1300"))
    except ValueError:
        min_mb = 1300
    if free < min_mb * 1048576:
        _log(f"[TTS] GPU requested but free VRAM {free // 1048576}MB < "
             f"{min_mb}MB -> CPU")
        return "cpu"
    try:
        name = torch.cuda.get_device_name(0)
    except Exception:
        name = "CUDA device"
    _log(f"[TTS] GPU enabled: {name} (free {free // 1048576}MB / {total // 1048576}MB)")
    return "cuda"


# --- 预训练基础模型（~1GB，不随包分发，首次运行自动下载到 exe 旁的
#     gsv_models 文件夹；旧版 ~/.cache/gsv 会自动迁移过去）-------------------

def _models_target_dir() -> str:
    """下载目标文件夹：引擎注入的环境变量 > 打包子进程推算 > dev 直跑 REPO_ROOT。"""
    env = os.environ.get("ARONA_GSV_MODELS")
    if env:
        return env
    if getattr(sys, "frozen", False):
        # child sits in <root>\TTS\AronaAI-TTS.exe -> program root is one up
        return os.path.join(os.path.dirname(os.path.dirname(sys.executable)),
                            "gsv_models")
    return os.path.join(REPO_ROOT, "gsv_models")


def _migrate_legacy_cache(target: str, cache: str) -> None:
    """旧版缓存 ~/.cache/gsv -> 目标文件夹（跨盘/占用/无权限失败则原地使用）。"""
    if os.path.isdir(target) or not os.path.isdir(cache):
        return
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.rename(cache, target)
    except OSError:
        pass


def _effective_models_dir():
    """Returns (models_dir passed to gsv TTS, effective dir for checks).

    Fresh installs download into the target folder next to the exe/main.py;
    an existing legacy ~/.cache/gsv is auto-migrated there (kept in place
    when the move fails). Falls back to the cache when the target folder
    cannot be created (e.g. Program Files without write permission).
    """
    target = _models_target_dir()
    cache = os.path.join(os.path.expanduser("~"), ".cache", "gsv")
    _migrate_legacy_cache(target, cache)
    for path in (target, cache):
        if os.path.isdir(path):
            return path, path
    try:
        os.makedirs(target, exist_ok=True)
    except OSError:
        return cache, cache
    return target, target


def _models_missing(models_dir: str) -> bool:
    # Mirror of gsv_tts.Download.check_pretrained_models + the int8 CNRoberta
    # file (TTS.py): any missing piece triggers a download on TTS() init.
    return not (
        os.path.isdir(os.path.join(models_dir, "chinese-hubert-base"))
        and os.path.isdir(os.path.join(models_dir, "g2p"))
        and os.path.isdir(os.path.join(models_dir, "sv"))
        and os.path.isfile(os.path.join(
            models_dir, "chinese-roberta-wwm-ext-large",
            "cnroberta_int8_dynamic.onnx"))
    )


def _open_download_console():
    """Attach a visible console for the model download.

    Only sys.stderr is redirected (tqdm/logging progress); the stdout JSON
    protocol pipe is never touched. Returns (saved_stderr, allocated) or
    None when no console could be provided (progress then stays invisible
    but the download still works).
    """
    import ctypes
    try:
        k32 = ctypes.windll.kernel32
    except (AttributeError, ValueError):
        return None
    saved = sys.stderr
    allocated = False
    if not k32.GetConsoleWindow():
        if not k32.AllocConsole():
            return None
        allocated = True
        try:
            k32.SetConsoleTitleW("AronaAI 正在下载语音基础模型（约1GB，请稍候）")
        except Exception:
            pass
    try:
        f = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        if allocated:
            k32.FreeConsole()
        return None
    sys.stderr = f
    return saved, allocated


def _close_download_console(handle, message: str = "", delay: float = 5.0) -> None:
    if not handle:
        return
    saved, allocated = handle
    try:
        if message:
            print(message, file=sys.stderr, flush=True)
            if delay > 0:
                time.sleep(delay)
    except Exception:
        pass
    cur = sys.stderr
    sys.stderr = saved
    if cur is not saved:
        try:
            cur.close()
        except Exception:
            pass
    if allocated:
        try:
            import ctypes
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass


def _prefetch() -> None:
    """Download the ~1GB pretrained base models if absent (startup path).

    Shows a console window with tqdm progress; completes with a short-lived
    success message before closing it again.
    """
    models_arg, effective = _effective_models_dir()
    if not _models_missing(effective):
        _log("[TTS] prefetch: pretrained models already present")
        return
    _tts_init(models_arg, effective, device="cpu")
    _log("[TTS] prefetch: pretrained models download complete")


def _pid_alive(pid: int) -> bool:
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong(0)
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    except Exception:
        return True  # cannot tell: assume alive (mtime backstop applies)


def _lock_is_stale(lock_path: str) -> bool:
    try:
        age = time.time() - os.path.getmtime(lock_path)
    except OSError:
        return False  # vanished: caller retries acquire
    if age > 3600:
        return True
    if age < 10:
        return False  # just created, pid not written yet
    try:
        with open(lock_path, "r", encoding="ascii") as f:
            pid = int(f.read().strip() or "0")
    except (OSError, ValueError):
        return age > 60
    if pid <= 0:
        return age > 60
    return not _pid_alive(pid)


def _acquire_download_lock(models_dir: str) -> bool:
    """Cross-process download mutex. True -> caller may download (lock held);
    False -> models already completed elsewhere (no lock held). Blocks while
    another process holds a live lock so two children never download at once."""
    try:
        os.makedirs(models_dir, exist_ok=True)
    except OSError:
        return True  # cannot lock (read-only dir): best effort anyway
    lock_path = os.path.join(models_dir, ".download.lock")
    deadline = time.time() + 65 * 60
    while time.time() < deadline:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not _models_missing(models_dir):
                return False
            if _lock_is_stale(lock_path):
                try:
                    os.remove(lock_path)
                except OSError:
                    pass
                continue
            time.sleep(3)
            continue
        except OSError:
            return True  # cannot create lock: proceed without
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
        finally:
            os.close(fd)
        return True
    # 65min backstop: steal the lock and proceed
    try:
        os.remove(lock_path)
    except OSError:
        pass
    return True


def _release_download_lock(models_dir: str) -> None:
    try:
        os.remove(os.path.join(models_dir, ".download.lock"))
    except OSError:
        pass


def _tts_init(models_arg, effective: str, device: str,
              gpt_model: str = None, sovits_model: str = None):
    """TTS() init with (1) a visible console while the ~1GB pretrained
    download runs and (2) a cross-process lock so concurrent children never
    download into the same directory."""
    missing = _models_missing(effective)
    owns = False
    console = None
    if missing:
        owns = _acquire_download_lock(effective)
        if owns and not _models_missing(effective):
            # 等锁期间已被别的进程下载完：不弹窗，直接让出锁
            _release_download_lock(effective)
            owns = False
        elif owns:
            console = _open_download_console()
            if console:
                print(f"缺少基础语音模型，开始下载到:\n  {effective}\n"
                      "（约 1GB，视网速约 5~30 分钟）…\n",
                      file=sys.stderr, flush=True)
    try:
        from gsv_tts import TTS
        tts = TTS(use_bert=True, device=device, models_dir=models_arg)
    except Exception:
        _close_download_console(
            console,
            f"\n下载失败，请检查网络后重试（删除 {effective} 可强制重新下载）。"
            "8 秒后自动关闭…",
            8.0)
        raise
    finally:
        if owns:
            _release_download_lock(effective)
    _close_download_console(console, "\n✔ 下载完成，5 秒后自动关闭…", 5.0)
    if gpt_model is not None:
        tts.load_gpt_model(gpt_model)
    if sovits_model is not None:
        tts.load_sovits_model(sovits_model)
    return tts


def _build_tts(device: str, gpt_model: str, sovits_model: str):
    models_arg, effective = _effective_models_dir()
    # Not bundled in the package: downloaded on demand (startup prefetch
    # normally handles it; this is the fallback path).
    return _tts_init(models_arg, effective, device, gpt_model, sovits_model)


# 热驻留：模型跨请求复用，参数/设备变化才重建
_STATE: dict = {"tts": None, "device": None, "gpt": None, "sovits": None}


def _get_tts(device: str, gpt_model: str, sovits_model: str):
    if (_STATE["tts"] is not None and _STATE["device"] == device
            and _STATE["gpt"] == gpt_model
            and _STATE["sovits"] == sovits_model):
        return _STATE["tts"]
    # 重建前先释放旧模型：否则新旧两份同时驻留（4GB 显存必顶满 →
    # CUDA illegal memory access → 驱动重置 → 主进程闪退）
    _drop_tts()
    tts = _build_tts(device, gpt_model, sovits_model)
    _STATE.update(tts=tts, device=device, gpt=gpt_model, sovits=sovits_model)
    return tts


def _drop_tts() -> None:
    _STATE.update(tts=None, device=None, gpt=None, sovits=None)
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _warmup(req: dict) -> None:
    device = _decide_device(bool(req.get("use_gpu")))
    _get_tts(device, req["gpt_model"], req["sovits_model"])
    _log(f"[TTS] Warmup ready (device={device})")


def _synth(req: dict) -> str:
    text = req["text"]
    reference_audio = req["reference_audio"]
    reference_text = req["reference_text"]
    pack_language = req["pack_language"]
    gpt_model = req["gpt_model"]
    sovits_model = req["sovits_model"]
    translate_config = req.get("translate_config")

    translate_future = None
    if pack_language == "jp" and translate_config:
        translate_future = _TRANSLATE_EXEC.submit(
            _translate_zh_to_jp, text, *translate_config)

    import torch
    logical_cpus = os.cpu_count() or 4
    torch.set_num_threads(logical_cpus if logical_cpus <= 4 else min(logical_cpus - 1, 8))

    device = _decide_device(bool(req.get("use_gpu")))
    tts = _get_tts(device, gpt_model, sovits_model)

    if device == "cuda":
        # 释放 reserved 但未使用的缓存块，降低显存碎片导致的越界
        # （4GB 卡上第二条 infer 分配失败会以 illegal memory access 形式出现）
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass

    tts_lang = "ja" if pack_language == "jp" else "zh"
    ref_key = (reference_audio, reference_text, tts_lang, sovits_model)
    cached = _ref_cache_get(ref_key)

    def _migrate(o):
        if torch.is_tensor(o):
            if o.is_floating_point():
                return o.to(device=device, dtype=tts.tts_config.dtype)
            return o.to(device=device)
        if isinstance(o, dict):
            return {k: _migrate(v) for k, v in o.items()}
        if isinstance(o, tuple):
            return tuple(_migrate(v) for v in o)
        if isinstance(o, list):
            return [_migrate(v) for v in o]
        return o

    def apply_cache(t):
        if not cached:
            return
        prompt, spk = cached["prompt"], cached["spk"]
        if device == "cuda":
            # 磁盘缓存是 cpu/fp32 的，GPU 模式注入前迁到 cuda/模型 dtype
            prompt, spk = _migrate(prompt), _migrate(spk)
        t.prompt_audio_cache.update(prompt)
        t.spk_audio_cache.update(spk)

    apply_cache(tts)
    if cached:
        _log("[TTS] Ref cache hit")

    if translate_future is not None:
        translated = translate_future.result()
        _log(f"[TTS] Translate: {text[:30]!r} -> {translated[:30]!r}")
        text = translated

    text = _clean_text(text)
    _log(f"[TTS] Infer: lang={tts_lang}, text={text[:50]!r}")

    try:
        audio = tts.infer(
            spk_audio_path=reference_audio,
            prompt_audio_path=reference_audio,
            prompt_audio_text=reference_text,
            text=text,
            text_language=tts_lang,
            prompt_language=tts_lang,
        )
    except RuntimeError as e:
        msg = str(e)
        low = msg.lower()
        if device != "cuda" or ("out of memory" not in low and "cuda" not in low):
            raise
        first = msg.splitlines()[0][:160] if msg else repr(e)
        _log(f"[TTS] CUDA infer failed, retrying on CPU: {first}")
        del tts
        # 清掉 _STATE 里的 CUDA 对象引用并立即释放显存
        _drop_tts()
        device = "cpu"
        tts = _build_tts(device, gpt_model, sovits_model)
        _STATE.update(tts=tts, device="cpu", gpt=gpt_model, sovits=sovits_model)
        apply_cache(tts)
        audio = tts.infer(
            spk_audio_path=reference_audio,
            prompt_audio_path=reference_audio,
            prompt_audio_text=reference_text,
            text=text,
            text_language=tts_lang,
            prompt_language=tts_lang,
        )

    if cached is None and device != "cuda":
        _ref_cache_put(ref_key, tts)

    cache_dir = os.path.join(REPO_ROOT, "tts_cache")
    os.makedirs(cache_dir, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=cache_dir)
    tmp.close()
    audio.save(tmp.name)
    return tmp.name


def main() -> int:
    # The engine speaks UTF-8 on both directions (dev adds -X utf8, but the
    # packaged exe has no such flag): force it so Chinese text/paths are not
    # decoded as the ANSI codepage inside AronaAI-TTS.exe.
    for _stream in (sys.stdin, sys.stdout, sys.stderr):
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
    if sys.stdin is None:
        # windowed exe launched without redirected stdio (double-click)
        _log("[TTS] stdin not available; this process must be launched by "
             "the main program (TTS/AronaAI-TTS.exe).")
        return 1
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:
            _emit({"event": "error", "id": None, "msg": f"bad request json: {e}"})
            continue
        if not isinstance(req, dict):
            _emit({"event": "error", "id": None, "msg": "bad request not an object"})
            continue
        req_id = req.get("id")
        cmd = req.get("cmd")
        if cmd == "prefetch":
            try:
                _prefetch()
                _emit({"event": "ready", "id": req_id})
            except Exception:
                _emit({"event": "error", "id": req_id,
                       "msg": traceback.format_exc()})
            continue
        if cmd == "warmup":
            try:
                _warmup(req)
                _emit({"event": "ready", "id": req_id})
            except Exception:
                _drop_tts()
                _emit({"event": "error", "id": req_id,
                       "msg": traceback.format_exc()})
            continue
        if cmd != "speak":
            _emit({"event": "error", "id": req_id,
                   "msg": f"unknown cmd: {cmd!r}"})
            continue
        try:
            wav = _synth(req)
        except Exception:
            _drop_tts()
            _emit({"event": "error", "id": req_id,
                   "msg": traceback.format_exc()})
            continue
        _emit({"event": "result", "id": req_id, "wav": wav})
    return 0


def run() -> int:
    try:
        code = main()
    except (BrokenPipeError, KeyboardInterrupt):
        code = 0
    except Exception:
        try:
            _emit({"event": "error", "msg": traceback.format_exc()})
        except Exception:
            pass
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    run()
