# 异常引用检测功能架构设计

## 1. 功能定位

本功能用于辅助审稿系统发现参考文献层面的可解释风险信号，重点检查：

- DOI 是否存在；
- DOI 返回的题名、作者、期刊、年份是否与参考文献条目一致；
- 是否引用已撤稿、表达关切或存在出版状态更新的文献；

本功能不直接判断作者存在学术不端，也不直接判断引用是否构成不当引用。系统只输出可复核的异常信号，并提示编辑或作者进一步核查。

本版暂不包含以下模块：

- 引用集中度统计模块；
- 引用主题相关性检测模块；
- 历史投稿引用列表相似性检测模块。

上述三个模块作为后续扩展能力预留接口。

## 2. MVP 模块范围

第一版包含 5 个核心模块：

```text
论文文件输入
   ↓
1. 文本与结构解析模块
   ↓
2. 参考文献抽取与结构化模块
   ↓
3. DOI 与元数据校验模块
   ↓
4. 撤稿文献检测模块
   ↓
5. 风险汇总与报告生成模块
```

## 3. 模块一：文本与结构解析模块

### 3.1 功能边界

负责从论文文件中抽取基础文本和结构信息，包括标题、摘要、关键词、正文、参考文献区域和正文引用上下文。

本模块只做解析，不判断风险。

### 3.2 输入

```json
{
  "paper_id": "submission_001",
  "file_path": "uploads/submission_001.pdf",
  "file_type": "pdf"
}
```

支持输入类型：

- PDF；
- Word；
- 后续可扩展 HTML、LaTeX、XML。

### 3.3 输出

```json
{
  "paper_id": "submission_001",
  "title": "Paper title",
  "abstract": "Abstract text",
  "keywords": ["keyword1", "keyword2"],
  "body_text": "Full body text",
  "reference_section_text": "Raw references text",
  "citation_contexts": [
    {
      "citation_marker": "[12]",
      "context": "Previous studies have shown ... [12].",
      "section": "Introduction"
    }
  ]
}
```

### 3.4 推荐库和工具

| 工具 | 用途 | 是否必需 |
|---|---|---|
| `PyMuPDF` | PDF 文本抽取，速度快，部署轻 | 是 |
| `pdfplumber` | 辅助处理复杂 PDF 排版 | 可选 |
| `python-docx` | Word 文档解析 | 是 |
| `GROBID` | 论文结构化解析，识别标题、摘要、参考文献 | 推荐 |
| `regex` | 参考文献区、引用标记兜底识别 | 是 |

### 3.5 主要难点

- PDF 排版不统一；
- 参考文献区边界可能识别错误；
- 正文引用格式多样，例如 `[1]`、`(Smith, 2020)`、上标数字；
- Word 文件格式相对稳定，但作者上传版本可能包含修订痕迹或批注。

## 4. 模块二：参考文献抽取与结构化模块

### 4.1 功能边界

负责将参考文献区域拆分为单条参考文献，并抽取题名、作者、期刊、年份、DOI 等字段。

本模块不查询外部数据库，也不判断 DOI 是否真实。

### 4.2 输入

```json
{
  "paper_id": "submission_001",
  "reference_section_text": "Raw references text"
}
```

### 4.3 输出

```json
{
  "paper_id": "submission_001",
  "references": [
    {
      "ref_id": "R001",
      "raw_text": "Smith J. Example title. Journal A. 2020;1(1):1-10. doi:10.xxxx/xxxx",
      "title": "Example title",
      "authors": ["Smith J"],
      "journal": "Journal A",
      "publisher": null,
      "year": 2020,
      "doi": "10.xxxx/xxxx",
      "citation_markers": ["[1]"]
    }
  ]
}
```

### 4.4 推荐库和工具

| 工具 | 用途 | 是否必需 |
|---|---|---|
| `GROBID` | 参考文献结构化抽取 | 推荐 |
| `regex` | DOI、年份、卷期页码兜底抽取 | 是 |
| `rapidfuzz` | 后续字段匹配准备 | 可选 |
| `pandas` | 批量整理参考文献记录 | 是 |

### 4.5 主要难点

