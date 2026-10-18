# 覆盖 _pyinstaller_hooks_contrib 的 hook-sudachipy.py（GPL-2.0-or-later，
# 沿用原逻辑）。SPDX 标识见下。
#
# 原 hook 会打包 sudachidict_* 的数据（system.dic 约 193MB）并把它加成
# hiddenimport。这两样我们都不要：冻结包本来就没有 sudachidict 的 entry
# point 元数据（裸调 Dictionary() 会抛 ModuleNotFoundError），字典由
# tts_child._seed_sudachi_dictionary() 在首次日文合成时通过 sudachi.json
# 显式指向 langpacks/jp/sudachi/system.dic。AronaAI.spec 的 _prune_tts_datas
# 还会再删一次，作为第二道防线。
#
# SPDX-License-Identifier: GPL-2.0-or-later

from PyInstaller.utils.hooks import collect_data_files, is_module_satisfies

datas = collect_data_files('sudachipy')
hiddenimports = []

# v0.6.8 起新增 sudachipy.config 和 sudachipy.errors，
# 二进制扩展里会引用到。
if is_module_satisfies('sudachipy >= 0.6.8'):
    hiddenimports += [
        'sudachipy.config',
        'sudachipy.errors',
    ]
