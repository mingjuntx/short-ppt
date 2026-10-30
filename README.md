# Short PPT

**像做 PPT 一样，把短视频讲清楚。**

### 桌面指挥家

这是用户给“指哪放大”起的有趣叫法：手指像指挥棒，把观众的注意力带到桌面上的重点。项目和 Skill 名仍为 **Short PPT / `short-ppt`**。

现在支持连续重点轨迹：在一个放大事件中添加 `keyframes`，每帧记录 `t`（秒）、`x` / `y`（源画面归一化坐标），画面会平滑移动，最后恢复全景；顶部节点和字幕固定。格式见 [放大计划示例](assets/focus-plan.example.json)。

**当前自动检测仍采用稳定指向后触发，尚未自动生成连续追踪轨迹。** 连续轨迹需要人工或智能体结合真实画面复核。实拍测试中，近镜头、模糊及部分出框的食指有漏检；点赞手势未触发。复核补出的轨迹必须标明来源，不能称为自动识别成功。

给一段日常拍摄，自动提炼重点，生成 **顶部关键词节点、中文字幕、上方透明黑渐变、柔影字幕和粗宋体封面**；对可靠识别的手指或鼠标指向做平滑局部放大。

现在支持顶部关键词节点随话题切换：由调用 Skill 的智能体根据真实转录提炼节点标题与副标题，按实际时间生成 `chapters.json`，下方仍显示逐句字幕。用户不需要填写节点表，也不用另配 LLM API。

这是采用 `SKILL.md` 入口的 Agent Skill，也可以直接通过 Python 脚本使用。语音识别使用本地 FunASR / SeACo Paraformer；首次下载完成后，视频不需要上传到识别服务。

![封面与正片排版示意](assets/style-preview.svg)

上图是原创布局示意，不含真实视频或私人屏幕内容。仓库不附带个人参考图、模型权重或字体文件。

## 安装

已在 Windows、Python 3.11、CPU 环境验证。其他平台需自行确认字体、FFmpeg 与 ASR 依赖，尚未完成跨平台验证。

### 基础依赖