- 参考文献跨行导致切分错误；
- DOI 可能被换行、空格、标点破坏；
- 中文文献、书籍章节、会议论文结构化难度更高；
- 部分参考文献没有 DOI，不能直接判为异常。

## 5. 模块三：DOI 与元数据校验模块

### 5.1 功能边界

负责校验参考文献中的 DOI 是否存在，并检查 DOI 返回的元数据是否与参考文献条目一致。

本模块只判断元数据一致性，不判断引用是否合理。

### 5.2 输入

```json
{
  "paper_id": "submission_001",
  "references": [
    {
      "ref_id": "R001",
      "title": "Example title",
      "authors": ["Smith J"],
      "journal": "Journal A",
      "year": 2020,
      "doi": "10.xxxx/xxxx"
    }
  ]
}
```

### 5.3 输出

```json
{
  "paper_id": "submission_001",
  "doi_checks": [
    {
      "ref_id": "R001",
      "doi": "10.xxxx/xxxx",
      "doi_exists": true,
      "metadata_match_score": 0.86,
      "matched_title": true,
      "matched_year": true,
      "matched_journal": false,
      "crossref_title": "Example title",
      "crossref_journal": "Journal B",
      "risk_flag": "journal_mismatch"
    }
  ]
}
```

### 5.4 推荐库和工具

| 工具 | 用途 | 是否必需 |
|---|---|---|
| Crossref REST API | DOI 存在性与元数据校验 | 是 |
| PubMed API | 医学文献补充校验 | 可选 |
| OpenAlex API | 文献元数据补充 | 可选 |
| `requests` | API 请求 | 是 |
| `rapidfuzz` | 标题、期刊、作者模糊匹配 | 是 |
| `pandas` | 批量结果整理 | 是 |
| `SQLite` / `DuckDB` | 本地查询缓存 | 推荐 |

### 5.5 推荐判定规则

| 情况 | 风险等级 | 说明 |
|---|---|---|
| DOI 查询不到 | 高 | 可能为错误 DOI、伪造 DOI 或格式错误 |
| DOI 存在但标题明显不匹配 | 高 | 参考文献条目可能错误或拼接 |
| DOI 存在但年份不匹配 | 中 | 可能为 online first、录入错误或引用错误 |
| DOI 存在但期刊不匹配 | 中 | 可能为期刊缩写解析错误，也可能为元数据异常 |
| 无 DOI | 低到中 | 只提示复核，不能直接判异常 |

### 5.6 主要难点

- Crossref 元数据可能缺失或格式不统一；
- 期刊名可能存在缩写、旧名、新名；
- 作者名存在缩写、大小写、顺序差异；
- 旧文献、中文文献、书籍章节 DOI 覆盖不足。

## 6. 模块四：撤稿文献检测模块

### 6.1 功能边界

负责检查参考文献是否引用了已撤稿、表达关切、撤稿替换或存在出版状态更新的文献。

本模块只提示引用对象的出版状态，不判断作者引用是否违规。

### 6.2 输入

```json
{
  "paper_id": "submission_001",
  "references": [
    {
      "ref_id": "R001",
      "title": "Example title",
      "doi": "10.xxxx/xxxx"
    }
  ]
}
```

### 6.3 输出

```json
{
  "paper_id": "submission_001",
  "retraction_checks": [
    {
      "ref_id": "R001",
      "doi": "10.xxxx/xxxx",
      "is_retracted": true,
      "notice_doi": "10.xxxx/retraction",
      "retraction_nature": "Retraction",
      "retraction_date": "2024-01-31",
      "reason": "Concerns/Issues about Data",
      "risk_flag": "cites_retracted_work"
    }
  ]
}
```

### 6.4 推荐库和工具

| 工具 | 用途 | 是否必需 |
|---|---|---|
| Retraction Watch CSV | 本地撤稿 DOI 索引 | 是 |
| Crossref update metadata | 出版状态更新补充 | 推荐 |
| PubMed retraction status | 医学文献补充 | 可选 |
| `pandas` | 本地 DOI 匹配 | 是 |
| `SQLite` / `DuckDB` | 本地撤稿索引库 | 推荐 |

### 6.5 本地索引建议

建议将 Retraction Watch 数据预处理成本地索引表：

