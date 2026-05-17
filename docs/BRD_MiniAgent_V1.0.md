# MiniAgent 业务需求文档（BRD）

**版本**：V1.1
**日期**：2026-05-17
**作者**：龙虾
**项目代号**：MiniAgent

---

## 1 项目背景

### 1.1 现状与痛点

当前企业级 AI Agent 平台（如 WorkBuddy、LobeHub、Open WebUI）普遍存在以下问题：

- **部署门槛高**：依赖 Docker、Node.js 全量安装、Python venv 管理等，非技术用户无法独立部署
- **体积臃肿**：LobeHub 镜像 >1GB，Open WebUI 需完整 Python 环境，启动慢、资源占用高
- **定制困难**：添加自定义能力（Skill）需要理解复杂的插件架构，编写配置文件或修改源码
- **依赖云服务**：大多数平台强绑定特定 LLM 供应商，切换模型或使用私有部署模型需大量改造
- **离线不可用**：无网络环境下无法使用，不适合内网隔离场景

### 1.2 项目目标

MiniAgent 定位为**极致精简的本地 AI Agent 运行时**，核心目标：

1. **零安装部署**：解压即用，不依赖系统级安装的任何运行时（Python、Node.js 随包附带便携版）
2. **分钟级上手**：配置一个 API Key 即可开始对话，无需数据库、无需容器
3. **灵活可扩展**：通过 SKILL.md 文件定义能力，5 分钟添加一个新技能
4. **双模运行**：CLI 命令行 + Web UI 两种交互方式，满足不同场景
5. **企业内网友好**：支持私有化 LLM 部署，所有数据本地处理

### 1.3 目标用户

| 用户画像 | 使用场景 | 核心需求 |
|---------|---------|---------|
| 企业 IT 运维人员 | 自动化运维脚本生成、日志分析、系统巡检 | CLI 为主，批量执行，结果输出到文件 |
| 业务分析师 | 报告生成、数据处理、网页信息采集 | Web UI 为主，可视化结果，交互式对话 |
| AI 培训讲师 | 教学演示、学生实验环境 | 快速部署，干净的环境隔离 |
| 个人开发者 | 代码辅助、文档生成、日常自动化 | 轻量启动，扩展灵活 |
| 企业内网用户 | 离线环境下的 AI 助手 | 私有化模型支持，无外网依赖 |

---

## 2 业务范围

### 2.1 系统边界

MiniAgent 是一个**本地运行的 AI Agent 框架**，不涉及云服务托管、多用户管理、权限控制等 SaaS 能力。

```
┌─────────────────────────────────────────────────┐
│              MiniAgent 系统边界                    │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │ CLI 界面  │  │ Web UI   │  │ REST/WebSocket│  │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘   │
│       │              │               │             │
│  ┌────▼──────────────▼───────────────▼──────┐     │
│  │            Chat Engine                    │     │
│  │  (LLM 对话 + 工具调用 + 技能注入)          │     │
│  └────┬──────────┬──────────┬───────────────┘     │
│       │          │          │                      │
│  ┌────▼───┐ ┌───▼────┐ ┌──▼──────┐              │
│  │ Tools  │ │ Skills │ │ Config  │              │
│  │ 10个   │ │ SKILL  │ │ 三级优先 │              │
│  │ 内置   │ │ .MD    │ │ 级配置   │              │
│  └────────┘ └────────┘ └─────────┘              │
│                                                   │
│  ┌──────────────────────────────────────────┐    │
│  │          便携式 Runtime                   │    │
│  │  Node.js v22 + Python 3.13               │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
          │                          │
     ┌────▼────┐               ┌────▼────┐
     │ DashScope│              │ 私有化   │
     │ (阿里云) │              │ LLM API │
     └─────────┘               └─────────┘
```

### 2.2 在范围内（In Scope）

