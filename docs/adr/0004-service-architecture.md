# Service 常驻架构：显式启停 + watchfiles + 动态防抖 + 30s 轮询兜底

deep-obsidian 的后台文件监控服务采用显式启停模型，基于 `watchfiles`（Rust notify binding）实现跨平台文件监控，动态防抖，30 秒全量扫描兜底。

## 为什么

### 显式启停而非自动启动

- deep-obsidian 的用户同时使用 CLI 和 Service。如果每次 `deep-obsidian search` 都自动启动 daemon，会导致短暂延迟和用户困惑（"为什么 search 要等这么久？"）
- 自动启动方案（cocoindex 模式）适合"所有命令都经过 daemon"的工具，但 deep-obsidian 的 search/query 可以直接对已有 Cognee 数据操作，不需要 daemon 在线
- 显式启停给用户清晰的心智模型：`service start` = 开始自动同步，`service stop` = 停止

### watchfiles 而非 watchdog

- watchdog 在 Windows 上有已知问题：重命名事件检测不准确、网络驱动器支持差
- watchfiles 基于 Rust 的 `notify` crate，跨平台（Linux inotify / macOS FSEvents / Windows ReadDirectoryChangesW）一致性更好
- 用户可能在 Windows 上用 Obsidian，跨平台可靠性优先

### 动态防抖而非固定窗口

- 固定防抖窗口有两难：太短（如 50ms）可能被编辑器 save 的多次事件击穿，太长（如 300ms）延迟过高
- 动态防抖模仿 Watchman 的"settle"策略：在事件流活跃期间持续等待，直到 N 毫秒内无新事件才触发处理
- 文件系统事件是不可靠信号，不是精确账本——动态防抖配合哈希比对，给出"文件稳定后才处理"的保证

### 30 秒轮询兜底

- macOS FSEvents 可能延迟上报（历史 bug），Linux inotify 队列可能溢出
- Watchman 和 Git fsmonitor 都有定期全量对比机制
- 30 秒间隔在 I/O 开销和兜底及时性之间平衡

## 权衡

- **代价**：watchfiles（Rust）需要编译环境，增加安装复杂度
- **收益**：跨平台一致的事件语义，Windows 兼容
- **被拒绝的替代方案**：watchdog（纯 Python 但 Windows 坑多）、固定防抖窗口（不够灵活）
