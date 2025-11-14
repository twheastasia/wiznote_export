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


def sanitize_filename(name: str, fallback: str = "untitled", max_length: int = 80) -> str:
    """清理文件名中的非法字符"""
    if not name:
        name = fallback
    invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for char in invalid_chars:
        name = name.replace(char, '_')
    name = name.strip() or fallback
    return name[:max_length]


# API选择逻辑已移除,现在优先使用WebSocket API,失败时自动降级到REST API


def list_folders(api_client: WizNoteAPIClient):
    """
    列出所有文件夹
    
    Args:
        api_client: API客户端
    """
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
            
            # 转换为 Markdown 内容
            print(f"[{i}/{len(json_files)}] 转换: {relative_path}")
            
            markdown_content = converter.convert_to_content(str(json_file))
            
            if markdown_content is None:
                fail_count += 1
                print(f"  ✗ 失败: 无法读取或转换 {json_file}")
                continue
            
            # 使用 Markdown 内容的前15个字符作为文件名
            base_filename = converter.get_filename_from_content(markdown_content, max_length=15)
            output_filename = f"{base_filename}.md"
            
            # 所有文件直接放在输出目录下
            output_file = output_path / output_filename
            
            # 如果文件名冲突，添加序号
            counter = 1
            while output_file.exists():
                output_filename = f"{base_filename}_{counter}.md"
                output_file = output_path / output_filename
                counter += 1
            
            # 写入文件
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(markdown_content)
                
                success_count += 1
                print(f"  ✓ 成功: {output_filename}")
                logger.info(f"成功转换: {json_file} -> {output_file}")
                
            except Exception as write_error:
                fail_count += 1
                logger.error(f"写入文件失败 {output_file}: {str(write_error)}")
                print(f"  ✗ 失败: 无法写入 {output_filename}")
                
        except Exception as e:
            fail_count += 1
            logger.error(f"转换失败 {json_file}: {str(e)}")
            print(f"  ✗ 失败: {json_file} - {str(e)}")
    
    # 输出统计
    print("\n转换完成！")
    print(f"成功: {success_count} 个")
    print(f"失败: {fail_count} 个")
    print(f"输出目录: {output_path.absolute()}")


