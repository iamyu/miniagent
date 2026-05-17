# MiniAgent 便携运行时（Runtime）安装指南

本文档说明如何在没有 Node.js / Python 环境的电脑上，为 MiniAgent 配置便携版运行时。

---

## 目录结构要求

MiniAgent 启动时会按以下顺序查找运行时：

```
miniagent/
└── runtime/
    ├── node/
    │   └── node.exe          ← Node.js 便携版
    └── python/
        └── python.exe         ← Python 嵌入版
```

只要 `runtime/` 目录存在且包含对应的 exe 文件，MiniAgent 即可零安装运行。

---

## 一、Node.js 便携版

### 1. 下载地址

**官网**：https://nodejs.org/dist/

选择 **LTS 版本**（推荐 v22.x），下载 **Windows 二进制 zip 包**（不是安装器）：

```
https://nodejs.org/dist/v22.14.0/node-v22.14.0-win-x64.zip
```

> 选择文件名包含 `win-x64.zip` 的文件，**不要**下载 `.msi` 安装器。

### 2. 解压步骤

1. 下载 `node-v22.14.0-win-x64.zip`
2. 右键 → 解压到当前文件夹
3. 得到文件夹 `node-v22.14.0-win-x64`
4. 将该文件夹内的**所有内容**（不是文件夹本身）复制到：

```
D:\AI\miniagent\runtime\node\
```

最终 `runtime\node\` 目录下应直接看到 `node.exe`，而不是嵌套一层目录。

### 3. 验证

```cmd
D:\AI\miniagent\runtime\node\node.exe --version
```

输出版本号（如 `v22.14.0`）即成功。

---

## 二、Python 嵌入版

### 1. 下载地址

**官网**：https://www.python.org/downloads/windows/

在版本列表页找到 **Python 3.13.x**，下载 **Windows embeddable package（64-bit）**：

```
https://www.python.org/ftp/python/3.13.2/python-3.13.2-embed-amd64.zip
```

> 文件名包含 `embed-amd64.zip`，**不要**下载 `windows-installer.exe`。

### 2. 解压步骤

1. 下载 `python-3.13.2-embed-amd64.zip`
2. 右键 → 解压到当前文件夹
3. 得到多个文件（`python.exe`、`python313.dll`、`python313.zip` 等）
4. 将这些文件（不是文件夹）复制到：

```
D:\AI\miniagent\runtime\python\
```

最终 `runtime\python\` 目录下应直接看到 `python.exe`。

### 3. 验证

```cmd
D:\AI\miniagent\runtime\python\python.exe --version
```

输出版本号（如 `Python 3.13.2`）即成功。

### 4. 注意：嵌入版限制

Python 嵌入版**不包含 pip**，如需安装额外包，需：

1. 从 `https://bootstrap.pypa.io/get-pip.py` 下载 get-pip.py
2. 执行：`python.exe get-pip.py`
3. 或将所需包放到 `python313.zip` 中，或修改 `python313._pth` 文件

MiniAgent 的核心依赖（openai、pyyaml、duckduckgo-search）需通过完整 Python 安装后，将 `site-packages` 内容复制到嵌入版目录。

**推荐方式**：在另一台有 pip 的电脑上执行：

```bash
pip download openai pyyaml duckduckgo-search -d packages/
```

然后将下载的 `.whl` 文件解压，将内容复制到 `runtime\python\` 目录。

---

## 三、一键安装脚本

将以下脚本保存为 `setup_runtime.ps1`，放在 `miniagent\` 目录下运行。

### PowerShell 脚本（setup_runtime.ps1）

```powershell
# setup_runtime.ps1
# MiniAgent 便携运行时自动安装脚本
# 使用方法：在 miniagent 目录下，右键 → 用 PowerShell 运行

$ErrorActionPreference = "Stop"

$miniagentRoot = $PSScriptRoot
$runtimeDir = Join-Path $miniagentRoot "runtime"
$nodeDir = Join-Path $runtimeDir "node"
$pythonDir = Join-Path $runtimeDir "python"

# 创建目录
New-Item -ItemType Directory -Force -Path $nodeDir | Out-Null
New-Item -ItemType Directory -Force -Path $pythonDir | Out-Null

Write-Host "====================================" -ForegroundColor Cyan
Write-Host "  MiniAgent 便携运行时安装脚本" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# ---- Node.js ----
Write-Host "[1/2] 处理 Node.js ..." -ForegroundColor Yellow

$nodeUrl = "https://nodejs.org/dist/v22.14.0/node-v22.14.0-win-x64.zip"
$nodeZip = Join-Path $runtimeDir "node.zip"
$nodeTempDir = Join-Path $runtimeDir "node-temp"

