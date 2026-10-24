# 时间轴、字幕与本地工具

## 一个主时间轴

声音确定后再测时。使用实际 WAV 样本数/采样率计算长度，按帧向上取整，显式添加场景头尾留白。总帧数来自场景之和，不由标题或旧视频长度倒推。

字幕来自服务时间戳、强制对齐或人工校准；不要把整段按字数平均分配后声称精确同步。ASR 用于定位，显示文字仍以校正稿为准；必要时对齐 TTS 读法后再映射回显示稿。

给关键动作独立 cue，例如“结果出现”“放行下一条”。不要只把整个场景线性拉长来适配新声音；关键词变了，cue 也要重核。

## `build_timeline.py`

需要 Python 3.10+ 标准库，无联网、无 TTS、无视频渲染功能。

```bash
python3 scripts/build_timeline.py \
  --manifest /path/to/project/story.json \
  --output /path/to/project/timing-full-voice-r1
```

输出目录必须不存在且父目录存在，防止覆盖旧版。先验证全部输入，再生成 `timeline.json`、`captions.json`、`captions.srt` 和 `chapters.txt`。写入阶段发生磁盘错误仍可能留下不完整的新目录，只有成功退出并核查四个文件才算生成完成。

输入格式见[示例](../templates/story.json)：

- `edition` 是唯一制作版本；`contentBaseline` 标识内容来源。
- `fps` 只接受正整数；`width`/`height` 为正整数。此工具不处理变帧率或 `30000/1001` 帧率。
- `minSeconds` 为包含边界的下限；`maxSeconds` 为**严格小于**的上限。`null` 表示未设限制。含片头、留白和片尾；最终 MP4 还要单独检查，编码封装可能有轻微时长差异。
- `scenes` 顺序即播放顺序，无叠化重叠场景。叠化项目需专用时间轴，不能直接把叠化长度忽略后相加。
- 每场景指定本地 PCM WAV，相对于**输入清单目录**。不支持远程 URL、隐藏路径、越界或符号链接。检查 WAV 内容未截断，但不判断是否真的有人声。
- `headFrames`、`tailFrames` 是额外留白，音频自身静音已在实测时长内，不要重复计算。
- `captions[].startMs/endMs` 是相对于该 WAV 起点的整数毫秒；正区间、单调、可首尾相接，不允许重叠或越过音频长度。
- 拼接字幕文本必须与 `displayText` 一致，仅忽略空白，不忽略标点、大小写或数字。`spokenText` 单独保留，不被导入 SRT。
- `cues[].atMs` 也相对于 WAV 起点，必须有序且在音频内；按最近帧量化，限制在声音有效帧范围。

示例清单的音频路径和时间戳只是格式演示，仓库没有对应 WAV；必须先生成/提供音频并替换实测对齐数据，不能直接作为真片时间轴使用。

输出坐标：

| 字段 | 坐标含义 |
|---|---|
| scene `from` | 全局场景起点，帧 |
| `durationInFrames` | 头留白 + 向上取整的音频帧数 + 尾留白 |
| `audioFromFrame` | 相对场景起点的声音偏移 |
| `globalAudioFromFrame` | 全片声音起点 |
| scene `captions` | 已含头留白的场景局部毫秒 |
| 独立 `captions.json` / SRT | 全片毫秒 |
| cue `frame` / `globalFrame` | 场景局部 / 全片帧 |

输出中的 `audio` 路径仍相对于输入清单，不是输出目录。接入 Remotion 时把音频按明确清单放入 `public/`，由适配代码映射 `staticFile`；检查复制后 SHA-256 与 `audioSha256` 一致。不要在 React 中依赖本机绝对路径。

Remotion 适配应：用 `from`/`durationInFrames` 创建场景 Sequence，在局部 `audioFromFrame` 开始放音；本地字幕和 cue 跟随该 Sequence。独立字幕文件已经是全局时间，不能再次叠加场景偏移。

工具不会自动重写发音、生成对齐数据、拼音轨、混音乐或证明字幕与声音语义一致。换音频后旧字幕即使仍在长度范围内也可能错位，需要重新对齐。

## `inspect_media.py`

除 Python 外，需要可执行的 FFprobe 和 FFmpeg。路径可通过参数指定，不会自动安装。

```bash
python3 scripts/inspect_media.py \
  --video /path/to/delivery/final.mp4 \
  --timeline /path/to/project/timing-full-voice-r1/timeline.json \
  --audio required
```

- 检查单视频流、尺寸、平均帧率、实际计数帧数、容器与音视频流时长，再完整解码 AV 流。
- 时长同步容差为 `max(0.1秒, 2帧)`；上限仍按最终容器严格检查，不加容差放宽宣传限制。
- `required` 要求存在音轨；`absent` 要求完全无音轨；`optional` 允许两者。无旁白但保留音乐的版本应选 `required`。
- 输出 JSON 到标准输出，含媒体哈希与明确的 `notChecked`。需要保存时重定向到新报告文件，命令成功且 JSON 的 `status` 为 `PASS` 才算机器检查通过。
- 仅面向本地 MP4。缺少 stream timing 等信息时失败并提示人工核查，不猜测成功。
- 它不比较旁白实际说了什么，不检查响度、图标、内容或视觉质量；短测试片通过不代表整支视频已验收。

可用 FFmpeg 独立测量响度，并听审人声/背景音乐平衡；完整步骤见[验收](revision-delivery.md)。
