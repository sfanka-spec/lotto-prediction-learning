# Lottery AI V1.6.6

面向 **LOTTO 6/49** 与 **LOTTO MAX** 的统计分析与预测学习软件。

> **仅用于研究与教育用途。** 软件中的组合评分、排名、模拟结果和模型输出，不代表任何保证中奖的概率或收益。

[English README](README.md)

## 当前版本

**V1.6.6 — Public Release Hardening**

本版本重点包括：

- 增加面向公开共享的安全与文档加固；
- 明确源码与本地运行数据库之间的边界；
- 增加 GitHub Actions 自动测试；
- 增加公开数据、隐私与可复现性说明；
- 增加公开发布检查清单；
- 完整保留 V1.6.5 的统计正确性与运行稳定性修复。

详细版本说明请查看：

- `CHANGELOG_V1.6.6.md`
- `UPGRADE_V1.6.6.md`
- `CHANGELOG_V1.6.5.md`
- `VALIDATION_V1.6.5.txt`

旧版本说明仍保留在其他 `CHANGELOG_*.md` 和 `UPGRADE_*.md` 文件中。

## 主要功能

- 支持 LOTTO 6/49 与 LOTTO MAX
- 历史开奖数据抓取、校验与修复
- Production / Challenger 模型流程
- Random Control 随机基线
- Neural Shadow 研究模型
- Freeze -> Judge -> Learn 学习闭环
- 候选组合与投资组合分析
- Combination Concentration 组合集中度诊断
- CWC（Cumulative Winning Coverage）累计中奖号码覆盖
- Budget / Portfolio 研究工具
- 数据完整性审计
- 多数据源故障切换与恢复
- 过拟合与模型稳定性研究诊断

# 安装指南

## 1. 安装 Python

在 Windows 上安装较新的 **64-bit Python 3**。

安装时请勾选：

```text
Add Python to PATH
```

安装完成后，打开 PowerShell，输入：

```powershell
python --version
pip --version
```

如果提示找不到 `python`，请关闭 PowerShell 后重新打开一次。

## 2. 获取项目

### 方法 A：使用 Git

如果电脑已经安装 Git：

```powershell
git clone https://github.com/sfanka-spec/lotto-prediction-learning.git
cd lotto-prediction-learning
```

### 方法 B：下载 ZIP

也可以从 GitHub 的 **Releases** 页面下载 Source code ZIP，然后解压到本地文件夹。

## 3. 建立虚拟环境

在项目根目录打开 PowerShell：

```powershell
python -m venv .venv
```

然后启用虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

如果 PowerShell 阻止脚本运行，可以先执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

然后再执行：

```powershell
.\.venv\Scripts\Activate.ps1
```

## 4. 安装程序依赖

先升级 pip：

```powershell
python -m pip install --upgrade pip
```

再安装运行依赖：

```powershell
pip install -r requirements.txt
```

当前主要依赖包括：

- requests
- beautifulsoup4
- numpy
- scikit-learn
- tzdata
- pypdf

## 5. 启动 Lottery AI

在项目根目录运行：

```powershell
python app.py
```

正常情况下会打开桌面 GUI 界面。

# 测试与开发环境

如果需要运行测试：

```powershell
pip install -r requirements-dev.txt
```

然后执行：

```powershell
pytest
```

建议每次发布新版本前都运行完整测试。

# 更新本地版本

如果项目是通过 Git clone 获取的，可以运行：

```powershell
git pull origin main
```

然后重新确认依赖：

```powershell
pip install -r requirements.txt
```

# 项目目录结构

```text
lotto-prediction-learning/
├─ app.py
├─ lottery_ai/
├─ tests/
├─ data/
├─ requirements.txt
├─ requirements-dev.txt
├─ README.md
├─ README_CN.md
├─ PUBLIC_RELEASE_CHECKLIST.md
├─ CHANGELOG_*.md
└─ UPGRADE_*.md
```