```powershell
git clone https://github.com/mingjuntx/short-ppt.git
cd short-ppt
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

FFmpeg 优先使用 `FFMPEG_BINARY`，然后检查系统 FFmpeg，最后使用 `imageio-ffmpeg` 提供的二进制。烧录字幕需要 `subtitles` / libass，脚本会检查。

### 中文字体

推荐安装 [Noto Serif SC](https://fonts.google.com/noto/specimen/Noto+Serif+SC) 可变字体，以及 [Noto Sans SC](https://fonts.google.com/noto/specimen/Noto+Sans+SC) 的 Regular 和 Bold。字体使用遵循其许可证。

```powershell
.\.venv\Scripts\python.exe scripts/configure_fonts.py
```

自动找不到时，手动指定三个文件：

```powershell
.\.venv\Scripts\python.exe scripts/configure_fonts.py --serif ./fonts/serif.ttf --sans ./fonts/sans-regular.otf --sans-bold ./fonts/sans-bold.otf
```

配置写入被 Git 忽略的 `fonts.local.json`。`--dry-run` 只检查；覆盖已有配置使用 `--force`。封面可变字体字重设置为 750，静态字体保留自身字重。

### 可选：自动中文识别

已有 SRT 时可跳过。自动识别需约数 GB 可用空间；运行目录应选择空间充足的位置。

```powershell
.\.venv\Scripts\python.exe -m pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements-asr.txt
.\.venv\Scripts\python.exe scripts/setup_asr.py --runtime-root .local-runtime
```

初始化下载三个官方模型（SeACo Paraformer、FSMN-VAD、CT Transformer），并生成被 Git 忽略的 `runtime.json`。本仓库不分发模型权重，模型与依赖遵循各自许可。默认 CPU，不自动安装 CUDA。

### 可选：手指与鼠标指向检测

指向检测与放大在本机运行，不需要把视频上传到识别服务。先安装视觉依赖；要检测手指，再下载官方 MediaPipe 手部模型：

```powershell
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements-vision.txt
.\.venv\Scripts\python.exe scripts/setup_vision.py --runtime-root .local-runtime
```

模型位置保存到仅本机使用的 `vision.local.json`。已有配置时，只有明确需要替换才使用 `setup_vision.py --force`。未配置手部模型时只分析鼠标候选；也可在检测或合成时用 `--hand-model` 指定本地模型文件。

## 使用

已有字幕：

```powershell
.\.venv\Scripts\python.exe scripts/render.py --input inputs/video.mp4 --srt inputs/subtitles.srt --output-dir outputs/final --title "一段日常拍摄\n也有自己的风格" --cover-time 2.5
```

自动识别并合成，可选章节标题：

```powershell
.\.venv\Scripts\python.exe scripts/render.py --input inputs/video.mp4 --output-dir outputs/auto --title "一段日常拍摄\n也有自己的风格" --auto-subtitles --chapter-title "日常记录" --chapter-subtitle "中文识别与排版"
```

标题需要由内容提炼时，先识别再根据 TXT 选择标题：

```powershell
.\.venv\Scripts\python.exe scripts/transcribe.py --input inputs/video.mp4 --output outputs/transcript/recognized.srt
```

更多选项：`--hotwords "产品名 人名"`、`--aspect 9:16`、`--style custom-style.json`、`--cover-only`。字幕文件与自动识别模式互斥；遇到已有同名成品会停止，避免覆盖。

### 随话题切换的顶部节点

在 Skill 工作流中，智能体先转录，再按真实语义和句子边界提炼节点，通常每段约 6–20 秒；标题保持简短，不按固定秒数或词频机械轮播。每个节点可保留对应的字幕编号作为 `evidence`。

脚本独立使用时，参考 [节点格式示例](assets/chapter-plan.example.json)，准备时间表后执行：

```powershell
.\.venv\Scripts\python.exe scripts/chapters.py --plan chapters.json --duration 36
.\.venv\Scripts\python.exe scripts/render.py --input inputs/video.mp4 --srt inputs/subtitles.srt --chapters chapters.json --output-dir outputs/chapters --title "让每段视频\n都有清晰重点"
```

`--chapters` 与单个 `--chapter-title` / `--chapter-subtitle` 互斥。节点不得重叠或超出视频时长；输出会保留校验后的 `chapters.json`。语义提炼由调用 Skill 的智能体完成，渲染脚本负责时间校验和排版，不会凭空理解素材内容。

### 指哪放大

在合成命令中添加 `--auto-focus`，即可先检测指向，再围绕可靠目标平滑推近、停留和回退：

```powershell
.\.venv\Scripts\python.exe scripts/render.py --input inputs/video.mp4 --srt inputs/subtitles.srt --chapters chapters.json --auto-focus --output-dir outputs/focus --title "把关键位置\n讲得更清楚"
```

当前初始参数为约 **1.35 倍**放大、**0.45 秒**过渡；目标稳定停留约 0.6 秒后才考虑触发，并用约 6 秒的间隔节奏限制重复触发。放大只作用于原视频画面，顶部节点和下方字幕固定排版，不跟着放大或晃动。

也可以先检测、检查结果，再使用同一份计划合成：

```powershell
.\.venv\Scripts\python.exe scripts/detect_focus.py --input inputs/video.mp4 --output outputs/focus-plan.json
.\.venv\Scripts\python.exe scripts/render.py --input inputs/video.mp4 --srt inputs/subtitles.srt --focus outputs/focus-plan.json --output-dir outputs/reviewed-focus --title "把关键位置\n讲得更清楚"
```

`--focus` 与 `--auto-focus` 互斥。自动检测会保存 `detected-focus.json`，合成结果另存校验后的 `focus.json`，方便检查触发时间、目标位置与依据。没有可靠目标时，计划可以为空，画面保持原样，不会为凑效果猜一个放大点。

需要手动指定重点时，参考 [放大计划示例](assets/focus-plan.example.json)：`start` / `end` 为秒数，`x` / `y` 是源画面从左上角起的 0–1 坐标，`zoom` 支持 1–1.8 倍，`ramp` 是推近和回退各自的秒数。`focus.json` 保留源坐标，并另存 `rendered_events` 记录画幅裁切后的坐标。启用放大时会按源帧率规范化视频帧，以保持放大时间与原音同步。

样式加载顺序为默认预设 → `fonts.local.json` → `--style` → 命令行。每个 JSON 中的字体相对路径按该 JSON 所在目录解析。导出的 `style.json` 可能含本机路径，分享前请检查。

### 作为 Skill 使用

将仓库放到支持 `SKILL.md` 的智能体的个人 Skills 目录，文件夹命名 `short-ppt`。完成依赖、字体和模型配置后，附上视频：

```text
使用 $short-ppt，把这段视频像 PPT 一样讲清楚：提炼顶部关键词，生成中文字幕和粗宋体封面，在可靠识别到指向时平滑放大，不加署名。
```

## 验证与边界

指向放大采用“推近 → 停留 → 回退”的节奏。只有目标位置与指向动作足够明确时才使用；识别不确定则保持原画。手机拍屏、光标过小、遮挡或快速移动都会影响检测，也无法保证识别任意鼠标样式。结果中的 `confidence` 是启发式质量分数，不是经过校准的识别正确概率，仍需结合证据帧复核。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

验证覆盖渐变方向、字幕文字保留、按词分行、时间轴边界、短语气词合并，以及节点排序、重叠与视频时长校验。指向检测另覆盖静态 UI、相机运动、双手歧义与稳定停留；真实 FFmpeg 合成检查放大、回退、边界、固定字幕、帧数及音轨。发布时另使用无隐私合成视频和中文 SRT 检查封面、字幕、章节、完整解码及声音，并使用已下载模型识别官方公开短音频。真实素材的转录、节点和指向计划不提交到仓库。

口语、人名、产品名可能识别错误，自动结果仍需校对。时间戳与文字不对应时脚本会停止，保留原始 JSON 供检查。低清、抖动、摩尔纹不会因排版而恢复。默认保持完整时长和原音内容，不添加音乐、不剪辑、不自动上传成片。
