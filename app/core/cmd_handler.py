from app.core.cmd_registry import CommandRegistry
from app.helper.thread_helper import ThreadHelper
from app.message import Message
from app.message.message_search import MessageSearchHandler
from app.plugins.event_manager import EventManager
from app.plugins.plugin_manager import PluginManager
from app.utils.types import EventType, SearchType


class CommandHandler:

    def handle_message_job(self, 
                           msg, 
                           in_from=SearchType.OT, 
                           user_id=None, 
                           user_name=None, 
                           client_id=None):
        """
        处理消息事件
        """
        if not msg:
            return

        # 触发MessageIncoming事件
        EventManager().send_event(EventType.MessageIncoming, {
            "channel": in_from.value,
            "user_id": user_id,
            "user_name": user_name,
            "message": msg
        })

        # 系统内置命令
        command = CommandRegistry().get(msg)
        if command:
            # 启动服务
            ThreadHelper().start_thread(command.get("func"), ())
            # 消息回应
            Message().send_channel_msg(
                channel=in_from, 
                title="正在运行 %s ..." % command.get("desc"), 
                user_id=user_id, 
                client_id=client_id)
            return

        # 插件命令
        plugin_commands = PluginManager().get_plugin_commands()
        for command in plugin_commands:
            if command.get("cmd") == msg:
                # 发送事件
                EventManager().send_event(command.get("event"), command.get("data") or {})
                # 消息回应
                Message().send_channel_msg(
                    channel=in_from, 
                    title="正在运行 %s ..." % command.get("desc"), 
                    user_id=user_id, 
                    client_id=client_id)
                return

        # 站点搜索或者添加订阅
        ThreadHelper().start_thread(MessageSearchHandler(in_from, user_id, user_name, client_id).search_media_by_message, (msg,))