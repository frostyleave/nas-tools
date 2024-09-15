# author: https://github.com/jxxghp/MoviePilot/blob/main/app/helper/browser.py
import log
from typing import Callable, Any

from playwright.sync_api import sync_playwright, Page
from cf_clearance import sync_cf_retry, sync_stealth


class WaitElement:

    element = ''
    state = ''
    
    def __init__(self, _element, _state):
        self.element = _element
        self.state = _state


class PlaywrightHelper:
    def __init__(self, browser_type="chromium"):
        self.browser_type = browser_type

    @staticmethod
    def __pass_cloudflare(url: str, page: Page) -> bool:
        """
        尝试跳过cloudfare验证
        """
        sync_stealth(page, pure=True)
        page.goto(url)
        return sync_cf_retry(page)

    def action(self, 
               url: str,
               callback: Callable,
               cookies: str = None,
               ua: str = None,
               proxies: dict = None,
               headless: bool = False,
               timeout: int = 30) -> Any:
        """
        访问网页，接收Page对象并执行操作
        :param url: 网页地址
        :param callback: 回调函数，需要接收page对象
        :param cookies: cookies
        :param ua: user-agent
        :param proxies: 代理
        :param headless: 是否无头模式
        :param timeout: 超时时间
        """
        try:
            with sync_playwright() as playwright:
                browser = playwright[self.browser_type].launch(headless=headless)
                context = browser.new_context(user_agent=ua, proxy=proxies)
                page = context.new_page()
                if cookies:
                    page.set_extra_http_headers({"cookie": cookies})
                try:
                    if not self.__pass_cloudflare(url, page):
                        log.warn("cloudflare challenge fail！")
                    page.wait_for_load_state("networkidle", timeout=timeout * 1000)
                    # 回调函数
                    return callback(page)
                except Exception as e:
                    log.error(f"网页操作失败: {str(e)}")
                finally:
                    browser.close()
        except Exception as e:
            log.error(f"网页操作失败: {str(e)}")
        return None

    def get_page_source(self, 
                        url: str,
                        cookies: str = None,
                        ua: str = None,
                        proxies: dict = None,
                        headless: bool = False,
                        timeout: int = 20,
                        wait_item: WaitElement = None) -> str:
        """
        获取网页源码
        :param url: 网页地址
        :param cookies: cookies
        :param ua: user-agent
        :param proxies: 代理
        :param headless: 是否无头模式
        :param timeout: 超时时间
        """
        source = ""
        try:
            with sync_playwright() as playwright:
                browser = playwright[self.browser_type].launch(headless=headless, proxy=proxies)
                context = browser.new_context(user_agent=ua)
                page = context.new_page()
                if cookies:
                    page.set_extra_http_headers({"cookie": cookies})
                try:
                    if not self.__pass_cloudflare(url, page):
                        log.warn("cloudflare challenge fail!")

                    # 等待页面自动跳转
                    if wait_item and wait_item.element and wait_item.state:
                        page.wait_for_selector(wait_item.element, state=wait_item.state, timeout=timeout * 1000)

                    page.wait_for_load_state("networkidle", timeout=timeout * 1000)
                    source = page.content()
                except Exception as e:
                    log.error(f"获取网页源码失败: {str(e)}")
                    source = None
                finally:
                    browser.close()
        except Exception as e:
            log.error(f"获取网页源码失败: {str(e)}")
        return source

