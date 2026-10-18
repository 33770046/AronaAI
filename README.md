<div align="center">

<img src="./Assets/homepage.png" width="80%" alt="homepage" />

# AronaAI

正式版本：Rel.1.0.0

基于 PySide6 和 QFluentWidgets 

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=flat-square) ![PySide6](https://img.shields.io/badge/PySide6-6.11.2-green?style=flat-square) ![QFluentWidgets](https://img.shields.io/badge/qfluentwidgets-1.11.3-orange?style=flat-square) ![License](https://img.shields.io/badge/License-GPLv3-blue.svg?style=flat-square)

</div>

---

## 如何使用

### 1. 克隆仓库

```bash
git clone https://github.com/33770046/AronaAI.git
cd AronaAI
```

### 2. 创建并激活虚拟环境

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 运行项目

```bash
python main.py
```

### 5.构建项目

```bash
pyinstaller AronaAI.spec --noconfirm --clean
move "dist\AronaAI-TTS" "dist\AronaAI\TTS"
```

---

## 项目结构

```
AronaAI/
├── main.py                     # 入口
├── AronaAI.spec                # PyInstaller 打包配置（主程序 + TTS 模块两条流水线）
├── requirements.txt            # 依赖
├── README.md
├── LICENSE
├── COPYRIGHT
│
├── config/                     # 运行时生成：config.json（API Key、主题、TTS 等设置）
├── data/                       # 运行时生成：活动数据缓存
│   ├── crawler_cache/          # 活动列表 JSON 缓存
│   └── activity_images/        # 活动横幅图片缓存
├── tts_cache/                  # 运行时生成：合成音频与参考音频特征缓存
├── gsv_models/                 # 运行时生成：TTS 基础模型（约1GB，启用 TTS 时下载）
├── langpacks/jp/               # 运行时生成：日文字典（open_jtalk + sudachidict）
├── Update/                     # 运行时生成：更新包暂存与 updater.ps1
│
├── Assets/
│   ├── homepage.png
│   ├── Font/                   # 界面字体
│   ├── HomePage/               # 首页横幅图
│   ├── Logo/                   # 应用图标
│   ├── Chat/
│   │   ├── config.ini          # 成员映射（Arona / Plana）
│   │   ├── arona/
│   │   │   ├── arona.md        # 提示词
│   │   │   └── logo.png        # 头像
│   │   ├── plana/
│   │   │   ├── plana.md
│   │   │   └── logo.png
│   │   └── ChatHistory/        # 运行时生成：聊天记录
│   │       ├── arona.md
│   │       └── plana.md
│   ├── TTS/
│   │   ├── config.ini          # 语音包清单
│   │   ├── Arona_CN/           # 阿洛娜中文语音包
│   │   ├── Arona_JP/           # 阿洛娜日文语音包
│   │   └── Plana_JP/           # 普拉娜日文语音包
│   └── Spine/
│       ├── config.ini          # Spine 模型中文映射
│       ├── arona/              # Arona Spine 模型（需自行放置）
│       ├── plana/              # Plana Spine 模型（需自行放置）
│       └── web/
│           ├── index.html          # 桌宠页
│           ├── bridge-shim.js      # 桌宠页与宿主的 QWebChannel 兼容桥
│           ├── spine-player.js     # 应用会自行下载
│           └── spine-player.css    # 应用会自行下载
│
└── App/
    ├── __init__.py
    ├── main_window.py          # 主窗口（导航 / 托盘 / 主题 / 背景模糊）
    ├── config.py               # 配置项定义（QConfig + config.json）
    ├── ai_chat.py              # AI 聊天（API 调用 + 历史记录）
    ├── agent.py                # AI Agent（function calling + 工具实现）
    ├── backdrop.py             # 对话框毛玻璃背景
    ├── update_utils.py         # 路径解析 + 自动更新 + Spine 运行时下载
    ├── crawler/
    │   ├── __init__.py
    │   ├── models.py           # 数据模型
    │   ├── images.py           # 活动图片下载
    │   └── api_worker.py       # 活动 API 抓取（并行 + 缓存）
    ├── pages/
    │   ├── __init__.py
    │   ├── home_page.py        # 首页（活动日程概览）
    │   ├── chat_page.py        # 对话页
    │   ├── chat_bubble.py      # 聊天气泡
    │   ├── schedule_page.py    # 日程页（活动卡片）
    │   ├── settings_page.py    # 设置页
    │   ├── about_page.py       # 关于 / 许可 / 版权声明
    │   ├── spine_window.py     # Spine 桌面窗口（点击穿透 / 置顶规则 / 拖拽）
    │   └── spine_webview.py    # 桌宠页 WebView2 宿主（进程内 WSGI 资源服务）
    ├── tts/
    │   ├── __init__.py
    │   ├── tts_engine.py       # TTS 引擎（常驻子进程管理 + 模型预取单飞 + 音频播放）
    │   ├── tts_child.py        # TTS 子进程（模型常驻 + 推理 + 预热 + 模型/字典下载）
    │   ├── tts_host.py         # 打包专用入口（AronaAI-TTS.exe 由此构建）
    │   └── tts_config.py       # 语音包检测 + GPU/CUDA 支持探测
    ├── hooks/
    │   ├── hook-torch.py           # PyInstaller torch 收集覆写（CUDA DLL 裁剪与桩）
    │   ├── hook-sudachipy.py       # PyInstaller sudachipy 覆写（剔除字典数据）
    │   ├── gen_torch_stubs.py      # 生成 CUDA DLL 桩
    │   └── stubs/                  # 生成的桩文件（构建产物）
```

> 标注「运行时生成」的目录不会出现在仓库里，首次运行（或用到对应功能）时自动创建。

---

## 特别提醒

### 系统要求

| 功能 | 最低系统（x64） |
|---|---|
| 程序本体 | Windows 10 |
| 窗口背景效果（云母 / 云母增强 / 亚克力） | **Windows 11 22H2（build 22621）及以上** |

窗口背景效果依赖 DWM 系统背景（`DWMWA_SYSTEMBACKDROP_TYPE`），该属性自
Windows 11 build 22621 起才提供。以下情况该项设置会置灰不可用：

- Windows 10 全系（无 Mica，且未提供亚克力回退）
- Windows 11 21H2（build 22000），属性尚未引入

程序在这些系统上会使用不透明的普通窗口，其余功能不受影响。

### 硬件

请确保您的计算机有足够的硬盘（至少 5GB）存储空间

同时，在使用 TTS语音 功能时：

1. 应用内存占用峰值可能达到 3GB，请确保内存剩余空间足够。
2. 使用**GPU 加速**需要您的 NVIDIA 显卡支持 CUDA 12.6，且显存最好大于等于 4GB。
3. TTS 模块使用了 [chinokikiss/GSV-TTS-Lite](https://github.com/chinokikiss/GSV-TTS-Lite)，支持的 GPT-SoVITS 模型有 V2、V2Pro、V2ProPlus（中、日、英）。

---

## 重要声明——版权声明

1. **源代码**：本程序（指逻辑代码、脚本、配置文件）遵循 GNU General Public License v3.0 开源协议。
2. **美术资源**：本程序所使用的所有立绘、CG、音频、Spine 模型、图片、MomoTalk主题等美术素材，其知识产权及所有权均归 Nexon / Yostar 及其关联公司所有。
3. **免责声明**：本应用为粉丝制作的非商业性同人作品，仅供学习与交流使用，请勿用于任何商业用途或非法分发。
4. **许可证隔离**：本项目中的美术资源不适用 GPLv3 协议。使用、修改或分发这些资源时，需遵守《著作权法》及版权方（Nexon/Yostar）的相关规定，因滥用美术资源引发的法律责任由行为人自行承担。
