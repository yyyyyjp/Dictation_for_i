#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把技能安装到宿主的 skills 目录（默认 WorkBuddy）。

    python3 bin/install.py                      # -> ~/.workbuddy/skills/ielts-practice-export
    python3 bin/install.py --target ~/skills     # 自定义父目录
    python3 bin/install.py --force               # 覆盖已存在的旧版本
    python3 bin/install.py --check               # 安装后跑离线自检

其它宿主没有统一的 skills 目录，直接把本目录复制过去即可（见 PORTING.md）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "ielts-practice-export"
ROOT = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".cache", ".git", "dist")


def default_target() -> Path:
    home = Path.home()
    if os.name == "nt":
        return home / ".workbuddy" / "skills"
    return home / ".workbuddy" / "skills"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=None, help="skills 父目录")
    ap.add_argument("--force", action="store_true", help="覆盖已有安装")
    ap.add_argument("--check", action="store_true", help="安装后运行 tests/selftest.py")
    args = ap.parse_args(argv)

    parent = Path(args.target).expanduser() if args.target else default_target()
    dest = parent / NAME

    if dest.exists() and not args.force:
        print("已存在：%s\n加 --force 覆盖，或先手动备份。" % dest)
        return 1

    parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ROOT, dest, ignore=IGNORE)

    print("已安装到：%s" % dest)
    print("入口文件：%s" % (dest / "SKILL.md"))
    print("重开一个会话后即可在技能列表看到 %s。" % NAME)

    if args.check:
        r = subprocess.run([sys.executable, str(dest / "tests" / "selftest.py")])
        if r.returncode != 0:
            print("自检失败，请先修环境再使用。")
            return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
