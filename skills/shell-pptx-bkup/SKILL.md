---
name: shell-pptx
description: |
  Shell 品牌风格 PPT 生成技能，基于 HTML-to-PPTX 工作流。
  This skill should be used when:
  (1) 用户要求制作 PPT、演示文稿、幻灯片，且希望使用 Shell 品牌风格
  (2) 用户说"用 Shell 风格做 PPT"、"Shell 品牌色"、"延续之前的 PPT 风格"
  (3) 用户在 Shell 相关项目中需要生成演示文稿
  (4) 用户要求制作与 shell-ai-ppt2/shell-ai-ppt3 同风格的 PPT
  触发词: "PPT", "幻灯片", "演示文稿", "Shell PPT", "品牌风格", "Shell风格"
---

# Shell 品牌风格 PPT 生成技能

使用 HTML + html2pptx 生成符合 Shell 品牌规范的 PPTX 演示文稿。

## 前置依赖

### Node.js 包（通过 npm 安装）

```powershell
npm install pptxgenjs playwright sharp
```

- `pptxgenjs` — PPTX 文件生成
- `playwright` — 无头浏览器渲染 HTML
- `sharp` — 图片处理（html2pptx 内部依赖）

### html2pptx.js

构建脚本会自动按以下顺序查找 `html2pptx.js`：

1. `<project>/scripts/html2pptx.js`（项目自带）
2. `<project>/skills/shell-pptx/scripts/html2pptx.js`（项目 skill 目录）
3. `<project>/skills/pptx/scripts/html2pptx.js`（项目 pptx skill）
4. `$env:USERPROFILE\.claude\skills\document-skills\pptx\scripts\html2pptx.js`（Claude Code 内置 pptx skill）

如需完全独立于 pptx skill，可将 `html2pptx.js` 复制到项目的 `scripts/` 目录下。

### Playwright Chromium

首次使用需安装浏览器：
```powershell
npx playwright install chromium
```

构建脚本会自动检测已安装的 Chromium 路径（支持 Windows/macOS/Linux）。

## 工作流程

**重要：每步执行前检查上一步是否成功，若失败则立即停止并向用户报告，不要继续执行后续步骤。**

### Step 1: 确定结构与内容

#### 1a. 选择内容模板（推荐）

读取 `assets/content-templates/` 目录下的内容模板，根据用户的 PPT 主题选择最匹配的模板：

| 模板文件 | 适用场景 |
|----------|----------|
| `项目汇报.md` | 项目阶段性汇报、结项汇报、项目启动会 |
| `用户操作手册.md` | 系统操作手册、产品使用指南、功能变更操作指引（面向业务人员，不含架构模块总览） |
| `培训材料.md` | 产品培训、技能培训、新员工培训、系统操作培训 |
| `产品介绍.md` | 产品发布会、客户演示、内部产品宣讲、投标方案 |
| `方案评审.md` | 技术方案评审、架构评审、立项评审、方案选型 |

**选择规则：**
1. 优先按用户描述的场景关键词匹配（如用户说"项目汇报"→ 选 `项目汇报.md`）
2. 如无明确匹配，列出可用模板让用户选择
3. 如用户已有明确大纲，跳过模板直接进入 1c

**使用内容模板时：**
- 读取模板文件，向用户展示页面大纲
- 询问用户是否需要调整页面数量或增删页面
- 用户确认后，收集每页的实际内容填充占位符

#### 1b. 创建新内容模板（可选）

如用户的场景不在现有模板中，且该场景可能复用，可创建新模板：
1. 参考 `assets/content-templates/_FORMAT.md` 的格式规范
2. 在 `content-templates/` 下新建 `.md` 文件
3. 定义页面结构、每页布局类型和内容要点

#### 1c. 确认最终结构

1. 与用户确认 PPT 主题、最终页面大纲、页数
2. 明确每页的内容类型（封面 / 内容页 / 封底）和布局类型
3. 与用户确认项目目录名称（如 `my-ppt`）

### Step 2: 创建项目目录

**必须先检查目录是否已存在，若存在则自动重命名旧目录，再创建新目录。**

执行方式（PowerShell 5.1 格式）：

