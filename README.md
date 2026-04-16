# wechat-mcp-server

一个用于读取本机微信数据的 MCP Server：让 Claude Code 等 AI 助手可以通过 MCP 工具读取聊天记录/会话/联系人/收藏等。

## 功能特性

- 查询微信聊天记录、联系人、会话列表、收藏等
- **Skill 蒸馏**：从聊天记录提取个人沟通风格（统计 + Few-shot + 可生成系统提示词）
- **消息监听**：近实时获取新消息（轮询会话数据库）
- **表情包管理**：解析表情消息、构建表情包库，并支持解析 `[sticker:xxx]` 占位符

## 安装

```bash
# 克隆并安装
git clone <repo-url>
cd wechat-mcp-server
pip install -e .
```

## 初始化（首次必做）

首次使用需要提取微信数据库解密密钥（会写入到 `~/.wechat-cli/all_keys.json`）：

```bash
wechat-cli-mcp init
```

你也可以手动指定微信数据目录（`db_storage`）：

```bash
wechat-cli-mcp init --db-dir "D:\\...\\db_storage"
```

### 重要提示（务必看）

- **初始化时必须保证微信正在运行**（Windows 为 `Weixin.exe`），否则无法从进程内存提取密钥。
- **权限问题**：部分系统/环境下可能需要管理员权限运行终端。
- **只读原则**：本项目只读取/解析数据，不包含“发送消息”能力。
- **密钥文件位置**：默认使用 `~/.wechat-cli/all_keys.json`。删除该文件后需要重新执行 `init`。

## 启动 MCP Server

你有 3 种方式启动（任选其一）：

### 方式一：安装后直接启动（推荐）

安装 `pip install -e .` 后，会安装命令行入口：

```bash
wechat-cli-mcp
```

**Windows 下推荐使用 SSE 模式**（更稳定）：

```bash
wechat-cli-mcp --sse
```

或通过环境变量：

```bash
MCP_TRANSPORT=sse wechat-cli-mcp
```

启动后会显示：

```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### 方式二：配置到 Claude Code

在你的 `.mcp.json` 添加：

```json
{
  "mcpServers": {
    "wechat-cli-mcp": {
      "type": "stdio",
      "command": "wechat-cli-mcp"
    }
  }
}
```

**Windows 下推荐使用 SSE 配置**：

```json
{
  "mcpServers": {
    "wechat-cli-mcp": {
      "type": "sse",
      "url": "http://127.0.0.1:8000/sse"
    }
  }
}
```

或使用 Claude CLI：

```bash
claude mcp add wechat-cli-mcp -- wechat-cli-mcp
```

**注意**：如果使用 SSE 模式，需要先手动启动 server（方式一），然后再配置 IDE 连接。

### 方式三：用 Python 模块启动

```bash
python -m wechat_cli_mcp
```

Windows 下加 SSE 参数：

```bash
python -m wechat_cli_mcp --sse
```

## 工具列表（MCP Tools）

### 基础查询工具

| 工具 | 说明 |
|------|------|
| `wechat_sessions` | 列出最近聊天会话 |
| `wechat_history` | 读取指定会话的聊天记录 |
| `wechat_search` | 按关键词搜索消息 |
| `wechat_contacts` | 搜索联系人 |
| `wechat_unread` | 未读会话 |
| `wechat_new_messages` | 增量获取新消息（自上次检查之后） |
| `wechat_members` | 群成员列表 |
| `wechat_stats` | 会话统计 |
| `wechat_favorites` | 收藏/书签 |

### Skill 蒸馏工具

| 工具 | 说明 |
|------|------|
| `wechat_distill_skill` | 从聊天记录蒸馏个人沟通风格（返回 JSON 或 Markdown） |
| `wechat_save_skill` | 蒸馏并保存到文件（JSON 或 Markdown） |

示例：

```text
# 从多个会话蒸馏
wechat_distill_skill(chat_names="张三,李四,工作群", message_limit=500)

# 保存为 Markdown
wechat_save_skill(chat_names="张三", output_path="my_style.md", output_format="markdown")
```

### 消息监听工具

| 工具 | 说明 |
|------|------|
| `wechat_start_listener` | 启动监听（近实时） |
| `wechat_stop_listener` | 停止监听 |
| `wechat_listener_status` | 查看监听状态 |
| `wechat_get_buffered_messages` | 获取监听缓冲的新消息 |

说明：监听器会轮询会话数据库的最新时间戳来发现新消息，并将新消息缓冲到内存中供工具读取。

示例：

```text
wechat_start_listener(interval=0.5)
wechat_listener_status()
wechat_get_buffered_messages(clear=true)
wechat_stop_listener()
```

### 表情包工具

| 工具 | 说明 |
|------|------|
| `wechat_build_sticker_library` | 从聊天记录中提取表情包，生成表情包统计/列表 |
| `wechat_search_stickers` | 在表情包库中搜索 |
| `wechat_list_stickers` | 列出表情包库全部内容 |
| `wechat_add_sticker` | 手动添加表情到库（命名，用于占位符） |
| `wechat_parse_sticker_placeholder` | 解析文本里的 `[sticker:xxx]` 占位符 |

示例：

```text
wechat_build_sticker_library(chat_name="张三", limit=500)
wechat_search_stickers(query="搞笑", limit=10)
wechat_parse_sticker_placeholder(text="哈哈 [sticker:狗头]")
```

## 实时消息监听 CLI 工具

项目包含一个独立的命令行工具 `wechat-listen`，可以实时监听并显示微信新消息。

### 使用方法

**自动检测消息目录：**

```bash
wechat-listen
```

**指定消息目录：**

```bash
wechat-listen --msg-dir "D:\xwechat_files\wxid_xxx\db_storage\message"
```

**设置轮询间隔：**

```bash
wechat-listen --interval 0.3
```

### 功能说明

- 进入交互模式后，实时显示新收到的消息
- 显示发送者、会话、消息内容和时间
- 按 `Ctrl+C` 退出监听
- 适合用于实时监控微信消息

### 示例输出

```
启动监听器...
监听器已启动，监控: D:\xwechat_files\wxid_xxx\db_storage\message
按 Ctrl+C 退出
==================================================

[16:30:15] [群] 工作群
  张三: 大家好

[16:31:02] 李四
  李四: 收到

```

## 常见使用场景

### 场景 1：把你的聊天风格“蒸馏”成系统提示词

- 对多个你常用的会话做 `wechat_distill_skill`
- 将输出的 `system_prompt` 放到你使用的任意 LLM/Agent 的 system prompt 中

### 场景 2：自动回复（需要你自己实现“发送”）

本项目只负责**读数据 / 监听 / 风格蒸馏**。

你可以组合：
- `wechat_start_listener` 获取新消息
- LLM 根据蒸馏后的风格生成回复（可带 `[sticker:xxx]`）
- 再用 UI 自动化/其他方式去“发送”（发送不在本项目范围内）

## License

MIT
