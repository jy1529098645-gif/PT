# Highlight Recovery — RAW 高光恢复 / 局部曝光 / iPhone 风格调整

一个本地运行的小工具：在浏览器里打开，拖入 RAW 照片，做高光恢复、局部曝光、iPhone Photos 式的
全套基础调整，导出 JPEG / PNG / 16-bit TIFF。

- **后端**：Python 3.10+ / FastAPI / [rawpy](https://pypi.org/project/rawpy/)（libraw 绑定）
- **前端**：单页 vanilla JS，无前端框架，浏览器开 `http://127.0.0.1:8123`
- **格式**：21 种 RAW 扩展名（CR2/CR3、NEF/NRW、ARW、DNG、RAF、ORF、RW2、PEF、IIQ、3FR、MRW、DCR、KDC、X3F 等）

---

## 快速开始（Windows）

```powershell
# 双击 run.bat   或   pwsh -File .\run.ps1
```

启动器会自动安装依赖、起 uvicorn、打开浏览器到 `http://127.0.0.1:8123`。

手动启动：

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8123
```

---

## 界面结构

```
┌──── 顶栏 ────────────────────────────── 文件信息 ──── 重置 ──── [导出 JPEG/PNG/TIFF] ─┐
│                                                                                       │
│  ┌── 预设 (15) ──┐  ┌── 预览（拖动分隔条对比）───┐  ┌── 参数 Tab ──────────────────┐ │
│  │ • 自然微调    │  │                              │  │ 基础│色彩│细节│算法│局部│ │
│  │ • 强力恢复    │  │                              │  ├──────────────────────────────┤ │
│  │ • 天空恢复    │  │      [Before │ After]        │  │  曝光 / 鲜明度 / 高光        │ │
│  │ • 人像高光    │  │                              │  │  阴影 / 白色 / 黑点          │ │
│  │ • 婚纱白色    │  │                              │  │  亮度 / 对比度               │ │
│  │ • 室内窗外    │  │                              │  │  ...                         │ │
│  │ • 风光 HDR    │  │                              │  └──────────────────────────────┘ │
│  │ • 电影感      │  │                              │                                     │
│  │ • 鲜明 / 鲜明暖色 / 戏剧 / 银调黑白 / 自动增强 ...                                     │
│  └───────────────┘  └──────────────────────────────┘                                     │
└────────────────────────────────────────────────────────────────────────────────────┘
```

- 左：15 个预设。单击应用，双击仅复制参数。
- 中：上传后的预览。中间分隔条拖动对比原图 / 处理后。底栏可关对比模式。
- 右：参数面板，5 个 Tab。

---

## Tab 1 「基础」 — 8 个全局色调控件

| 滑块 | 范围 | 说明 |
| --- | --- | --- |
| 曝光 | ±2.00 EV | 线性 2^EV 增益（最前置） |
| **鲜明度** | ±100 | Apple Brilliance 复刻：智能提亮阴影 + 压暗高光 + 中间调局部对比 |
| 高光 | ±100 | 负值用所选「恢复算法」压暗；正值轻提 |
| 阴影 | ±100 | 阴影 toe 提升 / 压暗 |
| 白色 | ±100 | 顶端端点 |
| 黑点 | ±100 | 底端端点（lift / crush） |
| 亮度 | ±100 | γ 曲线提亮（区别于曝光的乘法增益） |
| 对比度 | ±100 | Sigmoid S-曲线（+） / 向中灰收敛（−） |

## Tab 2 「色彩」 — 4 个白平衡 + 饱和度控件

| 滑块 | 范围 | 说明 |
| --- | --- | --- |
| 饱和度 | ±100 | 经典 RGB 拉到 / 远离亮度 |
| **自然饱和度** | ±100 | Adobe Vibrance 风格：对低饱和色作用更强 |
| 色温 | ±100 | 蓝↔黄 轴 |
| 色调 | ±100 | 绿↔品红 轴 |

## Tab 3 「细节」 — 4 个细节 + 效果控件

| 滑块 | 范围 | 说明 |
| --- | --- | --- |
| **清晰度** | ±100 | 大半径 USM 限制在中间调（类似 Lightroom Clarity）。负值 = 柔焦 |
| **锐度** | 0–100 | 小半径 USM 边缘锐化 |
| **降噪** | 0–100 | 预览用双边滤波（快） / 导出用 Non-Local Means（高质量） |
| 晕影 | ±100 | 径向 r² 衰减；负 = 暗角 |

## Tab 4 「高光算法」 — 6 种专业恢复模式

主算法下拉框 + 算法专属参数。**仅在「高光」< 0 时生效**。

| 算法 ID | 原理 | 适用 |
| --- | --- | --- |
| `luminance_mask` | 亮度蒙版 + 拐点曲线（≈ Lightroom Highlights） | 通用 |
| `channel_aware` | 每通道 Reinhard 软滚降 + 整体 max-channel 缩放 | 日落、霓虹 |
| `hsl_compression` | 仅压 HSL 的 L 通道 | 人像、天空 |
| `detail_preserving` | Durand 2002 双边滤波 base/detail 分解 | 婚纱、云层 |
| `exposure_fusion` | 从线性 RAW 合成多虚拟曝光，Mertens 融合 | 室内窗外、HDR |
| `filmic_curve` | Blender 风格 Log 软滚降 | 电影、复古 |

辅助参数：阈值、平滑度、色彩保护、局部对比、饱和度恢复。

## Tab 5 「局部」 — 径向 + 渐变蒙版（**局部曝光**）

- 「+ 径向蒙版」/「+ 渐变蒙版」 加蒙版。
- 蒙版可在预览区直接拖动：中心点移动、四个边手柄改半径、端点改方向。
- 每个蒙版独立子滑块：曝光、高光、阴影、对比度、饱和度、色温、色调（7 个）。
- 支持启用 / 停用 / 反向 / 删除。
- 多个蒙版按顺序叠加（后面的看到前面的结果，匹配 Lightroom 行为）。

蒙版几何在归一化坐标存储（0–1），预览和导出共用同一规格，无需重新拟合。

---

## 15 个内置预设

**高光恢复类** — 自然微调 · 强力恢复 · 天空恢复 · 人像高光 · 婚纱白色 · 室内窗外 ·
风光 HDR · 电影感 · 舞台演唱会 · 雪景/海滩

**iPhone 风格 Look** — 鲜明 · 鲜明暖色 · 戏剧 · 银调黑白 · 自动增强

---

## 处理流水线

```
linear RGB (rawpy)
  │ 1. 全局曝光 (×2^EV)
  │ 2. 高光恢复 (6 种算法之一)
  │ 3. 白色 / 阴影 / 黑点
  │ 4. 色温 / 色调（WB）
  │ 5. 局部蒙版（径向 + 渐变）
  ▼
sRGB encode
  │ 6. 亮度 / 鲜明度 / 对比度
  │ 7. 自然饱和度 / 饱和度
  │ 8. 清晰度 / 降噪 / 锐度
  │ 9. 晕影
  ▼
JPEG / PNG / 16-bit TIFF
```

预览使用最长边 ≤ 1400 px 的降采样副本，单次处理通常 150–500 ms；导出会重新加载全分辨率 RAW，
24 MP 文件约 3–10 秒（开启高质量 NLM 降噪会更慢）。

---

## API

- `GET  /api/presets` — 列出预设、算法、默认参数
- `POST /api/upload`  — 表单字段 `file`，上传 RAW，返回 `session_id`
- `POST /api/preview` — JSON `{session_id, params}`，返回 JPEG bytes
- `POST /api/export`  — JSON `{session_id, params, format, quality}`，返回 JPEG/PNG/TIFF bytes

`params` 现包含 23 个全局字段 + `local_masks: [...]`。

---

## 项目结构

```
backend/
  main.py          FastAPI 入口
  raw_loader.py    rawpy / libraw 包装
  recovery.py      6 种高光恢复算法
  adjustments.py   iPhone 风格全局调整（鲜明度、清晰度、降噪 ...）
  masks.py         径向 + 渐变蒙版几何
  pipeline.py      参数 → 流水线 → 输出
  presets.py       15 个内置预设
frontend/
  index.html       UI（顶栏 + 预设列 + 预览 + Tab 参数面板）
  style.css        暗色主题
  app.js           交互（参数 / 蒙版拖动 / 预览 / 导出）
requirements.txt
run.bat / run.ps1
```