```powershell
$projectName = "my-ppt"  # 与用户确认的项目名
if (Test-Path $projectName) {
    # 重命名已有目录：追加时间戳
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $newName = "$($projectName)_bak_$($timestamp)"
    Rename-Item $projectName $newName
    Write-Host "已重命名已有目录为: $newName"
}

# 创建新目录
New-Item -ItemType Directory -Path "$projectName/slides", "$projectName/scripts" -Force | Out-Null
Write-Host "已创建项目目录: $projectName"
```

**✅ 此步骤成功后才能继续 Step 3。若失败，停止执行并提示用户。**

### Step 3: 复制 html2pptx.js

将 `html2pptx.js` 复制到项目的 `scripts/` 目录。

**该 skill 的根目录路径已在上方提供（Skill root directory），请用该路径替换以下命令中的 `<SKILL_ROOT>`：**

```powershell
# <SKILL_ROOT> = 上方注明的 Skill root directory（绝对路径）
Copy-Item "<SKILL_ROOT>\scripts\html2pptx.js" "my-ppt\scripts\"
```

**✅ 此步骤成功后才能继续 Step 4。若失败，停止执行并提示用户。**

### Step 4: 生成 HTML 幻灯片

从 `assets/` 目录复制模板到项目 `slides/` 目录，按规范修改内容。

| 页码 | 模板文件 | 说明 |
|------|----------|------|
| 第1页 | `template-cover.html` → `slide01-cover.html` | 封面 |
| 第2~N-1页 | `template-content.html` → `slide02-xxx.html` | 内容页 |
| 第N页 | `template-closing.html` → `slideNN-closing.html` | 封底 |

**每页 HTML 必须包含完整的 inline CSS，不依赖外部文件。**

#### 内容模板 → 布局类型映射

内容模板中每页的 `布局` 字段决定该页使用哪种 CSS 组件结构：

| 布局类型 | 实现方式 |
|----------|----------|
| `cover` | 复制 `template-cover.html`，只改文字 |
| `closing` | 复制 `template-closing.html`，只改文字 |
| `toc` | 复制 `template-content.html`，内容区写 `.toc-list`，`body` 加 class `toc-page` |
| `section-divider` | 复制 `template-content.html`，隐藏 `.header` 和 `.content`，`body` 加 class `section-divider`，内容用 `.divider-wrap` + `.divider-number` + `.divider-title` + `.divider-bar` |
| `bullets` | 复制 `template-content.html`，内容区写 `<ul>` 列表 |
| `three-cards` | 复制 `template-content.html`，用 `.card-row` + `.yellow-card` |
| `two-col` | 复制 `template-content.html`，用 `.two-col` + `.col` |
| `two-col-compare` | 复制 `template-content.html`，用 `.compare-row` + `.do-box` / `.dont-box` |
| `stats-grid` | 复制 `template-content.html`，用 `.card-row` + `.stat-card` |
| `info-card` | 复制 `template-content.html`，用 `.info-card` |
| `highlight-bar` | 复制 `template-content.html`，用 `.highlight-bar` |
| `dim-cards` | 复制 `template-content.html`，用 `.dim-card` |
| `table` | 复制 `template-content.html`，内容区写 `<table>` |
| `faq-grid` | 复制 `template-content.html`，用 `.faq-grid` + `.faq-row` + `.faq-item` |

**生成流程：**
1. 读取内容模板确定每页的布局类型
2. 封面/封底：复制对应模板文件，只改文字
3. 内容页：复制 `template-content.html`，根据布局类型在 `.content` 区域内写入对应 HTML 结构
4. 用用户提供的内容填充占位符

#### ⚠️ 强制规则：封面和封底必须严格基于模板生成

**封面页（slide01）和封底页（slideNN）严禁自行设计或手写 CSS/布局。**

正确做法：
1. **直接复制模板文件**：`Copy-Item assets/template-cover.html slides/slide01-cover.html`
2. **只修改文字内容**：替换模板中的占位文字（标题、副标题、日期等），不修改任何 CSS、HTML 结构、定位方式
3. **保留所有资源引用**：模板中的 base64 背景图、Logo 等不要删除或替换
4. **不添加/删除 HTML 元素**：模板的 div/img 结构原样保留

错误做法（严格禁止）：
- ❌ 自己手写封面页的 CSS 和 HTML 结构
- ❌ 用"简易版"（白底红条）替代模板封面
- ❌ 修改模板中的 `.top-bar`、`.bottom-bar`、`.bg`、`.logo` 等元素的样式或结构
- ❌ 删除模板中的背景图或 Logo

