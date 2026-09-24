# 来源、固定版本与源码审查

研究日期：2026-09-24。网页检索用于定位实现，实际采用的逻辑已拉取源码检查。上游声称的兼容性不等于本机验证。

| 项目 | 来源与版本 | 许可证 | 采用情况 |
|---|---|---|---|
| WeChatMsg | https://github.com/LC044/WeChatMsg ，检查当前公开仓库页面 | README 声明 MIT | 当前树主要为文档，作者声明停止更新；没有从该仓库取得可核实的 macOS 4.1.13 读取实现，因此未采用 |
| ylytdeng/wechat-decrypt | https://github.com/ylytdeng/wechat-decrypt | 无法核实 | git clone 返回认证/不可访问错误；未采用其中代码，不猜测许可证或兼容性 |
| macOS local toolkit | https://gist.github.com/acmerfight/0a01249ef72970d07a2603dbb629e80f ，固定 `c98dbb10cf23c30e83d5d744905101b0880887a0` | MIT，保留于 vendor/macos_toolkit/LICENSE | 上游报告 Apple Silicon/macOS 15.6.1/微信 4.1.15 实测；本机为 4.1.13，仍需真实验证。只采用 DB 封装、WAL 校验、密钥捕获，不采用发送/UI/媒体模块 |
| SQLCipher | https://github.com/sqlcipher/sqlcipher ，tag v4.6.1，commit `c5bd336ece77922433aaf6d6fe8cf203b0c299d5` | BSD 3-Clause，保留于 vendor/SQLCIPHER-LICENSE.md | 从源码编译 CommonCrypto 后端；用于实际页解密及 SQLite/WAL 读取，已通过虚构加密库测试 |

## 已核实的实现

macOS toolkit 的 `capture_keys.py` 使用 LLDB 符号断点 `CCKeyDerivationPBKDF`，按 arm64 ABI 读取函数参数，按目标数据库盐值筛选，验证第一页 HMAC 后接受密钥，不含硬编码微信内存偏移。原代码把密钥写到私有 JSON；本项目已改为匿名继承管道，仅处理联系人库及编号消息分片。没有运行上游持久化密钥的 bootstrap。

`sqlcipher_probe.py` 使用 C API `sqlite3_open_v2(..., SQLITE_OPEN_READONLY)`、`sqlite3_key` 和 `cipher_compatibility=4`。本项目只在密文快照上使用它。读取到的页由 SQLCipher 认证；未扫描与查询无关的每一页，不能把这个流程描述为整库每一页均已检查。

实际源码核对位置：SQLCipher `src/sqlcipher.c` 的 `sqlcipher_cipher_ctx_key_derive`、`sqlcipher_page_hmac`、`sqlcipher_page_cipher`；`src/crypto_cc.c` 的 KDF 和 AES 实现；`src/wal.c` 的 WAL 恢复逻辑。确认 SQLCipher 4 默认使用 4096 字节页、32 字节 AES key、AES-256-CBC、SHA512 页 HMAC、盐异或 0x3a 后 2 轮派生 HMAC key；口令派生为 256000 轮。raw key 直接使用，不再次做口令派生。参数只在第一页校验和实际 SQLCipher schema 查询通过后才算与客户端匹配。

WAL 的逻辑页号、页认证及恢复由 SQLCipher/SQLite 处理，本项目没有按 WAL frame 序号冒充数据库页号去解密。复制后先校验 WAL header 与每个有效 frame 的滚动 checksum、generation salt，仅保留最后提交前缀，再由 SQLCipher 查询。自测明确验证了“只复制主库会漏掉消息”和“未提交事务不可见”。

## 数据结构与本机匹配状态

上游 `wechat_db.py` 中可见真实读取 SQL：contact(username,nick_name,remark)、Msg_<群ID的MD5>、local_id/server_id/local_type/create_time/real_sender_id/message_content、Name2Id.user_name。它使用过返回上限，本项目已改为 SQL 时间筛选、每批 500 条、直到读取完毕，并核对数据库 COUNT。

本机已看到与 4.x 布局吻合的 contact/contact.db 与 message/message_0.db 至 message_5.db，文件头不是明文 SQLite。这只证明文件布局与加密状态，不证明字段、密钥方法或 schema 兼容。真实读取前必须查询 sqlite_master / PRAGMA table_info；不匹配就停止。

本机只读 task port 诊断：自身 Mach-O 头读取成功；官方微信 PID 访问返回 EPERM；没有进行密钥扫描。采用临时副本方案仍需实际登录配合，当前未执行。


分享版说明：前文为研究过程记录；本项目后来在 macOS 26.5.2 / Apple Silicon / 微信 4.1.13 完成过限定范围真实读取及图片验证。未包含任何真实聊天或账号数据。当前默认阻止交互式取密钥，不能保证无打扰读取新消息；其他环境需重新验证。
