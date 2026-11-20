import asyncio


def install_connection_reset_filter(loop: asyncio.AbstractEventLoop) -> None:
    """
    过滤 Windows 下 ProactorEventLoop 的连接重置噪音。

    对端（例如浏览器刷新页面）主动断开 keep-alive 连接时，ProactorEventLoop
    会在 _call_connection_lost 中对已重置的 socket 执行 shutdown，抛出
    ConnectionResetError，被 asyncio 当成「回调异常」打印完整堆栈。
    该异常不影响服务，这里直接忽略；其它异常仍交给默认处理器。
    """
    previous_handler = loop.get_exception_handler()

    def handler(active_loop, context):
        exc = context.get("exception")
        message = context.get("message") or ""
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)) \
                and "_call_connection_lost" in message:
            return
        if previous_handler is None:
            active_loop.default_exception_handler(context)
        else:
            previous_handler(active_loop, context)

    loop.set_exception_handler(handler)
