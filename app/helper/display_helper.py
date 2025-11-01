import os

from pyvirtualdisplay import Display

from app.utils.commons import singleton
from config import XVFB_PATH

import log


@singleton
class DisplayHelper(object):
    _display = None

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.stop_service()
        if self.can_display():
            try:
                self._display = Display(visible=False, size=(1024, 768))
                self._display.start()
                os.environ["NASTOOL_DISPLAY"] = "true"
            except Exception as err:
                log.exception("[虚拟显示]初始化异常: ", err)

    def get_display(self):
        return self._display

    def stop_service(self):
        os.environ["NASTOOL_DISPLAY"] = ""
        if self._display:
            self._display.stop()

    @staticmethod
    def can_display():
        for path in XVFB_PATH:
            if os.path.exists(path):
                return True
        return False

    def __del__(self):
        self.stop_service()
