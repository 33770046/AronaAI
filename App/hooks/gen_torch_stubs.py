# -*- mode: python ; coding: utf-8 -*-
"""生成极小的 PE32+ 桩 DLL，用来替换三个体积巨大的 CUDA 库。

第三阶段实验：torch/lib 里的 cusparse64_12.dll（274 MB）+ cusolver64_11.dll
（132 MB）合计 406 MB。静态绑定它们的只有 torch_cuda.dll（以及同样被替换的
cusolver64_11.dll 自己），而我们的负载（稠密 GPT-SoVITS 推理）从不执行
稀疏 / 稠密求解器内核。cufft64_11.dll（265 MB）有意不做桩：参考音频的频谱图
会在 CUDA 上跑 torch.stft（已实测，给它做桩会抛可捕获的
`cuFFT error: CUFFT_INVALID_PLAN`）。

所有导出都指向同一个返回 1 的函数——对这三套 ABI 来说都是错误码——所以万一
真调到了被桩住的 API，torch 的 CHECK 宏会抛出可捕获的 Python 异常，而不是
闷头使用未初始化的输出参数。

导出名的来源（加载器要求所有静态导入的名字都必须存在，多导出无害）：
  * torch/lib 下每个 PE 的静态导入表和延迟导入表，排除三个目标本身；
  * 对剩余文件做 ASCII 字符串扫描（GetProcAddress 可能用到的名字）。

这台机器上没有 MSVC/MinGW/clang，PE 是手写出来的；靠 ctypes.WinDLL 加载并
逐个解析导出符号来验证（`python App/hooks/gen_torch_stubs.py` 会跑这个自检）。
"""

import os
import re
import struct

STUB_DLLS = (
    "cusparse64_12.dll",
    "cusolver64_11.dll",
)

_STRING_RE = re.compile(rb"(?:cusparse|cusolver|cufft)[A-Za-z0-9_]{2,80}")

# mov eax, 1; ret -> 返回状态 1（对应 NOT_INITIALIZED / INVALID_PLAN 等错误码）
_CODE = b"\xB8\x01\x00\x00\x00\xC3"


def _align(v, a):
    return (v + a - 1) // a * a


def _rva_to_off(rva, sections):
    for va, vs, raw, _ in sections:
        if va <= rva < va + vs:
            return raw + (rva - va)
    return None


def _parse_imports(path):
    """解析一个 PE 文件，返回 {dll 基名小写: 导入的符号集合}。"""
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] != b"MZ":
        return None
    e = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e:e + 4] != b"PE\0\0":
        return None
    fh = e + 4
    nsec, = struct.unpack_from("<H", data, fh + 2)
    optsz, = struct.unpack_from("<H", data, fh + 16)
    opt = fh + 20
    if struct.unpack_from("<H", data, opt)[0] != 0x20B:
        return None
    imagebase, = struct.unpack_from("<Q", data, opt + 24)
    dd = opt + 112
    imp_rva, = struct.unpack_from("<I", data, dd + 8)
    dil_rva, = struct.unpack_from("<I", data, dd + 13 * 8)
    secs = []
    for i in range(nsec):
        o = opt + optsz + i * 40
        vs, va, rs, raw = struct.unpack_from("<IIII", data, o + 8)
        secs.append((va, vs, raw, rs))

    def cstr(rva):
        off = _rva_to_off(rva, secs)
        if off is None:
            return None
        end = data.find(b"\0", off)
        if end < 0 or end - off > 300:
            return None
        return data[off:end].decode("ascii", "replace")

    def thunks(int_rva):
        names = set()
        off = _rva_to_off(int_rva, secs)
        if off is None:
            return names
        while True:
            ent, = struct.unpack_from("<Q", data, off)
            if ent == 0:
                break
            off += 8
            if ent & (1 << 63):
                continue
            n = cstr(ent + 2)
            if n:
                names.add(n)
        return names

    out = {}
    if imp_rva:
        off = _rva_to_off(imp_rva, secs)
        while off is not None:
            oft, _, _, nrva, ft = struct.unpack_from("<IIIII", data, off)
            if oft == 0 and nrva == 0 and ft == 0:
                break
            off += 20
            dll = cstr(nrva)
            if dll:
                out.setdefault(dll.lower(), set()).update(thunks(oft or ft))
    if dil_rva:
        off = _rva_to_off(dil_rva, secs)
        while off is not None:
            attrs, nrva, _, pint = struct.unpack_from("<IIII", data, off)
            if nrva == 0:
                break
            off += 32
            dll = cstr(nrva if attrs & 1 else nrva - imagebase)
            if dll:
                if not (attrs & 1):
                    pint -= imagebase
                out.setdefault(dll.lower(), set()).update(thunks(pint))
    return out


