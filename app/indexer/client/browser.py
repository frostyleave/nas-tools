# author: https://github.com/jxxghp/MoviePilot/blob/main/app/helper/browser.py
import os
import time
from config import Config
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
               proxy: bool = False,
               headless: bool = True,
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
            proxies={
                'server': Config().get_proxies().get('http')
            } if proxy else None
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
                        proxy: bool = False,
                        headless: bool = True,
                        timeout: int = 20,
                        wait_item: WaitElement = None) -> str:
        """
        获取网页源码
        :param url: 网页地址
        :param cookies: cookies
        :param ua: user-agent
        :param proxy: 是否使用代理
        :param headless: 是否无头模式
        :param timeout: 超时时间
        """
        source = ""
        try:
            proxies={
                'server': Config().get_proxies().get('http')
            } if proxy else None
            with sync_playwright() as playwright:
                browser = playwright[self.browser_type].launch(headless=headless, proxy=proxies)
                context = browser.new_context(user_agent=ua)
                page = context.new_page()
                if cookies:
                    page.set_extra_http_headers({"cookie": cookies})
                try:
                    log.info(f'[Playwright]开始访问{url}')
                    if not self.__pass_cloudflare(url, page):
                        log.warn("cloudflare challenge fail!")

                    # 等待页面自动跳转
                    if wait_item and wait_item.element and wait_item.state:
                        page.wait_for_selector(wait_item.element, state=wait_item.state, timeout=timeout * 1000)

                    page.wait_for_load_state("networkidle", timeout=timeout * 1000)
                    source = page.content()
                except Exception as e:
                    log.error(f"获取网页源码失败: {str(e)} {page.content() if page else ''}")
                    source = None
                finally:
                    browser.close()
        except Exception as e:
            log.error(f"获取网页源码失败: {str(e)}")
        return source
    

    def download_file(self, 
                        url: str,
                        cookies: str = None,
                        ua: str = None,
                        proxy: bool = False,
                        headless: bool = True,
                        timeout: int = 30,
                        save_path: str = None,
                        save_name: str = None) -> str:
        """
        访问文件下载页、完成文件下载
        :param url: 网页地址
        :param cookies: cookies
        :param ua: user-agent
        :param proxy: 是否使用代理
        :param headless: 是否无头模式
        :param timeout: 超时时间
        :param save_path: 文件保存目录
        :param save_name: 文件名
        """
        try:
            proxies={
                'server': Config().get_proxies().get('http')
            } if proxy else None
            
            with sync_playwright() as playwright:
                browser = playwright[self.browser_type].launch(headless=headless, proxy=proxies, downloads_path=save_path)
                context = browser.new_context(user_agent=ua)
                page = context.new_page()
                if cookies:
                    page.set_extra_http_headers({"cookie": cookies})

                try:
                                       
                    # 监听下载事件
                    def handle_download(download):
                        # 设置保存路径
                        save_folder = save_path or os.getcwd()
                        target_path = os.path.join(save_folder, download.suggested_filename)
                        # 文件重复下载
                        if os.path.exists(target_path):
                            timestamp = time.strftime("%Y%m%d%H%M%S")
                            name, ext = os.path.splitext(download.suggested_filename)
                            target_path = os.path.join(save_folder, f"{name}_{timestamp}{ext}")
                        download.save_as(target_path)
                        setattr(download, 'save_path', target_path)

                    # 绑定下载事件
                    page.on("download", handle_download)
                    # 访问 URL，开始下载
                    with page.expect_download() as download_info:
                        page.goto(url, wait_until="networkidle", timeout=timeout * 1000)

                    download = download_info.value                  
                        
                    # 检查下载是否失败
                    if download:
                        if download.failure():
                            print(f"Download failed: {download_info.failure}")
                            return None
                        return download.save_path

                    return None
                except Exception as e:
                    log.error(f"Playwright下载文件失败: {str(e)}")
                    return None
                finally:
                    browser.close()
        except Exception as e:
            log.error(f"Playwright下载失败: {str(e)}")
            return None
        
    
    def initiate_download(self, page, url, timeout):
        # 启动下载并等待完成
        with page.expect_download(timeout=timeout * 1000) as download_info:
            page.goto(url)
        return download_info.value

    def process_downloaded_file(self, download, download_dir, save_name):
        # 获取下载的文件路径
        file_path = download.path()

        # 生成新的文件名以避免重复（如果没有提供 save_name）
        if not save_name:
            original_name = os.path.basename(download.suggested_filename)
            save_name = original_name

        # 如果文件已经存在，添加时间戳避免冲突
        final_save_path = os.path.join(download_dir, save_name)
        if os.path.exists(final_save_path):
            timestamp = time.strftime("%Y%m%d%H%M%S")
            name, ext = os.path.splitext(save_name)
            final_save_path = os.path.join(download_dir, f"{name}_{timestamp}{ext}")


        return final_save_path

