// 初始化路由
const router = new Navigo("/", { hash: true });

router
  // 首页
  .on("/", function () {
    router.navigate("/index");
  })
  .on("/index", function (match) {
    loadPage("/static/pages/index.html", match.queryString);
  })
  // 探索模块
  .on("/ranking", function (match) {
    loadPage("/static/pages/ranking.html", match.queryString);
  })
  .on("/tv_ranking", function (match) {
    loadPage("/static/pages/tv_ranking.html", match.queryString);
  })
  .on("/bangumi", function (match) {
    loadPage("/static/pages/bangumi.html", match.queryString);
  })
  .on("/media_detail", function (match) {
    loadPage("/static/pages/mediainfo.html", match.queryString);
  })
  .on("/recommend", function (match) {
    loadPage("/static/pages/recommend.html", match.queryString);
  })
  .on("/discovery_person", function (match) {
    loadPage("/static/pages/person.html", match.queryString);
  })
  // 资源搜索
  .on("/search", function (match) {
    loadPage("/static/pages/search.html", match.queryString);
  })

  // 订阅模块
  .on("/movie_rss", function (match) {
    loadPage("/static/pages/rss.html?t=MOV", match.queryString);
  })
  .on("/tv_rss", function (match) {
    loadPage("/static/pages/rss.html?t=TV", match.queryString);
  })
  .on("/user_rss", function (match) {
    loadPage("/static/pages/user_rss.html", match.queryString);
  })
  .on("/rss_calendar", function (match) {
    loadPage("/static/pages/rss_calendar.html", match.queryString);
  })
  .on("/rss_history", function (match) {
    loadPage("/static/pages/rss_history.html", match.queryString);
  })
  .on("/rss_parser", function (match) {
    loadPage("/static/pages/rss_parser.html", match.queryString);
  })

  // 服务
  .on("/service", function (match) {
    loadPage("/static/pages/service.html", match.queryString);
  })

  // 下载管理
  .on("/downloading", function (match) {
    loadPage("/static/pages/downloading.html", match.queryString);
  })
  // 下载配置
  .on("/download_setting", function (match) {
    loadPage("/static/pages/download_setting.html", match.queryString);
  })
  // 文件管理
  .on("/mediafile", function (match) {
    loadPage("/static/pages/mediafile.html", match.queryString);
  })
  .on("/torrent_remove", function (match) {
    loadPage("/static/pages/torrent_remove.html", match.queryString);
  })
  .on("/history", function (match) {
    loadPage("/static/pages/history.html", match.queryString);
  })
  .on("/unidentification", function (match) {
    loadPage("/static/pages/unidentification.html", match.queryString);
  })
  .on("/tmdbcache", function (match) {
    loadPage("/static/pages/tmdbcache.html", match.queryString);
  })

  // 系统设置
  .on("/basic", function (match) {
    loadPage("/static/pages/basic.html", match.queryString);
  })
  .on("/library", function (match) {
    loadPage("/static/pages/library.html", match.queryString);
  })
  .on("/notification", function (match) {
    loadPage("/static/pages/notification.html", match.queryString);
  })
  .on("/directorysync", function (match) {
    loadPage("/static/pages/directorysync.html", match.queryString);
  })
  .on("/filterrule", function (match) {
    loadPage("/static/pages/filterrule.html", match.queryString);
  })
  .on("/customwords", function (match) {
    loadPage("/static/pages/customwords.html", match.queryString);
  })

  // 站点管理
  .on("/indexer", function (match) {
    loadPage("/static/pages/indexer.html?p=1", match.queryString);
  })
  .on("/ptindexer", function (match) {
    loadPage("/static/pages/indexer.html?p=0", match.queryString);
  })
  .on("/site", function (match) {
    loadPage("/static/pages/site.html", match.queryString);
  })
  .on("/statistics", function (match) {
    loadPage("/static/pages/statistics.html", match.queryString);
  })
  .on("/brushtask", function (match) {
    loadPage("/static/pages/brushtask.html", match.queryString);
  })

  // 唤起App中转页面
  .on("/open", function (match) {
    loadPage("/static/pages/openapp.html", match.queryString);
  })

  // 插件管理
  .on("/plugin", function (match) {
    loadPage("/static/pages/plugin.html", match.queryString);
  })

  // 用户管理
  .on("/users", function (match) {
    loadPage("/static/pages/users.html", match.queryString);
  })

  // 404处理
  .notFound(() => {
    $("#page_content").html(`<system-error title="404" text='没有找到这个页面，请检查是不是输错地址了...'></system-error>`);
  })
  
;
  

function loadPage(htmlPath, queryString) {

  let params = {};
  // 查询参数封装
  if (queryString) {
    queryString.split("&").forEach(kv => {
      let [k, v] = kv.split("=");
      params[k] = v;
    });
  }
  // 优先使用htmlPath中的参数
  const [path, paramString] = htmlPath.split("?");
  if (paramString) {
    paramString.split("&").forEach(kv => {
      let [k, v] = kv.split("=");
      params[k] = v;
    });
  }

  // 把参数挂到容器上
  if (params) {
    $("#page_content").data("params", params);
  }

  // 直接加载HTML文件
  $("#page_content").load(htmlPath, function(_, status, xhr) {

    if (status == "error") {
      $("#page_content").html(`<system-error title="${xhr.status}" text="${xhr.statusText || ''}"></system-error>`);
    } else {
      // 滚动到顶部
      $(window).scrollTop(0);
    }
  });

}

router.resolve();

function navigateTo(target) {
  if (target) {
    var current = router.current && router.current[0];
    // 同页面, 只刷新内容, 不新增历史
    if (current && current.url === target) {
      // 直接调用 handler, 传入当前匹配的数据
      current.route.handler({
        data: current.data,
        params: current.route.params || {},
        queryString: current.queryString,
        hashString: current.hashString
      });
      return;
    } 
    
    // 正常跳转
    router.navigate(target);
  }
};


window.navigateTo = navigateTo;