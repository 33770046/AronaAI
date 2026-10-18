import hashlib
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path


def supports_backdrop() -> bool:
    """当前系统是否支持「窗口背景效果」这项设置（云母 / 云母增强 / 亚克力）。

    这三种效果都依赖 DWM 系统背景（DWMWA_SYSTEMBACKDROP_TYPE），
    而该属性自 Windows 11 build 22621（22H2）起才提供。所以最低要求是
    22621，而不是 Windows 11 的起始版本 22000——在 21H2 上调用会被静默忽略。
    """
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22621


def get_bundle_dir() -> Path:
    """只读的程序资源目录。

    PyInstaller onedir 会把 Assets、LICENSE 等打包数据放进 _internal/，
    也就是 sys._MEIPASS 指向的位置；源码运行时就是仓库根目录。
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    return Path(__file__).resolve().parent.parent


def get_base_dir() -> Path:
    """可写的安装目录。

    放 config/、data/、Update/。打包后是 exe 所在目录，源码运行时是仓库根。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_assets_dir() -> Path:
    return get_bundle_dir() / "Assets"


def list_spine_models() -> list:
    """扫描 Assets/Spine，返回可用的桌面模型名。

    每个模型是一个子目录，内含 <name>_spr.skel 和 <name>_spr.atlas；
    web/ 目录（spine 播放器运行时）排除在外。资源目录缺失或为空时
    退回到 ["arona"]，保证桌面模型仍能启动。
    """
    root = get_assets_dir() / "Spine"
    models = []
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name == "web":
                continue
            if (entry / f"{entry.name}_spr.skel").is_file():
                models.append(entry.name)
    return models or ["arona"]


def spine_model_display_names() -> dict:
    """返回「模型目录名 -> 中文显示名」的映射。

    读 Assets/Spine/config.ini 里 "Arona = 阿洛娜" 这样的行。没登记的模型
    用目录名代替。文件不存在时返回空字典，调用方直接用原始名字即可。
    匹配不区分大小写，配置里的 "Arona" 能对上目录 arona。
    """
    cfg = get_assets_dir() / "Spine" / "config.ini"
    names = {}
    if not cfg.is_file():
        return names
    try:
        for raw in cfg.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if key and val:
                names[key.lower()] = val
    except OSError:
        return names
    return names


def get_exe_name() -> str:
    """安装目录里程序主文件的名字。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).name
    return "main.py"


def validate_zip(zip_path: Path):
    """校验下载下来的升级包。

    返回 (ok, message)。ok=False 表示必须放弃这次更新。
    """
    if not zip_path.exists():
        return False, "升级包不存在"
    if zip_path.stat().st_size == 0:
        return False, "升级包为空文件"

    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad is not None:
                return False, f"升级包已损坏: {bad}"
            names = zf.namelist()
            if not names:
                return False, "升级包中没有文件"
            roots = {n.split('/')[0] for n in names}
            if get_exe_name() not in roots:
                return False, f"升级包缺少 {get_exe_name()}"
    except zipfile.BadZipFile:
        return False, "不是有效的 zip 文件"
    except Exception as e:
        return False, f"校验升级包时出错: {e}"
    return True, ""


def stage_zip(zip_path: Path, version: str) -> Path:
    """解压到 Update/staging_{version}/，返回该暂存目录。"""
    update_dir = get_base_dir() / "Update"
    staging = update_dir / f"staging_{version}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(staging)
    return staging


def _ps_quote(value) -> str:
    """把值转成 PowerShell 单引号字符串字面量。"""
    return "'" + str(value).replace("'", "''") + "'"


def build_relaunch_command() -> list:
    """更新后重新启动应用要用的命令行。

    指向安装目录里的 exe / main.py，并保留当前进程收到的其它命令行参数。
    """
    install = get_base_dir()
    if getattr(sys, "frozen", False):
        cmd = [str(install / get_exe_name())]
    else:
        cmd = [sys.executable, str(install / "main.py")]
    cmd += sys.argv[1:]
    return cmd


def write_updater_script(staging: Path, install_dir: Path, exe_name: str,
                         relaunch_cmd: list, main_pid: int) -> Path:
    """生成 updater.ps1：等主进程退出、替换文件、再重新启动。"""
    update_dir = install_dir / "Update"
    update_dir.mkdir(parents=True, exist_ok=True)
    script = update_dir / "updater.ps1"

    args_literal = ",\n  ".join(_ps_quote(a) for a in relaunch_cmd)

    ps = f"""$ErrorActionPreference = 'Stop'

$MainPid     = {main_pid}
$StagingDir  = {_ps_quote(str(staging))}
$InstallDir  = {_ps_quote(str(install_dir))}
$ExeName     = {_ps_quote(exe_name)}
$RelArgs     = @(
  {args_literal}
)

$ExePath  = Join-Path $InstallDir $ExeName
$Backup   = Join-Path $InstallDir ($ExeName + '.old')
$LogPath  = Join-Path (Join-Path $InstallDir 'Update') 'updater.log'

function Write-Log($msg) {{
  try {{ Add-Content -Path $LogPath -Value ("$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  " + $msg) -Encoding UTF8 }} catch {{}}
}}

