# 黑渐变视频与封面 Skill

给一段日常拍摄，自动生成 **中文字幕、上方透明黑渐变、柔影字幕、章节标题和粗宋体封面**。

现在支持顶部关键词节点随话题切换：由调用 Skill 的智能体根据真实转录提炼节点标题与副标题，按实际时间生成 `chapters.json`，下方仍显示逐句字幕。用户不需要填写节点表，也不用另配 LLM API。

这是采用 `SKILL.md` 入口的 Agent Skill，也可以直接通过 Python 脚本使用。语音识别使用本地 FunASR / SeACo Paraformer；首次下载完成后，视频不需要上传到识别服务。

![封面与正片排版示意](assets/style-preview.svg)

上图是原创布局示意，不含真实视频或私人屏幕内容。仓库不附带个人参考图、模型权重或字体文件。

## 安装

已在 Windows、Python 3.11、CPU 环境验证。其他平台需自行确认字体、FFmpeg 与 ASR 依赖，尚未完成跨平台验证。

### 基础依赖

```powershell
git clone https://github.com/mingjuntx/video-gradient-editorial.git
cd video-gradient-editorial
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

样式加载顺序为默认预设 → `fonts.local.json` → `--style` → 命令行。每个 JSON 中的字体相对路径按该 JSON 所在目录解析。导出的 `style.json` 可能含本机路径，分享前请检查。

### 作为 Skill 使用

将仓库放到支持 `SKILL.md` 的智能体的个人 Skills 目录，文件夹命名 `video-gradient-editorial`。完成依赖、字体和模型配置后，附上视频：

```text
使用 $video-gradient-editorial，为这段视频生成中文字幕、黑渐变正片和粗宋体封面，不加署名。
```

## 验证与边界

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

验证覆盖渐变方向、字幕文字保留、按词分行、时间轴边界、短语气词合并，以及节点排序、重叠与视频时长校验。发布时另使用无隐私合成视频和中文 SRT 检查封面、字幕、章节、完整解码及声音，并使用已下载模型识别官方公开短音频。真实素材的转录和节点计划不提交到仓库。

口语、人名、产品名可能识别错误，自动结果仍需校对。时间戳与文字不对应时脚本会停止，保留原始 JSON 供检查。低清、抖动、摩尔纹不会因排版而恢复。默认保持完整时长和原音内容，不添加音乐、不剪辑、不自动上传成片。
