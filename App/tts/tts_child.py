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

# urllib 默认用 Windows 系统证书库，精简版/新装系统可能缺根证书
# （VMware 上实测 CERTIFICATE_VERIFY_FAILED）。改用 certifi 自带的根证书。
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except Exception:
    pass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# JP 语言包不打进冻结包（见 AronaAI.spec 的 _prune_tts_datas），启动预取时下
# （宿主在语音语言为日文时要求），首次日配合成时再兜底补齐：
#   open_jtalk 字典（~24MB，解压 ~102MB）→ langpacks/jp/openjtalk-dict
#   sudachidict system.dic（~73MB，解压 ~202MB）→ langpacks/jp/sudachi
# 都是首次运行才生成的可写数据，不能用 REPO_ROOT：冻结后它指向只读的
# _internal，写入会报 WinError 5。
def _data_root() -> str:
    """运行时生成的数据的根目录（源码运行 = 仓库根，冻结 = exe 所在目录）。"""
    if getattr(sys, "frozen", False):
        # <root>\TTS\AronaAI-TTS.exe 的上两级
        return os.path.dirname(os.path.dirname(sys.executable))
    return REPO_ROOT


_JP_LANGPACK_DIR = os.path.join(_data_root(), "langpacks", "jp")
_JTALK_DICT_DIR = os.path.join(_JP_LANGPACK_DIR, "openjtalk-dict")
_JTALK_DICT_ZIP = "pyopenjtalk/dictionary/"
_JP_SUDACHI_DIR = os.path.join(_JP_LANGPACK_DIR, "sudachi")
_SUDACHI_SYS_DIC = os.path.join(_JP_SUDACHI_DIR, "system.dic")
_SUDACHI_CFG = os.path.join(_JP_SUDACHI_DIR, "sudachi.json")
_SUDACHI_DICT_ZIP = "sudachidict_core/resources/"
_JTALK_WHEEL_FALLBACK = (
    "https://files.pythonhosted.org/packages/40/02/"
    "939abaa07066337ce1a9e405159f186b2b383fd4ab89754c68af6af29026/"
    "pyopenjtalk_plus-0.4.1.post9-cp310-cp310-win_amd64.whl"
)

_TRANSLATE_EXEC = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts-translate")

# gsv_tts/Download.py 每次只读 1KB，1GB 的包要读约一百万次，速度被拖死。
# 把每次读取的下限抬到 64KB（urllib3 自己的默认值）。
_MIN_DOWNLOAD_CHUNK = 65536


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _progress(pct, label: str = "", done: bool = False) -> None:
    """通过 stdout 协议上报下载进度，由宿主渲染进度条。

    pct 为 0-100，None 表示进度未知。失败不影响下载本身。
    """
    try:
        _emit({"event": "progress", "pct": pct, "label": label,
               "done": bool(done)})
    except Exception:
        pass


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


def _cache_root() -> str:
    """缓存根目录，与主程序的 get_base_dir()/tts_cache 保持一致。"""
    return os.path.join(_data_root(), "tts_cache")


def _ref_cache_dir() -> str:
    return os.path.join(_cache_root(), "ref_cache")


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
        return {"prompt": prompt, "spk": spk}
    except Exception:
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
    except Exception:
        pass


def _decide_device(want_gpu: bool) -> str:
    if not want_gpu:
        return "cpu"
    try:
        import torch
        if not torch.cuda.is_available():
            return "cpu"
        free, _ = torch.cuda.mem_get_info()
    except Exception:
        return "cpu"
    try:
        min_mb = int(os.environ.get("TTS_MIN_FREE_VRAM_MB", "1300"))
    except ValueError:
        min_mb = 1300
    if free < min_mb * 1048576:
        return "cpu"
    return "cuda"


# 预训练基础模型约 1GB，不随包分发，首次运行下载到 exe 旁的 gsv_models；
# 旧版 ~/.cache/gsv 会自动迁移过去。

