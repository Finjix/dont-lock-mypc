#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
臭网易不要锁我电脑
==================

通过固定时间间隔微移鼠标，防止电脑进入锁屏 / 息屏状态。

原理：
  1. 用 Win32 ``SendInput`` 注入微小的鼠标相对移动（先右移再左移，最终
     位置不变、肉眼无感）。注入的输入会刷新系统的“最后一次输入时间”，
     从而骗过基于空闲检测的锁屏策略。
  2. 同时调用 ``SetThreadExecutionState`` 阻止系统休眠、关闭显示器。

仅支持 Windows，只用标准库，无需安装任何第三方包。

用法示例：
  python dont_lock.py               每 30 秒微移一次鼠标
  python dont_lock.py -i 60         每 60 秒一次
  python dont_lock.py --idle-aware  仅当电脑空闲达到间隔时才微移
  python dont_lock.py --hidden      后台无窗口运行
  python dont_lock.py --stop        停止正在运行的实例
"""

import argparse
import ctypes
import math
import random
import subprocess
import sys
import time
from ctypes import wintypes as wt
from pathlib import Path

if sys.platform != "win32":
    sys.exit("错误：此脚本仅支持 Windows。")

# ---------------------------------------------------------------------------
# Win32 API 绑定
# ---------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

WAIT_OBJECT_0 = 0x0000
EVENT_MODIFY_STATE = 0x0002
STOP_EVENT_NAME = r"Local\DontLockMyPC_StopEvent"


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wt.DWORD),
        ("wParamL", wt.WORD),
        ("wParamH", wt.WORD),
    )


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = (("type", wt.DWORD), ("u", _INPUTUNION))


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = (("cbSize", wt.UINT), ("dwTime", wt.DWORD))


class POINT(ctypes.Structure):
    _fields_ = (("x", wt.LONG), ("y", wt.LONG))


user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wt.UINT
user32.GetLastInputInfo.argtypes = (ctypes.POINTER(LASTINPUTINFO),)
user32.GetLastInputInfo.restype = wt.BOOL
user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
user32.GetCursorPos.restype = wt.BOOL
user32.SetCursorPos.argtypes = (wt.INT, wt.INT)
user32.SetCursorPos.restype = wt.BOOL

kernel32.GetTickCount.restype = wt.DWORD
kernel32.SetThreadExecutionState.argtypes = (wt.DWORD,)
kernel32.SetThreadExecutionState.restype = wt.DWORD
kernel32.CreateEventW.argtypes = (ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR)
kernel32.CreateEventW.restype = ctypes.c_void_p
kernel32.OpenEventW.argtypes = (wt.DWORD, wt.BOOL, wt.LPCWSTR)
kernel32.OpenEventW.restype = ctypes.c_void_p
kernel32.SetEvent.argtypes = (ctypes.c_void_p,)
kernel32.SetEvent.restype = wt.BOOL
kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, wt.DWORD)
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
kernel32.CloseHandle.restype = wt.BOOL


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def log(message: str = "") -> None:
    """pythonw 下 stdout 为 None，此时什么都不输出。"""
    if sys.stdout is not None:
        print(message, flush=True)


def warn(message: str) -> None:
    stream = sys.stderr if sys.stderr is not None else sys.stdout
    if stream is not None:
        print(message, file=stream, flush=True)


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def is_pythonw() -> bool:
    return Path(sys.executable).name.lower() == "pythonw.exe"


# ---------------------------------------------------------------------------
# 核心动作
# ---------------------------------------------------------------------------

def idle_seconds() -> float:
    """系统自最后一次输入（含注入的输入）以来经过了多少秒。"""
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


def wiggle_mouse(pixels: int) -> int:
    """向右再向左注入 1~N 像素的相对移动，最终位置不变。返回实际幅度。"""
    n = random.randint(1, max(1, pixels))
    before = POINT()
    have_before = bool(user32.GetCursorPos(ctypes.byref(before)))
    for dx in (n, -n):
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi.dx = dx
        inp.mi.dy = 0
        inp.mi.dwFlags = MOUSEEVENTF_MOVE
        if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
            # 注意：被 UIPI 拦截时 SendInput 可能不设置 GetLastError
            raise ctypes.WinError(ctypes.get_last_error())
    # “提高指针精确度”可能带来细微漂移，保险起见校回原位
    if have_before:
        after = POINT()
        if user32.GetCursorPos(ctypes.byref(after)):
            if (after.x, after.y) != (before.x, before.y):
                user32.SetCursorPos(before.x, before.y)
    return n


# ---------------------------------------------------------------------------
# 停止信号：用命名事件通知正在运行的实例退出
# ---------------------------------------------------------------------------

def signal_stop() -> bool:
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, STOP_EVENT_NAME)
    if not handle:
        return False
    try:
        return bool(kernel32.SetEvent(handle))
    finally:
        kernel32.CloseHandle(handle)


def do_stop() -> int:
    if signal_stop():
        log("已发送停止信号，正在运行的实例会自动退出。")
        return 0
    log("没有找到正在运行的实例。")
    return 1


# ---------------------------------------------------------------------------
# 后台模式：用 pythonw 重新拉起自己，脱离控制台窗口
# ---------------------------------------------------------------------------

def respawn_detached() -> int:
    script = str(Path(__file__).resolve())
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.is_file():
        command = [str(pythonw), script]
        creationflags = subprocess.DETACHED_PROCESS
    else:
        # 找不到 pythonw 时退而求其次：以无窗口方式运行 python
        command = [str(exe), script]
        creationflags = subprocess.CREATE_NO_WINDOW

    passthrough = [arg for arg in sys.argv[1:] if arg != "--hidden"]
    if "-q" not in passthrough and "--quiet" not in passthrough:
        passthrough.append("--quiet")
    command += passthrough

    try:
        subprocess.Popen(
            command,
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        warn(f"[错误] 后台启动失败：{exc}")
        return 1

    log("[OK] 已在后台无窗口启动。")
    log("     停止方法：python dont_lock.py --stop 或 start.bat --stop")
    return 0


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------

def print_banner(args: argparse.Namespace) -> None:
    if args.idle_aware:
        mode = f"空闲检测（空闲满 {args.interval} 秒后开始微移）"
    else:
        mode = f"固定间隔（每 {args.interval} 秒微移一次）"
    bar = "=" * 56
    print(bar)
    print("  臭网易不要锁我电脑 · 开始运行")
    print(f"  模式：{mode}")
    print(f"  幅度：1~{args.pixels} 像素，原位往返，肉眼无感")
    print("  停止：按 Ctrl+C 关闭窗口，或运行 dont_lock.py --stop")
    print(bar)


def show_status(args, started, next_at, wiggles) -> None:
    if sys.stdout is None:
        return
    elapsed = fmt_duration(time.monotonic() - started)
    if args.idle_aware:
        detail = f"空闲 {idle_seconds():4.0f}s / {args.interval}s"
    else:
        remain = max(0, math.ceil(next_at - time.monotonic()))
        detail = f"下次微移 {remain}s 后"
    line = f"已运行 {elapsed} | 微移 {wiggles} 次 | {detail} | Ctrl+C 退出"
    sys.stdout.write("\r" + line.ljust(72))
    sys.stdout.flush()


def run(args: argparse.Namespace) -> int:
    stop_event = kernel32.CreateEventW(None, True, False, STOP_EVENT_NAME)
    if not stop_event:
        warn("[警告] 创建停止事件失败，--stop 将无法停止本实例。")

    if not kernel32.SetThreadExecutionState(
        ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    ):
        warn("[警告] SetThreadExecutionState 失败，无法阻止系统休眠/熄屏。")

    started = time.monotonic()
    next_at = started + args.interval
    wiggles = 0
    try:
        if not args.quiet:
            print_banner(args)
        while True:
            now = time.monotonic()
            if args.idle_aware:
                due = idle_seconds() >= args.interval
            else:
                due = now >= next_at
            if due:
                try:
                    moved = wiggle_mouse(args.pixels)
                except OSError as exc:
                    warn(f"\n[警告] 注入鼠标输入失败：{exc}")
                    moved = 0
                wiggles += 1
                next_at = now + args.interval
                if not args.quiet:
                    stamp = time.strftime("%H:%M:%S")
                    print(f"\r[{stamp}] 第 {wiggles} 次微移鼠标（{moved}px）" + " " * 8)
            # 每秒醒一次：刷新状态、响应停止信号
            if stop_event:
                if kernel32.WaitForSingleObject(stop_event, 1000) == WAIT_OBJECT_0:
                    log("\n收到 --stop 停止信号，退出。")
                    return 0
            else:
                time.sleep(1.0)
            if not args.quiet:
                show_status(args, started, next_at, wiggles)
    except KeyboardInterrupt:
        log("\n已停止，鼠标恢复正常，再见。")
        return 0
    finally:
        kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        if stop_event:
            kernel32.CloseHandle(stop_event)


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"不是有效整数：{text!r}")
    if value <= 0:
        raise argparse.ArgumentTypeError("必须为正整数")
    return value


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dont_lock.py",
        description="通过定时微移鼠标防止电脑锁屏（仅 Windows，无第三方依赖）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  dont_lock.py                前台运行，每 30 秒微移一次鼠标\n"
            "  dont_lock.py -i 60          间隔改为 60 秒\n"
            "  dont_lock.py --idle-aware   仅当电脑空闲达到间隔时才微移\n"
            "  dont_lock.py --hidden       后台无窗口运行（用 --stop 停止）\n"
            "  dont_lock.py --stop         停止正在运行的实例\n"
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--hidden", action="store_true",
        help="后台无窗口运行；停止请用 --stop")
    group.add_argument(
        "--stop", action="store_true",
        help="向正在运行的实例发送停止信号后退出")
    parser.add_argument(
        "-i", "--interval", type=positive_int, default=30, metavar="秒",
        help="微移间隔秒数（默认 30；--idle-aware 模式下兼作空闲阈值）")
    parser.add_argument(
        "-p", "--pixels", type=positive_int, default=2, metavar="像素",
        help="每次微移的最大幅度（默认 2 像素，实际随机 1~N）")
    parser.add_argument(
        "--idle-aware", action="store_true",
        help="仅当系统空闲时间达到间隔秒数时才微移，平时不打扰正常使用")
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="静默运行，不输出任何状态信息")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if is_pythonw():
        args.quiet = True
    if args.stop:
        return do_stop()
    if args.hidden and not is_pythonw():
        return respawn_detached()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
