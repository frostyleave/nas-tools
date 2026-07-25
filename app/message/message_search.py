import os.path
import re

import log

from app.downloader import Downloader
from app.indexer import Indexer
from app.media import Media
from app.message import Message
from app.modules.search import SearchProxy
from app.sites import SitesManager
from app.modules.subscribe import Subscribe
from app.utils.types import SearchType, RssType

from config import Config

SEARCH_MEDIA_CACHE = {}
SEARCH_MEDIA_TYPE = {}


class MessageSearchHandler:

    def __init__(self, 
                 in_from: SearchType, 
                 user_id, 
                 user_name=None, 
                 client_id=None):
        """
        消息搜索
        :param in_from: 搜索下载的请求来源
        :param user_id: 需要发送消息的，传入该参数，则只给对应用户发送交互消息
        :param user_name: 用户名称
        """
        self.in_from = in_from
        self.user_id = user_id
        self.user_name = user_name
        self.client_id = client_id


    def search_media_by_message(self, input_str):
        """
        输入字符串，解析要求并进行资源搜索
        :param input_str: 输入字符串，可以包括标题、年份、季、集的信息，使用空格隔开
        :return: 请求的资源是否全部下载完整、请求的文本对应识别出来的媒体信息、请求的资源如果是剧集，则返回下载后仍然缺失的季集信息
        """
        global SEARCH_MEDIA_TYPE
        global SEARCH_MEDIA_CACHE

        if not input_str:
            log.info("【Searcher】搜索关键字有误！")
            return

        input_str = str(input_str).strip()
        log.info(f"【Searcher】关键字: {input_str}")

        # 如果是数字，表示选择项
        if input_str.isdigit() and int(input_str) < 10:
            # 获取之前保存的可选项
            choose = int(input_str) - 1
            if choose < 0 or not SEARCH_MEDIA_CACHE.get(self.user_id) or \
                    choose >= len(SEARCH_MEDIA_CACHE.get(self.user_id)):
                self.__send_channel_msg(title="输入有误！")
                log.warn(f"【Searcher】错误的输入值: {input_str}")
                return
            
            media_info = SEARCH_MEDIA_CACHE[self.user_id][choose]
            search_media_type = SEARCH_MEDIA_TYPE.get(self.user_id)
            if not search_media_type or search_media_type == "SEARCH":
                # 如果是豆瓣数据，需要重新查询TMDB的数据
                if media_info.douban_id:
                    log.info("【message】豆瓣id: %s" % media_info.douban_id)
                    _title = media_info.get_title_string()
                    # 重新根据豆瓣ID查询媒体数据
                    media_info = Media().get_mediainfo_from_id('DB:' + media_info.douban_id, media_info.type)
                    if not media_info or not media_info.tmdb_info:
                        self.__send_channel_msg(title="%s 从TMDB查询不到媒体信息!" % _title)
                        return
                # 搜索
                self.__search_media(media_info=media_info)
            else:
                # 订阅
                self.__add_media_rss(media_info=media_info)
        # 接收到文本
        else:
            if input_str.startswith("订阅"):
                # 订阅
                SEARCH_MEDIA_TYPE[self.user_id] = "SUBSCRIBE"
                input_str = re.sub(r"订阅[:：\s]*", "", input_str)
            elif input_str.startswith("http"):
                # 下载链接
                SEARCH_MEDIA_TYPE[self.user_id] = "DOWNLOAD"
            else:
                # 搜索
                input_str = re.sub(r"(搜索|下载)[:：\s]*", "", input_str)
                SEARCH_MEDIA_TYPE[self.user_id] = "SEARCH"
                
            # 下载链接
            if SEARCH_MEDIA_TYPE[self.user_id] == "DOWNLOAD":
                # 检查是不是有这个站点
                site_info = SitesManager().get_site(siteurl=input_str)
                # 尝试下载种子文件
                result = Downloader().save_torrent_file(url=input_str,
                                                       cookie=site_info.cookie,
                                                       ua=site_info.ua,
                                                       proxy=site_info.proxy)
                filepath = result.file_path
                content = result.content
                retmsg = result.ret_msg

                # 下载种子出错
                if (not content or not filepath) and retmsg:
                    self.__send_channel_msg(title=retmsg)
                    return
                
                # 识别文件名
                filename = os.path.basename(filepath)
                # 识别
                meta_info = Media().get_media_info(title=filename)
                if not meta_info:
                    self.__send_channel_msg(title="无法识别种子文件名！")
                    return
                
                # 开始下载
                meta_info.set_torrent_info(enclosure=input_str)
                Downloader().download(media_info=meta_info,
                                      torrent_file=filepath,
                                      in_from=self.in_from,
                                      user_name=self.user_name)
            # 搜索或订阅
            else:
                log.info("【Searcher】正在识别 %s ..." % input_str)

                # 获取字符串中可能的RSS站点列表
                site_dict = [{"id": site.id, "name": site.name } for site in SitesManager().get_sites(rss=True)]
                rss_sites, content = self.__get_idlist_from_string(input_str, site_dict)

                # 获取字符串中可能的搜索站点列表
                # content = input_str
                indexer_dict = [{ "id": indexer.name, "name": indexer.name } for indexer in Indexer().get_indexers()]
                search_sites, _ = self.__get_idlist_from_string(input_str, indexer_dict)

                # 获取字符串中可能的下载设置
                downloader_dict = [{ "id": dl.get("id"), "name": dl.get("name") } for dl in Downloader().get_download_setting().values()]
                download_setting, content = self.__get_idlist_from_string(content, downloader_dict)
                if download_setting:
                    download_setting = download_setting[0]

                # 识别媒体信息，列出匹配到的所有媒体
                if not content:
                    self.__send_channel_msg(title="无法识别搜索内容！")
                    return

                log.info("【Searcher】正在识别 %s 的媒体信息..." % content)
                # 搜索名称
                medias = SearchProxy().search_media_by_keyword(keyword=content)
                if not medias:
                    # 查询不到媒体信息
                    self.__send_channel_msg(title="%s 查询不到媒体信息！" % content)
                    return
                
                log.info(f"【Searcher】关键字 {content} 共找到{len(medias)}条数据" )
                # 保存识别信息到临时结果中，由于消息长度限制只取前8条
                SEARCH_MEDIA_CACHE[self.user_id] = []
                for meta_info in medias[:8]:
                    # 合并站点和下载设置信息
                    meta_info.rss_sites = rss_sites
                    meta_info.search_sites = search_sites
                    meta_info.set_download_info(download_setting=download_setting)
                    SEARCH_MEDIA_CACHE[self.user_id].append(meta_info)

                if 1 == len(SEARCH_MEDIA_CACHE[self.user_id]):
                    # 只有一条数据，直接开始搜索
                    media_info = SEARCH_MEDIA_CACHE[self.user_id][0]
                    search_media_type = SEARCH_MEDIA_TYPE.get(self.user_id)
                    if not search_media_type or search_media_type == "SEARCH":
                        
                        if media_info.douban_id:
                            # 如果是豆瓣数据，需要重新查询TMDB的数据
                            log.info("【message】豆瓣id: %s" % media_info.douban_id)
                            _title = media_info.get_title_string()
                            media_info = Media().get_mediainfo_from_id('DB:' + media_info.douban_id, mtype=media_info.type)

                            if not media_info or not media_info.tmdb_info:
                                self.__send_channel_msg(title="%s 从TMDB查询不到媒体信息！" % _title)
                                return
                            
                        # 发送消息
                        self.__send_channel_msg(title=media_info.get_title_vote_string(),
                                              text=media_info.get_overview_string(),
                                              image=media_info.get_message_image(),
                                              url=media_info.get_detail_url())
                        # 开始搜索
                        self.__search_media(media_info)
                    else:
                        # 添加订阅
                        self.__add_media_rss(media_info=media_info)
                else:
                    # 发送消息通知选择
                    Message().send_channel_list_msg(channel=self.in_from,
                                                    title="共找到%s条相关信息，请回复对应序号" % len(SEARCH_MEDIA_CACHE[self.user_id]),
                                                    medias=SEARCH_MEDIA_CACHE[self.user_id],
                                                    user_id=self.user_id,
                                                    client_id=self.client_id)
                    
    def __search_media(self, media_info):
        """
        开始搜索和发送消息
        """
        # 检查是否存在，电视剧返回不存在的集清单
        exist_flag, no_exists, messages = Downloader().check_exists_medias(meta_info=media_info)
        if messages:
            self.__send_channel_msg(title="\n".join(messages))

        # 已经存在
        if exist_flag:
            return

        # 开始搜索
        self.__send_channel_msg(title="开始搜索 %s ..." % media_info.title)
        search_result, no_exists, search_count, download_count = SearchProxy().search_one_torrent(media_info=media_info,
                                                                                               in_from=self.in_from,
                                                                                               no_exists=no_exists,
                                                                                               sites=media_info.search_sites,
                                                                                               user_name=self.user_name)
        # 没有搜索到数据
        if not search_count:
            self.__send_channel_msg(title="%s 未搜索到任何资源" % media_info.title)
        else:
            # 搜索到了但是没开自动下载
            if download_count is None:
                self.__send_channel_msg(title="%s 共搜索到%s个资源，点击选择下载" % (media_info.title, search_count),
                                      image=media_info.get_message_image(),
                                      url="search")
                return
            # 搜索到了但是没下载到数据
            if download_count == 0:
                self.__send_channel_msg("%s 共搜索到%s个结果，但没有下载到任何资源" % (media_info.title, search_count))

        # 没有下载完成，且打开了自动添加订阅，添加订阅
        if not search_result and Config().get_config('pt').get('search_no_result_rss'):
            self.__add_media_rss(media_info=media_info, state='R')


    def __add_media_rss(self, media_info, state='D'):
        """
        开始添加订阅和发送消息
        """
        # 添加订阅
        mediaid = f"DB:{media_info.douban_id}" if media_info.douban_id else media_info.tmdb_id
        code, msg, media_info = Subscribe().add_rss_subscribe(media_info=media_info,
                                                              mtype=media_info.type,
                                                              name=media_info.title,
                                                              year=media_info.year,
                                                              channel=RssType.Auto,
                                                              season=media_info.begin_season,
                                                              mediaid=mediaid,
                                                              state=state,
                                                              rss_sites=media_info.rss_sites,
                                                              search_sites=media_info.search_sites,
                                                              download_setting=media_info.download_setting,
                                                              in_from=self.in_from,
                                                              user_name=self.user_name)
        if code == 0:
            log.info("【Web】%s %s 已添加订阅" % (media_info.type.value, media_info.get_title_string()))
        else:
            if self.in_from in Message().get_search_types():
                log.info("【Web】%s 添加订阅失败：%s" % (media_info.title, msg))
                self.__send_channel_msg(title="%s 添加订阅失败：%s" % (media_info.title, msg))


    def __send_channel_msg(self, title, text='', image='', url=''):
        Message().send_channel_msg(title=title,
                                   text=text,
                                   image=image,
                                   url=url,
                                   channel=self.in_from,
                                   user_id=self.user_id,
                                   client_id=self.client_id)
        
    def __get_idlist_from_string(self, content, dicts):
        """
        从字符串中提取id列表
        :param content: 字符串
        :param dicts: 字典
        :return:
        """
        if not content:
            return [], ''
        
        id_list = []
        content_list = content.split()
        for dic in dicts:
            if dic.get('name') in content_list and dic.get('id') not in id_list:
                id_list.append(dic.get('id'))
                content = content.replace(dic.get('name'), '')

        return id_list, re.sub(r'\s+', ' ', content).strip()