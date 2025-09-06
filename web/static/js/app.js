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

  // 服务
  .on("/service", function (match) {
    loadPage("/static/pages/service.html", match.queryString);
  })

  // 下载管理
  .on("/downloading", function (match) {
    loadPage("/static/pages/downloading.html", match.queryString);
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
    $("#page_content").html("<h3>404 页面不存在</h3>");
  });

function loadPage(htmlPath, queryString) {

  // 显示加载动画
  if (NProgress) {
    NProgress.start();
  }

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
      $("#page_content").html(`
        <div class="container-xl">
          <div class="empty">
            <div class="empty-img">
              <img src="/static/img/undraw_page_not_found_su7k.svg" height="128" alt="">
            </div>
            <p class="empty-title">页面加载失败</p>
            <p class="empty-subtitle text-muted">
              ${xhr.status} ${xhr.statusText}
            </p>
            <div class="empty-action">
              <a href="#/index" class="btn btn-primary">
                返回首页
              </a>
            </div>
          </div>
        </div>
      `);
    } else {

      // 页面加载成功后，刷新相关组件
      if (typeof fresh_tooltip === 'function') {
        fresh_tooltip();
      }
      if (typeof init_filetree_element === 'function') {
        init_filetree_element();
      }

      // 滚动到顶部
      $(window).scrollTop(0);
    }
  });

  if (NProgress) {
    NProgress.done();
  }
  
}

router.resolve();

function navigateTo(path) {
  if (path) {
    router.navigate(path);
  }
};


window.navigateTo = navigateTo;