```text
original_doi
retraction_doi
title
journal
publisher
retraction_nature
retraction_date
reason
source_record_id
source_url
updated_at
```

检测时优先本地匹配：

```text
reference DOI → original_doi
reference DOI → retraction_doi
```

如本地无匹配，再尝试 Crossref update metadata 或 PubMed 状态补充。

### 6.6 主要难点

- 撤稿状态数据库需要定期更新；
- DOI 大小写、URL 形式、空格和标点需要标准化；
- 某些撤稿记录没有 DOI，只能通过题名模糊匹配；
- 引用撤稿论文不一定违规，可能是合理讨论或明确标注。

## 7. 模块五：风险汇总与报告生成模块

### 7.1 功能边界

负责汇总前面模块的检测结果，生成统一风险卡片，并输出给系统报告页。

本模块不重新检测，只做归并、去重、分级和文案生成。

### 7.2 输入

```json
{
  "paper_id": "submission_001",
  "references": [],
  "doi_checks": [],
  "retraction_checks": []
}
```

### 7.3 输出

```json
{
  "module": "reference_anomaly_detection",
  "paper_id": "submission_001",
  "risk_items": [
    {
      "risk_type": "reference_anomaly",
      "severity": "high",
      "confidence": 0.84,
      "evidence": "参考文献中 5 条 DOI 元数据不匹配，2 条文献已被撤稿",
      "location": "References",
      "review_required": true,
      "suggested_action": "请作者核对参考文献真实性，并请编辑复核撤稿文献引用"
    }
  ],
  "summary": {
    "total_references": 52,
    "doi_found_count": 38,
    "doi_missing_count": 14,
    "doi_not_found_count": 2,
    "doi_mismatch_count": 5,
    "retracted_reference_count": 2
  }
}
```

### 7.4 推荐库和工具

| 工具 | 用途 | 是否必需 |
|---|---|---|
| `pydantic` | 定义统一输入输出结构 | 推荐 |
| `jsonschema` | 校验 JSON 输出 | 可选 |
| `pandas` | 汇总统计 | 是 |
| `jinja2` | 生成 HTML / Markdown 报告 | 可选 |

### 7.5 风险等级建议

| 风险类型 | 默认等级 | 说明 |
|---|---|---|
| DOI 不存在 | 高 | 需作者核对 |
| DOI 与标题不匹配 | 高 | 需作者核对 |
| DOI 与期刊或年份不匹配 | 中 | 需人工复核 |
| 引用已撤稿文献 | 高 | 需确认是否已说明撤稿状态 |
| 无 DOI 且无法补全 | 低到中 | 只提示复核 |

## 8. 推荐目录结构

```text
reference_anomaly_detection/
  config/
    thresholds.yaml
    journal_aliases.yaml
    publisher_aliases.yaml
    retraction_watch_index.csv

  parsers/
    document_parser.py
    reference_extractor.py
    citation_context_extractor.py

  checkers/
    doi_metadata_checker.py
    retraction_checker.py

  services/
    crossref_client.py
    pubmed_client.py
    openalex_client.py

  models/
    schemas.py

  reports/
    report_builder.py

  tests/
    test_document_parser.py
    test_reference_extractor.py
    test_doi_metadata_checker.py
    test_retraction_checker.py

  main.py
```

## 9. 统一数据结构

### 9.1 ReferenceItem

```json
{
  "ref_id": "R001",
  "raw_text": "Original reference string",
  "title": "Reference title",
  "authors": ["Author A", "Author B"],
  "journal": "Journal name",
  "publisher": "Publisher name",
  "year": 2020,
  "doi": "10.xxxx/xxxx",
  "citation_markers": ["[1]"]
}
```

### 9.2 DoiCheckResult

```json
{
  "ref_id": "R001",
  "doi": "10.xxxx/xxxx",
  "doi_exists": true,
  "metadata_match_score": 0.86,
  "matched_title": true,
  "matched_year": true,
  "matched_journal": false,
  "risk_flag": "journal_mismatch"
}
```

### 9.3 RetractionCheckResult

```json
{
  "ref_id": "R001",
  "doi": "10.xxxx/xxxx",
  "is_retracted": true,
  "notice_doi": "10.xxxx/retraction",
  "retraction_nature": "Retraction",
  "retraction_date": "2024-01-31",
  "reason": "Concerns/Issues about Data",
  "risk_flag": "cites_retracted_work"
}
```

