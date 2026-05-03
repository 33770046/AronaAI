# AronaAI 设置面板 —— 完整使用指南

> 一个基于 PyQt5 和 qfluentwidgets 的 Windows 桌面应用  
> *“可曾听闻 碧蓝档案 阿洛娜”*

![Python](https://img.shields.io/badge/Python-3.8%2B-blue) ![PyQt5](https://img.shields.io/badge/PyQt5-5.15.11-green) ![qfluentwidgets](https://img.shields.io/badge/qfluentwidgets-1.11.2-orange) ![License](https://img.shields.io/badge/License-MIT-yellow)

---

## 📖 目录

1. [项目简介](#项目简介)
2. [克隆仓库之后：完整环境搭建](#克隆仓库之后完整环境搭建)
   - [1. 克隆代码](#1-克隆代码)
   - [2. 创建并激活虚拟环境](#2-创建并激活虚拟环境)
   - [3. 安装依赖](#3-安装依赖)
   - [4. 运行项目](#4-运行项目)
3. [处理 IDE 配置文件夹 `.idea`](#处理-ide-配置文件夹-idea)
4. [常见问题 FAQ](#常见问题-faq)
5. [打包为 exe](#打包为-exe)
6. [项目结构](#项目结构)
7. [贡献与许可](#贡献与许可)

---

## 项目简介

AronaAI 设置面板是一个采用 **PyQt5** 与 **qfluentwidgets** 构建的 Windows 桌面工具，提供类似 Fluent Design 风格的用户界面，用于展示和配置 AronaAI 相关功能。  
**当前状态**：测试版本，部分功能尚未完全实现，部分 Bug 正在修复中。

---

## 克隆仓库之后：完整环境搭建

以下步骤从零开始，确保你可以在任意 Windows 电脑上成功运行该项目。