| 功能域 | 功能项 | 说明 |
|-------|-------|------|
| 对话引擎 | LLM 对话 | 基于 OpenAI 兼容协议，支持 Qwen、DeepSeek、私有化模型等 |
| 对话引擎 | 工具调用（Function Calling） | LLM 自动调用内置工具，最多 10 轮工具调用循环 |
| 对话引擎 | 技能注入 | 根据 trigger 关键词自动匹配 SKILL.md，注入到 system prompt |
| 对话引擎 | 上下文管理 | 对话历史管理，可配置最大历史轮数 |
| 对话引擎 | 对话历史持久化 | SQLite 自动保存，进程退出后历史不丢失 |
| 工具系统 | 文件操作 | 读取、写入、编辑、列目录 |
| 工具系统 | 命令执行 | CMD/Shell 命令执行（含危险命令拦截） |
| 工具系统 | 脚本执行 | Node.js 和 Python 脚本/内联代码执行 |
| 工具系统 | 网络搜索 | DuckDuckGo 搜索（无需 API Key） |
| 工具系统 | 网页抓取 | URL 内容抓取与解析 |
| 工具系统 | 文档保存 | 生成物自动保存到 output 目录 |
| 技能系统 | SKILL.md 加载 | YAML frontmatter + Markdown 正文的技能定义格式 |
| 技能系统 | 关键词匹配 | 基于触发词的自动技能激活 |
| 技能系统 | 常驻技能 | always-on 技能始终注入 system prompt |
| 技能系统 | 热重载 | 运行时动态加载/刷新技能 |
| 交互界面 | CLI 模式 | 交互式对话 + 单次查询模式 |
| 交互界面 | Web 模式 | FastAPI + WebSocket 流式对话 |
| 交互界面 | Web UI | 白色主题三视图（对话/Skills/设置） |
| 交互界面 | 历史对话展示 | Web UI 侧边栏显示最近对话，支持自动刷新和手动刷新 |
| 配置管理 | 三级配置 | 项目级 > 用户级 > 环境变量 > 默认值 |
| 数据持久化 | SQLite 数据库 | 对话历史自动保存到 ~/.miniagent/history.db |
| 便携运行 | 内置 Runtime | Node.js 22 + Python 3.13 便携版随包附带 |

### 2.3 不在范围内（Out of Scope）

| 排除项 | 原因 |
|-------|------|
| 多用户管理 / 权限控制 | 本地单用户工具，无多租户需求 |
| 模型训练 / 微调 | Agent 框架，不涉及模型能力建设 |
| 移动端适配 | 聚焦桌面端使用场景 |
| 插件市场 / 技能分享 | 初期聚焦核心能力，技能管理保持文件系统级别 |
| 多模态（图片/语音/视频） | 当前仅支持文本输入输出 |
| MCP 协议支持 | 初期不引入，保持架构简单 |

---

## 3 功能需求

### 3.1 对话引擎（FR-100）

#### FR-101：LLM 对话

| 需求项 | 说明 |
|-------|------|
| 需求描述 | 通过 OpenAI 兼容 API 与 LLM 进行对话 |
| 输入 | 用户消息（文本） |
| 输出 | LLM 回复（文本） |
| 协议 | OpenAI Chat Completions API（/v1/chat/completions） |
| 模型支持 | 默认 qwen-plus，可通过配置切换任意 OpenAI 兼容模型 |
| 参数 | model、temperature（默认 0.7）、max_tokens（默认 4096） |
| 响应模式 | 同步（CLI）+ 流式（Web WebSocket） |

#### FR-102：Function Calling 工具调用

| 需求项 | 说明 |
|-------|------|
| 需求描述 | LLM 在对话中自动识别需要调用工具的场景，发起工具调用 |
| 触发方式 | LLM 在 response 中返回 tool_calls 字段 |
| 执行流程 | 解析工具名和参数 → 执行工具 → 将结果回传 LLM → 继续对话 |
| 循环限制 | 最多 10 轮工具调用，防止无限循环 |
| 错误处理 | 工具执行失败时将错误信息回传 LLM，由 LLM 决定如何继续 |

#### FR-103：技能匹配与注入

| 需求项 | 说明 |
|-------|------|
| 需求描述 | 根据用户消息中的关键词，自动匹配并激活对应的 Skill |
| 匹配规则 | SKILL.md 中定义的 triggers 列表，命中数量越多优先级越高 |
| 注入方式 | Skill 内容注入到 system prompt 的 "# Active Skills" / "# Activated Skills" 区段 |
| 常驻技能 | always: true 的技能始终注入，不依赖关键词匹配 |
| 手动激活 | 支持 /use \<skill-name\> 命令手动激活指定技能 |

