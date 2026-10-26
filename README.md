# iPhoneMirrorEnhancer —— 屏幕级联镜像放大投影

## 项目目的

解决「**屏幕级联镜像**」问题，实现：

```
iPhone ──镜像──> macOS(小窗口) ──本工具放大──> 扩展屏/电视(全屏,不变形)
                      │
                      └──音频──> 多蓝牙音箱同步输出（Audio MIDI Setup 多输出设备）
```

- **视频**：把 macOS 上 `iPhone 镜像` 那个**很小的窗口**，实时捕捉、等比放大、全屏渲染到扩展桌面（可接电视）。
- **音频**：Mac 系统声音通过 **Audio MIDI Setup** 配置的「多输出设备」，**同时**输出到多台蓝牙音箱，做到多设备同步发声。

典型场景：手机投屏到 Mac，Mac 再把画面投到电视全屏，声音同步推给客厅多台蓝牙音箱。

---

## 一、视频部分：小窗口 → 电视全屏（本工具）

### 原理

```
iPhone 镜像窗口（屏幕上一小块，如 666×346 点）
        │  CGWindowList 定位窗口 bounds（点坐标）
        ▼
AVFoundation AVCaptureScreenInput（GPU 加速）
        │  流式抓取窗口区域，Retina 物理像素（1332×692）
        │  后台队列持续回调，~30-60fps
        ▼
CVPixelBuffer → BGRA 字节（numpy 处理行填充）
        │  pygame.image.frombuffer("BGRA")
        ▼
scale = min(屏宽/帧宽, 屏高/帧高) 等比放大 → smoothscale
        ▼
扩展屏全屏居中显示，四周留黑边（不变形）
```

即使镜像窗口在 Mac 上显示得很小，也只会被放大这一小块，**不会把整个主屏复制过去**，且保持原始宽高比、不拉伸变形。

> **刷新率**：默认用 **AVFoundation（GPU 加速）** 捕获，可达 30-60fps；若该后端启动失败或 3 秒内不出帧，自动回退到兼容的 CGWindowList 方案（约 10fps）。程序每 3 秒打印一次实际 `fps`。
> **注意**：macOS 上报的屏幕尺寸是"逻辑点"分辨率。早期版本误用 `mss` 抓帧时把像素区域当点坐标传入导致抓到整屏；现统一用窗口区域捕获，区域精确、分辨率更高。

### 安装

```bash
cd /Users/51pwn/MyWork/iPhoneMirrorEnhancer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> 依赖：`pygame`、`numpy`、`pyobjc-framework-Cocoa`、`pyobjc-framework-Quartz`、`pyobjc-framework-AVFoundation`、`pyobjc-framework-CoreMedia`、`pyobjc-framework-libdispatch`

### 运行

```bash
./run.sh --list-displays    # 查看显示器序号（0=主屏，1=扩展屏…）
./run.sh                    # 默认全屏到扩展屏[1]
./run.sh --display 1        # 指定扩展屏
./run.sh --fps 60           # 提高帧率
```

快捷键：`Esc` 退出，`R` 重新定位窗口（窗口被移动/缩放后按一次）。

### 前置条件

1. **屏幕录制权限**：系统设置 → 隐私与安全性 → 屏幕录制 → 勾选你的终端，并**重启终端**。未授权会抓出全黑帧。
2. **镜像窗口保持可见**：不要最小化或被完全遮挡。
3. **已连接扩展屏/电视**：先 `--list-displays` 确认序号。

> 质量说明：放大的是镜像窗口的**原生像素**（Retina 下约 1332×692），放到 1080p 电视约 1.4x 放大，清晰度足够。若把镜像窗口再拖小，放大倍数变大、画质会变软。

### 配置（config.py）

| 字段 | 含义 |
|---|---|
| `WINDOW_OWNER` | 镜像窗口进程名（默认 `iPhone Mirroring`） |
| `DISPLAY_INDEX` | 全屏目标扩展屏序号 |
| `FRAME_MS` | 帧间隔毫秒（30fps≈33ms） |
| `PRESERVE_ASPECT` | 保持比例不变形（默认 True） |
| `BACKGROUND` | 黑边颜色 |

---

## 二、音频部分：多蓝牙音箱同步输出

Mac 系统声音要**同时**播到多台蓝牙音箱，分两步：

### 1. 用 Audio MIDI Setup 建「多输出设备」

1. 打开 **应用程序 → 实用工具 → 音频 MIDI 设置**（Audio MIDI Setup）。
2. 点击窗口左下角 **+** → 选 **创建多输出设备**（Create Multi-Output Device）。
3. 在新出现的「多输出设备」里，**勾选**你要同时出声的若干台蓝牙音箱（可同时连接多台）。
4. 点上方小喇叭图标，把它**设为默认输出设备**（或用它命名后的名字在系统声音里选）。
5. 建议把采样率统一（如 44.1kHz），避免不同音箱时钟漂移。

> 作用：把「多个蓝牙输出」打包成一个逻辑设备，Mac 把同一路音频**同时分发**到这些音箱。

### 2. 或在控制中心用「同步播放」

macOS 较新版本支持系统级多音箱：
1. 菜单栏点**控制中心**（或点小喇叭图标）。
2. 展开**声音输出**。
3. 勾选多台设备，并启用 **「同步播放」/ Play Simultaneously**。
4. 系统会把同一音频流同步推到所选的多台音箱。

### 说明与注意

- **同步精度**：蓝牙音箱各自接收延迟不同，多台一起放时可能有不完全对齐的听感；Audio MIDI Setup 的多输出设备适合"多台同时发声"的级联场景。
- 电视画面延时可忽略；音频若想进一步对齐，可在「音频 MIDI 设置」里给不同输出加**偏移**。
- 若音箱支持 AirPlay，也可通过控制中心的 AirPlay 多设备「同步播放」直接多选。

---

## 常见问题

- **扩展屏偶尔黑屏/闪烁** → 已做三层防护：AVFoundation 后台流式抓帧；只渲染最新帧；**自动跳过过渡期黑帧**，始终保留上一帧，避免整屏闪黑。
- **刷新率偏低** → 默认已用 GPU 加速捕获（约 30-60fps）；若仍打印 `fps` 偏低，说明回退到了兼容后端，可检查屏幕录制权限。
- **画面全黑** → 屏幕录制权限未给/未重启终端；或镜像窗口被遮挡。
- **找不到窗口** → `ps aux | grep -i mirror` 看真实进程名，用 `--owner` 指定。
- **扩展屏序号报错** → 先 `--list-displays`。
- **音频只在个别音箱出声** → 检查「多输出设备」里是否勾全所有音箱，且已设为默认输出。
