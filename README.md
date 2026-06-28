# MiniAgent

精简版 AI Agent：Chat + Skills + Tools，接入千问模型。

## 快速开始

```bash
# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 如果用到 pptx skill，安装 Node 依赖
npm install

# 3. 配置 API Key（二选一）
#    方式A：编辑 config.json，填入 api_key
#    方式B：设置环境变量 DASHSCOPE_API_KEY=sk-xxxxx

# 4. 启动
python main.py web        # Web UI（推荐），浏览器打开 http://localhost:7860
python main.py web -debug  # Web UI + Debug， debug log 在 C:\Users\Lenovo\.miniagent
查看log：Get-Content .\debug_default.log -Wait -Tail 20 -Encoding UTF8

python main.py chat       # 终端交互式对话
python main.py chat -q "你好"  # 单次问答


```

## 配置

编辑项目根目录 `config.json`：

```json
{
  "model": "qwen-plus",
  "api_key": "",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "temperature": 0.7,
  "max_tokens": 32768,
  "max_history": 20,
  "system_prompt": "你是一个有帮助的 AI 助手。请用中文回答问题。"
}
```

- `api_key` 留空时从环境变量 `DASHSCOPE_API_KEY` 读取
- API Key 获取：https://dashscope.console.aliyun.com/

## 运行模式

| 命令 | 说明 |
|------|------|
| `python main.py chat` | 终端交互式对话 |
| `python main.py web` | 启动 Web UI，默认端口 7860 |
| `python main.py chat -q "问题"` | 单次问答后退出 |
| `python main.py skills --init` | 初始化 skills 目录 |

Web UI 中可用命令：`/clear`, `/skills`, `/tools`, `/reload`, `/quit`

## Skills

将 Skill 放在 `~/.miniagent/skills/<skill-name>/SKILL.md`。

Skill 支持可选的 YAML frontmatter：

```markdown
---
description: "Skill 描述"
triggers:
  - "关键词1"
  - "关键词2"
---

# Skill 内容

这里是 skill 的具体指令...
```

- `description`：skill 简述，显示在列表中
- `triggers`：触发关键词列表，用户输入包含这些词时自动加载
- 没有 triggers 的 skill 不会自动加载，只能手动指定
