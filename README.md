# 微信群聊总结技能（macOS）

这是技能说明加本地 Python 项目，不是双击即用的独立应用。需要朋友自己的 Mac、Codex 会话及本人微信账号。只有 macOS 26.5.2 / Apple Silicon / 微信 4.1.13 做过实际验证；Windows、Intel Mac 和其他微信版本未验证。

## 已知限制（安装前阅读）

默认不退出或重启微信，不启动临时微信，不弹出登录窗口。当前读取新增加密记录仍需要临时密钥；尚未实现无重登录的自动持续读取。普通 export/images 命令因此可能明确停止，不能据此认为微信没登录。交互式取密钥只在用户明确同意本次登录流程后使用 --interactive-login；它可能要求退出当前微信、进入临时副本并手机确认。仅处理本人数据，不关闭 SIP，不持久保存密钥。

总结和图片理解由当前 Codex 会话完成，不要求另配模型 API Key；导出 CLI 本身不能独立语义总结。微信消息及图片在交给 Codex 阅读时进入该会话处理范围，不能称为完全离线 AI。生成的 HTML 可离线打开。

## 安装

1. 将此目录解压到一个准备长期保留的目录，用 Codex 打开这个目录。
2. 告诉 Codex：请先读 README.md，检查我的 Mac 环境，安装此项目依赖和微信总结技能。保留默认不退出微信、不重启、不弹登录的限制；不要在我未明确同意时启用交互式登录流程。
3. 安装依赖需要 uv、Git、Xcode Command Line Tools（含 clang、make、Swift、LLDB）和网络。让 Codex 检查并安装缺少的工具；不要将原作者的 .venv 或二进制复制过来。准备好后在解压的项目目录执行：

```sh
bash scripts/setup.sh
python3 scripts/install_skill.py
.venv/bin/python -m wechat_report fixture --out outputs/fixture-verified
.venv/bin/python -m unittest discover -s tests -v
```

setup.sh 创建 Python 3.12.14 虚拟环境、安装固定 Python 依赖和 Chromium，下载并校验固定 SQLCipher 提交，编译 SQLCipher 和本机 OCR。安装技能脚本会将实际解压路径写入朋友自己的技能副本；遇到同名技能会停止，不覆盖。移动项目后需调整技能中的路径。安装后在 Codex 新任务中检查技能是否可用。

fixture 和测试只验证虚构数据及程序行为，不证明这台电脑已成功读取真实微信。

## 使用

在 Codex 中说：使用 wechat-group-report-mac 技能，总结「完整群名」过去24小时的聊天，读取图片，生成离线网页报告。不要退出或重启我的微信。

支持24/48/72小时及指定起止时间。同名群需确认群ID，多账号需选择本人账号。缺少无打扰读取能力时应如实说明，不把历史导出冒充最新消息。

每次运行输出 messages.json、messages.txt、report.json、summary.md、index.html、report.png；较长PNG可编号分图。使用方法、图片审阅和来源要求见 skills/ 和 docs/。调度任务不在分享包内，朋友如需定时总结，应在自己的 Codex 中另行设置，且受相同读取限制。

## 包含与不包含

包含项目源代码、测试、技能、安装脚本、固定依赖列表、研究记录及所用第三方许可证。不含原作者的真实聊天、图片、报告、数据库、账号目录、密钥、缓存、虚拟环境、定时任务或本地二进制。

第三方来源与固定提交见 docs/RESEARCH.md；保留 vendor/ 中的许可证。此分享版未在另一台电脑完成安装和真实读取验证。

## 开源许可

本项目代码采用 MIT 许可证，见 [LICENSE](LICENSE)。第三方代码保留各自原始许可证：macOS toolkit 为 MIT，SQLCipher 为 BSD-3-Clause；详见 vendor/ 和 docs/RESEARCH.md。
