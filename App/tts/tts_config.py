from dataclasses import dataclass
from pathlib import Path

from App.update_utils import get_assets_dir


@dataclass
class VoicePack:
    key: str
    character: str
    language: str
    display_name: str
    gpt_model: Path
    sovits_model: Path
    reference_audio: Path
    reference_text: str


def _parse_tts_config() -> dict[str, dict[str, VoicePack]]:
    config_path = get_assets_dir() / "TTS" / "config.ini"
    if not config_path.exists():
        return {}

    lines = config_path.read_text(encoding="utf-8").splitlines()
    characters: dict[str, str] = {}
    variants: dict[str, list[str]] = {}

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if "[" in val:
            parts = [p.strip().strip("[]") for p in val.split(",") if p.strip()]
            variants[key] = parts
        else:
            characters[key] = val

    tts_dir = get_assets_dir() / "TTS"
    result: dict[str, dict[str, VoicePack]] = {}

    for char, display_name in characters.items():
        char_variants = variants.get(char, [])
        char_packs: dict[str, VoicePack] = {}

        for var_key in char_variants:
            var_dir = tts_dir / var_key
            if not var_dir.is_dir():
                continue

            lang = "jp" if var_key.endswith("_JP") else "cn"

            gpt_files = list(var_dir.glob("*.ckpt"))
            sovits_files = list(var_dir.glob("*.pth"))
            if not gpt_files or not sovits_files:
                continue

            ref_dir = var_dir / "reference"
            ref_files = list(ref_dir.glob("*.ogg")) + list(ref_dir.glob("*.mp3"))
            if not ref_files:
                continue

            ref_audio = ref_files[0]
            ref_text = ref_audio.stem

            pack = VoicePack(
                key=var_key,
                character=char,
                language=lang,
                display_name=display_name,
                gpt_model=gpt_files[0],
                sovits_model=sovits_files[0],
                reference_audio=ref_audio,
                reference_text=ref_text,
            )
            char_packs[lang] = pack

        if char_packs:
            result[char] = char_packs

    return result


_TTS_CONFIG: dict[str, dict[str, VoicePack]] | None = None


def _ensure_loaded():
    global _TTS_CONFIG
    if _TTS_CONFIG is None:
        _TTS_CONFIG = _parse_tts_config()


def get_voice_pack(character: str, language: str) -> VoicePack | None:
    _ensure_loaded()
    return _TTS_CONFIG.get(character, {}).get(language)


def has_voice_pack(character: str, language: str) -> bool:
    return get_voice_pack(character, language) is not None


def list_characters() -> list[str]:
    _ensure_loaded()
    return list(_TTS_CONFIG.keys())


def _frozen_tts_dir() -> Path | None:
    """Self-contained TTS package folder next to the exe (packaged builds)."""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "TTS"
    return None


def _frozen_torch_version(tts_dir: Path) -> str:
    """torch version baked into the TTS package, e.g. '2.14.0+cu126'."""
    try:
        for d in (tts_dir / "_internal").glob("torch-*.dist-info"):
            name = d.name
            if name.startswith("torch-") and name.endswith(".dist-info"):
                return name[len("torch-"):-len(".dist-info")]
    except OSError:
        pass
    return ""


def detect_gpu_support() -> tuple[bool, str]:
    """Detect NVIDIA GPU + CUDA torch for the TTS GPU toggle.

    Returns (supported, label). Never imports torch (main process stays light).
    Packaged builds read the TTS package folder instead of the main process
    environment; dev keeps using the venv's torch metadata.
    """
    import shutil
    import subprocess

    tts_dir = _frozen_tts_dir()
    if tts_dir is not None:
        if not (tts_dir / "AronaAI-TTS.exe").is_file():
            return False, "未安装 TTS 模块"
        torch_ver = _frozen_torch_version(tts_dir)
        has_cuda_torch = "+cu" in torch_ver or (
            not torch_ver
            and (tts_dir / "_internal" / "torch" / "lib" / "torch_cuda.dll").is_file()
        )
    else:
        import importlib.metadata as _md
        try:
            torch_ver = _md.version("torch")
        except Exception:
            torch_ver = ""
        has_cuda_torch = "+cu" in torch_ver

    gpu_name = ""
    vram_mb = 0
    try:
        exe = shutil.which("nvidia-smi")
        if exe:
            r = subprocess.run(
                [exe, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=3,
                creationflags=0x08000000,
            )
            if r.returncode == 0 and r.stdout.strip():
                line = r.stdout.strip().splitlines()[0]
                if "," in line:
                    name, mem = line.rsplit(",", 1)
                    gpu_name = name.strip()
                    try:
                        vram_mb = int(mem.strip().split()[0])
                    except (ValueError, IndexError):
                        vram_mb = 0
                else:
                    gpu_name = line.strip()
    except Exception:
        pass

    if not gpu_name:
        return False, "未检测到 NVIDIA 显卡"
    if not has_cuda_torch:
        return False, f"当前为 CPU 版 torch（{torch_ver or '未安装'}）"
    if 0 < vram_mb < 2048:
        return False, f"显存过小（{vram_mb}MiB，需要 2GB 以上）"
    # 2.14.0+cu126 -> "CUDA 12.6"
    label = "CUDA"
    if "+cu" in torch_ver:
        digits = torch_ver.split("+cu", 1)[1]
        if digits.isdigit() and len(digits) >= 3:
            try:
                label = f"CUDA {int(digits[:-1])}.{int(digits[-1:])}"
            except ValueError:
                pass
    return True, label
