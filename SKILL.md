---
name: tech-video-workflow
description: Create and revise source-grounded technical explainer and release videos using Remotion, including design briefs, user-benefit scripts, official logos, voice auditions, pronunciation corrections, captions, timing, local export, and QA. Use for technical video production or revising an existing cut; not for article-only writing, ordinary code review, or autonomous publishing.
---

# Technical Video Workflow

把版本资料和源码证据转成面向用户的技术讲解视频，而不是录屏念代码。先设计，再制作；合成声音是否自然、画面是否清楚，由实际试听和预览验证，不由工具名称保证。

## 先确定本次任务

- 识别用户要新片、精简、换声、改读音、补图标还是仅导出。只执行需要的阶段。
- 确认受众、内容版本、画幅、时长范围、交付目录和素材授权。能从上下文得到的不要重复问。
- 修订前确定**用户认可的内容基线**、工程快照和音轨；不能把文件名更大的版本自动当作正确基线。
- 用户撤销“五分钟”等限制后，同步修改设计、标题和验收条件，不为旧标题偷偷删章节或加速。
- 在独立制作目录操作，不修改作为研究对象的业务仓库。默认不上传文档、音频或成片。

## 按任务读取

| 任务 | 必须参考 |
|---|---|
| 研究、脚本、时长规划 | [内容设计](references/design.md)及[设计模板](templates/design-brief.md) |
| Remotion 场景、动画与官方图标 | [画面与实现](references/visuals-remotion.md) |
| 选声音、自然化、专名与局部补录 | [配音工作流](references/voice.md)；用百炼时再读[阿里云路径](references/aliyun-tts.md) |
| 音频测时、字幕、动画触发点 | [时间轴与本地工具](references/timing-tools.md) |
| 版本修订、渲染、最终交付 | [修订与验收](references/revision-delivery.md) |
| 需要外部技能或接口资料 | [官方来源与依赖边界](references/sources.md) |

## 制作顺序与关口

1. **核查并落盘设计。** 锁定发布 tag/commit；建立“用户问题—收益—证据—限制”对应关系。设计文档完成后才开始正式动画；用户要求逐步批准时等待，否则不为每个阶段重复停顿。
2. **先做代表片段。** 选择能体现视觉语言的镜头和包含数字、项目名称的短试听。付费调用、传出文本及声音选择按用户授权范围执行；试听通过不等于授权全片。
3. **声音先定，时间再排。** 用实际音频时长、对齐后的字幕及必要停顿建立主时间轴；无配音时可按阅读节奏设计，但必须标明尚未做声音对齐。
4. **实现解释性动画。** 每章有对象、过程或前后对比，不只是轮换标题。以帧驱动运动，图文与旁白同步，等待图片与字体就绪后渲染。
5. **分层验收。** 文稿事实、格式/解码、字幕边界、抽样画面、实际听审分别记录；任何一层通过都不能代替其他层。
6. **新目录交付。** 输出本地成片、字幕、旁白稿、所需音轨、可复现工程与来源说明。明确哪些验证完成、哪些还需用户确认。

## 不随版本变化的约束

- 讲具体用户收益，也讲依赖、默认值、适用范围和取舍；不编造客户、性能倍数或官方背书。
- 显示文字与 TTS 输入分开。画面、字幕和公开文稿用 `3.7.0` 等数字版本号及规范项目名称；发音别名只进入声音生成层。
- 缓存依据实际请求内容、音色、模型、风格、语速、格式和发音规则，不按句子序号复用；变更后重新测时。
- 官方 Logo 从官方页面或仓库取得，保留来源、比例及权利说明；不能用 AI 重绘品牌标识，也不能仅因文件存在就宣称已出现在画面。
- 不默认克隆真人声音，不绕过服务额度或访问限制，不打印/提交密钥，不因服务失败擅自切换区域或付费平台。
- 未完成渲染、听审或导出时，交付已有产物并说明缺口，不把工程、截图或测试通过说成成片完成。

## 随附能力

两个 Python 3.10+ 本地工具：`scripts/build_timeline.py` 从 PCM WAV 与已对齐字幕生成帧时间轴、SRT 和章节；`scripts/inspect_media.py` 调用 FFprobe/FFmpeg 检查本地 MP4。用法和限制见[工具说明](references/timing-tools.md)。

本 Skill 不附带 TTS 凭据、商标素材、模型权重、Remotion 应用或自动发布器。根据实际环境选用官方技能和工具，不假定它们已安装。
