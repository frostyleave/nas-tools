from datetime import datetime
from threading import Event

from jinja2 import Template

from app.helper import RssHelper
from app.helper import ThreadHelper
from app.media.meta.metainfo import MetaInfo
from app.media.tmdbv3api.objs.movie import Movie
from app.mediaserver import MediaServer
from app.plugins.modules._base import _IPluginModule
from app.subscribe import Subscribe
from app.utils.types import MediaType, RssType

class TmdbHotMovieRank(_IPluginModule):
    # 插件名称
    module_name = "TMDB热门电影"
    # 插件描述
    module_desc = "监控TMDB热门电影, 自动添加订阅。"
    # 插件图标
    module_icon = "tmdb.png"
    # 主题色
    module_color = "#01B3E3"
    # 插件版本
    module_version = "1.0"
    # 插件作者
    module_author = "frostyleave"
    # 作者主页
    author_url = "https://github.com/frostyleave"
    # 插件配置项ID前缀
    module_config_prefix = "tmdb_hot_movie_"
    # 加载顺序
    module_order = 18
    # 可使用的用户级别
    auth_level = 2

    # 退出事件
    _event = Event()
    # 私有属性
    mediaserver = None
    subscribe = None
    rsshelper = None
    movie = None

    _enable = False
    _onlyonce = False
    _cron = ""
    _vote = 0

    def init_config(self, config: dict = None):
        self.mediaserver = MediaServer()
        self.subscribe = Subscribe()
        self.rsshelper = RssHelper()
        self.movie = Movie()
        if config:
            self._enable = config.get("enable")
            self._onlyonce = config.get("onlyonce")
            self._cron = self.quartz_cron_compatible(config.get("cron"))
            self._vote = float(config.get("vote")) if config.get("vote") else 0

        # 停止现有任务
        self.stop_service()

        # 启动服务
        if self.get_state() or self._onlyonce:
            if self._cron:
                self._cron_job = self.add_cron_job(self.__refresh_rank, self._cron, 'TMDB热门电影订阅')

            if self._onlyonce:
                self.info("TMDB热门电影订阅服务启动，立即运行一次")
                ThreadHelper.start_thread(self.__refresh_rank, ())
                # 关闭一次性开关
                self._onlyonce = False
                self.update_config({
                    "onlyonce": False,
                    "enable": self._enable,
                    "cron": self._cron,
                    "vote": self._vote
                })

    def get_state(self):
        return self._enable and self._cron

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
                            'title': '开启TMDB热门电影订阅',
                            'required': "",
                            'tooltip': '开启后，自动监控TMDB热门电影变化，有新内容时如媒体服务器不存在且未订阅过，则会添加订阅',
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
                   {% for Item in TmdbHotMovieHistory %}
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
        return "订阅历史", Template(template).render(HistoryCount=len(results), TmdbHotMovieHistory=results), None

    @staticmethod
    def get_script():
        """
        删除榜单订阅历史记录的JS脚本
        """
        return """
          // 删除榜单订阅历史记录
          function TmdbHotMovie_delete_history(id){
            axios_post_do("run_plugin_method", {"plugin_id": 'TmdbHotMovie', 'method': 'delete_rank_history', 'tmdb_id': id}, function (ret) {
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
            self.remove_job(self._cron_job)
        except Exception as e:
            print(str(e))

    def __refresh_rank(self):
        """
        刷新榜单
        """
        try:
            rank_list = self.movie.popular()
            if not rank_list:
                self.error(f"未查TMDB热门电影询到数据")
                return
            else:
                self.info(f"TMDB热门电影 共 {len(rank_list)} 条数据")
            for tmdb_info in rank_list:
                if self._event.is_set():
                    self.info(f"订阅服务已停止")
                    return

                tmdb_id = tmdb_info.id
                title = tmdb_info.title

                if not tmdb_id:
                    self.info(f"{title}: 没有返回tmdb id, 不进行识别订阅")
                    continue
             
                # 识别媒体信息
                # 检查是否已处理过
                unique_flag = f"tmdb_hot_movie: {title} ({tmdb_id})"
                if self.rsshelper.is_rssd_by_simple(torrent_name=unique_flag, enclosure=None):
                    self.info(f"已处理过: {title} (tmdb id: {tmdb_id})")
                    continue
                
                vote = tmdb_info.vote_average
                if self._vote and vote < self._vote:
                    self.info(f"{title} 评分 {vote} 低于限制 {self._vote}, 跳过...")
                    continue

                year = tmdb_info.release_date[0:4]
                item_id = self.mediaserver.check_item_exists(mtype=MediaType.MOVIE,
                                                             title=title,
                                                             year=year,
                                                             tmdbid=tmdb_id)

                media_info = MetaInfo(title=title, mtype=MediaType.MOVIE)
                media_info.set_tmdb_info(tmdb_info)

                if item_id:
                    self.info(f"媒体服务器已存在: {title}")
                    self.__update_history(media=media_info, state="DOWNLOADED")
                    continue

                # 检查是否已订阅过
                if self.subscribe.check_history(tmdb_id):
                    self.info(f"{title} 已订阅过")
                    self.__update_history(media=media_info, state="RSS")
                    continue
                
                if self.subscribe.check_movie_in_rss(media_info.tmdb_id):
                    self.info(f"{title} 已订阅")
                    self.__update_history(media=media_info, state="RSS")
                    continue

                # 添加处理历史
                self.rsshelper.simple_insert_rss_torrents(title=unique_flag, enclosure=None)
                # 添加订阅
                code, msg, rss_media = self.subscribe.add_rss_subscribe(
                    media_info=media_info,
                    mtype=MediaType.MOVIE,
                    mediaid=item_id,
                    name=title,
                    year=year,
                    channel=RssType.Auto,
                    in_from='TMDB热门电影订阅'
                )
                if not rss_media or code != 0:
                    self.warn("%s 添加订阅失败: %s" % (title, msg))
                    # 订阅已存在
                    if code == 9:
                        self.__update_history(media=media_info, state="RSS")
                else:
                    self.info("%s 添加订阅成功" % title)
                    self.__update_history(media=media_info, state="RSS")
        except Exception as e:
            self.error(str(e))

        self.info(f"刷新完成")