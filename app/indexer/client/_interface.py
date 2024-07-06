# coding: utf-8
import copy
import json
import time
from urllib.parse import quote

from pyquery import PyQuery
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as es
from selenium.webdriver.support.wait import WebDriverWait

from app.helper import ChromeHelper
from app.indexer.client._spider import TorrentSpider
from app.utils import ExceptionUtils
from app.utils.string_utils import StringUtils
from config import Config


class InterfaceSpider(object):
    torrentspider = None
    torrents_info_array = []
    result_num = 100

    def __init__(self, indexer):
        self.torrentspider = TorrentSpider()
        self._indexer = indexer
        self.init_config()

    def init_config(self):
        self.torrents_info_array = []
        self.result_num = Config().get_config('pt').get('site_search_result_num') or 100

    def search(self, keyword, page=None, mtype=None):
        """
        开始搜索
        :param: keyword: 搜索关键字
        :param: indexer: 站点配置
        :param: page: 页码
        :param: mtype: 类型
        :return: (是否发生错误，种子列表)
        """
        if not keyword:
            keyword = ""
        if isinstance(keyword, list):
            keyword = " ".join(keyword)

        chrome = ChromeHelper()
        if not chrome.get_status():
            return True, []
        
        # 请求路径
        torrentspath = self._indexer.search.get('paths', [{}])[0].get('path', '') or ''
        search_url = self._indexer.domain + torrentspath.replace("{keyword}", quote(keyword))

        # 请求方式，支持GET和POST
        # method = self._indexer.search.get('paths', [{}])[0].get('method', '')

        # referer = self._indexer.domain
        
        # 使用浏览器打开页面
        if not chrome.visit(url=search_url,
                            cookie=self._indexer.cookie,
                            ua=self._indexer.ua,
                            proxy=self._indexer.proxy):
            return True, []

        # 等待页面加载完成
        time.sleep(3)
        # 获取HTML文本
        html_text = chrome.get_html()
        if not html_text:
            return True, []

        list_selector = self._indexer.torrents.get('list')
        if not list_selector:
            return False, []

        field_selector = self._indexer.torrents.get('fields')
        if not field_selector:
            return False, []

        # 种子筛选器
        torrents_selector = list_selector.get('selector', 'pre')
        if not torrents_selector:
            return False, []
        
        # 解析HTML文本
        html_doc = PyQuery(html_text)
        html_list = html_doc(torrents_selector)
        if not html_list:
            return False, []
        
        json_str = html_list[0]
        if not json_str.text:
            return False, []
        
        json_obj = json.loads(json_str.text)
        if not json_obj:
            return False, []
        
        data_root = list_selector.get('root')
        if data_root:
            tmp_data = json_obj
            params = data_root.split('>')
            for param_name in params:
                tmp_data = tmp_data.get(param_name)
                if not tmp_data:
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
            return False, []
        
        for data_item in data_list:
            item_size = self.get_dic_val(data_item, field_selector.get('size'))
            if item_size:
                item_size = item_size.replace("\n", "").strip()
            torrent = {
                'indexer': self._indexer.id,
                'title': self.get_dic_val(data_item, field_selector.get('title')),
                'enclosure': self.get_dic_val(data_item, field_selector.get('download')),
                'pubdate': self.get_dic_val(data_item, field_selector.get('date_added')),
                'size': StringUtils.num_filesize(item_size)
            }
            self.torrents_info_array.append(torrent)
        
        return False, self.torrents_info_array
    
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
