"""
种子下载与解析模块

负责从各种来源（HTTP/PT站点/爬虫）下载种子文件并解析其内容。
从 Downloader 类中提取，遵循单一职责原则。
"""

import os
import re
from typing import Optional
from urllib.parse import unquote

from bencode import bdecode

import log

from app.utils import TorrentUtils, RequestUtils, SiteUtils
from app.utils.torrent import TorrentDownloadResult
from app.indexer.client import InterfaceSpider, MTorrentSpider
from app.indexer.client.browser import PlaywrightHelper
from app.indexer.manager import IndexerManager
from app.models.model import IndexerInfo, UserSiteConf
from config import Config


class TorrentDownloader:
    """
    种子文件下载器和解析器

    负责从 URL 下载种子文件、解析种子内容、处理站点特殊逻辑。
    """

    def __init__(self, torrent_temp_path: str, sites_manager=None):
        """
        :param torrent_temp_path: 种子文件临时存储目录
        :param sites_manager: SitesManager 实例（用于获取站点信息）
        """
        self._torrent_temp_path = torrent_temp_path
        self._sites = sites_manager

    # ---- 公共接口 ----

    def get_torrent_info_with_site(self, url: str, indexer_info: IndexerInfo, page_url: str) -> TorrentDownloadResult:
        """
        根据下载链接所属的站点信息，把种子下载到本地, 返回种子内容
        :param url: 种子链接
        :param indexer_info: 索引站点对象
        :param page_url: 种子链接页面的url
        :return: TorrentDownloadResult
        """
        if not indexer_info:
            return self.get_torrent_info(url=url)

        parser = indexer_info.parser
        if parser == "InterfaceSpider" or parser == "MTorrentSpider":
            return self._get_torrent_file_with_spider(url, indexer_info, parser)

        cookie = indexer_info.cookie if indexer_info else None
        ua = indexer_info.ua if indexer_info else None
        proxy = True if indexer_info.proxy else False
        render = True if indexer_info.render else False

        return self.get_torrent_info(
            url=url,
            cookie=cookie,
            ua=ua,
            referer=page_url,
            proxy=proxy,
            render=render
        )

    def get_torrent_info(self, url, cookie=None, ua=None, referer=None,
                         proxy=False, render=False) -> TorrentDownloadResult:
        """
        把种子下载到本地, 返回种子内容
        :param url: 种子链接
        :param cookie: 站点Cookie
        :param ua: 站点UserAgent
        :param referer: 关联地址
        :param proxy: 是否使用内置代理
        :param render: 是否需要使用渲染
        :return: TorrentDownloadResult
        """
        if not url:
            return TorrentDownloadResult(ret_msg="URL为空")
        if url.startswith("magnet:"):
            return TorrentDownloadResult(content=url, ret_msg=("%s 为磁力链接" % url))

        try:
            if render:
                file_path = PlaywrightHelper().download_file(url=url,
                                                             cookies=cookie,
                                                             ua=ua,
                                                             proxy=proxy,
                                                             save_path=self._torrent_temp_path)
                if not file_path:
                    return TorrentDownloadResult(ret_msg='文件下载失败')
                read_result = TorrentUtils.read_torrent_content(file_path)
                return TorrentDownloadResult(
                    file_path=file_path, content=read_result.content,
                    files_folder=read_result.files_folder,
                    files=read_result.files, ret_msg=read_result.ret_msg
                )

            save_result = self.save_torrent_file(url=url, cookie=cookie, ua=ua,
                                                  referer=referer, proxy=proxy)
            if save_result.ret_msg:
                log.info("【Downloader】种子文件下载结果: %s ", save_result.ret_msg)

            if not save_result.file_path or not save_result.content:
                return save_result

            # 解析种子文件
            resolve_result = TorrentUtils.resolve_torrent_files(save_result.content)
            return TorrentDownloadResult(
                file_path=save_result.file_path, content=save_result.content,
                files_folder=resolve_result.files_folder,
                files=resolve_result.files, ret_msg=resolve_result.ret_msg
            )

        except Exception as err:
            return TorrentDownloadResult(ret_msg=("下载种子文件出现异常: %s" % str(err)))

    def save_torrent_file(self, url, cookie=None, ua=None, referer=None,
                          proxy=False) -> TorrentDownloadResult:
        """
        把种子下载到本地
        :return: TorrentDownloadResult
        """
        log.debug("【Downloader】把种子 %s 下载到本地...", url)

        proxies = Config().get_proxies() if proxy else None
        req = RequestUtils(ua=ua, cookies=cookie, referer=referer,
                           proxies=proxies).get_res(url=url, allow_redirects=True)

        if req is None:
            return TorrentDownloadResult(ret_msg="无法打开链接: %s" % url)
        if req.status_code == 429:
            return TorrentDownloadResult(ret_msg="触发站点流控, 请稍后重试")
        if req.status_code != 200:
            return TorrentDownloadResult(ret_msg="下载种子出错, 状态码: %s" % req.status_code)
        if not req.content:
            return TorrentDownloadResult(ret_msg="未下载到种子数据")

        # 优先从 Header 判断内容类型
        content_type = req.headers.get('content-type', '').lower()
        if 'application/x-bittorrent' in content_type or 'application/octet-stream' in content_type:
            try:
                bdecode(req.content)  # 验证种子
                return self._resolve_torrent_from_http(url, req)
            except Exception:
                log.exception("【Downloader】保存种子文件失败: ")
                return TorrentDownloadResult(ret_msg="保存种子文件失败")

        # 尝试作为文本处理
        text_content = req.text
        if text_content.startswith("magnet:"):
            return TorrentDownloadResult(content=text_content, ret_msg="磁力链接")

        if "下载种子文件" in text_content:
            return self._process_first_time_download(
                text_content, url, cookie=cookie, ua=ua, referer=referer, proxy=proxy
            )

        return TorrentDownloadResult(ret_msg="下载内容有误, 请确认链接是否正确")

    def download_torrent_from_site(self, url: str, page_url: str,
                                   site_info: Optional[UserSiteConf]) -> TorrentDownloadResult:
        """
        从网站下载并解析种子信息
        :param url: 种子链接
        :param page_url: 页面地址
        :param site_info: 站点信息
        """
        if site_info:
            log.info("【Downloader】从PT站点HTTP链接下载种子: %s ", url)
            indexer_conf = IndexerManager().build_indexer_conf(
                url=site_info.strict_url, site_conf=site_info)
        else:
            log.debug("【Downloader】从HTTP链接下载种子: %s ", url)
            indexer_conf = IndexerManager().build_indexer_conf(url=url)

        return self.get_torrent_info_with_site(url, indexer_conf, page_url)

    # ---- 私有方法 ----

    def _get_torrent_file_with_spider(self, url: str, indexer_info: IndexerInfo,
                                       parser: str) -> TorrentDownloadResult:
        """
        通过爬虫把种子下载到本地
        :return: TorrentDownloadResult
        """
        req = MTorrentSpider(indexer_info).get_torrent(url) if parser == 'MTorrentSpider' \
            else InterfaceSpider(indexer_info).request(url)

        if req and req.status_code == 200:
            if not req.content:
                return TorrentDownloadResult(ret_msg="未下载到种子数据")
            file_name = self._get_url_torrent_filename(req, url)
            if not file_name:
                return TorrentDownloadResult(ret_msg="读取文件名称失败")

            file_path = os.path.join(self._torrent_temp_path, file_name)
            file_content = req.content
            with open(file_path, 'wb') as f:
                f.write(file_content)

            resolve_result = TorrentUtils.resolve_torrent_files(file_content)
            return TorrentDownloadResult(file_path=file_path, content=file_content,
                                         files_folder=resolve_result.files_folder,
                                         files=resolve_result.files,
                                         ret_msg=resolve_result.ret_msg)

        elif req is None:
            return TorrentDownloadResult(ret_msg="无法打开链接: %s" % url)
        elif req.status_code == 429:
            return TorrentDownloadResult(ret_msg="触发站点流控, 请稍后重试")
        else:
            return TorrentDownloadResult(ret_msg="下载种子出错, 状态码: %s" % req.status_code)

    def _resolve_torrent_from_http(self, url, req) -> TorrentDownloadResult:
        """从HTTP响应中解析并保存种子文件"""
        file_name = self._get_url_torrent_filename(req, url)
        if not file_name:
            return TorrentDownloadResult(ret_msg="读取文件名称失败")

        file_path = os.path.join(self._torrent_temp_path, file_name)
        file_content = req.content

        if not os.path.exists(file_path):
            with open(file_path, 'wb') as f:
                f.write(file_content)

        return TorrentDownloadResult(file_path=file_path, content=file_content)

    def _process_first_time_download(self, text_content, url, cookie=None, ua=None,
                                      referer=None, proxy=False) -> TorrentDownloadResult:
        """
        处理首次下载（站点需要确认/重定向的情况）
        :return: TorrentDownloadResult
        """
        try:
            form = re.findall(r'<form.*?action="(.*?)".*?>(.*?)</form>', text_content, re.S)
            if not form:
                log.warn("【Downloader】触发了站点首次种子下载, 无法解析页面form : %s ", url)
                return TorrentDownloadResult(ret_msg="未下载到种子数据")

            action = form[0][0]
            if not action or action == "?":
                action = url
            elif not action.startswith('http'):
                action = SiteUtils.get_base_url(url) + action

            if not action:
                log.warn("【Downloader】触发了站点首次种子下载, 无法解析页面form.action : %s ", url)
                return TorrentDownloadResult(ret_msg="未下载到种子数据")

            inputs = re.findall(r'<input.*?name="(.*?)".*?value="(.*?)".*?>', form[0][1], re.S)
            if not inputs:
                log.warn("【Downloader】触发了站点首次种子下载, 无法解析页面form.inputs : %s ", url)
                return TorrentDownloadResult(ret_msg="未下载到种子数据")

            data = {item[0]: item[1] for item in inputs}

            req = RequestUtils(ua=ua, cookies=cookie, referer=referer,
                               proxies=Config().get_proxies() if proxy else None).post_res(
                url=action, data=data)

            if req is None:
                log.warn("【Downloader】触发了站点首次种子下载, 且无法自动跳过: %s ", url)
                return TorrentDownloadResult(
                    ret_msg="触发了站点首次种子下载, 且无法自动跳过, 请手动在站点下载一次种子")

            if req.status_code != 200:
                log.warn("【Downloader】触发了站点首次种子下载, 且无法自动跳过, 返回码: %s, 错误原因: %s ",
                         req.status_code, req.reason)
                return TorrentDownloadResult(ret_msg="触发了站点首次种子下载, 尝试跳过时失败")

            content_type = req.headers.get('content-type', '').lower()

            if 'text/html' in content_type or 'text/plain' in content_type:
                text_content = req.text
                if not text_content.startswith("magnet:"):
                    log.warn("【Downloader】触发了站点首次种子下载, 自动跳过后text内容无法解析: %s ", text_content)
                    return TorrentDownloadResult(ret_msg="未下载到种子数据")
                return TorrentDownloadResult(content=text_content, ret_msg="磁力链接")

            if 'application/x-bittorrent' in content_type or 'application/octet-stream' in content_type:
                try:
                    bdecode(req.content)
                    return self._resolve_torrent_from_http(action, req)
                except Exception as err:
                    return TorrentDownloadResult(ret_msg=f"种子数据有误: {str(err)}")

        except Exception as err:
            log.warn(f"【Downloader】触发了站点首次种子下载, 尝试自动跳过时出现错误: {str(err)}, 链接: {url}")

        return TorrentDownloadResult(ret_msg="种子数据有误, 请确认链接是否正确")

    @staticmethod
    def _get_url_torrent_filename(req, url) -> str:
        """从下载请求中获取种子文件名"""
        if not req:
            return ""
        disposition = req.headers.get('content-disposition') or ""
        file_name = re.findall(r"filename=\"?(.+)\"?", disposition)
        if file_name:
            file_name = unquote(str(file_name[0].encode('ISO-8859-1').decode()).split(";")[0].strip())
            if file_name.endswith('"'):
                file_name = file_name[:-1]
        elif url and url.endswith(".torrent"):
            file_name = unquote(url.split("/")[-1])

        return file_name
