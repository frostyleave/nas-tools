// 页面正在加载中的标志
let NavPageLoading = false;
// 加载中页面的字柄
let NavPageXhr;
// 是否允许打断弹窗
let GlobalModalAbort = true;

// 当前页面地址
let CurrentPageUri = "";

// 初始化路由
const router = new Navigo("/", { hash: true });

router
  // 首页
  // .on("/", function () {
  //   router.navigate("/index");
  // })
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
  
// SPA页面加载
function loadPage(htmlPath, queryString) {

  let params = {};
  // 把htmlPath中的参数把参数挂到容器上
  const [path, paramString] = htmlPath.split("?");
  if (paramString) {
    paramString.split("&").forEach(kv => {
      let [k, v] = kv.split("=");
      params[k] = v;
    });
  }
  $("#page_content").data("params", params);

  // 直接加载HTML文件
  $("#page_content").load(htmlPath, function(_, status, xhr) {

    // 首次进入页面, 菜单数据没有加载完成
    var navbarMenu = document.querySelector("#navbar-menu")
    if (!navbarMenu || !navbarMenu.navbar_list) {
      return;
    }

    var page = window.location.hash;
    if (page && page.startsWith('#/')) {
      page = page.substring(1);
    }

    // 激活菜单
    var pageMenu = get_menu_id(page);
    var prevMenu = get_menu_id(CurrentPageUri);

    // 记录当前页面ID
    if (page !== CurrentPageUri) {
      CurrentPageUri = page;
    }

    // 刷新子菜单
    if (pageMenu !== prevMenu) {    
      active_menu(pageMenu);
    }

    // 隐藏等待动画
    hide_loading();
    // 关闭加载标记
    NavPageLoading = false;

    if (status == "error") {
      $("#page_content").html(`<system-error title="${xhr.status}" text="${xhr.statusText || ''}"></system-error>`);
    } else {
      // 滚动到顶部
      $(window).scrollTop(0);
    }

    // 加载完成
    render_other();

  });

}

// 页面切换
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

