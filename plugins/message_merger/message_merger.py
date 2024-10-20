import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_message import ChatMessage
from common.log import logger
from plugins import *
import time
import json
from bridge.context import EventContext

# 加载配置文件 12
def load_config():
    try:
        with open('plugins/message_merger/config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("[MessageMerger] 配置文件不存在，使用默认配置")
        return {}
    except json.JSONDecodeError:
        logger.error("[MessageMerger] 配置文件格式错误，使用默认配置")
        return {}

# 全局配置变量
config = load_config()

@plugins.register(name="MessageMerger", desc="合并多条消息后再发送给大模型", version="0.9", author="Assistant")
class MessageMerger(Plugin):
    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        self.config = config  # 使用全局配置
        if not self.config:
            self.config = {}
        self.messages = {}
        self.last_message_time = {}
        self.merging_sessions = set()
        logger.info("[MessageMerger] 插件已加载")

    def on_handle_context(self, e_context: EventContext):
        if e_context['context'].type != ContextType.TEXT:
            return

        content = e_context['context'].content
        session_id = e_context['context']['session_id']
        
        current_time = time.time()
        
        # 检查是否是开始合并的触发词
        if self.is_trigger(content, 'start_triggers'):
            self.start_merging(session_id)
            e_context.action = EventAction.BREAK_PASS
            return

        # 如果正在合并消息，所有消息都不回复
        if session_id in self.merging_sessions:
            self.add_message(session_id, content)
            e_context.action = EventAction.BREAK_PASS
            return

        # 检查是否是结束合并的触发词
        if self.is_trigger(content, 'end_triggers'):
            if session_id in self.merging_sessions:
                merged_content = self.end_merging(session_id)
                e_context['context'].content = merged_content
                e_context.action = EventAction.CONTINUE
            else:
                e_context.action = EventAction.BREAK_PASS
            return

        # 检查是否是即时合并的触发词
        if self.is_trigger(content, 'instant_triggers'):
            if session_id in self.messages:
                merged_content = self.instant_merge(session_id, content)
                e_context['context'].content = merged_content
                e_context.action = EventAction.CONTINUE
            else:
                e_context.action = EventAction.BREAK_PASS
            return

        # 处理普通消息
        self.handle_normal_message(session_id, content, current_time, e_context)

    def is_trigger(self, content, trigger_type):
        return any(trigger in content for trigger in self.config.get(trigger_type, []))

    def start_merging(self, session_id):
        self.merging_sessions.add(session_id)
        self.messages[session_id] = []
        logger.info(f"[MessageMerger] 开始合并消息: {session_id}")

    def add_message(self, session_id, content):
        self.messages[session_id].append(content)

    def end_merging(self, session_id):
        self.merging_sessions.remove(session_id)
        merged_content = "\n".join(self.messages[session_id])
        self.messages[session_id] = []
        logger.info(f"[MessageMerger] 结束合并消息: {merged_content}")
        return merged_content

    def instant_merge(self, session_id, content):
        merged_content = "\n".join(self.messages[session_id] + [content])
        self.messages[session_id] = []
        logger.info(f"[MessageMerger] 即时合并消息: {merged_content}")
        return merged_content

    def handle_normal_message(self, session_id, content, current_time, e_context):
        # 如果是新会话或者距离上一条消息超过设定时间,清空之前的消息
        if session_id not in self.messages or current_time - self.last_message_time.get(session_id, 0) > self.config.get('merge_interval', 60):
            self.messages[session_id] = []

        self.messages[session_id].append(content)
        self.last_message_time[session_id] = current_time

        # 如果消息数量达到设定值,则合并消息并发送
        if len(self.messages[session_id]) >= self.config.get('message_count', 6):
            merged_content = "\n".join(self.messages[session_id])
            e_context['context'].content = merged_content
            self.messages[session_id] = []
            logger.info(f"[MessageMerger] 合并消息: {merged_content}")
            e_context.action = EventAction.CONTINUE
        else:
            # 如果不满足合并条件,则不处理该消息
            e_context.action = EventAction.BREAK_PASS

    def get_help_text(self, **kwargs):
        帮助文本 = "消息合并插件使用说明：\n"
        帮助文本 += "1. 使用开始触发词开始合并消息，合并期间不会收到任何回复\n"
        帮助文本 += "2. 使用结束触发词结束合并并发送消息，此时会收到回复\n"
        帮助文本 += "3. 使用即时触发词立即合并并发送消息，会收到回复\n"
        帮助文本 += "4. 当消息数量达到设定值时，自动合并并发送，会收到回复\n"
        帮助文本 += "5. 合并过程中的所有消息都不会得到回复\n"
        帮助文本 += "6. 只有合并后的消息会发送给大模型进行回复\n"
        帮助文本 += "7. 如果长时间没有收到回复，请检查网络连接或重新发送消息"
        return 帮助文本
