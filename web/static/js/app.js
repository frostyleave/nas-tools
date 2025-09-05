// 初始化路由
const router = new Navigo("/", { hash: true });

router
  // 首页
  .on("/index", function () {
    loadPage("/static/pages/index.html");
  })
  .on("/", function () {
    router.navigate("/index");
  })

  // 探索模块
  .on("/ranking", function () {
    loadPage("/static/pages/ranking.html");
  })
  .on("/tv_ranking", function () {
    loadPage("/static/pages/tv_ranking.html");
  })
  .on("/bangumi", function () {
    loadPage("/static/pages/bangumi.html");
  })

  // 资源搜索
  .on("/search", function () {
    loadPage("/static/pages/search.html");
  })

  // 订阅模块
  .on("/movie_rss", function () {
    loadPage("/static/pages/movie_rss.html");
  })
  .on("/tv_rss", function () {
    loadPage("/static/pages/tv_rss.html");
  })
  .on("/user_rss", function () {
    loadPage("/static/pages/user_rss.html");
  })
  .on("/rss_calendar", function () {
    loadPage("/static/pages/rss_calendar.html");
  })

  // 服务
  .on("/service", function () {
    loadPage("/static/pages/service.html");
  })

  // 下载管理
  .on("/downloading", function () {
    loadPage("/static/pages/downloading.html");
  })

  // 文件管理
  .on("/mediafile", function () {
    loadPage("/static/pages/mediafile.html");
  })
  .on("/torrent_remove", function () {
    loadPage("/static/pages/torrent_remove.html");
  })
  .on("/history", function () {
    loadPage("/static/pages/history.html");
  })
  .on("/unidentification", function () {
    loadPage("/static/pages/unidentification.html");
  })
  .on("/tmdbcache", function () {
    loadPage("/static/pages/tmdbcache.html");
  })

  // 系统设置
  .on("/basic", function () {
    loadPage("/static/pages/basic.html");
  })
  .on("/library", function () {
    loadPage("/static/pages/library.html");
  })
  .on("/notification", function () {
    loadPage("/static/pages/notification.html");
  })
  .on("/directorysync", function () {
    loadPage("/static/pages/directorysync.html");
  })
  .on("/filterrule", function () {
    loadPage("/static/pages/filterrule.html");
  })
  .on("/customwords", function () {
    loadPage("/static/pages/customwords.html");
  })

  // 站点管理
  .on("/indexer", function () {
    loadPage("/static/pages/indexer.html");
  })
  .on("/ptindexer", function () {
    loadPage("/static/pages/ptindexer.html");
  })
  .on("/site", function () {
    loadPage("/static/pages/site.html");
  })
  .on("/statistics", function () {
    loadPage("/static/pages/statistics.html");
  })
  .on("/brushtask", function () {
    loadPage("/static/pages/brushtask.html");
  })

  // 插件管理
  .on("/plugin", function () {
    loadPage("/static/pages/plugin.html");
  })

  // 用户管理
  .on("/users", function () {
    loadPage("/static/pages/users.html");
  })

  // 404处理
  .notFound(() => {
    $("#page_content").html("<h3>404 页面不存在</h3>");
  });

function loadPage(htmlPath) {

  // 显示加载动画
  if (NProgress) {
    NProgress.start();
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