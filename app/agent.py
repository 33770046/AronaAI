import json
import subprocess
import os
import winreg
from datetime import datetime
from pathlib import Path

from .update_utils import get_assets_dir


CONTACT_TO_PROMPT = {
    "Arona": "arona",
    "Plana": "plana",
}


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前的日期和时间",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "在浏览器中打开网页链接",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要打开的网页URL"}
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_path",
            "description": "打开文件或文件夹",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件或文件夹的完整路径"}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "打开已安装的应用程序（从系统已安装列表中匹配）",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "应用名称"}
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_apps",
            "description": "列出系统中已安装的应用程序列表",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文本文件的内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件的完整路径"}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "将内容写入文本文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件的完整路径"},
                    "content": {"type": "string", "description": "要写入的文本内容"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "执行系统命令并返回输出结果",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"}
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "将重要信息保存到长期记忆中",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["偏好", "事实", "任务", "关系", "其他"],
                        "description": "记忆类别",
                    },
                    "content": {"type": "string", "description": "要记住的具体内容"},
                },
                "required": ["category", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "搜索长期记忆中与查询相关的内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]


def _get_current_time() -> str:
    now = datetime.now()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return f"当前时间：{now.strftime('%Y年%m月%d日 %H:%M:%S')}，{weekdays[now.weekday()]}"


def _open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        os.startfile(url)
        return f"已在浏览器中打开：{url}"
    except Exception as e:
        return f"打开网页失败：{e}"


def _open_path(path: str) -> str:
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return f"路径不存在：{path}"
    os.startfile(expanded)
    return f"已打开：{path}"


_APP_CACHE = None


def _scan_start_menu() -> dict:
    apps = {}
    search_dirs = []
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    app_data = os.environ.get("APPDATA", "")
    local_app_data = os.environ.get("LOCALAPPDATA", "")

    for base in [program_data, app_data, local_app_data]:
        if base:
            sm = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            if sm.exists():
                search_dirs.append(sm)

    for sm_dir in search_dirs:
        for lnk in sm_dir.rglob("*.lnk"):
            name = lnk.stem
            apps[name.lower()] = str(lnk)
    return apps


def _scan_registry() -> dict:
    apps = {}
    uninstall_keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for root_key, sub_key in uninstall_keys:
        try:
            with winreg.OpenKey(root_key, sub_key) as key:
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            try:
                                display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                                if not display_name:
                                    i += 1
                                    continue

                                install_loc = ""
                                for val_name in ["InstallLocation", "DisplayIcon", "UninstallString"]:
                                    try:
                                        raw = winreg.QueryValueEx(subkey, val_name)[0]
                                        if raw:
                                            p = Path(raw.strip('"'))
                                            if p.is_file():
                                                install_loc = str(p)
                                                break
                                            elif p.is_dir():
                                                exe = _find_exe_in_dir(str(p))
                                                install_loc = exe if exe else str(p)
                                                break
                                    except Exception:
                                        continue

                                apps[display_name.lower()] = install_loc
                            except Exception:
                                pass
                        i += 1
                    except OSError:
                        break
        except Exception:
            continue
    return apps


def _find_exe_in_dir(directory: str, depth: int = 1) -> str:
    """在目录中搜索可执行文件，depth控制搜索深度"""
    try:
        p = Path(directory)
        if not p.is_dir():
            return ""
        dir_name = p.name.lower()
        exe = p / f"{dir_name}.exe"
        if exe.is_file():
            return str(exe)
        if depth == 1:
            exes = list(p.glob("*.exe"))
            if exes:
                exes.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                return str(exes[0])
        elif depth == 2:
            for sub in p.iterdir():
                if sub.is_dir():
                    exe = sub / f"{sub.name.lower()}.exe"
                    if exe.is_file():
                        return str(exe)
            exes = []
            for sub in p.iterdir():
                if sub.is_dir():
                    exes.extend(sub.glob("*.exe"))
            if exes:
                exes.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                return str(exes[0])
    except Exception:
        pass
    return ""


def _scan_program_dirs() -> dict:
    """扫描 Program Files、AppData 等常见程序目录"""
    apps = {}
    dirs_to_scan = []

    for env in ["ProgramFiles", "ProgramFiles(x86)"]:
        base = os.environ.get(env, "")
        if base and os.path.isdir(base):
            dirs_to_scan.append(base)

    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        programs = Path(local_app) / "Programs"
        if programs.is_dir():
            dirs_to_scan.append(str(programs))

    app_data = os.environ.get("APPDATA", "")
    if app_data:
        for sub in ["SogouInput", "Tencent"]:
            p = Path(app_data) / sub
            if p.is_dir():
                dirs_to_scan.append(str(p))

    seen = set()
    skip_dirs = {
        "windows", "microsoft", "common files", "internet explorer",
        "windows nt", "windows defender", "package cache", "windows kits",
        "windowspowershell", "dotnet", "nuget", "pip", "python",
        "microsoft visual studio", "microsoft sdk", "msbuild",
    }

    for base_dir in dirs_to_scan:
        try:
            for item in Path(base_dir).iterdir():
                if not item.is_dir():
                    continue
                name_lower = item.name.lower()
                if name_lower in seen or name_lower.startswith("."):
                    continue
                if name_lower in skip_dirs or any(name_lower.startswith(s) for s in ("windows", "microsoft .", "python")):
                    continue
                exe = _find_exe_in_dir(str(item), depth=1)
                if exe:
                    apps[name_lower] = exe
                    seen.add(name_lower)
        except Exception:
            continue
    return apps


def _scan_path() -> dict:
    """扫描 PATH 环境变量中的可执行文件"""
    apps = {}
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    seen = set()
    system_dirs = {
        r"C:\Windows\System32", r"C:\Windows\SysWOW64", r"C:\Windows",
    }
    for d in path_dirs:
        if d in system_dirs or not os.path.isdir(d):
            continue
        try:
            for f in Path(d).iterdir():
                if f.suffix.lower() == ".exe" and f.is_file():
                    name = f.stem.lower()
                    if name not in seen:
                        apps[name] = str(f)
                        seen.add(name)
        except Exception:
            continue
    return apps


def _resolve_dir_entry(name: str, path: str) -> str:
    """对目录类型的条目，尝试找到其中的可执行文件"""
    p = Path(path.strip('"'))
    if p.is_file():
        return str(p)
    if p.is_dir():
        exe = _find_exe_in_dir(str(p), depth=1)
        if exe:
            return exe
    return ""


def _get_app_cache() -> dict:
    global _APP_CACHE
    if _APP_CACHE is not None:
        return _APP_CACHE

    apps = {}

    apps.update(_scan_registry())
    apps.update(_scan_start_menu())
    apps.update(_scan_program_dirs())
    apps.update(_scan_path())

    common_apps = {
        "notepad": r"C:\Windows\notepad.exe",
        "calc": r"C:\Windows\System32\calc.exe",
        "mspaint": r"C:\Windows\System32\mspaint.exe",
        "cmd": r"C:\Windows\System32\cmd.exe",
        "powershell": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "explorer": r"C:\Windows\explorer.exe",
        "taskmgr": r"C:\Windows\System32\Taskmgr.exe",
        "regedit": r"C:\Windows\regedit.exe",
    }
    for name, path in common_apps.items():
        if name not in apps:
            apps[name] = path

    bad_keys = set()
    for k, v in apps.items():
        v_stripped = v.strip('"')
        if v_stripped:
            if os.path.isfile(v_stripped):
                continue
            elif os.path.isdir(v_stripped):
                resolved = _resolve_dir_entry(k, v_stripped)
                if resolved:
                    apps[k] = resolved
                else:
                    bad_keys.add(k)
            else:
                bad_keys.add(k)
    for k in bad_keys:
        del apps[k]

    _APP_CACHE = apps
    return apps


def _list_apps() -> str:
    apps = _get_app_cache()
    if not apps:
        return "未找到已安装的应用程序。"

    display_names = sorted(apps.keys())
    if len(display_names) > 50:
        display_names = display_names[:50]
        display_names.append(f"... 共 {len(apps)} 个应用（仅显示前50个）")

    return "已安装的应用程序：\n" + "\n".join(f"- {n}" for n in display_names)


def _open_app(name: str) -> str:
    apps = _get_app_cache()
    name_lower = name.lower().strip()

    # 直接匹配已缓存的应用
    if name_lower in apps:
        target = apps[name_lower]
        if target and os.path.exists(target):
            try:
                os.startfile(target)
                return f"已启动：{name}"
            except Exception as e:
                return f"启动 {name} 失败：{e}"

    # 模糊匹配，找最相近的已安装应用
    best_match = None
    best_score = 0
    for app_name, app_path in apps.items():
        score = 0
        if name_lower == app_name:
            score = 100
        elif name_lower in app_name:
            score = 80 - len(app_name)
        elif app_name in name_lower:
            score = 60 - len(name_lower)
        if score > best_score and score > 0:
            best_score = score
            best_match = (app_name, app_path)

    if best_match:
        app_name, app_path = best_match
        if app_path and os.path.exists(app_path):
            try:
                os.startfile(app_path)
                return f"已启动：{app_name}"
            except Exception:
                pass

    return f"未找到应用：{name}\n提示：可以说「列出应用」查看已安装的程序"


def _read_file(path: str) -> str:
    p = Path(os.path.expanduser(path))
    if not p.exists():
        return f"文件不存在：{path}"
    if not p.is_file():
        return f"这不是一个文件：{path}"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > 3000:
            content = content[:3000] + "\n... (内容过长，已截断)"
        return content
    except Exception as e:
        return f"读取文件失败：{e}"


def _write_file(path: str, content: str) -> str:
    p = Path(os.path.expanduser(path))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入文件：{path}"
    except Exception as e:
        return f"写入文件失败：{e}"


def _run_command(command: str) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        output = result.stdout or ""
        if result.stderr:
            output += f"\n[stderr] {result.stderr}"
        if len(output) > 2000:
            output = output[:2000] + "\n... (输出过长，已截断)"
        return output.strip() or "(命令执行完成，无输出)"
    except subprocess.TimeoutExpired:
        return "命令执行超时（30秒限制）"
    except Exception as e:
        return f"命令执行失败：{e}"


def execute_tool(name: str, args: dict, contact_key: str = "") -> str:
    try:
        if name == "get_current_time":
            return _get_current_time()
        elif name == "open_url":
            return _open_url(args.get("url", ""))
        elif name == "open_path":
            return _open_path(args.get("path", ""))
        elif name == "open_app":
            return _open_app(args.get("name", ""))
        elif name == "list_apps":
            return _list_apps()
        elif name == "read_file":
            return _read_file(args.get("path", ""))
        elif name == "write_file":
            return _write_file(args.get("path", ""), args.get("content", ""))
        elif name == "run_command":
            return _run_command(args.get("command", ""))
        elif name == "save_memory":
            MemoryManager.add(contact_key, {
                "category": args.get("category", "其他"),
                "content": args.get("content", ""),
            })
            return "记忆已保存。"
        elif name == "search_memory":
            results = MemoryManager.search(contact_key, args.get("query", ""))
            if not results:
                return "未找到相关记忆。"
            return "\n".join(
                f"- [{m['category']}] {m['content']}" for m in results[:5]
            )
        else:
            return f"未知工具：{name}"
    except Exception as e:
        return f"工具执行出错：{type(e).__name__}: {e}"


class MemoryManager:
    @staticmethod
    def _memory_path(contact_key: str) -> Path:
        name = CONTACT_TO_PROMPT.get(contact_key, contact_key.lower())
        return get_assets_dir() / "Chat" / "Memory" / f"{name}.json"

    @staticmethod
    def load(contact_key: str) -> list[dict]:
        path = MemoryManager._memory_path(contact_key)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []

    @staticmethod
    def save(contact_key: str, memories: list[dict]):
        path = MemoryManager._memory_path(contact_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(memories, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def add(contact_key: str, memory: dict):
        memories = MemoryManager.load(contact_key)
        memory["timestamp"] = datetime.now().isoformat()
        memories.append(memory)
        MemoryManager.save(contact_key, memories)

    @staticmethod
    def search(contact_key: str, query: str) -> list[dict]:
        memories = MemoryManager.load(contact_key)
        if not query:
            return memories[-5:]
        query_lower = query.lower()
        return [
            m for m in memories
            if query_lower in m.get("content", "").lower()
            or query_lower in m.get("category", "").lower()
        ]
