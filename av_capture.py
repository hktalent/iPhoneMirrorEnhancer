"""基于 AVFoundation 的 GPU 加速屏幕捕获（高速后端）。

原理：
- 用 CGWindowList 定位 iPhone 镜像窗口位置（点坐标），换算成 AVCaptureScreenInput
  需要的 cropRect（显示器底部原点坐标）。
- AVCaptureScreenInput 以 GPU 加速流式抓取该区域，经 AVCaptureVideoDataOutput
  的 delegate 在后台 dispatch 队列上持续回调，远快于 CGWindowListCreateImage
  （后者有约 100ms/帧的固定开销）。
- 每帧通过 CVPixelBuffer 读取 BGRA 字节，存入线程安全槽位供主线程渲染。

注意：仍需『屏幕录制』权限。若该后端启动失败或长时间不出帧，调用方应回退到
capture.ContinuousCapture（CGWindowList 方案）。
"""

from __future__ import annotations

import threading
import numpy as np

import Quartz
import AVFoundation as AV
import CoreMedia as CM
import dispatch
from Foundation import NSObject
from Quartz import CoreVideo as CV
from AppKit import NSScreen


class _AVOutputDelegate(NSObject):
    """AVCaptureVideoDataOutput 回调：读取帧字节并交给 owner 槽位。"""

    def captureOutput_didOutputSampleBuffer_fromConnection_(
        self, output, sample_buffer, connection
    ):
        buf = CM.CMSampleBufferGetImageBuffer(sample_buffer)
        CV.CVPixelBufferLockBaseAddress(buf, 0)
        try:
            w = CV.CVPixelBufferGetWidth(buf)
            h = CV.CVPixelBufferGetHeight(buf)
            br = CV.CVPixelBufferGetBytesPerRow(buf)
            if w <= 0 or h <= 0:
                return None
            base = CV.CVPixelBufferGetBaseAddress(buf)
            raw = base.as_buffer(h * br)
            if br != w * 4:
                arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, br)[:, : w * 4]
                data = arr.copy().tobytes()
            else:
                data = raw
            self._owner._push(w, h, data)
        finally:
            CV.CVPixelBufferUnlockBaseAddress(buf, 0)
        return None


def find_window_bounds(owner: str):
    """返回 iPhone 镜像窗口的 bounds dict（点坐标，全局左上原点），无则 None。"""
    opts = (
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements
    )
    info = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)
    for w in info or []:
        if w.get("kCGWindowOwnerName") == owner:
            return w.get("kCGWindowBounds") or {}
    return None


def display_and_crop(bounds: dict):
    """窗口 bounds -> (displayID, cropRect CGRect)。"""
    X = bounds.get("X", 0); Y = bounds.get("Y", 0)
    W = bounds.get("Width", 0); H = bounds.get("Height", 0)
    cx = X + W / 2.0; cy = Y + H / 2.0
    for s in NSScreen.screens():
        f = s.frame()
        if f.origin.x <= cx <= f.origin.x + f.size.width and (
            f.origin.y <= cy <= f.origin.y + f.size.height
        ):
            did = s.deviceDescription()["NSScreenNumber"]
            crop = Quartz.CGRectMake(
                X - f.origin.x,
                (f.origin.y + f.size.height) - (Y + H),
                W,
                H,
            )
            return did, crop
    # 兜底：主屏
    return Quartz.CGMainDisplayID(), Quartz.CGRectMake(X, Y, W, H)


class AVCapture:
    """AVFoundation 高速捕获。start() 后 read() 取最新帧。"""

    def __init__(self, owner_name: str, target_fps: int = 60):
        self.owner_name = owner_name
        self.target_fps = max(15, min(120, target_fps))
        self._session = None
        self._screen_input = None
        self._delegate = None
        self._queue = None
        self._lock = threading.Lock()
        self._latest = None       # (seq, w, h, bgra_bytes)
        self._seq = 0
        self._current_bounds = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def start(self) -> bool:
        bounds = find_window_bounds(self.owner_name)
        if not bounds:
            return False
        did, crop = display_and_crop(bounds)
        try:
            session = AV.AVCaptureSession.alloc().init()
            screen_input = AV.AVCaptureScreenInput.alloc().initWithDisplayID_(did)
            screen_input.setCropRect_(crop)
            screen_input.setCapturesCursor_(False)
            screen_input.setMinFrameDuration_(
                CM.CMTimeMakeWithSeconds(1.0 / self.target_fps, 600)
            )
            out = AV.AVCaptureVideoDataOutput.alloc().init()
            out.setVideoSettings_(
                {CV.kCVPixelBufferPixelFormatTypeKey: CV.kCVPixelFormatType_32BGRA}
            )
            out.setAlwaysDiscardsLateVideoFrames_(True)
            delegate = _AVOutputDelegate.alloc().init()
            delegate._owner = self
            queue = dispatch.dispatch_queue_create(b"iphone.mirror.av", None)
            out.setSampleBufferDelegate_queue_(delegate, queue)

            session.addInput_(screen_input)
            session.addOutput_(out)
            session.startRunning()

            self._session = session
            self._screen_input = screen_input
            self._delegate = delegate
            self._queue = queue
            self._current_bounds = bounds
            return True
        except Exception:
            return False

    def stop(self):
        try:
            if self._session is not None:
                self._session.stopRunning()
        except Exception:
            pass
        self._session = None
        self._screen_input = None
        self._delegate = None

    # ------------------------------------------------------------------
    # 窗口移动跟踪
    # ------------------------------------------------------------------
    def refresh_location(self, force: bool = False) -> bool:
        """窗口位置变化超过阈值时更新 cropRect。"""
        if self._screen_input is None:
            return False
        try:
            b = find_window_bounds(self.owner_name)
            if not b:
                return False
            moved = force or self._current_bounds is None
            if not moved:
                old = self._current_bounds
                moved = (
                    abs(b.get("X", 0) - old.get("X", 0)) > 2
                    or abs(b.get("Y", 0) - old.get("Y", 0)) > 2
                )
            if moved:
                _did, crop = display_and_crop(b)
                self._screen_input.setCropRect_(crop)
                self._current_bounds = b
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 帧读取
    # ------------------------------------------------------------------
    def _push(self, w, h, bgra):
        with self._lock:
            self._seq += 1
            self._latest = (self._seq, w, h, bgra)

    def read(self):
        """返回 (seq, w, h, bgra_bytes) 或 None。"""
        with self._lock:
            return self._latest