# 检查是否已存在
if (Test-Path (Join-Path $nodeDir "node.exe")) {
    Write-Host "  Node.js 已存在，跳过下载。" -ForegroundColor Green
} else {
    Write-Host "  下载 Node.js v22.14.0 ..." -ForegroundColor Gray
    Invoke-WebRequest -Uri $nodeUrl -OutFile $nodeZip

    Write-Host "  解压 Node.js ..." -ForegroundColor Gray
    New-Item -ItemType Directory -Force -Path $nodeTempDir | Out-Null
    Expand-Archive -Path $nodeZip -DestinationPath $nodeTempDir -Force

    # 将解压内容移到 node 目录（去掉外层文件夹）
    $extractedDir = Get-ChildItem $nodeTempDir | Where-Object { $_.PSIsContainer } | Select-Object -First 1
    if ($extractedDir) {
        Copy-Item "$($extractedDir.FullName)\*" $nodeDir -Recurse -Force
    } else {
        Copy-Item "$nodeTempDir\*" $nodeDir -Recurse -Force
    }

    # 清理临时文件
    Remove-Item $nodeZip -Force -ErrorAction SilentlyContinue
    Remove-Item $nodeTempDir -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host "  Node.js 安装完成。" -ForegroundColor Green
}

# 验证 Node.js
$nodeExe = Join-Path $nodeDir "node.exe"
if (Test-Path $nodeExe) {
    $version = & $nodeExe --version
    Write-Host "  Node.js 版本: $version" -ForegroundColor Cyan
} else {
    Write-Host "  [警告] Node.js 未正确安装！" -ForegroundColor Red
}

Write-Host ""

# ---- Python ----
Write-Host "[2/2] 处理 Python ..." -ForegroundColor Yellow

$pythonUrl = "https://www.python.org/ftp/python/3.13.2/python-3.13.2-embed-amd64.zip"
$pythonZip = Join-Path $runtimeDir "python.zip"

if (Test-Path (Join-Path $pythonDir "python.exe")) {
    Write-Host "  Python 已存在，跳过下载。" -ForegroundColor Green
} else {
    Write-Host "  下载 Python 3.13.2 嵌入版 ..." -ForegroundColor Gray
    Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonZip

    Write-Host "  解压 Python ..." -ForegroundColor Gray
    Expand-Archive -Path $pythonZip -DestinationPath $pythonDir -Force

    Remove-Item $pythonZip -Force -ErrorAction SilentlyContinue

    Write-Host "  Python 安装完成。" -ForegroundColor Green
}

# 验证 Python
$pythonExe = Join-Path $pythonDir "python.exe"
if (Test-Path $pythonExe) {
    $version = & $pythonExe --version 2>&1
    Write-Host "  Python 版本: $version" -ForegroundColor Cyan
} else {
    Write-Host "  [警告] Python 未正确安装！" -ForegroundColor Red
}

Write-Host ""
Write-Host "====================================" -ForegroundColor Cyan
Write-Host "  安装完成！" -ForegroundColor Green
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "目录结构：" -ForegroundColor Gray
tree /F $runtimeDir 2>$null | Select-Object -First 20
Write-Host ""
Read-Host "按 Enter 退出"
```

### 运行方式

**方法一（推荐）**：

1. 将 `setup_runtime.ps1` 放到 `miniagent\` 目录
2. 右键 → **用 PowerShell 运行**

**方法二（命令行）**：

```powershell
powershell -ExecutionPolicy Bypass -File setup_runtime.ps1
```

> 如果系统禁止运行脚本，先执行：
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

---

## 四、手动验证清单

安装完成后，确认以下文件存在：

```
miniagent\runtime\node\node.exe          ← 必须
miniagent\runtime\node\npm.cmd           ← 可选（包管理）
miniagent\runtime\python\python.exe        ← 必须
miniagent\runtime\python\python313.dll    ← 必须
miniagent\runtime\python\python313.zip    ← 必须（标准库）
```

运行验证：

```cmd
runtime\node\node.exe --version
runtime\python\python.exe --version
```

两个命令均有版本输出即表示安装成功。

---

## 五、常见问题

### Q1：PowerShell 脚本无法运行

**解决**：以管理员身份运行 PowerShell，执行：
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### Q2：Python 嵌入版找不到模块（如 openai）

**原因**：嵌入版默认不包含 `site-packages` 搜索路径。

**解决**：编辑 `runtime\python\python313._pth`，取消注释 `import site` 一行，然后手动安装 pip 和依赖。

### Q3：下载速度慢

**解决**：手动从国内镜像下载后放到 `runtime\` 目录，再运行脚本（脚本会检测到已存在则跳过下载）。

- 淘宝 Node.js 镜像：`https://registry.npmmirror.com/-/binary/node/`
- 清华大学 Python 镜像：`https://pypi.tuna.tsinghua.edu.cn/simple/`

### Q4：公司电脑无法访问外网

**解决**：在能上网的电脑上下载好 zip 文件，拷贝到目标电脑，手动解压到 `runtime\` 对应目录。

---

## 六、版本对应关系

| 组件 | 推荐版本 | 下载文件名 |
|------|---------|------------|
| Node.js | v22.14.0 LTS | `node-v22.14.0-win-x64.zip` |
| Python | 3.13.2 | `python-3.13.2-embed-amd64.zip` |

> 版本需与 `miniagent\tools.py` 中 `_find_runtime()` 的预期兼容，建议使用上述推荐版本。
