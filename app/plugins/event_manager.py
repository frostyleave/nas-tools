from queue import Empty, Full, Queue

import log
from app.utils.commons import mask_sensitive, singleton
from app.utils.types import EventType

# 事件队列上限：处理不过来时丢弃新事件并告警，避免内存无限增长
EVENT_QUEUE_MAXSIZE = 500


@singleton
class EventManager:
    """
    事件管理器
    """

    # 事件队列
    _eventQueue = None
    # 事件响应函数字典
    _handlers: dict
    # 因队列满而被丢弃的事件数
    _dropped_count = 0

    def __init__(self):
        # 事件队列（有界）
        self._eventQueue = Queue(maxsize=EVENT_QUEUE_MAXSIZE)
        # 事件响应函数字典
        self._handlers = {}
        self._dropped_count = 0

    def get_event(self):
        """
        获取事件
        """
        try:
            event = self._eventQueue.get(block=True, timeout=1)
            # 拷贝一份，避免消费过程中注册/注销监听器导致遍历异常
            handlerList = self._handlers.get(event.event_type)
            return event, list(handlerList) if handlerList else []
        except Empty:
            return None, []

    def add_event_listener(self, etype: EventType, handler):
        """
        注册事件处理
        """
        try:
            handlerList = self._handlers[etype.value]
        except KeyError:
            handlerList = []
            self._handlers[etype.value] = handlerList
        if handler not in handlerList:
            handlerList.append(handler)
            log.debug(f"已注册事件：{etype.value}{handler}")

    def remove_event_listener(self, etype: EventType, handler):
        """
        移除监听器的处理函数
        """
        try:
            handlerList = self._handlers[etype.value]
            if handler in handlerList[:]:
                handlerList.remove(handler)
            if not handlerList:
                del self._handlers[etype.value]
        except KeyError:
            pass

    def send_event(self, etype: EventType, data: dict = None):
        """
        发送事件
        """
        if etype not in EventType:
            return
        event = Event(etype.value)
        event.event_data = data or {}
        log.debug(f"发送事件：{etype.value} - {mask_sensitive(event.event_data)}")
        try:
            self._eventQueue.put_nowait(event)
        except Full:
            # 事件处理跟不上（如 Webhook 超时、Plex 限速 sleep），丢弃新事件而不是无限堆积
            self._dropped_count += 1
            log.warn(f"事件队列已满（上限 {EVENT_QUEUE_MAXSIZE}），丢弃事件：{etype.value}，"
                     f"累计丢弃 {self._dropped_count} 次")

    def register(self, etype: [EventType, list]):
        """
        事件注册
        :param etype: 事件类型
        """

        def decorator(f):
            if isinstance(etype, list):
                for et in etype:
                    self.add_event_listener(et, f)
            elif type(etype) == type(EventType):
                for et in etype.__members__.values():
                    self.add_event_listener(et, f)
            else:
                self.add_event_listener(etype, f)
            return f

        return decorator


class Event:
    """
    事件对象
    """

    def __init__(self, event_type=None):
        # 事件类型
        self.event_type = event_type
        # 字典用于保存具体的事件数据
        self.event_data = {}


# 实例引用，用于注册事件
EventHandler = EventManager()
