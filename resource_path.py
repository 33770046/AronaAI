import os
import sys

def get_resource_path(relative_path):
    """获取资源文件的绝对路径，适用于开发和 PyInstaller 打包后"""
    if getattr(sys, 'frozen', False):
        # 打包后：exe 所在目录
        base_path = os.path.dirname(os.path.abspath(sys.executable))
    else:
        # 开发时：项目根目录
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)