主要模块：

- `lottery_ai/config.py` — 游戏规则与模型配置
- `lottery_ai/db.py` — SQLite 数据库与模型快照
- `lottery_ai/providers.py` — 开奖数据源、历史数据源与校验
- `lottery_ai/analysis.py` — 统计、概率与结构分析
- `lottery_ai/engine.py` — 组合评分与投资组合逻辑
- `lottery_ai/models.py` — Neural Shadow 模型
- `lottery_ai/learning.py` — Freeze / Judge / Learning 流程
- `lottery_ai/backtest.py` — Walk-forward、Shuffle、Null Test
- `lottery_ai/updater.py` — 数据更新、补全与恢复

# 首次运行与本地数据库

新用户**不需要**开发者自己的 `lottery.db`。

首次运行时，Lottery AI 会在本地自动创建 SQLite 数据库结构。之后可以通过程序内的数据更新/修复功能补全历史数据，也可以导入经过确认的 CSV 数据。

GitHub 仓库会刻意排除真实运行数据库、学习状态、日志、模型快照二进制文件、凭据和本地缓存。详细规则请查看 `data/README.md` 和 `PUBLIC_RELEASE_CHECKLIST.md`。

# 数据处理流程

软件采用较保守的数据与学习流程：

```text
Raw ingest
   -> validation
   -> clean draw data
   -> features
   -> model
   -> frozen prediction
   -> official result
   -> evaluation
   -> learning
```

可疑或异常历史数据可以保留用于审计，但不会自动进入 model-ready 数据集。

# 研究保护机制

项目包含多项用于减少误判与过拟合的机制：

- Random Baseline
- Shadow-only 实验模型
- Walk-forward 测试
- Shuffle placebo 测试
- Synthetic null 测试
- 开奖前冻结预测
- 开奖后只评估，不回写历史预测
- 明确区分 Portfolio Coverage 与单张彩票的 Combination Concentration

# 结果应该怎么理解

较高的模型分数只表示：

> 该组合在当前研究模型下的排名更高。

它**不表示**：

> 该合法彩票组合在官方随机开奖中具有被保证更高的中奖概率。

除非真实的非随机偏差经过严格、独立、长期验证，否则彩票结果应被视为随机事件。

# 常见问题

## `python` 无法识别

重新安装 Python，并确认安装时勾选：

```text
Add Python to PATH
```

然后关闭并重新打开 PowerShell。

## 虚拟环境无法启用

运行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

然后：

```powershell
.\.venv\Scripts\Activate.ps1
```

## 依赖安装失败

先运行：

```powershell
python -m pip install --upgrade pip
```

然后重试：

```powershell
pip install -r requirements.txt
```

## 程序可以打开，但数据无法更新

先检查网络连接。

程序使用多个数据源，并采用 fail-closed 设计：如果数据格式异常或无法通过验证，不会把它直接写成有效开奖数据。

# GitHub 与版本管理

建议每次准备新版本时：

1. 运行完整测试；
2. 更新 CHANGELOG；
3. 提交代码；
4. 创建新的 Git tag；
5. 发布 GitHub Release。

例如：

```text
v1.6.5
v1.6.6
v1.7.0
```

测试版可以使用：

```text
v1.7.0-beta.1
```

# 安全与隐私

不要把以下内容提交到 GitHub：

- `.env`
- API key
- token
- 密码
- 本地日志
- SQLite 本地运行数据库
- 模型缓存
- `__pycache__`
- 虚拟环境目录

仓库中的 `.gitignore` 已用于排除常见本地运行文件。

# License

当前没有授予公开软件许可证。

即使仓库改成 Public，也不等于自动允许他人复制、修改或重新发布。若希望真正开放使用，应由仓库所有者明确选择并加入 LICENSE。

# 免责声明

本软件仅用于统计研究与教育用途。

它不保证中奖、利润或预测优势，也不应被理解为赌博建议或财务建议。
