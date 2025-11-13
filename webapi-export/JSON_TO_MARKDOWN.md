# JSON 转 Markdown 工具使用说明

## 功能说明

这个工具可以将为知笔记导出的 JSON 格式文档批量转换为 Markdown 格式。

## 使用方法

### 1. 批量转换所有 JSON 文件

将 `docs` 目录下所有 `latest.json` 文件转换为 Markdown，所有文件直接输出到 `outputs/md` 目录：

```bash
python main.py --convert-json
```

转换后的文件会保存在 `outputs/md` 目录下，文件名格式为 `document_0001.md`、`document_0002.md` 等。

### 2. 指定自定义目录

可以指定自定义的输入和输出目录：

```bash
python main.py --convert-json --json-dir docs --md-output outputs/markdown
```

参数说明：
- `--convert-json`: 启用 JSON 转换模式
- `--json-dir`: 指定包含 JSON 文件的目录（默认：docs）
- `--md-output`: 指定 Markdown 输出目录（默认：outputs/md）

### 3. 转换单个文件

使用 `json_to_markdown.py` 直接转换单个文件：

```bash
python src/json_to_markdown.py input.json output.md
```

## 支持的格式

当前支持的 JSON 块类型：
- ✅ 文本块（text）
  - 标题（heading: 1-6）
  - 引用（quoted）
  - 文本样式：加粗、斜体、删除线、行内代码
- ✅ 表格块（table）
  - 自动生成 Markdown 表格
  - 保留表头和数据行

## 示例

### 输入 JSON 结构：
```json
{
  "blocks": [
    {
      "type": "text",
      "text": [{"insert": "项目周报", "attributes": {"style-bold": true}}],
      "heading": 1
    },
    {
      "type": "table",
      "rows": 3,
      "cols": 2,
      "children": ["cell1", "cell2", "cell3", "cell4"]
    }
  ]
}
```

### 输出 Markdown：
```markdown
# **项目周报**

| 表头1 | 表头2 |
| --- | --- |
| 单元格1 | 单元格2 |
| 单元格3 | 单元格4 |
```

## 注意事项

1. 所有转换后的文件会直接放在输出目录下，不保持原有目录结构
2. 文件名格式为 `document_0001.md`、`document_0002.md` 等，按发现顺序编号
3. 每个 `latest.json` 会被转换为一个独立的 `.md` 文件
4. 如果输出文件已存在，会被覆盖
5. 转换失败的文件会在日志中记录

## 测试

运行测试脚本：

```bash
python test_conversion.py
```

这会转换一个示例文件并显示前 20 行预览。
