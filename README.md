# AronaAI---阿洛娜AI

![](./Assets/homepage.png)

> 一个基于 PySide6 和 QFluentWidgets 的 Windows 桌面应用

![Python](https://img.shields.io/badge/Python-3.8%2B-blue) ![PySide6](https://img.shields.io/badge/PySide6-6.11.1-green) ![QFluentWidgets](https://img.shields.io/badge/qfluentwidgets-1.11.2-orange) ![License](https://img.shields.io/badge/License-GPLv3-blue.svg)

---

## 项目简介

AronaAI 设置面板是一个采用 **PySide6** 与 **QFluentWidgets** 构建的 Windows 桌面工具，提供类似 Fluent Design 风格的用户界面，用于展示和配置 AronaAI 相关功能。  
**当前状态**：测试版本，部分功能尚未完全实现，部分 Bug 正在修复中。

---

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

---

## 项目结构

```
AronaAI/
├── main.py                     # 入口
├── AronaAI.spec                # PyInstaller 打包配置
├── requirements.txt            # 依赖
├── README.md
├── LICENSE
├── COPYRIGHT
│
├── Assets/
│   ├── homepage.png
│   ├── Font/
│   ├── HomePage/
│   ├── Logo/
│   ├── Chat/
│   │   ├── config.ini          # 联系人名映射
│   │   ├── arona/
│   │   │   ├── arona.md        # 人设
│   │   │   └── logo.png        # 头像
│   │   └── plana/
│   │       ├── plana.md
│   │       └── logo.png
│   └── Spine/
│       ├── config.ini          # Spine 模型中文映射
│       ├── arona/              # Arona Spine 模型（需自行放置）
│       ├── plana/              # Plana Spine 模型（需自行放置）
│       └── web/
│           ├── index.html
│           ├── spine-player.js     # 应用会自行下载
│           └── spine-player.css    # 应用会自行下载
│
└── app/
    ├── __init__.py
    ├── main_window.py          # 主窗口（MSFluentWindow）
    ├── config.py               # 配置管理（QConfig + config.json）
    ├── ai_chat.py              # AI 聊天（API调用 + 历史记录）
    ├── agent.py                # AI Agent（function calling + 工具）
    ├── backdrop.py             # DWM 毛玻璃背景
    ├── scale_utils.py          # DPI 缩放
    ├── scroll_utils.py         # 触控滚动
    ├── update_utils.py         # 资源路径 + Spine 运行时
    ├── pages/
    │   ├── __init__.py
    │   ├── home_page.py        # 首页
    │   ├── chat_page.py        # 对话页（联系人列表 + 聊天）
    │   ├── chat_bubble.py      # 聊天气泡
    │   ├── schedule_page.py    # 日程页
    │   ├── settings_page.py    # 设置页（AI配置 + 模型选择）
    │   ├── about_page.py       # 关于页
    │   └── spine_window.py     # Spine 桌面宠物窗口
    └── crawler/
        ├── __init__.py
        ├── models.py           # 数据模型
        ├── gamekee.py          # GameKee 爬虫
        ├── images.py           # 图片下载
        └── api_worker.py       # API 工作线程
```

---

## 重要声明——版权声明

1. **源代码**：本程序（指逻辑代码、脚本、配置文件）遵循 GNU General Public License v3.0 开源协议。
2. **美术资源**：本程序所使用的所有立绘、CG、音频、模型、图片、MomoTalk主题等美术素材，其知识产权及所有权均归 Nexon / Yostar 及其关联公司所有。
3. **免责声明**：本应用为粉丝制作的非商业性同人作品，仅供学习与交流使用，请勿用于任何商业用途或非法分发。
4. **许可证隔离**：本项目中的美术资源不适用 GPLv3 协议。使用、修改或分发这些资源时，需遵守《著作权法》及版权方（Nexon/Yostar）的相关规定，因滥用美术资源引发的法律责任由行为人自行承担。
