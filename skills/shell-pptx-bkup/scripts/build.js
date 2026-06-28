// Shell PPTX Build Script — 基于 Shell 品牌风格的 HTML-to-PPTX 构建器
// 依赖: pptxgenjs, playwright, sharp, html2pptx
// 使用方法: 修改 CONFIG 和 slides 数组后，运行 node build.js

const pptxgen = require('pptxgenjs');
const path = require('path');
const fs = require('fs');
const playwright = require('playwright');

// ─── 配置区（按需修改）────────────────────────
const CONFIG = {
  slidesDir: path.resolve(__dirname, 'slides'),
  outputFile: path.resolve(__dirname, 'output.pptx'),
  title: 'Presentation Title',
  author: 'Shell China',
  subject: '',
};

// Playwright Chromium 路径自动检测
let CHROMIUM_EXE = null;
const PLAYWRIGHT_BROWSERS = path.join(
  process.env.LOCALAPPDATA || process.env.HOME,
  'ms-playwright'
);

// 自动查找最新版 chromium_headless_shell
function findChromium() {
  if (!fs.existsSync(PLAYWRIGHT_BROWSERS)) return null;
  const dirs = fs.readdirSync(PLAYWRIGHT_BROWSERS)
    .filter(d => d.startsWith('chromium_headless_shell-'))
    .sort((a, b) => {
      const va = parseInt(a.replace('chromium_headless_shell-', ''));
      const vb = parseInt(b.replace('chromium_headless_shell-', ''));
      return vb - va;
    });
  if (dirs.length === 0) return null;
  // Windows
  const exePath = path.join(PLAYWRIGHT_BROWSERS, dirs[0],
    'chrome-headless-shell-win64', 'chrome-headless-shell.exe');
  if (fs.existsSync(exePath)) return exePath;
  // macOS
  const macPath = path.join(PLAYWRIGHT_BROWSERS, dirs[0],
    'chrome-headless-shell-mac', 'chrome-headless-shell');
  if (fs.existsSync(macPath)) return macPath;
  // Linux
  const linuxPath = path.join(PLAYWRIGHT_BROWSERS, dirs[0],
    'chrome-headless-shell-linux', 'chrome-headless-shell');
  if (fs.existsSync(linuxPath)) return linuxPath;
  return null;
}

CHROMIUM_EXE = findChromium();
if (CHROMIUM_EXE) {
  const _origLaunch = playwright.chromium.launch.bind(playwright.chromium);
  playwright.chromium.launch = (opts = {}) => _origLaunch({ ...opts, executablePath: CHROMIUM_EXE });
  console.log('Chromium:', CHROMIUM_EXE);
}

// Find project root by searching upward for skills/ directory
function findProjectRoot(startDir) {
  let dir = startDir;
  for (let i = 0; i < 10; i++) {
    const skillsDir = path.join(dir, 'skills');
    if (fs.existsSync(skillsDir) && fs.statSync(skillsDir).isDirectory()) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

// html2pptx 路径自动检测（查找 pptx skill 或 shell-pptx 自带）
function findHtml2Pptx() {
  // 1. 优先查找 shell-pptx 自带（copied to <project>/scripts/）
  const local = path.resolve(__dirname, 'scripts', 'html2pptx.js');
  if (fs.existsSync(local)) return local;

  // 2. 查找项目根目录下的 skills/shell-pptx/ 和 skills/pptx/
  const projectRoot = findProjectRoot(__dirname);
  if (projectRoot) {
    const shellPptxPath = path.join(projectRoot, 'skills', 'shell-pptx', 'scripts', 'html2pptx.js');
    if (fs.existsSync(shellPptxPath)) return shellPptxPath;
    const pptxPath = path.join(projectRoot, 'skills', 'pptx', 'scripts', 'html2pptx.js');
    if (fs.existsSync(pptxPath)) return pptxPath;
  }

  // 3. 查找 pptx skill (Claude Code)
  const claudePath = path.join(
    process.env.USERPROFILE || process.env.HOME,
    '.claude', 'skills', 'document-skills', 'pptx', 'scripts', 'html2pptx.js'
  );
  if (fs.existsSync(claudePath)) return claudePath;

  throw new Error(
    'html2pptx.js not found. Expected locations:\n' +
    '  - <project>/scripts/html2pptx.js\n' +
    '  - <project>/skills/shell-pptx/scripts/html2pptx.js\n' +
    '  - <project>/skills/pptx/scripts/html2pptx.js\n' +
    '  - ~/.claude/skills/document-skills/pptx/scripts/html2pptx.js'
  );
}

const html2pptx = require(findHtml2Pptx());

// ─── 幻灯片列表（按顺序添加 HTML 文件名）────────
const slides = [
  // 'slide01-cover.html',
  // 'slide02-content.html',
  // ...
];

// ─── 构建逻辑（通常不需要修改）────────────────
async function build() {
  const pptx = new pptxgen();
  pptx.layout = 'LAYOUT_16x9';
  pptx.title = CONFIG.title;
  pptx.author = CONFIG.author;
  pptx.subject = CONFIG.subject;

  for (const slideFile of slides) {
    const htmlPath = path.join(CONFIG.slidesDir, slideFile);
    console.log('Processing:', slideFile);
    try {
      await html2pptx(htmlPath, pptx);
    } catch (e) {
      console.error('Error on', slideFile, ':', e.message);
      process.exit(1);
    }
  }

  await pptx.writeFile({ fileName: CONFIG.outputFile });
  console.log('DONE:', CONFIG.outputFile);
}

build().catch(e => { console.error(e); process.exit(1); });
