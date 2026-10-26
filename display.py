"""把捕获的帧放大并全屏渲染到指定扩展屏，保持宽高比不畸变。"""

from __future__ import annotations

import pygame


class MirrorDisplay:
    """全屏显示窗口。"""

    def __init__(self, display_index: int, background=(0, 0, 0)):
        pygame.display.init()
        pygame.display.set_caption("iPhone Mirror Enhancer")
        sizes = pygame.display.get_desktop_sizes()
        if display_index >= len(sizes):
            raise RuntimeError(
                f"扩展屏序号 {display_index} 不存在，本机只有 {len(sizes)} 块屏。"
                f"可用：{[i for i in range(len(sizes))]}"
            )
        self.background = background
        self.width, self.height = sizes[display_index]
        self.screen = pygame.display.set_mode(
            (self.width, self.height), pygame.FULLSCREEN, display=display_index
        )

    def _surface_from_frame(self, frame) -> pygame.Surface:
        """mss 帧(BGRA) -> pygame Surface(含尺寸)。"""
        return pygame.image.frombuffer(frame.bgra, frame.size, "BGRA")

    def render(self, surface: pygame.Surface, preserve_aspect: bool):
        """放大 surface 并按需保持比例居中绘制，随后刷新。"""
        self.screen.fill(self.background)
        fw, fh = surface.get_size()

        if preserve_aspect:
            scale = min(self.width / fw, self.height / fh)
            nw = max(1, int(fw * scale))
            nh = max(1, int(fh * scale))
        else:
            nw, nh = self.width, self.height

        if (nw, nh) != (fw, fh):
            surface = pygame.transform.smoothscale(surface, (nw, nh))
        ox = (self.width - nw) // 2
        oy = (self.height - nh) // 2
        self.screen.blit(surface, (ox, oy))
        pygame.display.flip()

    def quit(self):
        pygame.display.quit()