def export_notes_to_markdown(
    api_client: WizNoteAPIClient,
    output_dir: str,
    folders_filter: Optional[List[str]] = None,
):
    """导出笔记为 Markdown
    
    优先使用 WebSocket API(新API)获取笔记,如果失败则自动降级到 REST API(旧API)
    
    Args:
        api_client: API客户端
        output_dir: 输出目录
        folders_filter: 可选的文件夹过滤列表
    """
    # 检查WebSocket配置
    ws_config = api_client.config.get('websocket', {})
    websocket_available = ws_config.get('enabled', False)
    if not websocket_available:
        print("⚠ WebSocket API未启用,将仅使用 REST API")
        print("提示: 在 config.json 中设置 websocket.enabled=true 可启用 WebSocket API")

    converter = JsonToMarkdownConverter()
    base_path = Path(output_dir)
    base_path.mkdir(parents=True, exist_ok=True)

    folders = api_client.get_all_folders()
    if not folders:
        print("未找到任何文件夹。")
        return

    def normalize_folder(folder_entry):
        if isinstance(folder_entry, str):
            return {
                'path': folder_entry,
                'name': folder_entry.strip('/').split('/')[-1] or 'Root'
            }
        return {
            'path': folder_entry.get('path') or folder_entry.get('name') or '/',
            'name': folder_entry.get('name') or folder_entry.get('path', 'Root')
        }

    normalized_folders = [normalize_folder(item) for item in folders]

    if folders_filter:
        filter_set = set(folders_filter)
        normalized_folders = [folder for folder in normalized_folders if folder['path'] in filter_set]
        if not normalized_folders:
            print("未匹配到指定的文件夹，使用全部文件夹继续。")
            normalized_folders = [normalize_folder(item) for item in folders]

    total_notes = 0
    success_notes = 0
    failed_notes = 0
    websocket_success = 0
    rest_fallback_success = 0
    conversion_failures = []  # 记录转换失败的笔记

    print("\n开始导出笔记 (优先WebSocket API, 失败时自动降级REST API)...\n")

    # 创建raw_json保存目录(用于保存WebSocket返回的原始数据)
    raw_json_base = Path(output_dir + "_raw_json")
    raw_json_base.mkdir(parents=True, exist_ok=True)
    print(f"WebSocket原始JSON保存到: {raw_json_base.absolute()}\n")

    for folder in sorted(normalized_folders, key=lambda f: f['path']):
        folder_path = folder['path']
        relative = folder_path.strip('/')
        target_dir = base_path if not relative else base_path / Path(*[part for part in relative.split('/') if part])
        target_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n处理文件夹: {folder_path}")

        for note in api_client.get_all_notes_in_folder(folder_path):
            total_notes += 1
            doc_guid = note.get('docGuid')
            title = note.get('title') or doc_guid or 'untitled'

            print(f"  -> 获取笔记 {title} ({doc_guid})")
            
            markdown = None
            used_api = None
            
            # 策略: 优先尝试WebSocket API
            if websocket_available:
                try:
                    detail = api_client.get_note_detail_via_websocket(doc_guid)
                    if detail:
                        # 保存原始JSON
                        raw_json_folder = raw_json_base / Path(*[part for part in relative.split('/') if part]) if relative else raw_json_base
                        raw_json_folder.mkdir(parents=True, exist_ok=True)
                        raw_json_file = raw_json_folder / (sanitize_filename(title, fallback=doc_guid or 'untitled') + '.json')
                        try:
                            import json
                            with open(raw_json_file, 'w', encoding='utf-8') as f:
                                json.dump(detail, f, ensure_ascii=False, indent=2)
                        except Exception as json_exc:
                            print(f"     ⚠ 保存原始JSON失败: {json_exc}")

                        # 提取并转换数据
                        note_data = detail.get('data') or detail
                        if isinstance(note_data, dict) and 'blocks' not in note_data and 'data' in note_data:
                            note_data = note_data['data']

                        try:
                            markdown = converter.convert(note_data)
                            if markdown and markdown.strip():
                                used_api = 'WebSocket'
                                websocket_success += 1
                                print("     ✓ WebSocket API成功")
                        except Exception as conv_exc:
                            print(f"     ⚠ WebSocket转换失败: {conv_exc}, 尝试REST API...")
                except Exception as ws_exc:
                    print(f"     ⚠ WebSocket获取失败: {ws_exc}, 尝试REST API...")
            
            # 降级: 如果WebSocket失败,尝试REST API
            if not markdown or not markdown.strip():
                try:
                    note_content = api_client.download_note(doc_guid)
                    if note_content:
                        # 如果返回的是HTML,直接使用或转换
                        if isinstance(note_content, dict) and 'html' in note_content:
                            html_content = note_content['html']
                        else:
                            html_content = str(note_content)
                        
                        try:
                            html_converter = HTMLToMarkdownConverter(api_client.config)
                            markdown = html_converter.convert(html_content)
                            if markdown and markdown.strip():
                                used_api = 'REST'
                                rest_fallback_success += 1
                                print("     ✓ REST API降级成功")
                        except Exception as conv_exc:
                            print(f"     ✗ REST API转换失败: {conv_exc}")
                except Exception as rest_exc:
                    print(f"     ✗ REST API获取失败: {rest_exc}")
            
            # 检查最终结果
            if not markdown or not markdown.strip():
                failed_notes += 1
                conversion_failures.append({
                    'doc_guid': doc_guid,
                    'title': title,
                    'folder': folder_path,
                    'error': '所有API均失败或转换结果为空',
                    'timestamp': datetime.now().isoformat()
                })
                print("     ✗ 所有API均失败")
                continue
            
            # 写入Markdown文件
            filename = sanitize_filename(title, fallback=doc_guid or 'untitled') + '.md'
            output_file = target_dir / filename
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(markdown)
                success_notes += 1
                print(f"     ✓ 已导出: {output_file.name} (via {used_api})")
            except Exception as exc:
                failed_notes += 1
                conversion_failures.append({
                    'doc_guid': doc_guid,
                    'title': title,
                    'folder': folder_path,
                    'error': f'写入Markdown文件失败: {str(exc)}',
                    'timestamp': datetime.now().isoformat()
                })
                print(f"     ✗ 写入文件失败: {exc}")

    # 保存转换失败记录
    if conversion_failures:
        failure_log_path = Path(output_dir) / 'conversion_failures.json'
        try:
            import json
            with open(failure_log_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'total_failures': len(conversion_failures),
                    'strategy': 'WebSocket优先, REST降级',
                    'export_time': datetime.now().isoformat(),
                    'failures': conversion_failures
                }, f, ensure_ascii=False, indent=2)
            print(f"\n⚠ 转换失败记录已保存到: {failure_log_path.absolute()}")
        except Exception as log_exc:
            print(f"\n⚠ 保存失败记录时出错: {log_exc}")

    print("\n导出完成！")
    print(f"总笔记: {total_notes}")
    print(f"成功: {success_notes} (WebSocket: {websocket_success}, REST降级: {rest_fallback_success})")
    print(f"失败: {failed_notes}")
    print(f"输出目录: {Path(output_dir).absolute()}")
    print(f"原始JSON目录: {raw_json_base.absolute()}")


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
  
  # 导出笔记为Markdown(优先WebSocket,失败时自动降级REST)
  python main.py --export-md
  
  # 转换JSON为Markdown
  python main.py --convert-json
  
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

    parser.add_argument(
        '--export-md',
        action='store_true',
        help='导出笔记为 Markdown 格式'
    )

    parser.add_argument(
        '--export-output',
        default='outputs/markdown',
        help='Markdown 导出目录 (默认: outputs/markdown)'
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
    
    if args.export_md:
        export_notes_to_markdown(
            api_client,
            args.export_output,
        )
        return

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
        export_notes_to_markdown(
            api_client,
            config['download']['output_dir'],
            folders_filter=args.folders,
        )
        return
    if args.all:
        export_notes_to_markdown(
            api_client,
            config['download']['output_dir'],
        )
        return
    if args.incremental:
        print("增量备份功能已弃用，请使用 --all 或 --folders")
        return
    else:
        # 交互式选择
        print("\n请选择操作：")
        print("1. 备份所有笔记")
        print("2. 备份指定文件夹")
        print("3. 列出所有文件夹")
        print("0. 退出")
        
        choice = input("\n请输入选项 (0-3): ").strip()
        
        if choice == '1':
            export_notes_to_markdown(
                api_client,
                config['download']['output_dir'],
            )
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
                    export_notes_to_markdown(
                        api_client,
                        config['download']['output_dir'],
                        folders_filter=selected_folders,
                    )
                else:
                    print("未选择有效的文件夹。")
        elif choice == '3':
            list_folders(api_client)
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