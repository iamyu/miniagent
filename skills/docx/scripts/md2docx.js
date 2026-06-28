/**
 * md2docx.js — 通用 Markdown 转 Word 文档工具
 *
 * 用法：
 *   node md2docx.js <input.md> [output.docx]
 *
 * 支持的 Markdown 语法：
 *   # ~ #### 标题（H1-H4）
 *   **粗体**
 *   - 无序列表
 *   > 引用块
 *   [表格] Markdown 表格（| 分隔）
 *   --- 水平线
 *   图表 XX：xxx（居中灰色斜体，作为图表占位）
 *
 * 输出格式：A4 / 宋体正文10.5pt / 黑体标题 / 页眉页脚
 */

const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Header, Footer,
  AlignmentType, HeadingLevel, PageNumber, LevelFormat,
  BorderStyle, WidthType, ShadingType, Table, TableRow, TableCell
} = require("docx");

// ─── Config ───
const CFG = {
  fontBody: "SimSun",
  fontHeading: "SimHei",
  sizeBody: 21,       // 10.5pt
  sizeH1: 36,
  sizeH2: 28,
  sizeH3: 24,
  sizeH4: 22,
  headerText: "企业架构 第二版",
  defaultOutput: "",  // 如果不指定输出文件名，默认跟输入同名 .docx
};

// ─── CLI ───
const args = process.argv.slice(2);
if (args.length < 1) {
  console.error("用法: node md2docx.js <input.md> [output.docx]");
  process.exit(1);
}
const inputPath = path.resolve(args[0]);
const outputPath = args.length >= 2
  ? path.resolve(args[1])
  : inputPath.replace(/\.md$/i, "") + ".docx";

if (!fs.existsSync(inputPath)) {
  console.error("文件不存在:", inputPath);
  process.exit(1);
}

// ─── Markdown Parser ───

/** Parse inline bold **...** into TextRun array */
function parseInline(text, baseFont, baseSize) {
  const runs = [];
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  for (const part of parts) {
    if (part.startsWith("**") && part.endsWith("**")) {
      runs.push(new TextRun({ text: part.slice(2, -2), bold: true, font: baseFont, size: baseSize }));
    } else if (part) {
      runs.push(new TextRun({ text: part, font: baseFont, size: baseSize }));
    }
  }
  return runs;
}