try {{
  Write-Log 'Waiting for main process to exit...'
  $deadline = (Get-Date).AddSeconds(120)
  while ((Get-Process -Id $MainPid -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) {{
    Start-Sleep -Milliseconds 500
  }}
  Start-Sleep -Milliseconds 500

  Write-Log 'Backing up current exe...'
  if (Test-Path $ExePath) {{
    if (Test-Path $Backup) {{ Remove-Item $Backup -Force -ErrorAction SilentlyContinue }}
    Rename-Item $ExePath $Backup -Force
  }}

  Write-Log 'Copying staged files over install dir...'
  Copy-Item -Path (Join-Path $StagingDir '*') -Destination $InstallDir -Recurse -Force

  if (-not (Test-Path $ExePath)) {{
    if (Test-Path $Backup) {{ Rename-Item $Backup $ExePath -Force }}
    throw 'New exe not found after copy; restored backup'
  }}

  Write-Log 'Cleaning up staging and backup...'
  Remove-Item $Backup -Force -ErrorAction SilentlyContinue
  Remove-Item $StagingDir -Recurse -Force -ErrorAction SilentlyContinue

  Write-Log 'Relaunching app...'
  Start-Process -FilePath $RelArgs[0] -ArgumentList $RelArgs[1..($RelArgs.Length - 1)] -WorkingDirectory $InstallDir
  exit 0
}} catch {{
  Write-Log ('ERROR: ' + $_.Exception.Message)
  try {{
    if (Test-Path $Backup) {{ Rename-Item $Backup $ExePath -Force }}
  }} catch {{}}
  exit 1
}}
"""
    script.write_text(ps, encoding="utf-8")
    return script


def cleanup_leftovers() -> None:
    """清掉上一次更新留下的 .old 备份和 staging 目录。"""
    try:
        base = get_base_dir()
        old_exe = base / (get_exe_name() + ".old")
        if old_exe.exists():
            old_exe.unlink()
        update_dir = base / "Update"
        if update_dir.exists():
            for d in update_dir.glob("staging_*"):
                shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


# 官方 Spine Web Player 运行时（spine-runtimes 3.8，commit 8b4844b）。
# 这几个文件的再分发受 Spine Runtimes License Agreement（Esoteric Software）
# 限制，所以不随程序打包，改为按需下载。固定在确定的 commit 上并用 SHA256
# 校验，保证用的始终是同一份已知可用的文件。
_SPINE_RUNTIME_FILES = {
    "spine-player.js": {
        "size": 475015,
        "sha256": "3F335337A8FA9C51C6502A7557EA44CD2BCB4F22483ADAE275E4ECF5EC69FAEC",
        "urls": (
            "https://cdn.jsdelivr.net/gh/EsotericSoftware/spine-runtimes@"
            "8b4844bd4b193ba9e54487ed397a777993cbad56/spine-ts/build/spine-player.js",
            "https://raw.githubusercontent.com/EsotericSoftware/spine-runtimes/"
            "8b4844bd4b193ba9e54487ed397a777993cbad56/spine-ts/build/spine-player.js",
        ),
    },
    "spine-player.css": {
        "size": 28000,
        "sha256": "CDADE32EBE78146A24F4215051CA8FA590D92B8407F30465A15F1F2B9BB1009A",
        "urls": (
            "https://cdn.jsdelivr.net/gh/EsotericSoftware/spine-runtimes@"
            "8b4844bd4b193ba9e54487ed397a777993cbad56/spine-ts/player/css/spine-player.css",
            "https://raw.githubusercontent.com/EsotericSoftware/spine-runtimes/"
            "8b4844bd4b193ba9e54487ed397a777993cbad56/spine-ts/player/css/spine-player.css",
        ),
    },
}


def _spine_runtime_ok(target: Path) -> bool:
    """两个运行时文件都存在且大小、SHA256 与固定值一致时返回 True。"""
    for name, meta in _SPINE_RUNTIME_FILES.items():
        path = target / name
        if not path.is_file() or path.stat().st_size != meta["size"]:
            return False
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return False
        if digest.lower() != meta["sha256"].lower():
            return False
    return True


def ensure_spine_runtime() -> None:
    """确保 Spine Web Player 的文件存在，缺了就下载。

    目标是 get_assets_dir()/Spine/web：源码运行时可写，打包后在 exe 旁的
    _internal/ 下也可写。下载源是官方的 spine-runtimes 仓库（GitHub，
    jsDelivr 作为备用），固定在某个 commit 上，落盘前校验 SHA256。
    所有源都失败时抛 RuntimeError。
    """
    target = get_assets_dir() / "Spine" / "web"
    target.mkdir(parents=True, exist_ok=True)
    if _spine_runtime_ok(target):
        return

    failures = []
    for name, meta in _SPINE_RUNTIME_FILES.items():
        final = target / name
        if final.is_file() and final.stat().st_size == meta["size"]:
            try:
                if hashlib.sha256(final.read_bytes()).hexdigest().lower() == meta["sha256"].lower():
                    continue
            except OSError:
                pass
        last_error = None
        for url in meta["urls"]:
            part = target / (name + ".part")
            try:
                with urllib.request.urlopen(url, timeout=15) as resp:
                    data = resp.read()
                if len(data) != meta["size"] or \
                        hashlib.sha256(data).hexdigest().lower() != meta["sha256"].lower():
                    raise ValueError("下载内容校验失败")
                part.write_bytes(data)
                part.replace(final)  # atomic on the same filesystem
                last_error = None
                break
            except Exception as e:
                last_error = e
                try:
                    if part.exists():
                        part.unlink()
                except OSError:
                    pass
        if last_error is not None:
            failures.append(f"{name}: {last_error}")

    if failures:
        raise RuntimeError("无法获取 Spine 运行时: " + "; ".join(failures))
