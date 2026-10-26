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
from av_capture import AVCapture
from display import MirrorDisplay


def list_displays():
    pygame.display.init()
    sizes = pygame.display.get_desktop_sizes()
    print(f"pygame 识别到 {len(sizes)} 块屏（逻辑分辨率）：")
    for i, (w, h) in enumerate(sizes):
        tag = " (主屏)" if i == 0 else " (扩展屏)"
        print(f"  [{i}] {w}x{h}{tag}")


def run(owner: str, display_index: int, frame_ms: int, preserve_aspect: bool):
    disp = MirrorDisplay(display_index, background=config.BACKGROUND)

    # 优先用 AVFoundation 高速后端；启动失败或无帧则回退 CGWindowList
    cap_av = AVCapture(owner)
    cap_cg = None
    backend = "av" if cap_av.start() else "cg"
    if backend == "cg":
        cap_cg = ContinuousCapture(owner)
        cap_cg.start()
    print(f"[i] 捕获后端: {backend} (av=GPU加速 / cg=兼容)")
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
    av_start_t = time.time()
    av_fallback = False

    while running:
        # 处理事件
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    running = False
                elif e.key == pygame.K_r:
                    if backend == "av":
                        cap_av.refresh_location(force=True)
                    elif cap_cg is not None:
                        cap_cg._cap._win = None
                    print("[i] 已请求重新定位窗口")

        # 取最新一帧（统一为 (seq, bgra, w, h)）
        item = None
        if backend == "av":
            r = cap_av.read()
            if r is not None:
                item = (r[0], r[3], r[1], r[2])
            # AV 兜底：3 秒内无帧则回退
            if not av_fallback and time.time() - av_start_t > 3.0 and r is None:
                av_fallback = True
                print("[i] AV 后端未出帧，回退到兼容后端", flush=True)
                cap_av.stop()
                backend = "cg"
                cap_cg = ContinuousCapture(owner)
                cap_cg.start()
        else:
            r = cap_cg.read()
            if r is not None:
                seq0, frame = r
                item = (seq0, frame.bgra, frame.size[0], frame.size[1])

        if item is not None:
            seq0, bgra, w, h = item
            if seq0 != last_seq:
                last_seq = seq0
                # 跳过「基本全黑」的过渡帧，保留上一帧，避免整屏黑屏闪烁
                if not ContinuousCapture.is_blank(bgra):
                    surface = pygame.image.frombuffer(bgra, (w, h), "BGRA")
                    disp.render(surface, preserve_aspect)
                    last_surface = surface
                    stats_frames += 1
                elif last_surface is None:
                    disp.render(
                        pygame.image.frombuffer(bgra, (w, h), "BGRA"),
                        preserve_aspect,
                    )

        # 定期打印 FPS，便于判断刷新率
        if time.time() - stats_t0 >= 3.0:
            fps = stats_frames / max(1e-6, time.time() - stats_t0)
            print(f"[i] 显示刷新约 {fps:.1f} fps", flush=True)
            stats_t0 = time.time()
            stats_frames = 0

        if frame_ms:
            clock.tick(1000 // max(frame_ms, 1))

    if backend == "av":
        cap_av.stop()
    else:
        cap_cg.stop()
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
