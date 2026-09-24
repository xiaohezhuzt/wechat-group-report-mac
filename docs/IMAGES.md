> 当前 images 和 export 在缺少密钥时默认停止。不得擅自重启微信或添加 --interactive-login。只有用户明确同意本次登录流程才可启用。

# 图片解析与总结

新 `export` 默认增加 message_resource.db 的一次性密钥获取，并为所选消息中的图片准备本地素材。既有报告可补图，不重新扩展时间或读取其他群消息：

```sh
.venv/bin/python -m wechat_report images outputs/原报告目录 --out outputs/带图片的新目录
```

命令仅捕获该账号 `message/message_resource.db` 密钥，以资源表的群 ID、server_id、文件名和文件大小关联附件。不能按消息 XML 的 MD5 直接猜磁盘路径。资源关联不匹配、未下载、格式不支持明确保留 unavailable。

依赖：Pillow 解码、cryptography 解密、imageio-ffmpeg 的本地 FFmpeg 解码 WXGF 静态首帧；Apple Vision 做本机中英文 OCR。Swift 辅助程序由 `scripts/ocr_image.swift` 编译为 `.local/bin/wechat-image-ocr`，安装脚本已包含构建步骤。图片 DAT 候选密钥由当前账号和本机 kvcomm 元信息派生，只留内存；成功必须通过实际图像解码，不能仅看 magic header。FFmpeg 二进制来自 PyPI imageio-ffmpeg（BSD-2-Clause 封装，FFmpeg 本身遵循构建所示许可证）；本项目未将二进制提交仓库。

## 三个不同阶段

1. 文件成功定位与解码：状态 `needs_visual_review`，生成 media/<消息ID>.png、SHA256、尺寸、缩略图/首帧限制以及 Apple Vision OCR 结果。
2. 当前 Codex 会话逐张调用 view_image 实际看图。OCR 可能错读中文、小数、单位、币名，必须结合画面。生成以下结构的 image_reviews.json：

```json
{"images":[{"message_id":"实际消息ID","image_sha256":"images.json中的指纹","reviewer":"current_codex_session","summary":"图片直接显示的内容","visible_text":["确实能辨认的文字"],"uncertainties":["模糊或缺失的部分；无则空数组"]}]}
```

3. `.venv/bin/python -m wechat_report review-images 输出目录 输出目录/image_reviews.json` 合并为 `reviewed`。之后当前会话重新综合全部消息，生成 report.json，并登记全部 reviewed_image_ids。`render` 拒绝尚未审阅的图片，核验图片文件指纹，HTML 折叠来源区嵌入 PNG 与审阅记录。

图片识别会更新 messages.json，旧 report.json 的 messages_sha256 不再匹配；这是防止沿用“没看图”旧结论的保护，必须重新写报告。旧报告目录保持可用，新目录另行交付。

没有另配模型 API Key；语义理解由当前 Codex 会话完成。CLI 中的 OCR 是本地文字识别，不能宣传为脱离会话的完整图片理解或自动总结。查看图片会使该画面进入当前会话的处理范围。图片文字中的网址不会自动请求。

## 格式与限制

支持常见明文、旧 XOR DAT、V1/V2 DAT；WXGF 按上游已审查方法提取 HEVC 第一帧。保留 thumbnail_only/first_frame_only，不宣称完整解析动画/Live Photo。超过 64 MiB 或 4000 万像素的图不自动处理；解码临时文件在结束时清理。只有本地下载的附件可读，本模块不会联网下载原图。

输出 images.json 可逐张核对关联证据、文件指纹、OCR、审阅状态。messages.json / messages.txt 同步保留图片识别结果，report.json 仍通过原消息 ID 关联所有重要结论。

算法来源：MIT macOS toolkit commit c98dbb10cf23c30e83d5d744905101b0880887a0 的 media_pipeline.py；保留 vendor/macos_toolkit/LICENSE。格式研究参考 https://sarv.blog/posts/wxam/ 和 https://github.com/r266-tech/wxkey 。只借鉴本地文件解码；没有采用上游持久保存账号/管理员凭据或密钥的流程。