def compute_export_names(torch_lib_dir=None):
    if torch_lib_dir is None:
        import importlib.util as _ilu
        spec = _ilu.find_spec("torch")
        if not spec or not spec.origin:
            raise RuntimeError("cannot locate torch package")
        torch_lib_dir = os.path.join(os.path.dirname(spec.origin), "lib")
    need = {t: set() for t in STUB_DLLS}
    targets = {t.lower() for t in STUB_DLLS}
    scan_files = []
    for entry in sorted(os.listdir(torch_lib_dir)):
        if not entry.lower().endswith((".dll", ".pyd")):
            continue
        path = os.path.join(torch_lib_dir, entry)
        scan_files.append(path)
        if entry.lower() in targets:
            continue
        imps = _parse_imports(path)
        if not imps:
            continue
        for dll, names in imps.items():
            if dll in need:
                need[dll].update(names)
    for path in scan_files:
        if os.path.basename(path).lower() in targets:
            continue
        with open(path, "rb") as f:
            data = f.read()
        for m in _STRING_RE.finditer(data):
            name = m.group(0).decode("ascii")
            low = name.lower()
            if low.startswith("cusparse"):
                need["cusparse64_12.dll"].add(name)
            elif low.startswith("cusolver"):
                need["cusolver64_11.dll"].add(name)
            elif low.startswith("cufft") and "cufft64_11.dll" in need:
                need["cufft64_11.dll"].add(name)
    return {
        t: sorted(n for n in need[t] if n.isascii())
        for t in STUB_DLLS
    }


def build_stub(dll_name, names):
    names = sorted(set(names))
    n = len(names)
    if n == 0:
        raise ValueError(f"{dll_name}: empty export set")

    file_align, sect_align = 0x200, 0x1000
    sect_rva = sect_align
    sec = bytearray()

    def add(blob, align=1):
        while len(sec) % align:
            sec.append(0)
        off = len(sec)
        sec.extend(blob)
        return off

    code_off = add(_CODE, 16)
    name_offs = [add(x.encode("ascii") + b"\0") for x in names]
    dllname_off = add(dll_name.encode("ascii") + b"\0")
    funcs = struct.pack("<%dI" % n, *([sect_rva + code_off] * n))
    funcs_off = add(funcs, 4)
    ntab = b"".join(struct.pack("<I", sect_rva + o) for o in name_offs)
    ntab_off = add(ntab, 4)
    otab = struct.pack("<%dH" % n, *range(n))
    otab_off = add(otab, 2)
    exp_off = add(struct.pack(
        "<IIHHIIIIIII",
        0, 0, 0, 0,
        sect_rva + dllname_off,
        1, n, n,
        sect_rva + funcs_off,
        sect_rva + ntab_off,
        sect_rva + otab_off,
    ), 4)

    exp_rva, exp_size = sect_rva + exp_off, 40
    raw_size = _align(len(sec), file_align)
    size_of_image = _align(sect_rva + len(sec), sect_align)

    opt = bytearray()
    opt += struct.pack("<HBB", 0x20B, 14, 0)
    opt += struct.pack("<IIIII", raw_size, raw_size, 0,
                       sect_rva + code_off, sect_rva)
    opt += struct.pack("<Q", 0x180000000)
    opt += struct.pack("<II", sect_align, file_align)
    opt += struct.pack("<HHHHHH", 6, 0, 0, 0, 6, 0)
    opt += struct.pack("<I", 0)                       # Win32VersionValue
    opt += struct.pack("<II", size_of_image, 0x200)   # SizeOfImage/Headers
    opt += struct.pack("<IHH", 0, 3, 0x8560)          # CheckSum, Subsystem, DllChars
    opt += struct.pack("<QQQQ", 0x100000, 0x1000, 0x100000, 0x1000)
    opt += struct.pack("<II", 0, 16)                  # LoaderFlags/NumDirs
    dirs = [(0, 0)] * 16
    dirs[0] = (exp_rva, exp_size)
    for rva, sz in dirs:
        opt += struct.pack("<II", rva, sz)
    assert len(opt) == 0xF0, hex(len(opt))

    sect_hdr = struct.pack(
        "<8sIIIIIIHHI",
        b".text\0\0\0",
        len(sec), sect_rva, raw_size, 0x200, 0, 0, 0, 0,
        0xE0500020,  # code | execute | read | write | align16
    )
    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 0xF0, 0x1022)

    dos = bytearray(0x80)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x80)
    headers = bytes(dos) + b"PE\0\0" + coff + bytes(opt) + sect_hdr
    if len(headers) > 0x200:
        raise AssertionError("headers exceed FileAlignment")
    headers = headers.ljust(0x200, b"\0")
    return headers + bytes(sec).ljust(raw_size, b"\0")


def ensure_stubs(dest_dir, torch_lib_dir=None, force=True):
    """生成（或重新生成）桩 DLL，返回 ({小写名: 路径}, {dll: 导出数量})。"""
    names = compute_export_names(torch_lib_dir)
    os.makedirs(dest_dir, exist_ok=True)
    out = {}
    for dll in STUB_DLLS:
        path = os.path.join(dest_dir, dll)
        if force or not os.path.isfile(path):
            with open(path, "wb") as f:
                f.write(build_stub(dll, names[dll]))
        out[dll.lower()] = path
    return out, {k: len(v) for k, v in names.items()}


def _selftest():
    import ctypes

    names = compute_export_names()
    stub_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "stubs")
    paths, counts = ensure_stubs(stub_dir)
    ok = True
    for dll, path in paths.items():
        size = os.path.getsize(path)
        lib = ctypes.WinDLL(path)
        for name in names[dll]:
            if getattr(lib, name, None) is None:
                print(f"FAIL {dll}: cannot resolve {name!r}")
                ok = False
                break
        else:
            ret = getattr(lib, names[dll][0])()
            print(f"{dll}: {counts[dll]} exports resolved, first() -> {ret}, "
                  f"{size} bytes")
    if not ok:
        raise SystemExit(1)
    print("STUB SELFTEST PASS")


if __name__ == "__main__":
    _selftest()
