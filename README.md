# Highlight Recovery — RAW 高光恢复工具

一个本地运行的小工具，用于挽救 RAW 照片中过曝（高光溢出）的区域。后端用 Python +
[rawpy](https://pypi.org/project/rawpy/) （libraw 绑定）直接处理原始线性数据，前端是一个 FastAPI 托管的
单页 Web 应用，浏览器打开即用。

支持的 RAW 格式：Canon CR2/CR3、Nikon NEF/NRW、Sony ARW/SRF/SR2、Adobe DNG、
Fuji RAF、Olympus ORF、Panasonic RW2、Pentax PEF/RWL、Phase One IIQ、Hasselblad
3FR/FFF、Minolta MRW、Kodak DCR/KDC、Sigma X3F、Epson ERF 等。

---

## 快速开始（Windows）

需要 Python 3.10+（已用 3.13 验证）。

```powershell
# 1. 克隆 / 解压本仓库到任意目录
# 2. 双击 run.bat   或  pwsh -File .\run.ps1
```

启动脚本会自动安装依赖并打开浏览器到 `http://127.0.0.1:8123`。

手动运行：

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8123
```

---

## 界面

- **左栏**：内置 10 个预设。单击应用，双击仅复制参数（不切换为「激活」状态）。
- **中央**：上传后显示对比预览。中间分隔条左侧是原图，右侧是处理后；拖动分隔条任意位置对比。
  可在底栏关闭对比模式只看处理结果。
- **右栏**：实时参数。每个滑块拖动即时预览（约 50–200 ms）。
- **顶栏**：导出（JPEG / PNG / 16-bit TIFF）。导出会重新加载原始全分辨率 RAW 处理，耗时较久。

---

## 内置算法（六种，可在「恢复算法」下拉框切换）

| 算法 ID | 原理 | 适用场景 |
| --- | --- | --- |
| `luminance_mask` | 亮度蒙版 + 拐点曲线压缩，类似 Lightroom 的 Highlights 滑块 | 通用、最稳健 |
| `channel_aware` | 每通道独立 Reinhard 软滚降 + 整体最大通道缩放 | 日落、霓虹、单通道过曝 |
| `hsl_compression` | 转 HSL 仅压 L、可选择性恢复饱和度 | 人像皮肤、天空 |
| `detail_preserving` | Durand 2002 双边滤波 base/detail 分解 | 婚纱、云层等需要保留纹理 |
| `exposure_fusion` | 从线性 RAW 合成多虚拟曝光，Mertens 融合 | 室内窗外、HDR 风光 |
| `filmic_curve` | Blender 风格的 Log 软滚降曲线 | 电影、复古、柔和过渡 |

所有算法均在 **线性 RGB** 空间执行计算，最后才转回 sRGB，避免在压缩后再做 gamma 引入的色彩偏移与
带状（banding）伪影。

---

## 参数说明（10 个）

| 参数 | 范围 | 含义 |
| --- | --- | --- |
| 曝光（exposure） | −2.00 … +2.00 EV | 线性增益。在所有压缩之前应用 |
| 高光（highlights） | −100 … +100 | 负值越大压缩越强。`0` 时禁用算法（其他参数仍生效） |
| 白色（whites） | −100 … +100 | 顶端端点。压低画面最亮的几个百分点 |
| 阴影（shadows） | −100 … +100 | 阴影提亮，搭配高光压缩做局部 HDR 风格 |
| 阈值（threshold） | 0 … 100 | 压缩生效的起点，对应线性亮度 0%–100% |
| 平滑度（smoothness） | 0 … 100 | 蒙版边缘羽化的高斯 σ（像素），平滑过渡区 |
| 色彩保护（color_preservation） | 0 … 100 | 高时偏向「按比例缩放 RGB」（保色），低时偏向「逐通道压缩」（去饱） |
| 局部对比（local_contrast） | −100 … +100 | 在 `detail_preserving` / `filmic_curve` 等模式下控制细节增益 |
| 饱和度恢复（saturation_recovery） | 0 … 100 | 在已恢复的高光区域重新注入饱和度，避免「灰白」效果 |
| 恢复算法（method） | 上表六种之一 | 主算法选择 |

---

## 内置预设（10 个，可作为起点再微调）

1. **自然微调** — 轻度高光压缩，日常照片
2. **强力恢复** — 严重过曝救场
3. **天空恢复** — 过曝天空、云层、蓝调
4. **人像高光** — 保护皮肤色相
5. **婚纱白色** — 找回白色衣物褶皱质感
6. **室内窗外** — 室内拍摄窗户极强力恢复
7. **风光 HDR** — 风光天空与阴影平衡
8. **电影感** — 柔和胶片质感
9. **舞台演唱会** — 射灯环境，强阴影提升
10. **雪景 / 海滩** — 高反光环境

---

## 处理流程（pipeline）

输入：rawpy 出来的 **线性 float32 RGB** ∈ [0, 1]（已做去马赛克 + 相机白平衡 + 镜头色彩矩阵）。

```
linear RGB
   │  exposure (×2^EV)
   ▼
   │  highlight recovery（六种算法之一）
   ▼
   │  whites（顶端端点拉伸/压缩）
   ▼
   │  shadows（阴影 toe 提亮）
   ▼
   │  linear → sRGB（标准 sRGB 折线 + γ=2.4）
   ▼
   │  saturation recovery（HSL 内，仅在原始高光蒙版区域）
   ▼
   uint8 sRGB → JPEG/PNG/TIFF
```

预览使用最长边 ≤ 1400 px 的降采样副本，单次处理通常 50–250 ms；导出会重新加载全分辨率 RAW，
24 MP 文件约 3–8 秒。

---

## API（如需脚本批处理）

服务启动后：

- `GET  /api/presets` — 列出预设、算法、默认参数
- `POST /api/upload`  — 表单字段 `file`，上传 RAW，返回 `session_id`
- `POST /api/preview` — JSON `{session_id, params}`，返回 JPEG bytes
- `POST /api/export`  — JSON `{session_id, params, format, quality}`，返回 JPEG/PNG/TIFF bytes
- `DELETE /api/session/{id}` — 清理会话

---

## 项目结构

```
.
├── backend/
│   ├── main.py          FastAPI 入口
│   ├── raw_loader.py    rawpy / libraw 包装
│   ├── recovery.py      6 种高光恢复算法
│   ├── pipeline.py      参数 → 流水线 → 输出
│   └── presets.py       10 个内置预设
├── frontend/
│   ├── index.html       UI 骨架
│   ├── style.css        暗色主题
│   └── app.js           交互逻辑（vanilla JS，无框架）
├── requirements.txt
├── run.bat / run.ps1    启动器
└── README.md
```

---

## 已知限制 / 后续可扩展

- 仅在本机 127.0.0.1 监听，未做鉴权（设计如此，是本地工具）
- 未支持白平衡再调整（已经使用相机 as-shot），后续可加色温/色调滑块
- 未实现交互式径向 / 渐变蒙版，目前所有恢复都基于亮度蒙版
- 未支持 EXIF 写回到导出文件