function parseMarkdown(md) {
  const lines = md.split(/\r?\n/);
  const children = [];
  let i = 0;

  // Numbering reference counter
  let bulletRef = 0;
  const numberingConfigs = [];

  function getBulletRef() {
    // Reuse first bullet reference — docx-js continues numbering across paragraphs
    if (numberingConfigs.length === 0) {
      const ref = "bullet-" + (bulletRef++);
      numberingConfigs.push({
        reference: ref,
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "\u2022",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }, {
          level: 1, format: LevelFormat.BULLET, text: "\u25E6",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 1440, hanging: 360 } } }
        }]
      });
    }
    return numberingConfigs[0].reference;
  }

  function headingLevelFromHashes(h) {
    const map = { 1: HeadingLevel.HEADING_1, 2: HeadingLevel.HEADING_2, 3: HeadingLevel.HEADING_3, 4: HeadingLevel.HEADING_4 };
    return map[h] || HeadingLevel.HEADING_4;
  }
  function fontSizeFromLevel(h) {
    const map = { 1: CFG.sizeH1, 2: CFG.sizeH2, 3: CFG.sizeH3, 4: CFG.sizeH4 };
    return map[h] || CFG.sizeH4;
  }

  while (i < lines.length) {
    const line = lines[i];

    // Skip empty lines
    if (line.trim() === "") { i++; continue; }

    // Horizontal rule
    if (/^---+$/.test(line.trim())) { i++; continue; }

    // Heading: # ~ ####
    const headingMatch = line.match(/^(#{1,4})\s+(.+)/);
    if (headingMatch) {
      const h = headingMatch[1].length;
      const text = headingMatch[2].trim();
      children.push(new Paragraph({
        heading: headingLevelFromHashes(h),
        spacing: { before: h <= 2 ? 360 : 240, after: h <= 2 ? 200 : 120, line: 360 },
        children: [new TextRun({ text, font: CFG.fontHeading, size: fontSizeFromLevel(h), bold: true })]
      }));
      i++; continue;
    }

    // Figure reference: 图表 XX：xxx or 图 XX：xxx
    const figureMatch = line.match(/^(?:图表|图\s*\d+)\s*[-：:]\s*.+/);
    if (figureMatch) {
      children.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 200, after: 200, line: 360 },
        children: [new TextRun({ text: line.trim(), font: CFG.fontBody, size: CFG.sizeBody, italics: true, color: "666666" })]
      }));
      i++; continue;
    }

    // Table
    if (line.trim().startsWith("|")) {
      const tableLines = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        tableLines.push(lines[i]);
        i++;
      }
      // Skip separator row (|---|---|)
      const dataRows = tableLines.filter(r => !/^\|[\s\-:|]+\|$/.test(r.trim()));
      if (dataRows.length > 0) {
        const rows = dataRows.map(r => {
          const cells = r.split("|").slice(1, -1).map(c => c.trim());
          return new TableRow({
            children: cells.map(cellText => {
              return new TableCell({
                borders: {
                  top: { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" },
                  bottom: { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" },
                  left: { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" },
                  right: { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" },
                },
                margins: { top: 60, bottom: 60, left: 120, right: 120 },
                children: [new Paragraph({
                  spacing: { line: 300 },
                  children: parseInline(cellText, CFG.fontBody, CFG.sizeBody)
                })]
              });
            })
          });
        });
        children.push(new Table({
          width: { size: 9026, type: WidthType.DXA },
          rows
        }));
      }
      continue;
    }

    // Blockquote
    if (line.trim().startsWith(">")) {
      const quoteLines = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        quoteLines.push(lines[i].replace(/^>\s?/, "").trim());
        i++;
      }
      const quoteText = quoteLines.join("\n");
      children.push(new Paragraph({
        spacing: { before: 120, after: 120, line: 340 },
        indent: { left: 480 },
        border: { left: { style: BorderStyle.SINGLE, size: 6, color: "CCCCCC", space: 8 } },
        children: parseInline(quoteText, CFG.fontBody, CFG.sizeBody)
      }));
      continue;
    }

    // Bullet list
    if (/^[-*]\s+/.test(line)) {
      const bulletRefLocal = getBulletRef();
      while (i < lines.length) {
        const bline = lines[i];
        const match1 = bline.match(/^[-*]\s+(.+)/);
        const match2 = bline.match(/^\s{2,}[-*]\s+(.+)/);
        if (match2) {
          children.push(new Paragraph({
            numbering: { reference: bulletRefLocal, level: 1 },
            spacing: { line: 360, after: 60 },
            children: parseInline(match2[1], CFG.fontBody, CFG.sizeBody)
          }));
          i++;
        } else if (match1) {
          children.push(new Paragraph({
            numbering: { reference: bulletRefLocal, level: 0 },
            spacing: { line: 360, after: 60 },
            children: parseInline(match1[1], CFG.fontBody, CFG.sizeBody)
          }));
          i++;
        } else {
          break;
        }
      }
      continue;
    }

    // Ordered list
    if (/^\d+[.)]\s+/.test(line)) {
      const numRef = "numbered-" + (bulletRef++);
      numberingConfigs.push({
        reference: numRef,
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: "%1.",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }]
      });
      while (i < lines.length && /^\d+[.)]\s+/.test(lines[i])) {
        const text = lines[i].replace(/^\d+[.)]\s+/, "");
        children.push(new Paragraph({
          numbering: { reference: numRef, level: 0 },
          spacing: { line: 360, after: 60 },
          children: parseInline(text, CFG.fontBody, CFG.sizeBody)
        }));
        i++;
      }
      continue;
    }

    // Version record block (--- + **版本记录**：) — skip
    if (/^\*\*版本记录\*\*/.test(line.trim())) {
      // Skip until next section or EOF
      i++;
      while (i < lines.length) {
        if (/^##\s/.test(lines[i])) break;
        i++;
      }
      continue;
    }

    // Regular paragraph — consume consecutive non-empty lines as one paragraph
    const paraLines = [line];
    i++;
    while (i < lines.length && lines[i].trim() !== "" && !/^#{1,4}\s/.test(lines[i]) && !/^[-*]\s/.test(lines[i]) && !/^\d+[.)]\s/.test(lines[i]) && !lines[i].trim().startsWith("|") && !/^---+$/.test(lines[i].trim())) {
      paraLines.push(lines[i]);
      i++;
    }
    const paraText = paraLines.join("").trim();
    if (paraText) {
      children.push(new Paragraph({
        spacing: { line: 360, after: 120 },
        children: parseInline(paraText, CFG.fontBody, CFG.sizeBody)
      }));
    }
  }

  return { children, numberingConfigs };
}

// ─── Build Document ───
function buildDoc(inputPath) {
  const md = fs.readFileSync(inputPath, "utf-8");
  const { children, numberingConfigs } = parseMarkdown(md);

  return new Document({
    numbering: { config: numberingConfigs },
    styles: {
      default: {
        document: { run: { font: CFG.fontBody, size: CFG.sizeBody } }
      },
      paragraphStyles: [
        { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: CFG.sizeH1, bold: true, font: CFG.fontHeading },
          paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 } },
        { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: CFG.sizeH2, bold: true, font: CFG.fontHeading },
          paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 1 } },
        { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: CFG.sizeH3, bold: true, font: CFG.fontHeading },
          paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 2 } },
        { id: "Heading4", name: "Heading 4", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: CFG.sizeH4, bold: true, font: CFG.fontHeading },
          paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 3 } },
      ]
    },
    sections: [{
      properties: {
        page: {
          size: { width: 11906, height: 16838 }, // A4
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
        }
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [new TextRun({ text: CFG.headerText, font: CFG.fontBody, size: 18, color: "888888" })]
          })]
        })
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [
              new TextRun({ text: "— ", font: CFG.fontBody, size: 18, color: "888888" }),
              new TextRun({ children: [PageNumber.CURRENT], font: CFG.fontBody, size: 18, color: "888888" }),
              new TextRun({ text: " —", font: CFG.fontBody, size: 18, color: "888888" })
            ]
          })]
        })
      },
      children
    }]
  });
}

// ─── Main ───
async function main() {
  const doc = buildDoc(inputPath);
  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(outputPath, buffer);
  const stats = fs.statSync(outputPath);
  console.log("Generated:", outputPath);
  console.log("Size:", (stats.size / 1024).toFixed(1), "KB");
}

main().catch(err => {
  console.error("Error:", err.message || err);
  process.exit(1);
});
