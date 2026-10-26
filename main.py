"""iPhone Mirroring 画面实时放大·全屏到扩展屏（保持比例不变形）。

用法：
    python3 main.py                 # 按 config.py 默认配置运行
    python3 main.py --list-displays # 列出本机显示器的序号
    python3 main.py --display 2     # 指定用第 2 块屏全屏显示
    python3 main.py --owner "iPhone Mirroring"  # 指定窗口进程名

快捷键：
    Esc     退出
    R       重新定位窗口（窗口被移动/缩放后按一次）
"""

from __future__ import annotations

import argparse
import sys
import time

import pygame

import config
from capture import ContinuousCapture
from display import MirrorDisplay


def list_displays():
    pygame.display.init()
    sizes = pygame.display.get_desktop_sizes()
    print(f"pygame 识别到 {len(sizes)} 块屏（逻辑分辨率）：")
    for i, (w, h) in enumerate(sizes):
        tag = " (主屏)" if i == 0 else " (扩展屏)"
        print(f"  [{i}] {w}x{h}{tag}")


def run(owner: str, display_index: int, frame_ms: int, preserve_aspect: bool):
    cap = ContinuousCapture(owner)
    disp = MirrorDisplay(display_index, background=config.BACKGROUND)
    cap.start()

    print(
        f"[i] 窗口进程: {owner}\n"
        f"[i] 全屏目标: 显示器[{display_index}] {disp.width}x{disp.height}\n"
        f"[i] 保持比例: {preserve_aspect}  |  帧间隔: {frame_ms}ms\n"
        f"[i] 请确保 iPhone 镜像窗口可见；首次运行需授予『屏幕录制』权限。\n"
        f"[i] 按 Esc 退出，按 R 重新定位窗口。"
    )

    clock = pygame.time.Clock()
    running = True
    last_seq = -1
    last_surface = None
    stats_t0 = time.time()
    stats_frames = 0

    while running:
        # 处理事件
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    running = False
                elif e.key == pygame.K_r:
                    cap._cap._win = None  # 触发重新定位
                    print("[i] 已请求重新定位窗口")

        # 取最新一帧
        item = cap.read()
        if item is not None:
            seq, frame = item
            if seq != last_seq:
                last_seq = seq
                # 跳过「基本全黑」的过渡帧，保留上一帧，避免整屏黑屏闪烁
                if not cap.is_blank(frame):
                    surface = disp._surface_from_frame(frame)
                    disp.render(surface, preserve_aspect)
                    last_surface = surface
                    stats_frames += 1
                # 若新帧仍非 None 但偏黑，则继续保留上一帧（不重绘，避免闪黑）
                elif last_surface is None:
                    disp.render(
                        disp._surface_from_frame(frame), preserve_aspect
                    )

        # 定期打印 FPS，便于判断刷新率
        if time.time() - stats_t0 >= 3.0:
            fps = stats_frames / (time.time() - stats_t0)
            print(f"[i] 显示刷新约 {fps:.1f} fps", flush=True)
            stats_t0 = time.time()
            stats_frames = 0

        if frame_ms:
            clock.tick(1000 // max(frame_ms, 1))

    cap.stop()
    disp.quit()
    print("[i] 已退出。")


def main():
    ap = argparse.ArgumentParser(description="iPhone Mirroring 放大全屏显示")
    ap.add_argument("--list-displays", action="store_true", help="列出显示器序号")
    ap.add_argument("--display", type=int, default=config.DISPLAY_INDEX, help="扩展屏序号")
    ap.add_argument("--owner", default=config.WINDOW_OWNER, help="窗口进程名")
    ap.add_argument("--fps", type=int, default=0, help="目标帧率(0=不限)")
    ap.add_argument("--no-aspect", action="store_true", help="强制拉伸填满(会变形)")
    args = ap.parse_args()

    if args.list_displays:
        list_displays()
        return

    frame_ms = 1000 // args.fps if args.fps else config.FRAME_MS
    run(args.owner, args.display, frame_ms, preserve_aspect=not args.no_aspect)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 运行出错：{exc}", file=sys.stderr)
        sys.exit(1)