#### FR-104：上下文管理

| 需求项 | 说明 |
|-------|------|
| 需求描述 | 管理对话历史，控制上下文窗口大小 |
| 内存存储 | 内存 list 存储当前会话历史，供 LLM API 调用 |
| 历史轮数 | 可配置 max_history（默认 20 轮，即 40 条消息） |
| 超限处理 | 超过限制后截断最早的消息 |
| 清空操作 | /clear 命令清空全部历史（内存 + 数据库同步清理） |

#### FR-105：对话历史持久化

| 需求项 | 说明 |
|-------|------|
| 需求描述 | 每次对话自动保存到 SQLite 数据库，进程退出后历史不丢失 |
| 数据库路径 | ~/.miniagent/history.db（首次启动自动创建） |
| 存储引擎 | SQLite 3，Python 标准库内置，无需额外依赖 |
| 自动保存 | `_update_history` 方法在每次对话完成后自动调用 `save_conversation_pair` |
| 错误容忍 | 数据库写入失败仅打印 Warning，不影响对话功能 |

**数据库表结构：**

```sql
-- conversations 表：对话消息
CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT 'default',
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT  -- JSON 格式，存储技能匹配、工具调用等元信息
);

-- 索引：按 session + 时间快速查询
CREATE INDEX idx_conversations_session ON conversations(session_id, timestamp);

-- sessions 表：会话元数据
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    message_count INTEGER DEFAULT 0
);
```

**核心 API：**

| 方法 | 说明 |
|------|------|
| save_message(role, content, session_id, metadata) | 保存单条消息，同步更新 session 元数据 |
| save_conversation_pair(user_input, assistant_response, session_id) | 保存一对问答消息 |
| get_history(session_id, limit, offset) | 分页获取指定会话的历史消息 |
| get_recent_conversations(limit) | 获取最近活跃的会话列表 |
| clear_history(session_id) | 清除指定会话的所有消息和会话记录 |
| delete_message(message_id) | 删除指定消息 |
| get_message_count(session_id) | 获取会话消息总数 |

### 3.2 工具系统（FR-200）

#### FR-201：文件操作工具

| 工具名 | 功能 | 关键参数 |
|-------|------|---------|
| read_file | 读取文件内容，支持分页 | path, offset（行号，1-based）, limit（行数） |
| write_file | 写入文件，支持自动创建目录 | path, content |
| edit_file | 文本替换编辑，支持模糊匹配 | path, old_text, new_text, replace_all |
| list_dir | 列出目录内容，自动忽略常见无关目录 | path, recursive, max_entries |

**业务规则：**
- read_file 最大读取 128,000 字符
- edit_file 的 old_text 多次出现时，默认拒绝替换，需提供更多上下文或设 replace_all=true
- list_dir 自动忽略 .git、node_modules、\_\_pycache\_\_、.venv 等目录
- write_file 相对路径自动解析到 ~/.miniagent/ 目录

#### FR-202：命令执行工具

| 工具名 | 功能 | 关键参数 |
|-------|------|---------|
| shell | 执行 CMD 命令 | command, timeout（默认 30s，最大 300s）, cwd |

**业务规则：**
- 危险命令拦截：format、del /s、rmdir /s、diskpart、shutdown 等直接拒绝
- 输出截断：超过 50,000 字符截断
- Runtime 查找顺序：包内置 runtime/ → 项目级 ./runtime/ → 系统 PATH

#### FR-203：脚本执行工具

| 工具名 | 功能 | 关键参数 |
|-------|------|---------|
| run_node | 执行 Node.js 脚本或内联 JS | path 或 code, cwd, timeout（默认 60s）, args |
| run_python | 执行 Python 脚本或内联 Python | path 或 code, cwd, timeout（默认 60s）, args |

**业务规则：**
- path 和 code 互斥，不能同时提供
- 内联代码通过临时文件执行，执行后自动清理
- 自动清除 NODE_OPTIONS 环境变量（避免系统级 --use-system-ca 干扰）

#### FR-204：网络工具

| 工具名 | 功能 | 关键参数 |
|-------|------|---------|
| web_search | DuckDuckGo 搜索 | query, count（默认 5，最大 10） |
| web_fetch | 抓取 URL 内容并解析 | url |

