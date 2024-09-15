# coding: utf-8
import json
import log
import re
import requests

from urllib.parse import quote

from app.utils.string_utils import StringUtils
from config import Config


class InterfaceSpider(object):
    torrents_info_array = []
    result_num = 100

    def __init__(self, indexer):
        self._indexer = indexer
        self.init_config()

    def init_config(self):
        self.torrents_info_array = []
        self.result_num = Config().get_config('pt').get('site_search_result_num') or 100

    def search(self, keyword, page=None, mtype=None):
        """
        开始搜索
        :param: keyword: 搜索关键字
        :param: page: 页码
        :param: mtype: 类型
        :return: (是否发生错误，种子列表)
        """
        if not keyword:
            keyword = ""
        if isinstance(keyword, list):
            keyword = " ".join(keyword)

        list_selector = self._indexer.torrents.get('list')
        if not list_selector:
            log.warn(f"【InterfaceSpider】渲染器{self._indexer.name} 中torrents配置错误, 缺失list")
            return False, []

        # 种子筛选器
        torrents_selector = list_selector.get('selector', 'pre')
        if not torrents_selector:
            log.warn(f"【InterfaceSpider】渲染器{self._indexer.name} 中torrents->list配置错误, 缺失selector")
            return False, []
        
        field_selector = self._indexer.torrents.get('fields')
        if not field_selector:
            log.warn(f"【InterfaceSpider】渲染器{self._indexer.name} 中torrents配置错误, 缺失fields")
            return False, []

        # 请求路径
        search_config = self._indexer.search.get('paths', [{}])[0]
        torrents_path = search_config.get('path', '') or ''
        search_url = torrents_path.replace("{domain}", self._indexer.domain).replace("{keyword}", quote(keyword))

        response = self.request(search_url, search_config)

        if response.status_code != 200:
            log.warn(f"【InterfaceSpider】请求{search_url} 失败: {str(response.status_code)}")
            return True, []

        # 获取HTML文本
        html_text = response.text
        if not html_text:
            log.warn(f"【InterfaceSpider】session请求{search_url} 失败: 返回结果为空")
            return True, []
        
        # 解析文本
        json_obj = json.loads(html_text)
        if not json_obj:
            log.warn(f"【InterfaceSpider】json解析失败: {html_text}")
            return False, []
        
        data_root = list_selector.get('root')
        if data_root:
            tmp_data = json_obj
            params = data_root.split('>')
            for param_name in params:
                tmp_data = tmp_data.get(param_name)
                if not tmp_data:
                    log.warn(f"【InterfaceSpider】{param_name}字段值为空")
                    return False, []                
            json_obj = tmp_data
        
        data_list = []
        if isinstance(json_obj, dict):
            for value_item in json_obj.values():
                if isinstance(value_item, list):
                    data_list.extend(value_item)
                else:
                    data_list.append(value_item)
        elif isinstance(json_obj, list):
            data_list = json_obj
        else:
            log.warn(f"【InterfaceSpider】json对象结构错误: {html_text}")
            return False, []
        
        # 遍历结果, 生成种子信息
        for data_item in data_list:

            if not data_item:
                continue

            item_size = self.get_dic_val(data_item, field_selector.get('size'))
            if item_size and isinstance(item_size, str):
                item_size = item_size.replace("\n", "").strip()

            download_link = self.get_dic_val(data_item, field_selector.get('magnet'))
            # 有磁力链接时，校验磁力链接合法性
            if not download_link or download_link.startswith('magnet') == False or len(download_link) < 52:
                download_link = self.get_dic_val(data_item, field_selector.get('hash'))
                if download_link:
                    download_link = 'magnet:?xt=urn:btih:' + download_link
                else:
                    torrent_file = self.get_dic_val(data_item, field_selector.get('torrent'))
                    if torrent_file:
                        download_link = torrent_file
                        if download_link.startswith('http') == False:
                            torrent_domain = field_selector.get('torrent_domain')
                            if torrent_domain:
                                if torrent_domain.endswith('/') and download_link.startswith('/'):
                                    download_link = torrent_domain.strip('/') + download_link
                                elif torrent_domain.endswith('/') == False and download_link.startswith('/') == False:
                                    download_link = torrent_domain+ '/' + download_link
                                else:
                                    download_link = torrent_domain + download_link

            torrent = {
                'indexer': self._indexer.id,
                'title': self.get_dic_val(data_item, field_selector.get('title')),
                'enclosure': download_link,
                'pubdate': self.get_dic_val(data_item, field_selector.get('date_added')),
                'size': StringUtils.num_filesize(item_size) if isinstance(item_size, str) else item_size,
                'seeders' : self.get_dic_val(data_item, field_selector.get('seeders')),
                'downloadvolumefactor' : 0.0
            }
            self.torrents_info_array.append(torrent)
        
        return False, self.torrents_info_array
    

    def request(self, search_url, search_config=None):
        """
        执行请求
        :param: search_url: 请求链接
        :param: search_config: 站点搜索配置
        :return: response
        """

        # 定义请求头
        headers = { 'User-Agent': Config().get_ua() }

        # 代理
        proxies = Config().get_proxies() if self._indexer.proxy else None
        
        if not search_config:
            search_config = self._indexer.search.get('paths', [{}])[0]

        # 是否需要验证cookie
        check_cookie = search_config.get('cookie', False) or False
        
        # 创建一个会话对象
        session = requests.Session()

        # 发送请求
        log.info(f"【InterfaceSpider】开始请求: {search_url}")
        response = session.get(search_url, headers=headers, allow_redirects=True,  proxies=proxies)

        if response.status_code != 200:
            log.warn(f"【InterfaceSpider】请求{search_url} 失败: {str(response.status_code)}")
            return response

        if check_cookie:
            # 使用正则表达式从响应内容中提取 cookie 值
            match = re.search(r'document.cookie = "([^=]+)=([^;]+);', response.text)
            if match:
                cookie_name = match.group(1)
                cookie_value = match.group(2)
                # 设置 cookie
                session.cookies.set(cookie_name, cookie_value)

            # 重新发送请求
            response = session.get(search_url, headers=headers, allow_redirects=True,  proxies=proxies)

        return response

    def get_dic_val(self, dict_obj, key_name):
        if not key_name:
            return None
        
        if key_name.find('>') == -1:
            return dict_obj.get(key_name)
        
        tmp_data = dict_obj

        params = key_name.split('>')
        for param_name in params:
            tmp_data = tmp_data.get(param_name)
            if not tmp_data:
                return None
        
        return tmp_data