### Step 5: 复制构建脚本并修改配置

**不要自己创建 `build.js`——直接复制模板文件，然后只修改 CONFIG 和 slides 两个区块。**

复制模板：

```powershell
# <SKILL_ROOT> = 上方注明的 Skill root directory（绝对路径）
Copy-Item "<SKILL_ROOT>\scripts\build.js" "my-ppt\build.js"
```

然后只修改文件中的两个配置区块：

**1. CONFIG（第 11-17 行）**——修改 `outputFile`、`title`、`subject`：

```js
const CONFIG = {
  slidesDir: path.resolve(__dirname, 'slides'),
  outputFile: path.resolve(__dirname, '最终文件名.pptx'),
  title: '演示文稿标题',
  author: 'Shell China',
  subject: '副标题或主题描述',
};
```

**2. slides 数组（第 90-94 行）**——填入实际的幻灯片文件名：

```js
const slides = [
  'slide01-cover.html',
  'slide02-xxx.html',
  'slide03-xxx.html',
  // ...
  'slideNN-closing.html',
];
```

**⚠️ 不要修改文件其余部分**（Chromium 检测、html2pptx 加载、构建逻辑等）。模板已包含完整的 require、findChromium()、findHtml2Pptx()、build() 等逻辑，无需自己编写。

### Step 6: 构建并交付

```powershell
cd my-ppt; node build.js
```

**✅ 构建成功后，告知用户 PPTX 文件路径。若失败，检查错误信息并提示用户修复依赖（npm install pptxgenjs playwright sharp）。**

## 品牌设计规范

### 色彩系统

| 用途 | 色值 | 说明 |
|------|------|------|
| **Shell 红（主色）** | `#DD1D21` | 强调色、边框点缀、左侧竖线、底部条 |
| **Shell 黄（辅色）** | `#FBCE07` | Header 底线、分隔线、高亮标签、卡片顶部边框 |
| **深色文字** | `#1A1A1A` | 标题、正文 |
| **中灰文字** | `#555555` | 副标题、描述文字 |
| **浅灰文字** | `#AAAAAA` | 脚注、次要信息 |
| **白色背景** | `#FFFFFF` | 所有页面背景（禁用黑色/深色背景） |
| **成功绿** | `#27AE60` | 已完成阶段徽章、Do 列表 |
| **警告红** | `#E74C3C` | Don't 列表 |
| **进度灰** | `#EEEEEE` | 未来阶段徽章 |
| **红色信息卡背景** | `#FFF8F8` | 左边框信息卡背景 |
| **黄色信息卡背景** | `#FFFBF0` | 黄色顶部卡片背景 |
| **成功绿背景** | `#F0FFF0` | Do 列表背景 |
| **警告红背景** | `#FFF0F0` | Don't 列表背景 |

### 字体

| 元素 | 字体 | 字号 | 颜色 |
|------|------|------|------|
| 封面主标题 | Arial, sans-serif | 30pt | `#1A1A1A` |
| 封面副标题 | Arial | 16pt | `#DD1D21` |
| 内页标题 (h1) | Arial | 18pt | `#1A1A1A`（白底黑字，红色底部边框） |
| 小节标签 | Arial | 9pt | `#DD1D21` |
| 卡片标题 (h3) | Arial | 10-11pt | `#DD1D21` |
| 正文 | Arial | 8.5-10pt | `#333333` |
| 列表项 | Arial | 7-8.5pt | `#333333` |
| 统计数字 | Arial | 22-26pt | `#DD1D21` |
| 脚注 | Arial | 8pt | `#AAAAAA` |

### 布局规范

**画布**: 720pt × 405pt (16:9)，对应 PPTX LAYOUT_16x9

**封面页结构**（严格按照 `template-cover.html`）:
- Shell 品牌背景图（全幅覆盖，`background-size: cover`）
- 左上角 Shell Logo（绝对定位）
- 顶部黄色细条（`#FBCE07`，0.56% 高度）
- 底部黄色细条（`#FBCE07`，0.56% 高度）
- 标题/副标题/作者/日期：绝对定位，使用 `cqw` 单位，颜色 `#404040`/`#606060`
- 底部脚注区：Copyright、日期、页码

**内容页结构**:
- 顶部 Header：白色背景 `#FFFFFF`，黑色 18pt 标题，底部 3pt 黄色底线
- 内容区白色背景，18pt/14pt padding
- 内容不可溢出画布底部（使用 `overflow: hidden`）

