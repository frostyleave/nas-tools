import pytz
import re
import xml.dom.minidom

from datetime import datetime, timedelta
from threading import Event

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from jinja2 import Template

from app.helper import RssHelper
from app.media import Media
from app.mediaserver import MediaServer
from app.plugins.modules._base import _IPluginModule
from app.subscribe import Subscribe
from app.utils import RequestUtils, DomUtils
from app.utils.types import MediaType, SearchType, RssType
from config import Config
from web.backend.web_utils import WebUtils


class DoubanRank(_IPluginModule):
    # 插件名称
    module_name = "豆瓣榜单订阅"
    # 插件描述
    module_desc = "监控豆瓣热门榜单，自动添加订阅。"
    # 插件图标
    module_icon = "movie.jpg"
    # 主题色
    module_color = "#01B3E3"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    module_config_prefix = "doubanrank_"
    # 加载顺序
    module_order = 16
    # 可使用的用户级别
    auth_level = 2

    # 退出事件
    _event = Event()
    # 私有属性
    mediaserver = None
    subscribe = None
    rsshelper = None
    media = None
    _douban_address = {
        'movie-real-time': { 'addr' : 'https://rsshub.app/douban/movie/weekly/subject_real_time_hotest', 'name' : '实时热门书影音' },
        'movie_weekly_best': { 'addr' : 'https://rsshub.app/douban/movie/movie_weekly_best', 'name' : '一周电影口碑榜' },
        'movie-hot-gaia': { 'addr' : 'https://rsshub.app/douban/movie/weekly/movie_hot_gaia', 'name' : '热门电影' },
        'tv_chinese_best_weekly': { 'addr' : 'https://rsshub.app/douban/movie/weekly/tv_chinese_best_weekly', 'name' : '华语口碑剧集榜' },
        'show-domestic': { 'addr' : 'https://rsshub.app/douban/movie/weekly/show_domestic', 'name' : '热门综艺' },
        'movie-ustop': { 'addr' : 'https://rsshub.app/douban/movie/ustop', 'name' : '北美电影票房榜' },
        'movie-top250': { 'addr' : 'https://rsshub.app/douban/movie/weekly/movie_top250', 'name' : '电影TOP250' },
    }
    _enable = False
    _onlyonce = False
    _cron = ""
    _rss_addrs = []
    _ranks = []
    _vote = 0
    _scheduler = None
    _useproxy = False

    def init_config(self, config: dict = None):
        self.mediaserver = MediaServer()
        self.subscribe = Subscribe()
        self.rsshelper = RssHelper()
        self.media = Media()
        if config:
            self._enable = config.get("enable")
            self._onlyonce = config.get("onlyonce")
            self._useproxy = config.get("useproxy")
            self._cron = self.quartz_cron_compatible(config.get("cron"))
            self._vote = float(config.get("vote")) if config.get("vote") else 0
            rss_addrs = config.get("rss_addrs")
            if rss_addrs:
                if isinstance(rss_addrs, str):
                    self._rss_addrs = rss_addrs.split('\n')
                else:
                    self._rss_addrs = rss_addrs
            else:
                self._rss_addrs = []
            self._ranks = config.get("ranks") or []

        # 停止现有任务
        self.stop_service()

        # 启动服务
        if self.get_state() or self._onlyonce:
            timezone = Config().get_timezone()
            self._scheduler = BackgroundScheduler(timezone=timezone)

            if self._cron:
                self.info(f"订阅服务启动，周期: {self._cron}")
                self._scheduler.add_job(self.__refresh_rss, CronTrigger.from_crontab(self._cron))

            if self._onlyonce:
                self.info("订阅服务启动，立即运行一次")
                self._scheduler.add_job(self.__refresh_rss, 'date',
                                        run_date=datetime.now(tz=pytz.timezone(timezone)) + timedelta(seconds=3))
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config({
                    "onlyonce": False,
                    "enable": self._enable,
                    "cron": self._cron,
                    "ranks": self._ranks,
                    "vote": self._vote,
                    "useproxy": self._useproxy,
                    "rss_addrs": "\n".join(self._rss_addrs)
                })
            if self._scheduler.get_jobs():
                # 启动服务
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self):
        return self._enable and self._cron and (self._ranks or self._rss_addrs)

    @staticmethod
    def get_fields():
        return [
            # 同一板块
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '开启豆瓣榜单订阅',
                            'required': "",
                            'tooltip': '开启后，自动监控豆瓣榜单变化，有新内容时如媒体服务器不存在且未订阅过，则会添加订阅，仅支持rsshub的豆瓣RSS',
                            'type': 'switch',
                            'id': 'enable',
                        }
                    ],
                    [
                        {
                            'title': '立即运行一次',
                            'required': "",
                            'tooltip': '打开后立即运行一次（点击此对话框的确定按钮后即会运行，周期未设置也会运行），关闭后将仅按照刮削周期运行（同时上次触发运行的任务如果在运行中也会停止）',
                            'type': 'switch',
                            'id': 'onlyonce',
                        }
                    ],
                    [
                        {
                            'title': '使用代理',
                            'required': "",
                            'type': 'switch',
                            'id': 'useproxy',
                        }
                    ],
                    [
                        {
                            'title': '刷新周期',
                            'required': "required",
                            'tooltip': '榜单数据刷新的时间周期，支持5位cron表达式；应根据榜单更新的周期合理设置刷新时间，避免刷新过于频繁',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 0 0 ? *',
                                }
                            ]
                        },
                        {
                            'title': '评分',
                            'required': "",
                            'tooltip': '大于该评分的才会被订阅（以TMDB评分为准），不填则不限制',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'vote',
                                    'placeholder': '0',
                                }
                            ]
                        }
                    ],
                    [
                        {
                            'title': 'RssHub订阅地址',
                            'required': '',
                            'tooltip': '每一行一个RSS地址，访问 https://docs.rsshub.app/routes/social-media#豆瓣 查询可用地址',
                            'type': 'textarea',
                            'content':
                                {
                                    'id': 'rss_addrs',
                                    'placeholder': 'https://rsshub.app/douban/movie/classification/:sort?/:score?/:tags?',
                                    'rows': 5
                                }
                        }
                    ]
                ]
            },
            {
                'type': 'details',
                'summary': '热门榜单',
                'tooltip': '内建支持的豆瓣榜单，使用https://rsshub.app数据源，可直接选择订阅',
                'content': [
                    # 同一行
                    [
                        {
                            'id': 'ranks',
                            'type': 'form-selectgroup',
                            'content': {
                                'movie_weekly_best': {
                                    'id': 'movie_weekly_best',
                                    'name': '一周电影口碑榜',
                                },
                                'movie-hot-gaia': {
                                    'id': 'movie-hot-gaia',
                                    'name': '热门电影',
                                },
                                'tv_chinese_best_weekly': {
                                    'id': 'tv_chinese_best_weekly',
                                    'name': '华语口碑剧集榜',
                                },
                                'movie-ustop': {
                                    'id': 'movie-ustop',
                                    'name': '北美电影票房榜',
                                },
                                'show-domestic': {
                                    'id': 'show-domestic',
                                    'name': '热门综艺',
                                },
                                'movie-top250': {
                                    'id': 'movie-top250',
                                    'name': '电影TOP250',
                                },
                                'movie-real-time': {
                                    'id': 'movie-real-time',
                                    'name': '实时热门书影音',
                                }
                            }
                        },
                    ]
                ]
            }
        ]

    def get_page(self):
        """
        插件的额外页面，返回页面标题和页面内容
        :return: 标题，页面内容，确定按钮响应函数
        """
        results = self.get_history()
        template = """
             <div class="table-responsive table-modal-body">
               <table class="table table-vcenter card-table table-hover table-striped">
                 <thead>
                 <tr>
                   <th></th>
                   <th>标题</th>
                   <th>类型</th>
                   <th>状态</th>
                   <th>添加时间</th>
                   <th></th>
                 </tr>
                 </thead>
                 <tbody>
                 {% if HistoryCount > 0 %}
                   {% for Item in DoubanRankHistory %}
                     <tr id="movie_rank_history_{{ Item.id }}">
                       <td class="w-5">
                         <img class="rounded w-5" src="{{ Item.image }}"
                              onerror="this.src='../static/img/no-image.svg'" alt=""
                              style="min-width: 50px"/>
                       </td>
                       <td>
                         <div>{{ Item.name }} ({{ Item.year }})</div>
                         {% if Item.rating %}
                           <div class="text-muted text-nowrap">
                           评份: {{ Item.rating }}
                           </div>
                         {% endif %}
                       </td>
                       <td>
                         {{ Item.type }}
                       </td>
                       <td>
                         {% if Item.state == 'DOWNLOADED' %}
                           <span class="badge bg-green">已下载</span>
                         {% elif Item.state == 'RSS' %}
                           <span class="badge bg-blue">已订阅</span>
                         {% elif Item.state == 'NEW' %}
                           <span class="badge bg-blue">新增</span>
                         {% else %}
                           <span class="badge bg-orange">处理中</span>
                         {% endif %}
                       </td>
                       <td>
                         <small>{{ Item.add_time or '' }}</small>
                       </td>
                       <td>
                         <div class="dropdown">
                           <a href="#" class="btn-action" data-bs-toggle="dropdown"
                              aria-expanded="false">
                             <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-dots-vertical {{ class }}"
                                  width="24" height="24" viewBox="0 0 24 24"
                                  stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">
                               <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>
                               <circle cx="12" cy="12" r="1"></circle>
                               <circle cx="12" cy="19" r="1"></circle>
                               <circle cx="12" cy="5" r="1"></circle>
                             </svg>
                           </a>
                           <div class="dropdown-menu dropdown-menu-end">
                             <a class="dropdown-item text-danger"
                                href='javascript:DoubanRank_delete_history("{{ Item.id }}")'>
                               删除
                             </a>
                           </div>
                         </div>
                       </td>
                     </tr>
                   {% endfor %}
                 {% else %}
                   <tr>
                     <td colspan="6" align="center">没有数据</td>
                   </tr>
                 {% endif %}
                 </tbody>
               </table>
             </div>
           """
        return "订阅历史", Template(template).render(HistoryCount=len(results),
                                                     DoubanRankHistory=results), None

    @staticmethod
    def get_script():
        """
        删除榜单订阅历史记录的JS脚本
        """
        return """
          // 删除榜单订阅历史记录
          function DoubanRank_delete_history(id){
            axios_post_do("run_plugin_method", {"plugin_id": 'DoubanRank', 'method': 'delete_rank_history', 'tmdb_id': id}, function (ret) {
              $("#movie_rank_history_" + id).remove();
            });

          }
        """

    def delete_rank_history(self, tmdb_id):
        """
        删除同步历史
        """
        return self.delete_history(key=tmdb_id)

    def __update_history(self, media, state):
        """
        插入历史记录
        """
        if not media:
            return
        value = {
            "id": media.tmdb_id,
            "name": media.title,
            "year": media.year,
            "type": media.type.value,
            "rating": media.vote_average or 0,
            "image": media.get_poster_image(),
            "state": state,
            "add_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        if self.get_history(key=media.tmdb_id):
            self.update_history(key=media.tmdb_id, value=value)
        else:
            self.history(key=media.tmdb_id, value=value)

    def stop_service(self):
        """
        停止服务
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))

    def __refresh_rss(self):
        """
        刷新RSS
        """
        self.info(f"开始刷新RSS ...")

        for rank_id in self._ranks:
            addr_info = self._douban_address.get(rank_id, {})
            if not addr_info or not addr_info.get('addr'):
                continue
            self.__try_do_rss_subscribe(addr_info.get('addr'), addr_info.get('name'))

        if self._rss_addrs:
            for addr in self._rss_addrs:
                if not addr:
                    continue
                self.__try_do_rss_subscribe(addr, '榜单(自定义)')

        self.info(f"所有RSS刷新完成")

    def __try_do_rss_subscribe(self, addr, rss_name=''):
        try:
            self.info(f"获取RSS: {addr} ...")
            rss_infos = self.__get_rss_info(addr)
            if not rss_infos:
                self.error(f"RSS地址: {addr} ，未查询到数据")
                return
            else:
                self.info(f"RSS地址: {addr} ，共 {len(rss_infos)} 条数据")
            for rss_info in rss_infos:
                if self._event.is_set():
                    self.info(f"订阅服务停止")
                    return

                title = rss_info.get('title')
                douban_id = rss_info.get('doubanid')

                if not douban_id:
                    self.info(f"{title}: 没有返回豆瓣id, 不进行识别订阅")
                    continue
             
                # 识别媒体信息
                # 检查是否已处理过
                unique_flag = f"doubanrank: {title} (DB:{douban_id})"
                if self.rsshelper.is_rssd_by_simple(torrent_name=unique_flag, enclosure=None):
                    self.info(f"已处理过: {title} (豆瓣id: {douban_id})")
                    continue
                # 查询媒体信息
                media_info = WebUtils.get_mediainfo_from_id(mediaid=f"DB:{douban_id}", wait=True)
                if not media_info:
                    self.warn(f"未查询到媒体信息: {title} (豆瓣id: {douban_id})")
                    continue

                if self._vote and media_info.vote_average and media_info.vote_average < self._vote:
                    self.info(f"{media_info.get_title_string()} 评分 {media_info.vote_average} 低于限制 {self._vote}, 跳过...")
                    continue

                # 检查媒体资源是否存在
                item_id = self.mediaserver.check_item_exists(mtype=media_info.type,
                                                             title=media_info.title,
                                                             year=media_info.year,
                                                             tmdbid=media_info.tmdb_id,
                                                             season=media_info.get_season_seq())
                if item_id:
                    self.info(f"媒体服务器已存在: {media_info.get_title_string()}")
                    self.__update_history(media=media_info, state="DOWNLOADED")
                    continue

                season = media_info.get_season_string()
                # 检查是否已订阅过
                if self.subscribe.check_history(media_info.tmdb_id, season=season):
                    self.info(f"{media_info.get_title_string()}{season} 已订阅过")
                    self.__update_history(media=media_info, state="RSS")
                    continue

                if media_info.type:
                    if media_info.type == MediaType.MOVIE:
                        if self.subscribe.check_movie_in_rss(media_info.tmdb_id):
                            self.info(f"[电影]{title} 已在订阅中")
                            self.__update_history(media=media_info, state="RSS")
                            return
                    elif self.subscribe.check_tv_in_rss(media_info.tmdb_id, season=season):
                        self.info(f"[剧集]{title} 已在订阅中")
                        self.__update_history(media=media_info, state="RSS")
                        return

                # 添加处理历史
                self.rsshelper.simple_insert_rss_torrents(title=unique_flag, enclosure=None)
                # 添加订阅
                code, msg, rss_media = self.subscribe.add_rss_subscribe(
                    media_info=media_info,
                    mediaid=f"DB:{douban_id}",
                    mtype=media_info.type,
                    name=media_info.title,
                    year=media_info.year,
                    season=media_info.begin_season,
                    channel=RssType.Auto,
                    in_from= rss_name if rss_name else SearchType.PLUGIN
                )
                if not rss_media or code != 0:
                    self.warn("%s 添加订阅失败: %s" % (media_info.get_title_string(), msg))
                    # 订阅已存在
                    if code == 9:
                        self.__update_history(media=media_info, state="RSS")
                else:
                    self.info("%s 添加订阅成功" % media_info.get_title_string())
                    self.__update_history(media=media_info, state="RSS")
        except Exception as e:
            self.error(str(e))

    def __get_rss_info(self, addr):
        """
        获取RSS
        """
        try:
            proxy = Config().get_proxies() if self._useproxy else None
            ret = RequestUtils(proxies=proxy).get_res(addr)
            if not ret:
                self.error(f"开始请求订阅链接 {addr} 失败")
                return []
            ret.encoding = ret.apparent_encoding
            ret_xml = ret.text
            ret_array = []
            # 解析XML
            dom_tree = xml.dom.minidom.parseString(ret_xml)
            rootNode = dom_tree.documentElement
            items = rootNode.getElementsByTagName("item")
            for item in items:
                try:
                    # 标题
                    title = DomUtils.tag_value(item, "title", default="")
                    # 链接
                    link = DomUtils.tag_value(item, "link", default="")
                    if not title and not link:
                        self.warn(f"条目标题和链接均为空，无法处理")
                        continue
                    doubanid = re.findall(r"/(\d+)/", link)
                    if doubanid:
                        doubanid = doubanid[0]
                    if doubanid and not str(doubanid).isdigit():
                        self.warn(f"解析的豆瓣ID格式不正确: {doubanid}")
                        continue
                    # 返回对象
                    ret_array.append({
                        'title': title,
                        'link': link,
                        'doubanid': doubanid
                    })
                except Exception as e1:
                    self.error("解析RSS条目失败: " + str(e1))
                    continue
            return ret_array
        except Exception as e:
            self.error("获取RSS失败: " + str(e))
            return []