// 计算菜单名称
function get_menu_id(input) {

  if (!input) return '';

  // 移除开头的 # 或 /
  let path = input.replace(/^[#\/]+/, '');

  // 查找 ? 的位置
  const queryIndex = path.indexOf('?');
  if (queryIndex !== -1) {
    path = path.substring(0, queryIndex);
  }

  return path;
}

// 导航菜单点击
function navmenu(page) {
 
  // 修复空格问题
  page = page.replaceAll(" ", "%20");

  // 移除/
  if (page.startsWith('/')) {
    page = page.substring(1);
  }

  // 主动点击时清除页码, 刷新页面也需要清除
  sessionStorage.removeItem("CurrentPage");

  // 解除滚动事件
  $(window).unbind('scroll');

  // 停止上一次加载
  if (NavPageXhr && NavPageLoading) {
    NavPageXhr.abort();
  }
  // 显示等待动画
  menu_swith_wait();

  // 加载新页面
  NavPageLoading = true;

  // 页面切换
  navigateTo(page);

}

function render_other() {

  // 修复登录页面刷新问题
  if (document.title === "登录 - NAStool") {
    // 刷新页面
    window.location.reload();
  } else {
    // 关掉已经打开的弹窗
    if (GlobalModalAbort && $(".modal")) {
      $(".modal").modal("hide");
    }
    // 刷新tooltip
    fresh_tooltip();
    // 刷新filetree控件
    init_filetree_element();
  }

}

// 刷新子菜单
function active_menu(pageMenu) {

  // 子菜单当前可见
  if ($('#top-sub-navbar').is(':visible')) {

    let navLinks = document.querySelectorAll('#top-sub-navbar a');
    if (navLinks) {
      // 移除活动标记
      $(navLinks).removeClass('active');
      let selectNav = Array.from(navLinks).find(link => link.getAttribute('data-id') === pageMenu);
      // 子菜单切换, 无需额外处理
      if (selectNav) {
        // 添加活动标记
        $(selectNav).addClass('active');
        return;
      }
    }

  }

  // 当前子菜单不可见，或点击的菜单不在子菜单中，说明是大菜单切换，需要重绘或者清空子菜单

  // 获取ul元素
  const ulElement = document.querySelector('#top-sub-navbar ul');
  // 清空现有的li元素
  ulElement.innerHTML = '';

  var navList = [];
  // 找到当前页面菜单配置
  var navbarMenu = document.querySelector("#navbar-menu")
  if (!navbarMenu || !navbarMenu.navbar_list) {
    return;
  }

  var currentMenu = navbarMenu.navbar_list.find(item => item.page === pageMenu);
  if (currentMenu) {
    // 激活主菜单
    navbarMenu.update_active(pageMenu);
    navList = currentMenu.nav;
  } else {
    // 找不到当前菜单，说是子菜单刷新页面
    for (var menuItem of navbarMenu.navbar_list) {
      if (menuItem.nav) {
        if (menuItem.nav.find(navItem => navItem.page === pageMenu)) {
          // 激活主菜单
          navbarMenu.update_active(menuItem.page);
          navList = menuItem.nav;
          break;
        }
      }
    }
  }

  // 没有子菜单
  if (!navList) {
    // 激活主菜单
    navbarMenu.update_active(pageMenu);
    // 隐藏子菜单
    $('#top-sub-navbar').hide();
    return;
  }

  // 重新绘制子菜单
  navList.forEach(item => {

    const aElement = document.createElement('a');
    aElement.className = 'nav-link top-nav-link';
    aElement.href = '#';
    aElement.innerHTML = `<span class="tab-icon" style="color:var(--tblr-body-color);display: inline-flex;align-items: anchor-center;">${item.icon}</span><span class="tab-text">${item.name}</span>`;
    aElement.setAttribute('data-bs-toggle', 'tab');
    aElement.setAttribute('data-id', item.page);
    aElement.onclick = () => navmenu(item.page); // 根据 item.page 设定点击行为

    if (pageMenu == item.page) {
      aElement.classList.add('active');
    }

    const liElement = document.createElement('li');
    liElement.className = 'nav-item';
    liElement.appendChild(aElement);
    ulElement.appendChild(liElement);

  });

  $('#top-sub-navbar').show();
  // 更新元素菜单显隐
  update_tab_display();

}

// 更新子菜单图标、名称显示
function update_tab_display() {

    if (!$('#top-sub-navbar').is(':visible')) {
      return;
    }

    const menu = document.querySelector('.nav.nav-tabs');
    if (!menu) return;

    // 克隆原始菜单用于测量（避免污染实际DOM）
    const clone = menu.cloneNode(true);
    clone.style.visibility = 'hidden';
    document.body.appendChild(clone);

    // 初始化测量元素
    const items = Array.from(clone.querySelectorAll('.nav-item'));
    const links = items.map(item => item.querySelector('.nav-link'));
    const textElements = links.map(link => link.querySelector('.tab-text'));
    const iconElements = links.map(link => link.querySelector('.tab-icon'));

    // 测量模式函数（返回总宽度）
    function measureMode(mode) {
      textElements.forEach(el => el.style.display =
        mode === 'ICON' ? 'none' : 'inline-flex');
      iconElements.forEach(el => el.style.display =
        mode === 'TEXT' ? 'none' : 'inline-flex');

      return Array.from(clone.querySelectorAll('.nav-item'))
        .reduce((sum, item) => sum + item.offsetWidth, 0);
    }

    // 获取容器可用宽度
    const containerWidth = menu.parentElement.offsetWidth;

    // 按优先级测量三种模式
    const modeWidths = {
      BOTH: measureMode('BOTH'),
      ICON: measureMode('ICON'),
      TEXT: measureMode('TEXT')
    };

    // 移除克隆体
    document.body.removeChild(clone);

    // 选择最佳显示模式
    let bestMode = 'ICON'; // 默认图标模式
    if (modeWidths.BOTH <= containerWidth) {
      bestMode = 'BOTH';
    } else if (modeWidths.TEXT <= containerWidth) {
      bestMode = 'TEXT';
    }

    // 应用最终模式
    menu.querySelectorAll('.nav-item').forEach((item, index) => {
      item.querySelector('.tab-text').style.display =
        bestMode === 'ICON' ? 'none' : 'inline-flex';
      item.querySelector('.tab-icon').style.display =
        bestMode === 'TEXT' ? 'none' : 'inline-flex';
    });
}

// 浏览器回退事件绑定
window.addEventListener('popstate', function (event) {

  // 解除滚动事件
  $(window).unbind('scroll');

  var pageMenu = get_menu_id(window.location.hash);
  if (!pageMenu) {
    pageMenu = 'index';
  }
  // 刷新子菜单
  active_menu(pageMenu);

});

router.resolve();

// 暴露菜单点击函数
window.navmenu = navmenu;