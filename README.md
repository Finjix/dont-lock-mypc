# 臭网易不要锁我电脑

一个 PY 脚本，通过固定时间间隔移动鼠标，防止电脑进入锁屏状态。

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `dont_lock.py` | 主脚本，仅支持 Windows，只用标准库，无需 pip 安装任何东西 |
| `start.bat` | 启动器，自动寻找 Python 并运行主脚本 |

## 快速开始

1. 安装 Python 3.7+：<https://www.python.org/downloads/>（安装时勾选 *Add Python to PATH*）
2. 双击 `start.bat`

默认每 30 秒把鼠标向右再向左微移 1~2 像素（位置不变，肉眼无感），
同时调用系统 API 阻止休眠、熄屏。

## 常用命令

```bat
start.bat                 :: 前台运行，每 30 秒微移一次
start.bat -i 60           :: 间隔改为 60 秒
start.bat --idle-aware    :: 仅当电脑空闲达到间隔时才微移，平时完全不动
start.bat --hidden        :: 后台无窗口运行
start.bat --stop          :: 停止正在运行的实例
start.bat -h              :: 查看全部参数
```

也可以直接运行 `python dont_lock.py ...`，参数相同。

## 开机自启（可选）

`Win + R` 输入 `shell:startup` 回车，把 `start.bat` 的快捷方式放进去，
并在快捷方式属性的“目标”末尾加上 ` --hidden`。

## 原理

- 用 `SendInput` 注入鼠标相对移动，刷新系统“最后一次输入时间”，骗过基于空闲的锁屏策略；
- 用 `SetThreadExecutionState` 阻止系统休眠 / 关闭显示器。

## 常见问题

- **还是被锁了？** 少数管控软件只统计真实硬件输入、忽略程序注入的输入，
  这种情况下任何纯软件方案都无效，只能上硬件方案（如用开发板模拟 USB 鼠标）。
- 仅供防止自己的电脑被闲置锁屏，请勿用于逃避合理的安全管理策略 :)