**业务规则：**
- web_fetch 自动去除 HTML 标签，提取纯文本
- web_fetch 最大抓取 50,000 字符
- web_fetch 支持 HTML、JSON、纯文本内容类型

#### FR-205：文档保存工具

| 工具名 | 功能 | 关键参数 |
|-------|------|---------|
| save_document | 保存生成物到 output 目录 | content, filename（可选，自动生成） |

**业务规则：**
- 输出目录：MiniAgent 安装目录 /output/
- 无 filename 时自动生成带时间戳的文件名
- 根据内容自动推断文件扩展名（.html、.md、.json、.csv、.txt）

### 3.3 技能系统（FR-300）

#### FR-301：技能定义格式

技能通过 SKILL.md 文件定义，采用 YAML frontmatter + Markdown body 格式：

```yaml
---
description: "技能描述，用于展示和 LLM 理解"
triggers:
  - "关键词1"
  - "关键词2"
always: false
---

# 技能标题

技能的完整指令内容，注入到 system prompt 中。
支持 Markdown 格式。
```

**字段说明：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| description | string | 是 | 技能描述，显示在 UI 列表和 LLM 提示中 |
| triggers | string[] | 否 | 触发关键词列表，匹配用户输入 |
| always | boolean | 否 | 是否常驻注入（默认 false） |

#### FR-302：技能加载

| 需求项 | 说明 |
|-------|------|
| 存储位置 | ~/.miniagent/skills/\<skill-name\>/SKILL.md |
| 加载时机 | 引擎初始化时加载，/reload 命令热重载 |
| 解析方式 | YAML frontmatter 解析元数据，Markdown body 作为指令内容 |
| 初始化 | miniagent skills --init 创建示例技能目录 |

#### FR-303：技能匹配

| 需求项 | 说明 |
|-------|------|
| 匹配方式 | 用户输入（小写化）包含 skill 的 trigger 关键词 |
| 排序规则 | 命中关键词数量越多优先级越高 |
| 常驻技能 | always: true 的技能不计入匹配，始终注入 |
| 手动激活 | /use \<name\> 命令手动激活，不依赖关键词匹配 |

### 3.4 CLI 界面（FR-400）

| 命令 | 说明 |
|------|------|
| `python main.py` | 默认启动交互式 chat 模式 |
| `python main.py chat` | 显式启动 chat 模式 |
| `python main.py chat -q "问题"` | 单次查询模式，输出结果后退出 |
| `python main.py chat -c config.json` | 指定项目级配置文件 |
| `python main.py web` | 启动 Web 服务器（默认 http://localhost:7860） |
| `python main.py web -p 8080` | 指定端口 |
| `python main.py skills` | 列出所有已加载技能 |
| `python main.py skills --init` | 初始化技能目录（含示例） |

**内置斜杠命令（chat 模式）：**

| 命令 | 功能 |
|------|------|
| /clear | 清空对话历史 |
| /skills | 列出所有技能 |
| /tools | 列出所有工具 |
| /reload | 热重载技能 |
| /use \<name\> | 手动激活指定技能 |
| /quit、/exit、/q | 退出程序 |

### 3.5 Web 界面（FR-500）

#### FR-501：后端 API

