# 内容模板格式规范

## 什么是内容模板

内容模板定义**某个场景下 PPT 应该有哪些页、每页写什么内容**。它不涉及样式排版——样式由布局模板（template-cover / template-content / template-closing）和 CSS 组件处理。

内容模板解决的问题是："用户要做一个项目汇报 PPT，但我不知道该写哪些页、每页放什么内容。"

## 文件格式

每个内容模板是一个 `.md` 文件，放在 `content-templates/` 目录下。

### 结构

```markdown
# 内容模板：{模板名称}

> **适用场景：** {列举 2-3 个典型场景}
> **建议页数：** {N-M 页}
> **布局提示：** {可选，整体风格建议}

---

## 第 1 页 — 封面

- **布局：** cover
- **标题：** {标题占位符或说明}
- **副标题：** {副标题占位符}
- **底部信息：** 汇报人 | 部门 | 日期

---

## 第 2 页 — {页面名称}

- **布局：** {布局类型，见下表}
- **标题：** {页面标题}
- **内容要点：**
  - {要点 1}
  - {要点 2}
  - {要点 3}
- **内容提示：** {可选，给生成时的注意事项}

---

...（更多页面）

## 最后一页 — 封底

- **布局：** closing
- **结束语：** {如 "Thank You" / "Q&A" 等}
```

## 布局类型参考

内容模板中 `布局` 字段引用以下类型，对应 `template-content.html` 中的 CSS 组件：

| 布局类型 | 适用场景 | 对应 CSS 组件 |
|----------|----------|---------------|
| `cover` | 封面页 | template-cover.html |
| `closing` | 封底页 | template-closing.html |
| `toc` | 目录页（编号章节列表） | `.toc-list` + `.toc-item` + `.toc-num` + `.toc-name` |
| `section-divider` | 章节分隔页（大序号+章节名居中） | `.divider-wrap` + `.divider-number` + `.divider-title` + `.divider-bar` |
| `bullets` | 标题 + 要点列表 | 基础内容页，直接写 `<ul>` |
| `three-cards` | 三个并列要点 | `.card-row` + `.yellow-card` |
| `two-col` | 左右对比/双栏内容 | `.two-col` + `.col` |
| `two-col-compare` | Do/Don't 或优劣势对比 | `.compare-row` + `.do-box` / `.dont-box` |
| `stats-grid` | 数据指标展示 | `.card-row` + `.stat-card` |
| `info-card` | 重点信息突显 | `.info-card` |
| `highlight-bar` | 关键结论/架构要点 | `.highlight-bar` |
| `dim-cards` | 多维度分析卡片 | `.dim-card`（Data/Tech/People 等）|
| `table` | 表格数据 | 手写 `<table>` |
| `faq-grid` | FAQ 2x2 网格（每格一问一答） | `.faq-grid` + `.faq-row` + `.faq-item` |

## 如何创建新内容模板

1. 在 `content-templates/` 下新建 `.md` 文件，命名格式：`{场景名}.md`（如 `季度复盘.md`）
2. 按上述结构编写页面大纲
3. 每页包含：布局类型 + 标题 + 内容要点
4. 内容要点用 `{占位符}` 标记需要用户填充的信息
5. 可添加 `内容提示` 字段给生成时额外指导

## 如何使用内容模板

1. 用户提供 PPT 主题和场景
2. 从 `content-templates/` 中选择最匹配的模板（或让用户选择）
3. 基于模板大纲，与用户确认/调整页面结构
4. 用户提供实际内容，填充占位符
5. 按 SKILL.md 标准工作流生成 HTML → PPTX
