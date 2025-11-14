#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为知笔记API客户端
基于官方API文档实现
"""

import os
import json
import time
import ssl
import base64
import requests
from typing import Dict, List, Optional, Generator, Any
from functools import wraps
import logging
from tenacity import retry, stop_after_attempt, wait_exponential
import websocket

logger = logging.getLogger(__name__)


def rate_limit(calls_per_second: int = 10):
    """限流装饰器"""
    def decorator(func):
        last_called = [0.0]
        min_interval = 1.0 / calls_per_second
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            left_to_wait = min_interval - elapsed
            if left_to_wait > 0:
                time.sleep(left_to_wait)
            result = func(*args, **kwargs)
            last_called[0] = time.time()
            return result
        return wrapper
    return decorator


class WizNoteAPIClient:
    """为知笔记API客户端"""
    
    def __init__(self, auth, config: Dict):
        self.auth = auth
        self.config = config
        self.timeout = config['api']['timeout']
        self.rate_limit_per_second = config['api']['rate_limit_per_second']
        
        # 从认证信息获取知识库信息
        kb_info = auth.get_kb_info()
        self.kb_guid = kb_info['kb_guid']
        self.kb_server = kb_info['kb_server']
        
        # 应用限流到所有API方法
        self._apply_rate_limit()
    
    def _apply_rate_limit(self):
        """应用限流到所有API方法"""
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if callable(attr) and not attr_name.startswith('_') and attr_name != 'request':
                setattr(self, attr_name, rate_limit(self.rate_limit_per_second)(attr))
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    def request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """统一的请求方法，带重试机制"""
        # 构建完整URL
        if endpoint.startswith('/'):
            url = f"{self.kb_server}{endpoint}"
        else:
            url = endpoint
            
        headers = self.auth.get_headers()
        
        if 'headers' in kwargs:
            headers.update(kwargs['headers'])
            kwargs.pop('headers')
        
        logger.debug(f"{method} {url}")
        
        response = requests.request(
            method,
            url,
            headers=headers,
            timeout=self.timeout,
            **kwargs
        )
        
        # 检查响应
        if response.status_code == 401:
            # Token过期，刷新后重试
            logger.info("Token过期，刷新中...")
            self.auth.refresh_token()
            headers = self.auth.get_headers()
            response = requests.request(
                method,
                url,
                headers=headers,
                timeout=self.timeout,
                **kwargs
            )
        
        response.raise_for_status()
        return response
    
    def get_all_folders(self) -> List[Dict]:
        """获取所有文件夹
        
        官方API: GET /ks/category/all/:kbGuid
        """
        response = self.request('GET', f'/ks/category/all/{self.kb_guid}')
        
        if response.status_code == 200:
            try:
                result = response.json()
                logger.info(f"文件夹响应: {result}")
                if isinstance(result, list):
                    logger.info(f"获取到 {len(result)} 个文件夹")
                    return result
                elif isinstance(result, dict) and result.get('returnCode') == 200:
                    folders = result.get('result', [])
                    logger.info(f"获取到 {len(folders)} 个文件夹")
                    return folders
            except Exception as e:
                logger.error(f"解析文件夹响应失败: {e}")
        
        return []
    
    def get_notes_in_folder(self, folder_path: str = "/", 
                           start: int = 0, count: int = 100,
                           order_by: str = "modified",
                           ascending: str = "desc") -> Dict:
        """获取文件夹中的笔记列表
        
        官方API: GET /ks/note/list/category/:kbGuid
        参数:
        - category: 文件夹路径
        - start: 分页起始
        - count: 每页数量
        - orderBy: 排序字段 (title/created/modified)
        - ascending: 排序方向 (asc/desc)
        - withAbstract: 是否包含摘要
        """
        params = {
            "category": folder_path,
            "start": start,
            "count": count,
            "orderBy": order_by,
            "ascending": ascending,
            "withAbstract": "true"
        }
        
        response = self.request('GET', f'/ks/note/list/category/{self.kb_guid}', params=params)
        
        if response.status_code == 200:
            try:
                result = response.json()
                # 返回格式可能是直接的数组或包含returnCode的对象
                if isinstance(result, list):
                    return {
                        'notes': result,
                        'total': len(result)
                    }
                elif isinstance(result, dict):
                    if result.get('returnCode') == 200:
                        notes = result.get('result', [])
                        return {
                            'notes': notes,
                            'total': result.get('total', len(notes))
                        }
                    else:
                        logger.error(f"获取笔记列表失败: {result.get('returnMessage')}")
            except Exception as e:
                logger.error(f"解析笔记列表响应失败: {e}")
        
        return {'notes': [], 'total': 0}
    
    def get_all_notes_in_folder(self, folder_path: str = "/") -> Generator[Dict, None, None]:
        """获取文件夹中的所有笔记（自动分页）"""
        start = 0
        count = 100
        
        while True:
            result = self.get_notes_in_folder(folder_path, start, count)
            notes = result['notes']
            
            if not notes:
                break
            
            for note in notes:
                yield note
            
            start += len(notes)
            
            # 如果返回的笔记数少于请求数，说明已经到最后一页
            if len(notes) < count:
                break
    
    def get_note_info(self, doc_guid: str) -> Optional[Dict]:
        """获取笔记信息
        
        官方API: GET /ks/note/view/:kbGuid/:docGuid/
        """
        try:
            response = self.request('GET', f'/ks/note/view/{self.kb_guid}/{doc_guid}/')
            
            if response.status_code == 200:
                # 检查响应内容
                content_type = response.headers.get('content-type', '')
                
                if 'application/json' in content_type:
                    try:
                        result = response.json()
                        if isinstance(result, dict):
                            if result.get('returnCode') == 200:
                                return result.get('result')
                            else:
                                logger.error(f"获取笔记信息失败: {result.get('returnMessage')}")
                        else:
                            # 可能直接返回笔记信息
                            return result
                    except Exception as e:
                        logger.error(f"解析笔记信息响应失败: {e}")
                else:
                    # 可能是HTML内容
                    logger.debug(f"获取到非JSON响应，内容类型: {content_type}")
                    return None
        except Exception as e:
            logger.error(f"获取笔记信息异常: {e}")
        
        return None
    
    def download_note(self, doc_guid: str, download_info: bool = True, 
                     download_data: bool = True) -> Optional[Dict]:
        """下载笔记内容
        
        官方API: GET /ks/note/download/:kbGuid/:docGuid
        参数:
        - downloadInfo: 是否下载笔记信息
        - downloadData: 是否下载笔记数据
        """
        params = {
            "downloadInfo": 1 if download_info else 0,
            "downloadData": 1 if download_data else 0
        }
        
        response = self.request('GET', f'/ks/note/download/{self.kb_guid}/{doc_guid}', params=params)
        
        if response.status_code == 200:
            # 检查响应类型
            content_type = response.headers.get('content-type', '')
            
            if 'application/json' in content_type:
                # JSON响应，包含笔记信息和内容
                try:
                    result = response.json()
                    if isinstance(result, dict) and result.get('returnCode') == 200:
                        # 返回笔记数据，兼容不同结构
                        if 'result' in result:
                            return result.get('result')
                        else:
                            return result
                    return result
                except Exception as e:
                    logger.error(f"解析笔记下载响应失败: {e}")
            else:
                # 可能是HTML内容
                return {
                    'html': response.text,
                    'guid': doc_guid
                }
        
        return None
    
    def get_editor_token_info(self, doc_guid: str) -> Optional[Dict]:
        """获取编辑器 WebSocket token 信息
        
        通过 POST /ks/note/{kbGuid}/{docGuid}/tokens 获取编辑器专用信息
        返回包含 editorToken, editorPermission, userId, displayName, avatarUrl 等信息
        """
        endpoint = f'/ks/note/{self.kb_guid}/{doc_guid}/tokens'
        
        try:
            response = self.request('POST', endpoint)
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, dict) and result.get('returnCode') == 200:
                    editor_info = result.get('result', {})
                    if editor_info.get('editorToken'):
                        logger.debug(f"成功获取编辑器 token 信息")
                        return editor_info
                    else:
                        logger.warning(f"响应中没有 editorToken: {result}")
                else:
                    logger.warning(f"获取编辑器 token 失败: {result}")
        except Exception as e:
            logger.error(f"获取编辑器 token 异常: {e}")
        
        return None

    def get_note_detail_via_websocket(self, doc_guid: str) -> Optional[Dict]:
        """通过 WebSocket 获取笔记 JSON 详情"""
        ws_config = self.config.get('websocket', {})
        if not ws_config.get('enabled'):
            logger.warning("WebSocket 功能未启用，请在配置中设置 websocket.enabled 为 true")
            return None

        url_template = ws_config.get('url_template') or "wss://wiz.frp.linyanli.cn/editor/{kbGuid}/{docGuid}"
        ws_url = url_template.format(kbGuid=self.kb_guid, docGuid=doc_guid)
        logger.debug(f"WebSocket URL: {ws_url}")
        
        # 获取编辑器信息
        # 优先使用配置中的 editor_token
        editor_token_config = ws_config.get('editor_token', '').strip()
        if editor_token_config:
            logger.debug(f"使用配置中的 editor_token: {editor_token_config[:20]}...")
            token = editor_token_config
            # 使用已有的用户信息
            user_id = self.auth.user_guid
            display_name = self.auth.username
            avatar_url = f"{self.kb_server}/as/user/avatar/{self.auth.user_guid}"
            permission = "w"
        else:
            # 通过 API 获取编辑器信息
            logger.debug("从 API 获取编辑器 token 信息...")
            editor_info = self.get_editor_token_info(doc_guid)
            if not editor_info:
                logger.error("无法获取编辑器 token 信息")
                return None
            
            token = editor_info.get('editorToken')
            user_id = editor_info.get('userId')
            display_name = editor_info.get('displayName')
            avatar_url = editor_info.get('avatarUrl')
            permission = editor_info.get('editorPermission', 'w')
            
            if not token:
                logger.error("编辑器信息中没有 token")
                return None
            
            logger.debug(f"获取到 editor token: {token[:20]}...")
        
        headers = {
            "Origin": ws_config.get('origin', self.kb_server),
            "User-Agent": ws_config.get('user_agent', 'WizNote-Team-Backup/1.0'),
        }
        
        # 同时也在请求头中添加 token
        if token:
            headers['X-Wiz-Token'] = token

        cookies = ws_config.get('cookies')
        if cookies:
            headers["Cookie"] = cookies
            logger.debug(f"使用 Cookie: {cookies[:50]}..." if len(cookies) > 50 else f"使用 Cookie: {cookies}")

        additional = ws_config.get('additional_headers') or {}
        for key, value in additional.items():
            if value:
                headers[key] = value

        header_list = [f"{key}: {value}" for key, value in headers.items() if value]

        sslopt = {}
        if ws_config.get('skip_tls_verify'):
            sslopt = {"cert_reqs": ssl.CERT_NONE}

        try:
            logger.debug(f"正在连接 WebSocket: {ws_url}")
            ws = websocket.create_connection(
                ws_url,
                header=header_list,
                timeout=ws_config.get('connect_timeout', 10),
                sslopt=sslopt or None,
            )
            logger.debug("WebSocket 连接成功")
        except Exception as e:
            logger.error(f"建立 WebSocket 连接失败: {e}")
            return None

        # 准备握手消息
        handshake_msg = {
            "a": "hs",
            "id": None,
            "auth": {
                "appId": self.kb_guid,
                "userId": user_id,
                "displayName": display_name,
                "avatarUrl": avatar_url,
                "docId": doc_guid,
                "token": token,
                "permission": permission
            }
        }
        
        # 连接后立即发送第一次握手
        logger.debug(f"发送第一次握手消息 (token: {token[:20]}...)")
        ws.send(json.dumps(handshake_msg))

        init_payload = ws_config.get('init_payload')
        if init_payload:
            encoding = (ws_config.get('init_payload_encoding') or 'text').lower()
            payload_bytes: Optional[bytes] = None
            if encoding == 'hex':
                try:
                    payload_bytes = bytes.fromhex(init_payload.replace(' ', ''))
                    logger.debug(f"发送 hex init_payload: {len(payload_bytes)} bytes")
                except ValueError as exc:
                    logger.error(f"init_payload hex 解析失败: {exc}")
            elif encoding == 'base64':
                try:
                    payload_bytes = base64.b64decode(init_payload)
                    logger.debug(f"发送 base64 init_payload: {len(payload_bytes)} bytes")
                except Exception as exc:
                    logger.error(f"init_payload base64 解析失败: {exc}")
            if payload_bytes is not None:
                ws.send(payload_bytes, opcode=websocket.ABNF.OPCODE_BINARY)
            else:
                logger.debug(f"发送 text init_payload: {init_payload[:100]}...")
                ws.send(init_payload)

        ws.settimeout(ws_config.get('message_timeout', 10))

        note_payload: Optional[Dict[str, Any]] = None
        message_count = 0
        session_id = None
        handshake_sent = False  # 标记是否已发送握手
        
        try:
            while True:
                try:
                    message = ws.recv()
                    message_count += 1
                except websocket.WebSocketTimeoutException:
                    logger.debug(f"WebSocket 超时，共接收 {message_count} 条消息")
                    break
                except websocket.WebSocketConnectionClosedException:
                    logger.debug(f"WebSocket 连接关闭，共接收 {message_count} 条消息")
                    break

                if not message:
                    continue

                if isinstance(message, bytes):
                    try:
                        message = message.decode('utf-8')
                    except UnicodeDecodeError:
                        logger.debug(f"消息 #{message_count}: 无法解码的二进制数据")
                        continue

                try:
                    payload = json.loads(message)
                    logger.debug(f"消息 #{message_count}: {json.dumps(payload, ensure_ascii=False)[:200]}...")
                except json.JSONDecodeError:
                    logger.debug(f"消息 #{message_count}: 非JSON数据: {message[:200]}...")
                    continue

                # 记录所有消息类型
                msg_type = payload.get('a')
                logger.debug(f"消息类型: {msg_type}")

                # 收到 init 消息后,再次发送握手
                if msg_type == 'init' and not handshake_sent:
                    session_id = payload.get('id')
                    logger.debug(f"收到 init 消息，session_id: {session_id}")
                    logger.debug(f"发送第二次握手消息: {json.dumps({**handshake_msg, 'auth': {**handshake_msg['auth'], 'token': token[:20] + '...'}}, ensure_ascii=False)}")
                    ws.send(json.dumps(handshake_msg))
                    handshake_sent = True
                    continue

                # 处理握手响应消息
                if msg_type == 'hs':
                    logger.debug("收到握手响应")
                    
                    # 发送获取文档数据的请求
                    f_request = {"a": "f", "c": self.kb_guid, "d": doc_guid}
                    logger.debug(f"发送 f 请求获取文档数据: {json.dumps(f_request, ensure_ascii=False)}")
                    ws.send(json.dumps(f_request))
                    continue

                # 处理文档数据消息
                if msg_type == 'f' and 'data' in payload:
                    note_payload = payload.get('data')
                    logger.info(f"成功获取笔记数据 (消息 #{message_count})")
                    break
        finally:
            ws.close()
            logger.debug(f"WebSocket 连接已关闭，共处理 {message_count} 条消息")

        if note_payload is None:
            logger.warning(f"未通过 WebSocket 获取到笔记数据: {doc_guid} (共接收 {message_count} 条消息)")
            return None

        return note_payload
    
    def get_note_html(self, doc_guid: str) -> Optional[str]:
        """获取笔记的HTML内容"""
        note_data = self.download_note(doc_guid, download_info=False, download_data=True)
        
        if note_data:
            if isinstance(note_data, dict):
                return note_data.get('html', '')
            elif isinstance(note_data, str):
                return note_data
        
        return None
    
    def get_attachments(self, doc_guid: str) -> List[Dict]:
        """获取笔记的附件列表
        
        注意：官方API文档中没有明确的获取附件列表接口
        可能需要从笔记内容中解析或使用其他方式
        """
        # 尝试从笔记信息中获取附件
        note_info = self.get_note_info(doc_guid)
        if note_info and 'attachments' in note_info:
            return note_info['attachments']
        
        return []
    
    def download_attachment(self, doc_guid: str, att_guid: str) -> Optional[bytes]:
        """下载附件
        
        官方API: GET /ks/attachment/download/:kbGuid/:docGuid/:attGuid
        """
        response = self.request(
            'GET', 
            f'/ks/attachment/download/{self.kb_guid}/{doc_guid}/{att_guid}',
            stream=True
        )
        
        if response.status_code == 200:
            # 流式下载大文件
            chunks = []
            for chunk in response.iter_content(chunk_size=self.config['download']['chunk_size']):
                if chunk:
                    chunks.append(chunk)
            return b''.join(chunks)
        else:
            logger.error(f"下载附件失败: HTTP {response.status_code}")
            return None
    
    def create_folder(self, parent_folder: str, folder_name: str) -> bool:
        """创建文件夹
        
        官方API: POST /ks/category/create/:kbGuid
        """
        data = {
            "parent": parent_folder,
            "name": folder_name
        }
        
        response = self.request('POST', f'/ks/category/create/{self.kb_guid}', json=data)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('returnCode') == 200:
                logger.info(f"创建文件夹成功: {parent_folder}/{folder_name}")
                return True
            else:
                logger.error(f"创建文件夹失败: {result.get('returnMessage')}")
        
        return False


if __name__ == "__main__":
    # 测试代码
    import sys
    from auth import WizNoteAuth
    
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # 读取配置
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'config.json')
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # 设置日志
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 测试API客户端
    auth = WizNoteAuth(config)
    if auth.login():
        client = WizNoteAPIClient(auth, config)
        
        # 获取文件夹
        print("\n测试获取文件夹...")
        folders = client.get_all_folders()
        if folders:
            print(f"获取到 {len(folders)} 个文件夹")
            # 检查数据格式
            if folders:
                print(f"第一个文件夹数据类型: {type(folders[0])}")
                if isinstance(folders[0], str):
                    print(f"文件夹列表 (前5个): {folders[:5]}")
                else:
                    print(f"文件夹列表 (前5个): {[f.get('name', str(f)) for f in folders[:5]]}")
                
                # 获取根目录的笔记
                print("\n获取根目录中的笔记...")
                notes_result = client.get_notes_in_folder("/", count=5)
                notes = notes_result['notes']
                if notes:
                    print(f"找到 {len(notes)} 个笔记")
                    for note in notes[:3]:
                        print(f"  - {note.get('title', 'Untitled')}")
    else:
        print("登录失败！")