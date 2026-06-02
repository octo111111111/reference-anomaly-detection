# reference-anomaly-detection

参考文献异常检测工具（Python ≥ 3.10）：从投稿论文 PDF/Word 中解析参考文献，校验 DOI 与 Crossref 元数据是否一致，并检测是否引用已撤稿文献。输出可复核的风险信号，供编辑或作者人工核查。

当前版本：**0.5.0**

## 功能概览

| 模块 | 能力 |
|------|------|
| 一 | 解析标题、摘要、正文、参考文献区、引用上下文 |
| 二 | 拆分参考文献条目，启发式提取题名、作者、期刊、年份、DOI |
| 三 | Crossref 校验 DOI 存在性及元数据一致性；**无 DOI 时通过书目检索尝试解析 DOI** |
| 四 | 本地 Retraction Watch 索引：**DOI 精确匹配**；无 DOI 时用**解析 DOI** 或 **题名 FTS + 模糊匹配** |
| 五 | 汇总 DOI / 撤稿风险，生成 JSON 报告 |

本工具**不**判定学术不端，仅输出异常信号与建议复核项。

## 无 DOI 参考文献（0.5.0+）

许多参考文献只写题名、不写 DOI。流水线对无 DOI 条目会：

1. **书目解析**：调用 Crossref `works` 检索，得分达标时得到 `doi_source=resolved` 的补充校验（`ref_id` 后缀 `-resolved`）。
2. **撤稿题名匹配**：在本地 Retraction Watch 索引中用 FTS 召回 + `rapidfuzz` 模糊匹配；高置信命中 `cites_retracted_work`，中等置信 `cites_retracted_work_title_possible`。

有参考文献 **DOI** 时仅做 DOI 匹配，**不会**因题名相似而误报。

阈值见 `reference_anomaly_detection/config/thresholds.yaml` 与 `retraction.yaml`。

## 快速开始

### 安装

```bash
cd reference-anomaly-detection
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -e ".[dev]"
```

### 构建撤稿索引（生产环境必做）

从 [Retraction Watch Database](https://retractionwatchdatabase.org/) 下载 CSV 后：

```bash
reference-build-retraction-index --csv data/RetractionWatch.csv
```

升级本仓库后请**重新构建**索引（含 FTS5 题名索引）。开发测试可用样例 CSV：

```bash
reference-build-retraction-index --csv reference_anomaly_detection/tests/data/retraction_watch_sample.csv
```

### 一键检测

```bash
reference-run --file path/to/paper.pdf --output reports/summary.json
```

摘要打印到 stderr，汇总 JSON 输出到 stdout 或 `--output` 指定文件。可选：

- `--db`：撤稿 SQLite 路径  
- `--skip-retraction`：跳过撤稿检测  
- `--mailto`：Crossref polite pool 邮箱  
- `--no-cache`：禁用 Crossref 本地缓存  
- `--save-intermediate DIR`：保存各步骤中间 JSON  

## 命令行入口

| 命令 | 说明 |
|------|------|
| `reference-run` | 模块一至五一键流水线 |
| `reference-parse` | 模块一：解析论文 |
| `reference-extract` | 模块二：结构化参考文献 |
| `reference-check-doi` | 模块三：DOI / 元数据校验 |
| `reference-build-retraction-index` | 构建撤稿 SQLite 索引 |
| `reference-check-retraction` | 模块四：撤稿检测 |
| `reference-summarize` | 模块五：风险汇总 |

## 配置

| 文件 | 用途 |
|------|------|
| `reference_anomaly_detection/config/thresholds.yaml` | DOI 元数据相似度、书目解析阈值、API 超时 |
| `reference_anomaly_detection/config/retraction.yaml` | 撤稿索引路径、题名匹配阈值、FTS Top-K |
| `reference_anomaly_detection/config/journal_aliases.yaml` | 期刊别名 |

## 文档

- **[使用指南](docs/使用指南.md)**：环境、分步 CLI、Python API、FAQ  
- **[架构设计](architecture.md)**：仓库目录、五模块边界、输入输出、扩展规划  

## 仓库目录

```text
reference-anomaly-detection/
├── reference_anomaly_detection/   # Python 包（parsers / checkers / services / pipeline）
├── data/                          # 放置 RetractionWatch.csv（不入库）
├── reports/                       # CLI 输出目录（运行产物不入库）
├── docs/                          # 使用指南
├── architecture.md                # 架构与目录说明
└── pyproject.toml
```

详见 [architecture.md §8](architecture.md#8-仓库目录结构当前实现)。

## 开发

```bash
pytest
```

## 依赖

PyMuPDF、python-docx、pydantic、requests、rapidfuzz、PyYAML（见 `pyproject.toml`）。

## 许可

见仓库根目录许可文件（如有）。
