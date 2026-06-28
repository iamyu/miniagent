# 历史对话记录功能说明

## 📋 功能概述

MiniAgent 现在支持使用 SQLite 数据库持久化保存历史对话记录，并在 Web UI 的侧边栏中显示最近的对话历史。

---

## ✨ 主要特性

### 1. **自动保存**
- 每次对话都会自动保存到数据库
- 无需手动操作，完全透明
- 包含用户消息和助手回复

### 2. **持久化存储**
- 数据保存在 `~/.miniagent/history.db`（SQLite 数据库）
- 重启应用后历史记录不会丢失
- 支持多会话管理

### 3. **Web UI 展示**
- 在侧边栏 Skills 下方显示最近 5 条对话
- 显示用户消息预览、助手回复预览和时间戳
- 点击刷新按钮可手动更新历史列表

### 4. **智能时间显示**
- 刚刚、X分钟前、X小时前、X天前
- 超过7天显示具体日期

---

## 🗂️ 数据库结构

### conversations 表
```sql
CREATE TABLE conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT 'default',
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT
)
```

### sessions 表
```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    message_count INTEGER DEFAULT 0
)
```

---

## 🔧 API 端点

### 获取历史对话
```
GET /api/history?limit=50
```

**响应示例：**
```json
{
  "history": [
    {
      "id": 1,
      "role": "user",
      "content": "Hello, how are you?",
      "timestamp": "2026-05-17 15:30:00",
      "metadata": null
    },
    {
      "id": 2,
      "role": "assistant",
      "content": "I'm doing well, thank you!",
      "timestamp": "2026-05-17 15:30:05",
      "metadata": null
    }
  ],
  "count": 2
}
```

### 获取最近会话
```
GET /api/recent-sessions?limit=10
```

**响应示例：**
```json
{
  "sessions": [
    {
      "session_id": "default",
      "title": "Session default",
      "created_at": "2026-05-17 15:00:00",
      "updated_at": "2026-05-17 15:30:00",
      "message_count": 20
    }
  ]
}
```

---

## 💻 使用方法

### CLI 模式
历史记录会自动保存到数据库，无需特殊操作。

清除历史：
```bash
/clear  # 同时清除内存和数据库中的历史
```

### Web UI 模式

1. **查看历史**
   - 打开 Web UI（默认 http://localhost:7860）
   - 在左侧边栏的 "Skills" 下方可以看到 "历史对话" 区域
   - 自动显示最近 5 条对话

2. **刷新历史**
   - 点击历史区域标题旁的刷新图标 🔄
   - 或等待发送新消息后自动刷新

3. **历史记录内容**
   - 用户消息（加粗显示，最多40字符）
   - 助手回复预览（灰色，最多60字符）
   - 时间戳（相对时间显示）

---

## 🛠️ 技术实现

### 核心文件

| 文件 | 功能 |
|------|------|
| `miniagent/database.py` | 数据库管理类 HistoryDB |
| `miniagent/chat.py` | ChatEngine 集成数据库保存 |
| `miniagent/web.py` | API 端点 `/api/history`, `/api/recent-sessions` |
| `miniagent/static/index.html` | UI 布局（历史区域） |
| `miniagent/static/styles.css` | 历史列表样式 |
| `miniagent/static/app.js` | 前端加载和显示逻辑 |

### 关键代码

#### 保存对话（chat.py）
```python
def _update_history(self, user_input: str, response_text: str) -> None:
    """Update conversation history and save to database."""
    self.history.append({"role": "user", "content": user_input})
    self.history.append({"role": "assistant", "content": response_text})

    # Save to database for persistence
    try:
        self.db.save_conversation_pair(
            user_input=user_input,
            assistant_response=response_text,
            session_id=self.session_id
        )
    except Exception as e:
        print(f"Warning: Failed to save history to database: {e}")
```

#### 加载历史（app.js）
```javascript
async function loadHistory() {
    const response = await fetch(`${API_BASE}/api/history?limit=10`);
    const data = await response.json();
    
    // Group messages into conversations and display
    // ...
}
```

---

## ⚙️ 配置选项

### 修改数据库路径

