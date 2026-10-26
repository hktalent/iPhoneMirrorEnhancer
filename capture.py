"""捕获 iPhone 镜像窗口的画面。

原理：
1. 通过 CoreGraphics 的 CGWindowList 找到 "iPhone Mirroring" 窗口在屏幕上的位置。
2. 用 CGWindowListCreateImage 抓取该窗口区域（返回 Retina 物理像素，区域精确）。
3. 通过 CGBitmapContext 把 CGImage 转成固定的 BGRA 字节缓冲（自动处理行填充），
   供 pygame 以 "BGRA" 格式 frombuffer 直接消费。

要点：mss 在 macOS 上报的是"点"分辨率，直接用会把像素区域误当点坐标，
导致抓到整屏。改用 CGWindowListCreateImage 后区域精确、分辨率更高。

注意：需要"屏幕录制"权限，未授权会返回黑图。
"""

from __future__ import annotations

import threading
import time

import Quartz  # pyobjc-framework-Quartz
from AppKit import NSScreen  # pyobjc-framework-Cocoa


class _Frame:
    """一帧画面：BGRA 字节缓冲 + 尺寸。"""

    __slots__ = ("bgra", "size")

    def __init__(self, bgra: bytes, w: int, h: int):
        self.bgra = bgra
        self.size = (w, h)


class MirrorCapture:
    """实时捕获指定窗口画面。"""

    def __init__(self, owner_name: str):
        self.owner_name = owner_name
        self._win = None      # 最近一次命中的窗口信息 dict
        self._rect = None     # 窗口点坐标 CGRect
        self._scale = 2.0     # Retina 缩放因子

    # ------------------------------------------------------------------
    # 窗口定位
    # ------------------------------------------------------------------
    def _find_window(self):
        """返回窗口信息 dict 或 None。"""
        opts = (
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements
        )
        info = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)
        for w in info or []:
            if w.get("kCGWindowOwnerName") == self.owner_name:
                return w
        return None

    @staticmethod
    def _backing_scale_for_point(x: float, y: float) -> float:
        """窗口中心落在哪个屏幕，就取该屏的 Retina 缩放因子。"""
        for s in NSScreen.screens():
            f = s.frame()
            if f.origin.x <= x <= f.origin.x + f.size.width and (
                f.origin.y <= y <= f.origin.y + f.size.height
            ):
                return s.backingScaleFactor()
        return 2.0

    def locate(self) -> bool:
        """定位窗口，建立抓取上下文。找不到返回 False。"""
        win = self._find_window()
        if not win:
            self._win = None
            self._rect = None
            return False
        self._win = win
        b = win.get("kCGWindowBounds") or {}
        self._scale = self._backing_scale_for_point(
            b.get("X", 0) + b.get("Width", 0) / 2.0,
            b.get("Y", 0) + b.get("Height", 0) / 2.0,
        )
        self._rect = Quartz.CGRectMake(
            b.get("X", 0), b.get("Y", 0), b.get("Width", 0), b.get("Height", 0)
        )
        return True

    @property
    def pixel_size(self):
        """窗口的物理像素尺寸（用于信息展示）。"""
        if self._win is None:
            return None
        b = self._win.get("kCGWindowBounds") or {}
        return (int(b.get("Width", 0) * self._scale),
                int(b.get("Height", 0) * self._scale))

    # ------------------------------------------------------------------
    # 抓帧
    # ------------------------------------------------------------------
    def grab(self):
        """抓取一帧。返回 _Frame(BGRA)，未定位/失败返回 None。"""
        if self._rect is None or self._win is None:
            return None
        # 捕获窗口内容（忽略窗口阴影/边框，取最佳分辨率）
        img = Quartz.CGWindowListCreateImage(
            self._rect,
            Quartz.kCGWindowListOptionIncludingWindow,
            self._win.get("kCGWindowNumber"),
            Quartz.kCGWindowImageBoundsIgnoreFraming
            | Quartz.kCGWindowImageBestResolution,
        )
        if img is None:
            return None
        w = Quartz.CGImageGetWidth(img)
        h = Quartz.CGImageGetHeight(img)
        if w <= 0 or h <= 0:
            return None
        # CGImage -> 原始字节（可能带行填充）
        prov = Quartz.CGImageGetDataProvider(img)
        data = Quartz.CGDataProviderCopyData(prov)
        n = Quartz.CFDataGetLength(data)
        raw = Quartz.CFDataGetBytes(data, Quartz.CFRangeMake(0, n), None)
        # 按行填充裁剪成 w*h*4（CGImage 每行按 64/16 字节对齐）
        stride = n // h if h else w * 4
        import numpy as np
        buf = np.frombuffer(raw, dtype=np.uint8).reshape(h, stride)
        bgra = buf[:, : w * 4].copy().tobytes()
        return _Frame(bgra, w, h)

    def close(self):
        """释放资源（当前无额外句柄，保留接口一致性）。"""
        return None


class ContinuousCapture:
    """后台线程持续抓帧，主线程只取「最新一帧」。

    把抓帧(慢,~100ms/帧)与渲染上屏(快)解耦：
    - 始终只渲染最新帧，避免慢抓帧拖垮渲染节奏；
    - 抓帧线程不依赖 pygame，与主线程的显示互不干扰。
    """

    def __init__(self, owner_name: str, relocate_every: int = 60):
        self._cap = MirrorCapture(owner_name)
        self._relocate_every = max(1, relocate_every)
        self._lock = threading.Lock()
        self._latest = None   # (seq, _Frame)
        self._seq = 0
        self._stop = threading.Event()
        self._thread = None
        self.frames_captured = 0

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        frame_no = 0
        while not self._stop.is_set():
            if not self._cap.locate():
                time.sleep(0.5)
                continue
            f = self._cap.grab()
            frame_no += 1
            if f is not None:
                with self._lock:
                    self._seq += 1
                    self._latest = (self._seq, f)
                self.frames_captured += 1
            # 每隔若干帧重新定位，以跟踪窗口移动/缩放
            if frame_no >= self._relocate_every:
                frame_no = 0

    def read(self):
        """返回 (seq, _Frame) 或 None（尚无帧）。线程安全。"""
        with self._lock:
            return self._latest

    @staticmethod
    def is_blank(bgra, sample_stride: int = 4000) -> bool:
        """粗略判断一帧是否基本全黑（用于跳过手机过渡期黑帧）。

        入参可为 _Frame 或纯 BGRA bytes。
        """
        if hasattr(bgra, "bgra"):
            bgra = bgra.bgra
        b = bgra
        n = len(b)
        if n == 0:
            return True
        step = max(1, sample_stride)
        non_zero = 0
        checked = 0
        for i in range(0, n, step):
            non_zero += 1 if b[i] != 0 else 0
            checked += 1
            if non_zero > max(1, checked // 100):  # 允许约1%噪点
                return False
        return True

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._cap.close()