**封底页结构**（严格按照 `template-closing.html`）:
- 白色背景，内容居中
- 顶部黄色细条（`#FBCE07`） + 底部黄色细条
- 居中大图（Shell 品牌图，35% 宽 × 65% 高）
- 结束语（"Arial Black"，`#404040`） + 副标题（`#666666`）
- 底部脚注：Copyright、日期、页码

## 可复用 CSS 组件

所有内容页模板中已包含以下组件类名，直接使用：

### 信息展示
- `.info-card` — 红色左边框信息卡（背景 `#FFF8F8`，5pt 左边框 `#DD1D21`）
- `.yellow-card` — 黄色顶部三列卡片（3pt 黄色上边框）
- `.highlight-bar` — 重点突显条（白色/浅灰底 + 红色左边框，标题红色，正文深灰）
- `.stat-card` — 数据统计卡（大号红色数字 + 灰色标签）

### 布局
- `.two-col` / `.col` — 双列布局
- `.three-col` / `.col-3` — 三列布局
- `.card-row` — 等宽卡片行

### 导航结构
- `.toc-list` / `.toc-item` / `.toc-num` / `.toc-name` — 目录页（编号章节列表）
- `.divider-wrap` / `.divider-number` / `.divider-title` / `.divider-bar` — 章节分隔页（大序号+章节名居中+黄色分隔线）

### 阶段/状态
- `.badge-done` — 绿色"已完成"徽章 (`#27AE60`)
- `.badge-active` — 黄色"进行中"徽章 (`#FBCE07`)
- `.badge-future` — 灰色"未来"徽章 (`#EEEEEE`)

### 对比
- `.do-box` / `.dont-box` — Do / Don't 对比框（绿色/红色左边框）

### FAQ
- `.faq-grid` / `.faq-row` / `.faq-item` — FAQ 2x2 网格（每格一问一答，红色左边框）

### 维度卡片
- `.dim-card` — 三维度（Data/Tech/People）需求/成就卡片

## 关键注意事项

1. **禁用黑色背景**：所有页面（封面、内容、封底）必须使用白色 `#FFFFFF` 背景
2. **封面/封底必须基于模板**：封面页（slide01）和封底页（slideNN）**严禁自行设计**。必须直接复制模板文件，只修改文字内容，不修改 CSS/HTML 结构、不删除背景图和 Logo。详见 Step 4 中的强制规则。
3. **html2pptx 限制**：
   - `<p>` 标签不能以 Unicode 符号（如 `◯`、`✓`）开头，改用纯文字标识
   - 所有元素必须有显式 position（封面页的竖线/条带使用 `position: absolute` + `z-index`）
   - 内容不可超出 720pt × 405pt 画布边界
3. **内容密度控制**：
   - 内页正文 8-8.5pt，列表项 7-8pt
   - 如内容较多，适当缩小字号和间距（最小不低于 6.5pt / 1.2 line-height）
   - 使用 `overflow: hidden` 防止溢出
4. **每页独立 HTML 文件**：不使用外部 CSS/JS，每张幻灯片是完整独立的 HTML
5. **图片/图标**：如有需要，使用 base64 内联或 `<img>` 引用本地路径

## 模板文件

### 布局模板（样式层）

| 文件 | 用途 |
|------|------|
| `assets/template-cover.html` | 封面页模板 |
| `assets/template-content.html` | 内容页模板（含全部可复用组件 CSS） |
| `assets/template-closing.html` | 封底页模板 |
| `scripts/build.js` | 构建脚本模板 |

### 内容模板（内容层）

| 文件 | 用途 |
|------|------|
| `assets/content-templates/_FORMAT.md` | 内容模板格式规范与编写指南 |
| `assets/content-templates/项目汇报.md` | 项目阶段性汇报、结项汇报场景 |
| `assets/content-templates/用户操作手册.md` | 系统操作手册、产品使用指南场景 |
| `assets/content-templates/培训材料.md` | 产品/技能/新员工培训场景 |
| `assets/content-templates/产品介绍.md` | 产品发布、客户演示、投标方案场景 |
| `assets/content-templates/方案评审.md` | 技术方案评审、架构评审场景 |

使用时将布局模板复制到项目目录，按内容模板的大纲填充内容，通过 `node build.js` 构建。