| 端点 | 方法 | 说明 |
|------|------|------|
| / | GET | 返回 index.html 主页面 |
| /static/* | GET | 静态文件服务 |
| /api/config | GET | 返回配置信息（API Key 脱敏） |
| /api/tools | GET | 返回工具列表 |
| /api/skills | GET | 返回技能列表 |
| /api/chat | POST | 同步聊天接口 |
| /api/clear | POST | 清空对话历史 |
| /api/history | GET | 获取对话历史（?limit=50，默认 50 条） |
| /api/recent-sessions | GET | 获取最近会话列表（?limit=10，默认 10 条） |
| /api/reload-skills | POST | 重载技能 |
| /api/ws | WebSocket | 流式聊天（text/tool_start/tool_end/done/error/system/status） |

#### FR-502：WebSocket 消息协议

| 消息类型 | 方向 | 说明 |
|---------|------|------|
| {message: "..."} | Client → Server | 用户消息 |
| {type: "text", content: "..."} | Server → Client | 文本内容（流式） |
| {type: "tool_start", name: "...", args: {...}} | Server → Client | 工具调用开始 |
| {type: "tool_end", name: "...", result: "...", truncated: bool} | Server → Client | 工具调用结束 |
| {type: "status", content: "..."} | Server → Client | 状态信息（如技能激活） |
| {type: "system", content: "..."} | Server → Client | 系统消息 |
| {type: "done"} | Server → Client | 回复完成 |
| {type: "error", content: "..."} | Server → Client | 错误消息 |

#### FR-503：Web UI 布局

```
┌──────────┬────────────────────────────────────┐
│  侧边栏   │           主内容区                  │
│          │                                     │
│ [Logo]   │  ┌─ 聊天视图 ────────────────────┐  │
│          │  │ 标题栏 + 清空按钮              │  │
│ [新建对话] │  │                               │  │
│ [Skills]  │  │ 欢迎页 / 对话消息列表          │  │
│ [设置]    │  │                               │  │
│          │  │                               │  │
│ ──────── │  │                               │  │
│ Skills   │  ├───────────────────────────────┤  │
│ 列表     │  │ 输入框 + Skill选择 + 发送按钮   │  │
│          │  └───────────────────────────────┘  │
│ ──────── │                                     │
│ 状态     │  ┌─ Skills 视图 ──────────────────┐  │
│ Model    │  │ 技能卡片网格                    │  │
│ API      │  └───────────────────────────────┘  │
│ WS       │                                     │
│          │  ┌─ 设置视图 ─────────────────────┐  │
│ [User]   │  │ API 配置表单                   │  │
│          │  │ 关于信息                        │  │
│          │  └───────────────────────────────┘  │
└──────────┴────────────────────────────────────┘
```

**UI 设计规范：**
- 主色调：#2563EB（蓝色）
- 背景：#FFFFFF（白色）
- 三视图切换：对话 / Skills / 设置
- 侧边栏固定展示 Skills 列表，点击自动填入 @skill-name
- 侧边栏展示历史对话列表（最近 5 组），每组显示用户消息（加粗，最多 40 字符）+ 助手回复预览（灰色，最多 60 字符）+ 相对时间
- 历史对话支持：手动点击 🔄 按钮刷新、发送新消息后 2 秒自动刷新
- 响应式布局，支持宽屏拉伸

### 3.6 配置管理（FR-600）

#### FR-601：三级配置优先级

```
优先级：高 → 低

1. 项目级 config.json（-c 参数指定）
2. 用户级 ~/.miniagent/config.json
3. 环境变量（DASHSCOPE_API_KEY、DASHSCOPE_BASE_URL、MINIAGENT_MODEL）
4. 代码默认值
```

#### FR-602：配置项清单

| 配置项 | 默认值 | 说明 |
|-------|--------|------|
| model | qwen-plus | LLM 模型名称 |
| api_key | "" | API 密钥（环境变量覆盖） |
| base_url | https://dashscope.aliyuncs.com/compatible-mode/v1 | API 基础 URL |
| temperature | 0.7 | 生成温度 |
| max_tokens | 4096 | 最大生成 token 数 |
| max_history | 20 | 最大历史轮数 |
| system_prompt | "你是一个有帮助的 AI 助手。请用中文回答问题。" | 系统提示词 |
| skills_dir | null（默认 ~/.miniagent/skills/） | 技能目录路径 |

### 3.7 便携运行时（FR-700）

| 需求项 | 说明 |
|-------|------|
| Node.js | v22.14.0 便携版，约 83MB 单文件 |
| Python | 3.13.2 embeddable 版，约 10MB |
| 存放位置 | MiniAgent 安装目录 /runtime/node/ 和 /runtime/python/ |
| 查找顺序 | 包内置 → 项目级 ./runtime/ → 系统 PATH |
| 无需安装 | 不需要管理员权限，不修改系统环境变量 |

---

## 4 非功能需求

### 4.1 性能要求

| 指标 | 要求 |
|------|------|
| CLI 启动时间 | < 2 秒（含技能加载） |
| Web 服务启动时间 | < 3 秒 |
| 首字响应时间（WebSocket） | 取决于 LLM API，本地处理延迟 < 100ms |
| 工具执行超时 | 可配置，默认 30s，最大 300s |
| 内存占用 | < 200MB（不含 LLM 调用） |

### 4.2 安全要求

| 需求项 | 说明 |
|-------|------|
| 危险命令拦截 | shell 工具内置危险命令黑名单，直接拒绝执行 |
| API Key 脱敏 | Web API 返回配置时隐藏完整 Key，仅显示是否有配置 |
| 配置文件排除 | config.json 纳入 .gitignore，防止密钥泄露 |
| 无远程回传 | 所有数据处理在本地完成，不向第三方服务回传 |
| 工具输出截断 | 文件读取和命令输出均有字符数上限，防止内存溢出 |

### 4.3 可用性要求

| 需求项 | 说明 |
|-------|------|
| 零安装 | 解压目录即可运行，不依赖系统级 Python/Node.js |
| 单文件启动 | python main.py 一条命令启动 |
| 错误提示 | 所有错误均以友好中文提示，包含解决建议 |
| 技能初始化 | skills --init 一键创建示例技能目录 |
| 热重载 | 技能修改后 /reload 即时生效，无需重启 |

### 4.4 兼容性要求

| 需求项 | 说明 |
|-------|------|
| 操作系统 | Windows 10/11（主目标），兼容 Linux/macOS |
| Python | 3.10+ |
| LLM API | 任何 OpenAI 兼容 API（DashScope、Ollama、vLLM、LM Studio 等） |
| 浏览器 | Chrome 90+、Edge 90+、Firefox 90+ |

---

## 5 技术架构

### 5.1 系统架构

```
miniagent/
├── main.py                 # 入口
├── requirements.txt        # 依赖：openai, pyyaml, duckduckgo-search
├── miniagent/
│   ├── __init__.py         # 版本号 v1.1.0
│   ├── __main__.py         # python -m miniagent 支持
│   ├── cli.py              # CLI 入口（chat/web/skills 子命令）
│   ├── chat.py             # ChatEngine（对话+工具循环+技能注入+历史持久化）
│   ├── tools.py            # 10 个内置工具 + ToolRegistry
│   ├── skills.py           # SkillsLoader + Skill
│   ├── database.py         # HistoryDB（SQLite 对话历史持久化）
│   ├── config.py           # 三级配置管理
│   ├── web.py              # FastAPI 后端 + WebSocket + 历史 API
│   └── static/             # Web UI 静态文件
│       ├── index.html      # 主页面
│       ├── styles.css      # 样式
│       └── app.js          # 交互逻辑（含历史对话刷新）
├── runtime/                # 便携式运行时（gitignore）
│   ├── node/node.exe       # Node.js 22.14.0
│   └── python/python.exe   # Python 3.13.2
├── output/                 # 生成物输出目录
└── ~/.miniagent/           # 用户数据目录（自动创建）
    ├── config.json         # 用户配置
    ├── history.db          # 对话历史数据库
    ├── skills/             # 技能目录
    └── output/             # 用户输出目录
```

### 5.2 核心依赖

| 包 | 版本 | 用途 |
|----|------|------|
| openai | >=1.0.0 | OpenAI 兼容 API 客户端 |
| pyyaml | >=6.0 | SKILL.md frontmatter 解析 |
| duckduckgo-search | >=6.0 | 免 API Key 的网络搜索 |
| fastapi | 运行时依赖 | Web 服务器 |
| uvicorn | 运行时依赖 | ASGI 服务器 |

### 5.3 数据流

```
用户输入
  │
  ▼
┌─────────────┐
│ 关键词匹配   │ ← Skills 系统匹配 trigger
│ 选择 Skill   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ 构建 System  │ ← 基础 prompt + 工具指令 + 技能内容
│ Prompt       │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌──────────┐
│ 调用 LLM API │────▶│ DashScope│
│              │◀────│ / 私有LLM │
└──────┬──────┘     └──────────┘
       │
       ├── 有 tool_calls ──▶ 执行工具 ──▶ 结果回传 LLM ──┐
       │                                                    │
       ├── 无 tool_calls ──▶ 返回文本 ──▶ 更新历史 ──▶ 输出 │
       │                                                   │
       └───────────────────────────────────────────────────┘
```

---

## 6 项目里程碑

### 第一阶段：核心框架（已完成）

| 编号 | 交付物 | 状态 |
|------|--------|------|
| M1.1 | ChatEngine + OpenAI 兼容 API 对接 | 已完成 |
| M1.2 | 10 个内置工具实现 | 已完成 |
| M1.3 | SKILL.md 技能系统（加载/匹配/注入） | 已完成 |
| M1.4 | CLI 交互式聊天 + 单次查询 | 已完成 |
| M1.5 | 三级配置管理 | 已完成 |
| M1.6 | 便携式 Runtime（Node.js + Python） | 已完成 |
| M1.7 | GitHub 仓库初始化 | 已完成 |

### 第二阶段：Web 界面（已完成）

| 编号 | 交付物 | 状态 |
|------|--------|------|
| M2.1 | FastAPI 后端 + REST API | 已完成 |
| M2.2 | WebSocket 流式对话 | 已完成 |
| M2.3 | Web UI 三视图（白色主题） | 已完成 |
| M2.4 | Skills 侧边栏 + 下拉选择 | 已完成 |
| M2.5 | SQLite 对话历史持久化（HistoryDB） | 已完成 |
| M2.6 | Web UI 历史对话展示（侧边栏 + 自动刷新） | 已完成 |

### 第三阶段：能力增强（规划中）

| 编号 | 交付物 | 优先级 |
|------|--------|--------|
| M3.1 | Markdown 渲染（代码高亮、表格、列表） | P1 |
| M3.3 | 多会话管理（新建/切换/删除/重命名） | P1 |
| M3.4 | 文件上传与预览 | P2 |
| M3.5 | Skills 市场（安装/卸载/搜索） | P2 |
| M3.6 | 流式输出 Markdown 实时渲染 | P2 |

### 第四阶段：生态扩展（远期）

| 编号 | 交付物 | 优先级 |
|------|--------|--------|
| M4.1 | MCP 协议支持 | P3 |
| M4.2 | 多模态输入（图片理解） | P3 |
| M4.3 | Agent 链式编排（多步骤任务） | P3 |
| M4.4 | 插件系统（Python 包形式） | P3 |

---

## 7 成功指标

| 指标 | 目标值 | 衡量方式 |
|------|--------|---------|
| 部署时间 | < 5 分钟（含 API Key 配置） | 新用户测试 |
| 技能添加时间 | < 5 分钟（从需求到可用） | 编写一个新 SKILL.md |
| 工具调用准确率 | > 90%（LLM 正确选择和调用工具） | 典型任务测试 |
| Web UI 首屏加载 | < 2 秒 | 浏览器 DevTools |
| 启动到可用时间 | < 3 秒（CLI/Web） | 计时测试 |
| 包体积 | < 100MB（不含 runtime） | 目录统计 |

---

## 8 风险与约束

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LLM API 不稳定 | 对话中断 | 完善错误处理，支持多个 API 提供商切换 |
| DuckDuckGo 搜索被限流 | web_search 返回空结果 | 提示用户，保留其他搜索工具扩展点 |
| Python embeddable 缺少标准库 | 部分功能不可用 | 核心依赖通过 pip 安装到 venv |
| 单用户限制 | 不适合团队共享 | 作为个人工具定位，后续可扩展为服务 |
| SQLite 数据膨胀 | 长期使用后数据库文件过大 | 提供按会话清理功能（clear_history） |

---

## 9 术语表

| 术语 | 全称 | 说明 |
|------|------|------|
| MiniAgent | Mini Agent | 本项目名称 |
| LLM | Large Language Model | 大语言模型 |
| Function Calling | - | LLM 工具调用能力（OpenAI 定义） |
| SKILL.md | - | 技能定义文件格式（YAML + Markdown） |
| Trigger | - | 技能触发关键词 |
| Runtime | - | 运行时环境（Node.js / Python 便携版） |
| DashScope | - | 阿里云百炼 LLM 平台 |
| BRD | Business Requirements Document | 业务需求文档 |
| CLI | Command Line Interface | 命令行界面 |
| WebSocket | - | 全双工通信协议 |
| FastAPI | - | Python ASGI Web 框架 |
| HistoryDB | - | SQLite 对话历史持久化模块（database.py） |
