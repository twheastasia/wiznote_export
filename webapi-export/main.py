#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为知笔记团队备份工具
主程序入口
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, List

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from auth import WizNoteAuth
from api_client import WizNoteAPIClient
from storage import LocalStorage
from downloader import NoteDownloader
from converter import HTMLToMarkdownConverter
from json_to_markdown import JsonToMarkdownConverter


def setup_logging(config: dict):
    """设置日志"""
    log_level = getattr(logging, config['logging']['level'].upper())
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # 创建日志目录
    log_file = config['logging']['log_file']
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    
    # 配置日志
    handlers = []
    
    # 文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format))
    handlers.append(file_handler)
    
    # 控制台处理器
    if config['logging']['console_output']:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(console_handler)
    
    # 配置根日志器
    logging.basicConfig(
        level=log_level,
        handlers=handlers
    )


def load_config(config_file: str) -> dict:
    """加载配置文件"""
    with open(config_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(config: dict, config_file: str):
    """保存配置文件"""
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


def check_credentials(config: dict) -> bool:
    """检查凭据是否已配置"""
    username = config['auth']['username']
    password = config['auth']['password']
    
    if not username or not password:
        print("错误：未配置用户名或密码！")
        print("请编辑 config/config.json 文件，填写您的为知笔记账号信息。")
        return False
    
    return True


def interactive_login(config: dict) -> bool:
    """交互式登录"""
    print("请输入您的为知笔记账号信息：")
    username = input("用户名/邮箱: ").strip()
    password = input("密码: ").strip()
    
    if not username or not password:
        print("用户名和密码不能为空！")
        return False
    
    config['auth']['username'] = username
    config['auth']['password'] = password
    
    # 询问是否保存
    save = input("是否保存账号信息到配置文件？(y/n): ").strip().lower()
    if save == 'y':
        save_config(config, args.config)
        print("账号信息已保存。")
    
    return True


def list_folders(api_client: WizNoteAPIClient):
    """列出所有文件夹"""
    print("\n您的文件夹列表：")
    print("-" * 50)
    
    folders = api_client.get_all_folders()
    if not folders:
        print("未找到任何文件夹。")
        return
    
    # 按层级显示文件夹
    for folder in sorted(folders):
        level = folder.count('/') - 2  # 计算层级
        indent = "  " * level
        folder_name = folder.strip('/').split('/')[-1] if folder != '/' else 'Root'
        print(f"{indent}{folder_name} ({folder})")


def list_knowledge_bases(auth: WizNoteAuth):
    """列出所有知识库"""
    print("\n您的知识库列表：")
    print("-" * 50)
    
    kb_list = auth.get_kb_list()
    if not kb_list:
        print("未找到任何知识库。")
        return
    
    for i, kb in enumerate(kb_list, 1):
        print(f"{i}. {kb['name']} ({kb['type']})")
        print(f"   GUID: {kb['kbGuid']}")
        print(f"   服务器: {kb['kbServer']}")
        if kb.get('bizName'):
            print(f"   所属团队: {kb['bizName']}")
        print()


def backup_specific_folders(downloader: NoteDownloader, folders: List[str]):
    """备份指定的文件夹"""
    print(f"\n开始备份指定的文件夹: {', '.join(folders)}")
    downloader.download_all(folders_filter=folders)


def backup_all(downloader: NoteDownloader):
    """备份所有笔记"""
    print("\n开始备份所有笔记...")
    downloader.download_all()


def incremental_backup(downloader: NoteDownloader):
    """增量备份"""
    print("\n执行增量备份...")
    print("只下载新增或修改的笔记。")
    downloader.download_all()


def convert_all_json_to_markdown(docs_dir: str = 'docs', output_dir: str = 'outputs/md'):
    """
    批量转换所有 latest.json 文件为 Markdown 格式
    
    Args:
        docs_dir: docs 目录路径
        output_dir: 输出目录路径
    """
    logger = logging.getLogger(__name__)
    docs_path = Path(docs_dir)
    output_path = Path(output_dir)
    
    if not docs_path.exists():
        logger.error(f"docs 目录不存在: {docs_dir}")
        print(f"错误: docs 目录不存在: {docs_dir}")
        return
    
    # 查找所有 latest.json 文件
    json_files = list(docs_path.rglob('latest.json'))
    
    if not json_files:
        logger.warning(f"在 {docs_dir} 目录下未找到任何 latest.json 文件")
        print(f"警告: 在 {docs_dir} 目录下未找到任何 latest.json 文件")
        return
    
    print(f"\n找到 {len(json_files)} 个 latest.json 文件")
    print(f"输出目录: {output_path}")
    print("开始转换...\n")
    
    # 创建转换器
    converter = JsonToMarkdownConverter()
    
    # 统计
    success_count = 0
    fail_count = 0
    
    # 确保输出目录存在
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 遍历转换
    for i, json_file in enumerate(json_files, 1):
        try:
            # 构建相对路径用于显示
            relative_path = json_file.relative_to(docs_path)
            
            # 使用父目录名作为文件名（更有意义）
            # 例如: docs/xxx/yyy/zzz/latest.json -> zzz.md
            parent_name = json_file.parent.name
            
            # 如果父目录名是 GUID 格式，尝试使用上级目录名
            if len(parent_name) > 20 and '-' in parent_name:
                # 尝试找一个更有意义的名字，或者使用序号
                output_filename = f"document_{i:04d}.md"
            else:
                output_filename = f"{parent_name}.md"
            
            # 所有文件直接放在输出目录下
            output_file = output_path / output_filename
            
            # 如果文件名冲突，添加序号
            if output_file.exists():
                output_filename = f"document_{i:04d}.md"
                output_file = output_path / output_filename
            
            # 转换
            print(f"[{i}/{len(json_files)}] 转换: {relative_path}")
            
            if converter.convert_file(str(json_file), str(output_file)):
                success_count += 1
                print(f"  ✓ 成功: {output_filename}")
            else:
                fail_count += 1
                print(f"  ✗ 失败: {json_file}")
                
        except Exception as e:
            fail_count += 1
            logger.error(f"转换失败 {json_file}: {str(e)}")
            print(f"  ✗ 失败: {json_file} - {str(e)}")
    
    # 输出统计
    print("\n转换完成！")
    print(f"成功: {success_count} 个")
    print(f"失败: {fail_count} 个")
    print(f"输出目录: {output_path.absolute()}")


def main():
    parser = argparse.ArgumentParser(
        description='为知笔记备份工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 首次运行，交互式配置
  python main.py
  
  # 备份所有笔记
  python main.py --all
  
  # 备份指定文件夹
  python main.py --folders "/My Notes/" "/My Notes/Work/"
  
  # 列出所有文件夹
  python main.py --list
  
  # 增量备份
  python main.py --incremental
  
  # 使用自定义配置文件
  python main.py --config my_config.json --all
        """
    )
    
    parser.add_argument(
        '--config', 
        default='config/config.json',
        help='配置文件路径 (默认: config/config.json)'
    )
    
    parser.add_argument(
        '--all',
        action='store_true',
        help='备份所有笔记'
    )
    
    parser.add_argument(
        '--folders',
        nargs='+',
        help='备份指定的文件夹（文件夹路径）'
    )
    
    parser.add_argument(
        '--list',
        action='store_true',
        help='列出所有文件夹'
    )
    
    parser.add_argument(
        '--list-kb',
        action='store_true',
        help='列出所有知识库（个人+团队）'
    )
    
    parser.add_argument(
        '--kb',
        help='指定知识库GUID（如果不指定，使用个人知识库）'
    )
    
    parser.add_argument(
        '--incremental',
        action='store_true',
        help='增量备份（只下载新增或修改的笔记）'
    )
    
    parser.add_argument(
        '--no-convert',
        action='store_true',
        help='不转换为Markdown，保留原始HTML格式'
    )
    
    parser.add_argument(
        '--output',
        help='指定输出目录'
    )
    
    parser.add_argument(
        '--login',
        action='store_true',
        help='重新登录'
    )
    
    parser.add_argument(
        '--convert-json',
        action='store_true',
        help='将所有 latest.json 文件转换为 Markdown 格式'
    )
    
    parser.add_argument(
        '--json-dir',
        default='docs',
        help='JSON 文件所在的 docs 目录 (默认: docs)'
    )
    
    parser.add_argument(
        '--md-output',
        default='outputs/md',
        help='Markdown 输出目录 (默认: outputs/md)'
    )
    
    args = parser.parse_args()
    
    # 加载配置
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print(f"配置文件不存在: {args.config}")
        print("正在创建默认配置文件...")
        
        # 创建默认配置
        default_config_path = os.path.join(
            os.path.dirname(__file__), 
            'config', 
            'config.json'
        )
        os.makedirs(os.path.dirname(args.config), exist_ok=True)
        
        # 复制默认配置
        import shutil
        shutil.copy(default_config_path, args.config)
        
        config = load_config(args.config)
        print(f"已创建配置文件: {args.config}")
        print("请编辑配置文件填写您的账号信息后重新运行。")
        return
    
    # 设置日志
    setup_logging(config)
    logger = logging.getLogger(__name__)
    
    # 如果是 JSON 转换模式
    if args.convert_json:
        convert_all_json_to_markdown(args.json_dir, args.md_output)
        return
    
    # 覆盖配置
    if args.output:
        config['download']['output_dir'] = args.output
    
    if args.no_convert:
        config['format']['convert_to_markdown'] = False
    
    if args.incremental:
        config['sync']['incremental'] = True
    
    # 检查凭据
    if not args.login and not check_credentials(config):
        if not interactive_login(config):
            return
    
    # 创建认证管理器
    auth = WizNoteAuth(config)
    
    # 登录
    print("\n正在登录为知笔记...")
    if not auth.login():
        print("登录失败！请检查用户名和密码。")
        return
    
    print(f"登录成功！用户: {auth.username}")
    
    # 列出知识库
    if args.list_kb:
        list_knowledge_bases(auth)
        return
    
    # 切换知识库
    current_kb_name = '个人笔记'
    if args.kb:
        kb_list = auth.get_kb_list()
        kb_found = False
        for kb in kb_list:
            if kb['kbGuid'] == args.kb:
                if auth.switch_kb(args.kb):
                    current_kb_name = kb['name']
                    kb_found = True
                    print(f"\n已切换到知识库: {current_kb_name}")
                    break
        
        if not kb_found:
            print(f"\n未找到知识库: {args.kb}")
            print("使用 --list-kb 参数查看所有可用的知识库")
            return
    else:
        print(f"\n使用知识库: {current_kb_name}")
    
    # 创建API客户端
    api_client = WizNoteAPIClient(auth, config)
    
    # 列出文件夹
    if args.list:
        list_folders(api_client)
        return
    
    # 创建存储管理器
    storage = LocalStorage(
        config['download']['output_dir'],
        config['format']['preserve_structure']
    )
    
    # 创建转换器
    converter = None
    if config['format']['convert_to_markdown']:
        converter = HTMLToMarkdownConverter(config)
    
    # 创建下载器
    downloader = NoteDownloader(api_client, storage, converter)
    downloader.set_kb_name(current_kb_name)  # 设置知识库名称
    
    # 执行备份
    if args.folders:
        backup_specific_folders(downloader, args.folders)
    elif args.all or args.incremental:
        backup_all(downloader)
    else:
        # 交互式选择
        print("\n请选择操作：")
        print("1. 备份所有笔记")
        print("2. 备份指定文件夹")
        print("3. 列出所有文件夹")
        print("4. 增量备份")
        print("0. 退出")
        
        choice = input("\n请输入选项 (0-4): ").strip()
        
        if choice == '1':
            backup_all(downloader)
        elif choice == '2':
            folders = api_client.get_all_folders()
            if not folders:
                print("未找到任何文件夹。")
                return
            
            print("\n可用的文件夹：")
            for i, folder in enumerate(folders[:20], 1):  # 只显示前20个
                print(f"{i}. {folder}")
            
            if len(folders) > 20:
                print(f"... 还有 {len(folders) - 20} 个文件夹")
            
            selected = input("\n请输入要备份的文件夹编号（多个用空格分隔）: ").strip()
            if selected:
                indices = [int(x) - 1 for x in selected.split()]
                selected_folders = [folders[i] for i in indices if 0 <= i < len(folders)]
                if selected_folders:
                    backup_specific_folders(downloader, selected_folders)
                else:
                    print("未选择有效的文件夹。")
        elif choice == '3':
            list_folders(api_client)
        elif choice == '4':
            config['sync']['incremental'] = True
            incremental_backup(downloader)
        elif choice == '0':
            print("退出程序。")
            return
        else:
            print("无效的选项。")
    
    # 清理
    logger.info("备份任务完成。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n操作已取消。")
    except Exception as e:
        print(f"\n发生错误: {e}")
        import traceback
        traceback.print_exc()