### 9.4 RiskItem

```json
{
  "risk_type": "doi_metadata_mismatch",
  "severity": "medium",
  "confidence": 0.81,
  "evidence": "DOI 返回标题与参考文献标题相似度为 0.42",
  "location": "References, R012",
  "review_required": true,
  "suggested_action": "请作者核对该参考文献 DOI 与题名"
}
```

## 10. 系统嵌入方式

建议采用异步任务式嵌入：

```text
用户上传论文
  ↓
系统保存文件
  ↓
触发 reference_anomaly_detection 任务
  ↓
脚本输出 JSON
  ↓
后端存入 risk_items 表
  ↓
前端报告页展示风险卡片
```

### 10.1 后端存储字段建议

```text
id
paper_id
module_name
risk_type
severity
confidence
evidence
location
review_required
suggested_action
raw_json
created_at
```

### 10.2 前端展示建议

报告页展示为风险卡片：

```text
参考文献异常检测

发现 3 项需复核信号：
1. 2 条 DOI 未能在 Crossref 中检索到；
2. 5 条 DOI 元数据与参考文献题名或期刊不匹配；
3. 2 条参考文献为已撤稿文献。

系统说明：
以上结果仅提示参考文献真实性或出版状态异常，不构成学术不端结论。建议作者核对参考文献，编辑复核撤稿文献引用是否已明确说明。
```

## 11. 运行流程

### 11.1 单篇论文检测

```text
python main.py --paper-id submission_001 --file uploads/submission_001.pdf --output reports/submission_001_reference_report.json
```

### 11.2 批量检测

```text
python main.py --input manifest.csv --output-dir reports/
```

`manifest.csv` 示例：

```text
paper_id,file_path,file_type
submission_001,uploads/submission_001.pdf,pdf
submission_002,uploads/submission_002.docx,docx
```

## 12. 配置文件建议

### 12.1 thresholds.yaml

```yaml
doi_title_match_high_risk_threshold: 0.6
doi_title_match_medium_risk_threshold: 0.8
max_api_retry: 3
api_timeout_seconds: 10
cache_enabled: true
```

### 12.2 journal_aliases.yaml

```yaml
"J Biol Chem":
  - "Journal of Biological Chemistry"
"Nat Med":
  - "Nature Medicine"
```

## 13. 准确性风险与处理策略

| 风险 | 影响 | 处理策略 |
|---|---|---|
| PDF 参考文献抽取错分 | DOI 或题名校验失败 | 保留 raw_text，允许人工查看 |
| DOI 被换行或标点破坏 | 误判 DOI 不存在 | DOI 标准化和正则清洗 |
| Crossref 元数据缺失 | 误报元数据不匹配 | 接入 PubMed / OpenAlex 作为补充 |
| 期刊缩写差异 | 误报期刊不匹配 | 维护 journal_aliases 映射 |
| 引用撤稿文献但正文已说明 | 误报高风险 | 后续结合 citation_contexts 检查是否出现 retracted / withdrawn 等提示词 |
| 中文文献和书籍章节无 DOI | 误报无 DOI 异常 | 无 DOI 默认低风险，只提示复核 |

## 14. 后续扩展预留

本架构预留但暂不实现以下模块：

```text
checkers/
  concentration_checker.py
  topic_relevance_checker.py
  history_similarity_checker.py
```

后续可在不改动前四个模块的情况下，直接接入风险汇总模块。

预留输出字段：

```json
{
  "concentration_metrics": null,
  "topic_relevance": null,
  "reference_list_similarity": null
}
```

## 15. 第一版交付标准

第一版完成后，应满足：

- 能解析 PDF / Word 中的参考文献区域；
- 能抽取单条参考文献的 DOI、题名、作者、期刊、年份；
- 能查询 Crossref 并判断 DOI 是否存在；
- 能判断 DOI 返回元数据与参考文献是否明显不一致；
- 能通过本地 Retraction Watch 索引检测引用撤稿文献；
- 能输出统一 JSON 风险卡片；
- 能被后端异步任务调用；
- 能在系统报告页展示可解释结果。
