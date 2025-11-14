#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为知笔记 JSON 格式转 Markdown 工具
将为知笔记导出的 JSON 格式文档转换为 Markdown 格式
"""

import json
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class JsonToMarkdownConverter:
    """JSON 到 Markdown 的转换器"""
    
    def __init__(self):
        self.indent_level = 0
        self.in_table = False
    
    def convert_file(self, json_path: str, output_path: str) -> bool:
        """
        转换 JSON 文件为 Markdown 文件
        
        Args:
            json_path: 输入的 JSON 文件路径
            output_path: 输出的 Markdown 文件路径
            
        Returns:
            bool: 转换是否成功
        """
        try:
            # 读取 JSON 文件
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 转换为 Markdown
            markdown_content = self.convert(data)
            
            # 确保输出目录存在
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # 写入 Markdown 文件
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            
            logger.info(f"成功转换: {json_path} -> {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"转换失败 {json_path}: {str(e)}")
            return False
    
    def convert_to_content(self, json_path: str) -> Optional[str]:
        """
        转换 JSON 文件为 Markdown 内容（不写入文件）
        
        Args:
            json_path: 输入的 JSON 文件路径
            
        Returns:
            str: Markdown 内容，失败时返回 None
        """
        try:
            # 读取 JSON 文件
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 转换为 Markdown
            markdown_content = self.convert(data)
            return markdown_content
            
        except Exception as e:
            logger.error(f"转换失败 {json_path}: {str(e)}")
            return None
    
    @staticmethod
    def get_filename_from_content(content: str, max_length: int = 15) -> str:
        """
        从 Markdown 内容中提取文件名（使用前N个字符）
        
        Args:
            content: Markdown 内容
            max_length: 最大字符数，默认15
            
        Returns:
            str: 文件名（不含扩展名）
        """
        if not content:
            return "untitled"
        
        # 移除前导空白
        content = content.strip()
        
        # 如果以标题开头，去掉 # 符号
        if content.startswith('#'):
            content = content.lstrip('#').strip()
        
        # 获取第一行
        first_line = content.split('\n')[0].strip()
        
        # 如果第一行为空，尝试获取第二行
        if not first_line:
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            first_line = lines[0] if lines else "untitled"
        
        # 截取前 max_length 个字符
        filename = first_line[:max_length]
        
        # 移除文件名中的非法字符
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '\n', '\r', '\t']
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # 去掉前后空格
        filename = filename.strip()
        
        # 如果结果为空，使用默认名称
        if not filename:
            filename = "untitled"
        
        return filename
    
    def convert(self, data: Dict[str, Any]) -> str:
        """
        将 JSON 数据转换为 Markdown 文本
        
        Args:
            data: 为知笔记的 JSON 数据结构
            
        Returns:
            str: Markdown 格式的文本
        """
        if 'blocks' not in data:
            logger.warning("JSON 数据中没有找到 'blocks' 字段")
            return ""
        
        blocks = data['blocks']
        markdown_lines = []
        
        for block in blocks:
            block_md = self._convert_block(block, data)
            if block_md:
                markdown_lines.append(block_md)
        
        return '\n\n'.join(markdown_lines)
    
    def _convert_block(self, block: Dict[str, Any], root_data: Dict[str, Any]) -> str:
        """
        转换单个 block
        
        Args:
            block: block 数据
            root_data: 根数据，用于查找嵌套内容
            
        Returns:
            str: block 对应的 Markdown 文本
        """
        block_type = block.get('type', 'text')
        
        if block_type == 'text':
            return self._convert_text_block(block)
        elif block_type == 'table':
            return self._convert_table_block(block, root_data)
        else:
            logger.warning(f"未知的 block 类型: {block_type}")
            return self._convert_text_block(block)
    
    def _convert_text_block(self, block: Dict[str, Any]) -> str:
        """转换文本类型的 block"""
        text_content = block.get('text', [])
        
        # 处理空文本
        if not text_content:
            return ""
        
        # 提取文本和样式
        result_parts = []
        for text_item in text_content:
            text = text_item.get('insert', '')
            attributes = text_item.get('attributes', {})
            
            # 应用样式
            styled_text = self._apply_text_styles(text, attributes)
            result_parts.append(styled_text)
        
        result = ''.join(result_parts).strip()
        
        # 处理标题
        if block.get('heading'):
            heading_level = block.get('heading', 1)
            result = f"{'#' * heading_level} {result}"
        
        # 处理引用
        elif block.get('quoted'):
            result = f"> {result}"
        
        return result
    
    def _apply_text_styles(self, text: str, attributes: Dict[str, Any]) -> str:
        """应用文本样式"""
        if not attributes:
            return text
        
        # 加粗
        if attributes.get('style-bold'):
            text = f"**{text}**"
        
        # 斜体
        if attributes.get('style-italic'):
            text = f"*{text}*"
        
        # 删除线
        if attributes.get('style-strike'):
            text = f"~~{text}~~"
        
        # 行内代码
        if attributes.get('style-code'):
            text = f"`{text}`"
        
        # 颜色（作为注释保留）
        if attributes.get('style-color-6'):
            # Markdown 不原生支持颜色，可以作为注释或忽略
            pass
        
        return text
    
    def _convert_table_block(self, block: Dict[str, Any], root_data: Dict[str, Any]) -> str:
        """转换表格类型的 block"""
        rows = block.get('rows', 0)
        cols = block.get('cols', 0)
        children = block.get('children', [])
        
        if not rows or not cols or not children:
            return ""
        
        # 构建表格数据
        table_data = []
        for i in range(rows):
            row_data = []
            for j in range(cols):
                cell_index = i * cols + j
                if cell_index < len(children):
                    cell_id = children[cell_index]
                    cell_content = self._get_cell_content(cell_id, root_data)
                    row_data.append(cell_content)
                else:
                    row_data.append("")
            table_data.append(row_data)
        
        # 转换为 Markdown 表格
        return self._format_markdown_table(table_data, block.get('hasRowTitle', False))
    
    def _get_cell_content(self, cell_id: str, root_data: Dict[str, Any]) -> str:
        """获取表格单元格内容"""
        if cell_id not in root_data:
            return ""
        
        cell_blocks = root_data[cell_id]
        if not isinstance(cell_blocks, list):
            return ""
        
        # 合并单元格中的所有文本
        cell_texts = []
        for cell_block in cell_blocks:
            if 'text' in cell_block:
                text_parts = []
                for text_item in cell_block['text']:
                    text = text_item.get('insert', '')
                    attributes = text_item.get('attributes', {})
                    styled_text = self._apply_text_styles(text, attributes)
                    text_parts.append(styled_text)
                cell_texts.append(''.join(text_parts))
        
        return ' '.join(cell_texts).strip()
    
    def _format_markdown_table(self, table_data: List[List[str]], has_header: bool = False) -> str:
        """格式化为 Markdown 表格"""
        if not table_data:
            return ""
        
        lines = []
        
        # 处理表头（第一行）
        if table_data:
            header = table_data[0]
            lines.append('| ' + ' | '.join(header) + ' |')
            
            # 分隔线
            separator = '| ' + ' | '.join(['---'] * len(header)) + ' |'
            lines.append(separator)
        
        # 处理数据行
        for row in table_data[1:]:
            lines.append('| ' + ' | '.join(row) + ' |')
        
        return '\n'.join(lines)


def convert_json_to_markdown(json_path: str, output_path: str) -> bool:
    """
    便捷函数：转换单个 JSON 文件为 Markdown
    
    Args:
        json_path: 输入的 JSON 文件路径
        output_path: 输出的 Markdown 文件路径
        
    Returns:
        bool: 转换是否成功
    """
    converter = JsonToMarkdownConverter()
    return converter.convert_file(json_path, output_path)


if __name__ == '__main__':
    # 测试代码
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) < 2:
        print("用法: python json_to_markdown.py <json_file> [output_file]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace('.json', '.md')
    
    success = convert_json_to_markdown(input_file, output_file)
    sys.exit(0 if success else 1)
