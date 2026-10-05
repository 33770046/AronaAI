import hashlib
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path


def get_bundle_dir() -> Path:
    """Return the read-only program resource directory.

    PyInstaller onedir places bundled data (Assets, LICENSE) under
    _internal/ which sys._MEIPASS points to. In source runs this is the
    repo root.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    return Path(__file__).resolve().parent.parent


def get_base_dir() -> Path:
    """Return the writable install directory.

    Holds config/, data/, Update/. When frozen this is the folder containing
    the exe; in source runs it is the repo root.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_assets_dir() -> Path:
    return get_bundle_dir() / "Assets"


def list_spine_models() -> list:
    """Return available desktop model names by scanning Assets/Spine.

    Each model is a subdirectory holding <name>_spr.skel and
    <name>_spr.atlas. The web/ directory (the spine-player runtime) is
    excluded. Falls back to ["arona"] so the desktop model keeps working
    even when the assets directory is missing or empty.
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
    """Return a map of model dir name -> Chinese display name.

    Reads Assets/Spine/config.ini lines like "Arona = 阿洛娜". Models not
    listed fall back to their directory name. Returns an empty dict when the
    file is missing so callers can use the raw names. Matching is
    case-insensitive so config keys ("Arona") work with lower-case model
    dirs ("arona").
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
    """Name of the program's executable file in the install dir."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).name
    return "main.py"


def validate_zip(zip_path: Path):
    """Validate the downloaded upgrade zip.

    Returns (ok: bool, message: str). ok=False means the update must abort.
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
    """Extract the zip into Update/staging_{version}/; returns the staging dir."""
    update_dir = get_base_dir() / "Update"
    staging = update_dir / f"staging_{version}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(staging)
    return staging


def _ps_quote(value) -> str:
    """Quote a value as a PowerShell single-quoted string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def build_relaunch_command() -> list:
    """Build the argv to relaunch the app after update.

    Points at the exe/main.py in the install dir, keeping the other command
    line arguments passed to the current process.
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
    """Write updater.ps1 that waits for the app, swaps files, and relaunches."""
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
    """Remove stale .old backup and staging dirs left by a finished update."""
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


# Official Spine Web Player runtime (spine-runtimes 3.8, commit 8b4844b).
# Redistribution of these files is restricted by the Spine Runtimes License
# Agreement (c) Esoteric Software, so they are downloaded on demand instead of
# being bundled with the program. Pinned to a fixed commit and verified by
# SHA256 so the exact known-good files are always used.
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
    """True when both runtime files exist and match the pinned size/SHA256."""
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
    """Ensure the Spine Web Player files exist, downloading them if missing.

    The target is get_assets_dir()/Spine/web, which is writable in source
    runs and, for frozen builds, in the _internal/ folder next to the exe.
    Downloads are fetched from the official spine-runtimes repo (GitHub,
    with jsDelivr as fallback), pinned to a fixed commit and verified by
    SHA256 before being kept. Raises RuntimeError when every source fails.
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
