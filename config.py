"""全局配置。"""

# iPhone 镜像窗口的所有者进程名（macOS 自带的 iPhone 镜像应用）。
# 若你用了第三方镜像工具，改成对应进程名（可用 `ps aux | grep -i mirror` 查看）。
WINDOW_OWNER = "iPhone Mirroring"

# 用于全屏显示的扩展屏序号（pygame 枚举：0 = 主屏，1 = 第一块扩展屏…）。
# 可用 `--list-displays` 查看本机可用序号。
DISPLAY_INDEX = 1

# 目标帧率上限（毫秒/帧）。设为 0 表示不限制。
FRAME_MS = 1000 // 30

# 放大后是否保持原窗口宽高比（不做拉伸，超出部分留黑边）。
# 保持该选项为 True 才能保证"不变形"。
PRESERVE_ASPECT = True

# 显示背景色（留黑边时的颜色）。
BACKGROUND = (0, 0, 0)