在 `chat.py` 中自定义数据库位置：

```python
# 默认位置
self.db = HistoryDB()  # ~/.miniagent/history.db

# 自定义位置
from pathlib import Path
self.db = HistoryDB(Path("/custom/path/history.db"))
```

### 调整历史显示数量

在 `app.js` 中修改：

```javascript
// 默认显示最近 10 条消息（5 组对话）
const response = await fetch(`${API_BASE}/api/history?limit=10`);

// 修改为显示更多
const response = await fetch(`${API_BASE}/api/history?limit=20`);
```

### 修改会话 ID

在 `chat.py` 中设置不同的会话标识：

```python
self.session_id = "user_123"  # 自定义会话ID
```

---

## 🧪 测试

运行测试脚本验证功能：

```bash
python test_history.py
```

测试内容包括：
- ✅ 保存对话对
- ✅ 检索历史记录
- ✅ 获取最近会话
- ✅ 消息计数
- ✅ 清除历史

---

## 📊 性能考虑

### 数据库优化
- 已创建索引加速查询：`idx_conversations_session`
- 使用参数化查询防止 SQL 注入
- 自动提交事务确保数据一致性

### 内存管理
- 内存中仍保留最近 N 轮对话（由 `max_history` 配置控制）
- 数据库中保存完整历史
- 避免一次性加载过多历史到内存

### 建议配置
```json
{
  "max_history": 20  // 内存中保留 20 轮对话
}
```

---

## 🔍 常见问题

### Q: 历史记录保存在哪里？
A: `~/.miniagent/history.db`（Windows: `C:\Users\<用户名>\.miniagent\history.db`）

### Q: 如何备份历史记录？
A: 直接复制 `history.db` 文件即可

### Q: 如何删除所有历史？
A: 
```bash
# 方法1: 在聊天中输入
/clear

# 方法2: 删除数据库文件
rm ~/.miniagent/history.db  # Linux/Mac
del %USERPROFILE%\.miniagent\history.db  # Windows
```

### Q: 历史记录会影响性能吗？
A: 不会。数据库查询经过优化，且只加载最近的记录到 UI

### Q: 支持多用户吗？
A: 当前版本使用 `session_id` 区分不同会话，可以扩展为多用户支持

---

## 🚀 未来增强

- [ ] 支持导出历史为 JSON/Markdown
- [ ] 支持搜索历史对话
- [ ] 支持按日期筛选
- [ ] 支持标记重要对话
- [ ] 支持对话分组/标签
- [ ] 支持多用户隔离
- [ ] 支持云同步

---

## 📝 更新日志

### v1.1.0 (2026-05-17)
- ✅ 添加 SQLite 数据库支持
- ✅ 自动保存所有对话历史
- ✅ Web UI 侧边栏显示历史记录
- ✅ 新增 API 端点：`/api/history`, `/api/recent-sessions`
- ✅ 智能时间显示（相对时间）
- ✅ 手动刷新和自动刷新功能

### v1.1.2 (2026-06-13)
- ✅ 工具卡片内直接显示流式 chunk 内容，去除复杂的文件预览框逻辑

### v1.1.1 (2026-06-10)
- ✅ 工具卡片（shell/read_file 等）移入对话框气泡内部展示
- ✅ 历史对话数量显示、单条删除按钮及折叠/展开功能
- ✅ 侧边栏统一滚动条，发送消息后即时显示打字动画
- ✅ 单个对话步数从 10 增加到 30，ppt skill步数比较多
- ⏳ Run time 运行时隔离目录暂未启用，当前仍在 output 目录下创建文件（多用户时候才需要，本机运行不需要）
- ppt没有生成，html可以。但ppt 安装需要的包不成功。后续更新

### v1.2.0 (2026-06-27)
- ✅ Debug 日志合并：LLM 输出和通用 debug 归入同一个文件，受 `--debug` 开关统一控制
- ✅ 工具消息滑动窗口：新增 `max_tool_history` 配置项，超出的旧工具消息自动裁剪，控制上下文大小
- ✅ 项目目录统一：不同 tool 使用同一个项目目录


---

**最后更新**: 2026-06-27  
**作者**: MiniAgent Team