def _models_target_dir() -> str:
    """模型下载目录：优先环境变量，其次按是否冻结推算。"""
    env = os.environ.get("ARONA_GSV_MODELS")
    if env:
        return env
    if getattr(sys, "frozen", False):
        # <root>\TTS\AronaAI-TTS.exe 的上两级
        return os.path.join(os.path.dirname(os.path.dirname(sys.executable)),
                            "gsv_models")
    return os.path.join(REPO_ROOT, "gsv_models")


def _migrate_legacy_cache(target: str, cache: str) -> None:
    """把旧版 ~/.cache/gsv 迁到新目录；跨盘或无权限时失败就算了。"""
    if os.path.isdir(target) or not os.path.isdir(cache):
        return
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.rename(cache, target)
    except OSError:
        pass


def _effective_models_dir():
    """返回 (传给 gsv 的模型目录, 用于检查的目录)。

    目标目录建不出来时（比如装在 Program Files 下没有写权限）退回旧缓存目录。
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
    # 与 gsv_tts.Download.check_pretrained_models 加上 int8 CNRoberta 文件
    # 的判断保持一致：少任何一项，TTS() 初始化时都会触发下载。
    return not (
        os.path.isdir(os.path.join(models_dir, "chinese-hubert-base"))
        and os.path.isdir(os.path.join(models_dir, "g2p"))
        and os.path.isdir(os.path.join(models_dir, "sv"))
        and os.path.isfile(os.path.join(
            models_dir, "chinese-roberta-wwm-ext-large",
            "cnroberta_int8_dynamic.onnx"))
    )


def _prefetch(req: dict = None) -> None:
    """启动预取：基础模型（~1GB），下完后再下日文字典。

    串行执行：先把基础模型下完，再下日文字典，避免首次日配合成时才临时
    补字典。日文属于可选，失败也不能影响基础模型。

    是否下日文字典由宿主决定并放进请求里（want_jp）：本进程没有 PySide6，
    读不到用户设置。
    """
    want_jp = bool((req or {}).get("want_jp"))
    models_arg, effective = _effective_models_dir()
    need_models = _models_missing(effective)
    need_jp = want_jp and _jp_langpack_missing()

    if not need_models and not need_jp:
        return

    if need_models:
        _tts_init(models_arg, effective, device="cpu")

    if need_jp:
        try:
            _ensure_jp_langpack()
        except Exception:
            # 可选部分，失败不影响基础模型
            pass


def _jp_langpack_missing() -> bool:
    """日文字典是否还没下载。"""
    return not (
        os.path.isfile(os.path.join(_JTALK_DICT_DIR, "sys.dic"))
        and os.path.isfile(_SUDACHI_SYS_DIC)
    )


def _install_tqdm_progress_hook() -> bool:
    """接住 gsv_tts 的 tqdm 进度条，同时把它的读取块大小调大。

    gsv_tts/Download.py 自己建了一个 tqdm(...) 条并按块更新，那是基础模型
    下载过程中唯一的进度来源。继承 tqdm 就能把每次更新转成进度事件，
    不必改动库代码。

    同一文件里还硬编码了 block_size = 1024 并传给 iter_content()，等于每
    1KB 就做一次 socket 读取，1GB 要读约一百万次，速度远低于带宽上限
    （就是「只有 0.1 Mbps」那个现象）。这里包一层 response，把读取下限
    抬到 _MIN_DOWNLOAD_CHUNK，库代码一行不改。
    """
    try:
        from tqdm import tqdm as _tqdm
        import gsv_tts.Download as _gsv_download
    except Exception:
        return False
    if getattr(_gsv_download, "_arona_tqdm_hooked", False):
        return True

    # requests 的调用链：iter_content(chunk_size) -> stream(chunk_size) -> read
    class _WideChunkResponse:
        """包装 response，把 iter_content 的 chunk_size 抬到合理下限。"""

        __slots__ = ("_resp",)

        def __init__(self, resp):
            self._resp = resp

        def iter_content(self, chunk_size=1, decode_unicode=False):
            if chunk_size is None or chunk_size < _MIN_DOWNLOAD_CHUNK:
                chunk_size = _MIN_DOWNLOAD_CHUNK
            return self._resp.iter_content(chunk_size, decode_unicode)

        def __getattr__(self, name):
            return getattr(self._resp, name)

    _orig_get = _gsv_download.requests.get

    def _wide_get(*args, **kwargs):
        return _WideChunkResponse(_orig_get(*args, **kwargs))

    _wide_get._arona_original = _orig_get
    _gsv_download.requests.get = _wide_get

    class _ReportingTqdm(_tqdm):
        """除了 tqdm 自身的功能，还上报百分比。

        渲染被关掉，而 tqdm 在 disable 时 update() 会直接返回、不累加 self.n，
        所以这里自己数，不读 self.n。
        """

        def __init__(self, *args, **kwargs):
            kwargs.setdefault("disable", True)  # 不画进度条（进度改走 _progress 上报宿主）
            super().__init__(*args, **kwargs)
            self._arona_last = -1
            self._arona_seen = 0

        def update(self, n=1):
            try:
                self._arona_seen += n
                self._arona_report()
            except Exception:
                pass
            return super().update(n)

        def _arona_report(self):
            try:
                total = self.total
                if not total:
                    return
                seen = self._arona_seen
                pct = min(100.0, seen * 100.0 / total)
                ipct = int(pct)
                # 每 1% 才上报一次，避免把 stdout 管道刷爆
                if ipct == self._arona_last:
                    return
                self._arona_last = ipct
                mb = seen / 1048576
                tot_mb = total / 1048576
                _progress(pct, f"下载语音基础模型 {pct:.0f}% "
                               f"({mb:.0f}/{tot_mb:.0f} MB)")
            except Exception:
                pass

        def close(self):
            try:
                if self.total:
                    _progress(100, "语音基础模型下载完成", done=True)
            except Exception:
                pass
            return super().close()

    _gsv_download.tqdm = _ReportingTqdm
    _gsv_download._arona_tqdm_hooked = True
    return True


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
    """跨进程下载锁。True = 拿到锁可以下载；False = 别的进程已经下完了。

    有活锁时阻塞等待，避免两个子进程同时下载同一个目录。
    """
    try:
        os.makedirs(models_dir, exist_ok=True)
    except OSError:
        return True  # 目录只读，加不了锁，尽力而为
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
            return True  # 建不了锁文件，直接下
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
        finally:
            os.close(fd)
        return True
    # 等满 65 分钟还没等到，强行接管
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
    """初始化 TTS()，缺模型时走下载，并用跨进程锁防止多个子进程同时下。"""
    if getattr(sys, "frozen", False):
        # pyopenjtalk 字典没打进包（spec 里有意剔除 102MB），指向 langpacks，
        # 正常由启动预取（_prefetch -> _ensure_jp_langpack）下好，
        # 首次日配合成时再兜底补齐。
        os.environ.setdefault("OPEN_JTALK_DICT_DIR", _JTALK_DICT_DIR)
    missing = _models_missing(effective)
    owns = False
    if missing:
        owns = _acquire_download_lock(effective)
        if owns and not _models_missing(effective):
            # 等锁期间别的进程已经下完了
            _release_download_lock(effective)
            owns = False
        elif owns:
            _install_tqdm_progress_hook()
            _progress(0, "开始下载语音基础模型…")
    try:
        # 包里不带 cuDNN 子库（约 960MB，见 App/hooks/hook-torch.py）。
        # 关掉后 ATen 走原生 CUDA 卷积，实测比 cudnn 的算法搜索还快。
        import torch
        torch.backends.cudnn.enabled = False
        from gsv_tts import TTS
        tts = TTS(use_bert=True, device=device, models_dir=models_arg)
    except Exception as exc:
        if missing:
            _progress(None, f"语音基础模型下载失败：{exc}")
        raise
    finally:
        if owns:
            _release_download_lock(effective)
    if missing:
        _progress(100, "语音基础模型下载完成", done=True)
    if gpt_model is not None:
        tts.load_gpt_model(gpt_model)
    if sovits_model is not None:
        tts.load_sovits_model(sovits_model)
    return tts


def _build_tts(device: str, gpt_model: str, sovits_model: str):
    models_arg, effective = _effective_models_dir()
    # 正常由启动预取下好，这里是兜底路径
    return _tts_init(models_arg, effective, device, gpt_model, sovits_model)


# 模型热驻留：跨请求复用，只有参数或设备变了才重建
_STATE: dict = {"tts": None, "device": None, "gpt": None, "sovits": None}


def _get_tts(device: str, gpt_model: str, sovits_model: str):
    if (_STATE["tts"] is not None and _STATE["device"] == device
            and _STATE["gpt"] == gpt_model
            and _STATE["sovits"] == sovits_model):
        return _STATE["tts"]
    # 重建前必须先释放旧模型，否则新旧两份同时占显存，4GB 卡会顶满，
    # 表现为 CUDA illegal memory access → 驱动重置 → 主进程闪退
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


# 按顺序尝试的包索引。pypi.org 走 Fastly，国内经常被限速到 1 Mbps 以下
# （在这台机器实测只有 0.04-0.2 Mbps），而国内镜像能到几 Mbps。
# 官方源放最后，不影响海外用户。
#
# 两种索引的接口不一样：只有 pypi.org 提供 JSON API（/pypi/<name>/json），
# 镜像是 PEP 503 的 HTML 索引（/simple/<name>/），两条路都要处理。
_PYPI_MIRRORS = (
    ("aliyun", "https://mirrors.aliyun.com/pypi"),
    ("tuna", "https://pypi.tuna.tsinghua.edu.cn"),
)
_PYPI_OFFICIAL = "https://pypi.org"

# 查询元数据时每个索引的超时，不用于下载本体。
_INDEX_TIMEOUT = 8


def _http_get_text(url: str, timeout: int = _INDEX_TIMEOUT, headers: dict = None):
    req = urllib.request.Request(url, headers=headers or {
        "User-Agent": "pip/24.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _wheel_links_from_simple(name: str, base: str) -> list:
    """从 PEP 503 simple 索引解析出 [(文件名, 绝对链接)]。"""
    import urllib.parse
    html = _http_get_text(f"{base}/simple/{name}/")
    out = []
    for href, text in re.findall(
            r'<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>', html):
        fn = text.strip()
        url = urllib.parse.urljoin(f"{base}/simple/{name}/", href)
        url = url.split("#", 1)[0]
        if fn and url:
            out.append((fn, url))
    return out


def _pypi_json(name: str, version: str = None):
    """从第一个有响应的索引解析出包文件列表。

    返回 (files, base)：files 是 [(文件名, 链接)]，base 标明是哪个索引给的。
    镜像优先，避开 Fastly。

    每个索引的超时都很短：字典要在下载开始前解析完，慢的或不通的镜像
    不能把子进程卡住。
    """
    for _, base in _PYPI_MIRRORS:
        try:
            files = _wheel_links_from_simple(name, base)
            if files:
                return files, base
        except Exception:
            continue

    # 官方源优先用 JSON API，能拿到精确到版本的链接
    for suffix in ((f"{version}/json",) if version else ()) + ("json",):
        try:
            raw = _http_get_text(f"{_PYPI_OFFICIAL}/pypi/{name}/{suffix}",
                                 timeout=_INDEX_TIMEOUT)
            info = json.loads(raw)
            files = [(u.get("filename", ""), u.get("url", ""))
                     for u in info.get("urls", ())]
            if files:
                return files, _PYPI_OFFICIAL
        except Exception:
            continue
    return [], None


def _pyopenjtalk_wheel_url() -> str:
    """解析 pyopenjtalk-plus 的 win_amd64 + 当前 CP 版本 wheel 直链。

    与安装的 fork 同版本优先（字典格式随包，DIC_VERSION 102），失败回退
    latest，再失败用构建期固化的直链。镜像优先以避开 Fastly 限速。"""
    ver = None
    try:
        import importlib.metadata as _md
        ver = _md.version("pyopenjtalk-plus")
    except Exception:
        try:
            from pyopenjtalk.version import __version__ as _v
            ver = _v.replace("-", ".")
        except Exception:
            ver = None
    want_cp = f"cp{sys.version_info[0]}{sys.version_info[1]}"
    # 字典格式跟包版本绑定（DIC_VERSION），知道装的是哪个版本就必须版本
    # 对得上；只有所有索引都没有这个精确版本时，才退而求其次取最新。
    want_tags = []
    if ver:
        v = ver.replace("-", ".")
        want_tags = [f"pyopenjtalk_plus-{v}-", f"pyopenjtalk-plus-{v}-"]

    files, _ = _pypi_json("pyopenjtalk-plus", ver)
    matches = [(fn, url) for fn, url in files
               if fn.endswith(".whl") and "win_amd64" in fn
               and want_cp in fn]
    if want_tags:
        for fn, url in matches:
            if any(fn.startswith(t) for t in want_tags):
                return url
    if matches:
        # 索引按从旧到新排列，取最后一个
        fn, url = matches[-1]
        return url

    return _JTALK_WHEEL_FALLBACK


def _fetch_wheel(url: str, what: str, base: float = 0.0,
                 span: float = 100.0) -> str:
    """下载 wheel 到临时文件，返回路径（调用方负责清理）。

    base/span 把单个文件的进度映射到整体 0-100 的某一段，两个字典文件
    就能共用一条进度条。
    """
    fname = url.rsplit("/", 1)[-1]

    # 断点续传：把未完成的文件留在 langpack 目录里，中断后接着下。
    # 同时存下资源的校验标识，避免远端文件变了还往旧内容后面拼，
    # 那样会得到一个损坏的 wheel 且不报错。
    os.makedirs(_JP_LANGPACK_DIR, exist_ok=True)
    part = os.path.join(_JP_LANGPACK_DIR, fname + ".part")
    vtag_path = part + ".tag"
    have = os.path.getsize(part) if os.path.isfile(part) else 0
    saved_tag = ""
    if have:
        try:
            saved_tag = open(vtag_path, "r", encoding="utf-8").read().strip()
        except OSError:
            saved_tag = ""

    def _open(range_from):
        req = urllib.request.Request(url, headers={
            "User-Agent": "pip/24.0",
            **({"Range": f"bytes={range_from}-"} if range_from else {}),
        })
        return urllib.request.urlopen(req, timeout=60)

    def _validator(resp) -> str:
        for h in ("ETag", "Last-Modified", "Content-Length"):
            try:
                v = resp.headers.get(h)
            except Exception:
                v = None
            if v:
                return f"{h}={v}"
        return ""

    try:
        _progress(base, f"下载{what}…")
        # 已有前缀就带 Range 要剩下的部分；服务端不支持会回 200，那就重下。
        r = _open(have)
        resuming = False
        if have:
            code = getattr(r, "status", None) or r.getcode()
            if code == 206:
                # 只有确认是同一个资源时才敢复用前缀
                if save_tag := _validator(r):
                    if saved_tag and saved_tag != save_tag:
                        have = 0
                    else:
                        resuming = True
                        saved_tag = save_tag
                else:
                    resuming = True       # 服务端没给校验标识，尽力而为
            else:
                have = 0                  # 服务端忽略了 Range，重下
        if not resuming:
            have = 0
            # 从头下，记下校验标识供下次续传比对
            try:
                tag = _validator(r)
                if tag:
                    with open(vtag_path, "w", encoding="utf-8") as tf:
                        tf.write(tag)
            except OSError:
                pass
        with r, open(part, "ab" if resuming else "wb") as f:
            try:
                content_len = int(r.headers.get("Content-Length") or 0)
            except Exception:
                content_len = 0
            total_expected = have + content_len if content_len else 0
            total = have
            last_pct = -1
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
                mb = total / 1048576
                if total_expected:
                    frac = min(1.0, total / total_expected)
                    pct = base + span * frac
                    label = (f"下载{what} {pct:.0f}% "
                             f"({mb:.1f}/{total_expected / 1048576:.1f} MB)")
                else:
                    pct = None  # unknown size: indeterminate
                    label = f"下载{what} {mb:.1f} MB"
                ipct = -1 if pct is None else int(pct)
                if ipct != last_pct and (ipct < 0 or ipct % 2 == 0):
                    last_pct = ipct
                    _progress(pct, label)
        if total < 1_000_000:
            raise RuntimeError(f"{what} wheel too small ({total} bytes)")
        if total_expected and total != total_expected:
            raise RuntimeError(
                f"{what} incomplete: {total} of {total_expected} bytes "
                f"(partial kept for resume)")
        # 下完了：交给调用方，同时去掉 .part 后缀
        fd, wheel_path = tempfile.mkstemp(suffix=".whl")
        os.close(fd)
        os.replace(part, wheel_path)
        try:
            os.unlink(vtag_path)
        except OSError:
            pass
        return wheel_path
    except Exception:
        # 保留 .part，下次从这里续传
        raise


def _extract_wheel(wheel_path: str, prefix: str, dest_dir: str,
                   marker: str) -> None:
    """把 wheel 内 prefix/ 下的文件解压到 dest_dir；marker 最后 os.replace
    落地，供并发子进程判定就绪。"""
    import shutil
    import zipfile

    tmp_dir = dest_dir + ".part"
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        os.makedirs(tmp_dir, exist_ok=True)
        with zipfile.ZipFile(wheel_path) as zf:
            names = [n for n in zf.namelist()
                     if n.startswith(prefix) and not n.endswith("/")]
            if not names:
                raise RuntimeError(f"no files matching {prefix} inside wheel")
            for n in names:
                rel = n[len(prefix):]
                if not rel or ".." in rel.split("/"):
                    continue
                target = os.path.join(tmp_dir, *rel.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(n) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        os.makedirs(dest_dir, exist_ok=True)
        for f in sorted(os.listdir(tmp_dir), key=lambda x: x == marker):
            os.replace(os.path.join(tmp_dir, f),
                       os.path.join(dest_dir, f))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _sudachidict_wheel_url() -> str:
    """找到真正的 sudachidict-core 字典 wheel。

    simple 索引会列出所有版本，其中有个上古的 SudachiDict_core-0.0.0 只有
    几 KB，是元数据空壳；真正的字典是日期版本，约 77MB。这里按版本号取
    最新的日期版，绝不选那个空壳。
    """
    files, _ = _pypi_json("sudachidict-core")
    best = None            # (排序键, 文件名, 链接)
    for fn, url in files:
        low = fn.lower()
        if not low.endswith(".whl") or "py3-none-any" not in low:
            continue
        if not low.startswith("sudachidict_core-"):
            continue
        ver = fn[len("sudachidict_core-"):].split("-", 1)[0]
        # 日期版本是 8 位 YYYYMMDD，可能带 .N 后缀；0.0.0 是空壳
        parts = ver.split(".")
        if not parts[0].isdigit() or len(parts[0]) != 8:
            continue
        key = (int(parts[0]), int(parts[1]) if len(parts) > 1
               and parts[1].isdigit() else 0)
        if best is None or key > best[0]:
            best = (key, fn, url)
    if best is None:
        raise RuntimeError("sudachidict-core: no dated wheel found on any index")
    return best[2]


def _seed_sudachi_dictionary() -> None:
    """冻结包没有 sudachidict 的 entry point 元数据：bare Dictionary() 会抛
    ModuleNotFoundError。显式写 sudachi.json 指到 langpacks 的 system.dic
    并预置 pyopenjtalk.utils._SUDACHI_DICTIONARY（run_frontend 后处理必需，
    utils 模块级懒加载会在首次调用时直接使用该预置实例）。"""
    if not os.path.isfile(_SUDACHI_SYS_DIC):
        return
    if not os.path.isfile(_SUDACHI_CFG):
        fd, tmp = tempfile.mkstemp(dir=_JP_SUDACHI_DIR, suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"systemDict": _SUDACHI_SYS_DIC}, f)
        os.replace(tmp, _SUDACHI_CFG)
    try:
        import pyopenjtalk.utils as _pju
        if _pju._SUDACHI_DICTIONARY is None:
            from sudachipy import dictionary as _sd
            _pju._SUDACHI_DICTIONARY = _sd.Dictionary(_SUDACHI_CFG)
    except Exception as exc:
        raise RuntimeError(f"日文读音字典初始化失败: {exc}") from exc


def _ensure_jp_langpack() -> None:
    """落盘两份 JP 字典（冻结包有意不打包，见 spec）。

    正常由启动预取、在基础模型下完之后调用（语音语言为日文时）；
    首次日配合成时也会兜底调用，预取失败/离线时仍会重试。

    幂等；并发安全（marker 最后 os.replace 落地）。开发环境（非冻结）
    直接用 venv 内的包字典，不下载。

    进度经 _progress() 上报宿主，由设置页的 ProgressBar 显示（不弹控制台）。
    """
    if not getattr(sys, "frozen", False):
        return

    os.makedirs(_JP_LANGPACK_DIR, exist_ok=True)
    need_jt = not os.path.isfile(os.path.join(_JTALK_DICT_DIR, "sys.dic"))
    need_sd = not os.path.isfile(_SUDACHI_SYS_DIC)
    if not (need_jt or need_sd):
        return

    # 把 0-100 的进度按实际要下的文件数均分：只缺一个就占满整条，
    # 两个各占一半
    stages = []
    if need_jt:
        stages.append("jt")
    if need_sd:
        stages.append("sd")
    span = 100.0 / len(stages)
    bounds = {name: (i * span, span) for i, name in enumerate(stages)}

    _progress(0, "准备下载日文字典…")
    wheels = []
    try:
        if need_jt:
            base, sp = bounds["jt"]
            wheels.append(_fetch_wheel(_pyopenjtalk_wheel_url(),
                                       "open_jtalk 字典", base, sp))
            _progress(base + sp, "解压 open_jtalk 字典…")
            _extract_wheel(wheels[-1], _JTALK_DICT_ZIP, _JTALK_DICT_DIR,
                           marker="sys.dic")
        if need_sd:
            base, sp = bounds["sd"]
            os.makedirs(_JP_SUDACHI_DIR, exist_ok=True)
            wheels.append(_fetch_wheel(_sudachidict_wheel_url(),
                                       "sudachidict 词典", base, sp))
            _progress(base + sp, "解压 sudachidict 词典…")
            _extract_wheel(wheels[-1], _SUDACHI_DICT_ZIP, _JP_SUDACHI_DIR,
                           marker="system.dic")
        _seed_sudachi_dictionary()
        _progress(100, "日文字典下载完成", done=True)
    except Exception as exc:
        raise RuntimeError(
            f"日文字典下载失败（需联网一次，或手动放置：open_jtalk 字典到 "
            f"{_JTALK_DICT_DIR}（需含 sys.dic）、sudachidict system.dic 到 "
            f"{_JP_SUDACHI_DIR}）: {exc}") from exc
    finally:
        for w in wheels:
            try:
                os.unlink(w)
            except OSError:
                pass


def _split_for_tts(text: str, max_len: int = 60) -> list[str]:
    """长文本按句切分，逐段合成后拼接。

    t2s 自回归生成到 KV-cache 上限即停（不是 EOS），整段合成会静默截断
    尾句（实测 105 字丢尾部 10 字，长回复丢得更多）。切段把每段控制在
    上限内；过短碎片并入相邻段，避免单字孤段。"""
    pieces = []
    for part in re.split(r'(?<=[。！？!?；;\n])', text):
        part = part.strip()
        if not part:
            continue
        while len(part) > max_len:
            cut = max([part.rfind(c, 0, max_len + 1)
                       for c in '，,、：: '] + [-1])
            if cut < max_len // 2:
                cut = max_len
            pieces.append(part[:cut + 1].strip())
            part = part[cut + 1:].strip()
        if part:
            pieces.append(part)
    merged = []
    for p in pieces:
        if merged and len(p) < 8:
            merged[-1] += p
        else:
            merged.append(p)
    return merged or [text]


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
    if pack_language == "jp":
        # 与翻译 future 并行：首次需下载 ~24MB 字典 wheel（之后幂等秒回）
        _ensure_jp_langpack()

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

    if translate_future is not None:
        translated = translate_future.result()
        text = translated

    text = _clean_text(text)
    chunks = _split_for_tts(text)

    import soundfile as sf

    cache_dir = _cache_root()
    os.makedirs(cache_dir, exist_ok=True)

    def _write_wav(data, samplerate: int) -> str:
        tmp = tempfile.NamedTemporaryFile(
            suffix=".wav", delete=False, dir=cache_dir)
        tmp.close()
        sf.write(tmp.name, data, samplerate)
        return tmp.name

    streaming = bool(req.get("stream"))
    req_id = req.get("id")
    outs = []
    completed = 0
    while completed < len(chunks):
        try:
            out = tts.infer(
                spk_audio_path=reference_audio,
                prompt_audio_path=reference_audio,
                prompt_audio_text=reference_text,
                text=chunks[completed],
                text_language=tts_lang,
                prompt_language=tts_lang,
            )
        except RuntimeError as e:
            msg = str(e)
            low = msg.lower()
            if device != "cuda" or ("out of memory" not in low
                                    and "cuda" not in low):
                raise
            del tts
            # 清掉 _STATE 里的 CUDA 对象引用并立即释放显存
            _drop_tts()
            device = "cpu"
            tts = _build_tts(device, gpt_model, sovits_model)
            _STATE.update(tts=tts, device="cpu", gpt=gpt_model,
                          sovits_model=sovits_model)
            apply_cache(tts)
            continue
        if streaming:
            wav = _write_wav(out.audio_data, out.samplerate)
            _emit({"event": "result", "id": req_id, "wav": wav,
                   "stream": 1,
                   "last": 1 if completed == len(chunks) - 1 else 0})
        else:
            outs.append(out)
        completed += 1

    if cached is None and device != "cuda":
        _ref_cache_put(ref_key, tts)

    if streaming:
        return None
    import numpy as np
    merged = np.concatenate([o.audio_data for o in outs])
    samplerate = outs[0].samplerate
    return _write_wav(merged, samplerate)


def main() -> int:
    # 两个方向都是 UTF-8：源码运行有 -X utf8，打包后的 exe 没有这个参数，
    # 必须显式设置，否则 AronaAI-TTS.exe 里中文文本和路径会按 ANSI 码页解码。
    for _stream in (sys.stdin, sys.stdout, sys.stderr):
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
    if sys.stdin is None:
        # 双击启动的窗口程序，没有重定向的标准输入
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
                _prefetch(req)
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
        if wav is None:
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
