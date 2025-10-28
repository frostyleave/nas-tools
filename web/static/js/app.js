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
  // 登陆
  .on("/login", function (match) {
    showLogin();
  })
  // 首页
  .on("/index", function (match) {
    loadPage("/static/pages/index.html", match.queryString);
  })
  // 探索模块
  .on("/media_detail", function (match) {
    loadPage("/static/pages/mediainfo.html", match.queryString);
  })
  .on("/recommend", function (match) {
    loadPage("/static/pages/recommend.html", match.queryString);
  })
  .on("/discovery_person", function (match) {
    loadPage("/static/pages/person.html", match.queryString);
  })

  // 订阅模块
  .on("/rss_history", function (match) {
    loadPage("/static/pages/rss_history.html", match.queryString);
  })
  .on("/rss_parser", function (match) {
    loadPage("/static/pages/rss_parser.html", match.queryString);
  })

  // 下载器
  .on("/downloaders", function (match) {
    loadPage("/static/pages/downloaders.html", match.queryString);
  })
  // 下载配置
  .on("/download_setting", function (match) {
    loadPage("/static/pages/download_setting.html", match.queryString);
  })

  // 唤起App中转页面
  .on("/open", function (match) {
    loadPage("/static/pages/openapp.html", match.queryString);
  })

  // 404处理
  .notFound(() => {
    $("#page_content").html(`<system-error title="404" text='没有找到这个页面，请检查是不是输错地址了...'></system-error>`);
  })
  
;

router.resolve();


function showLogin() {

  $('#app-layout').addClass('d-none');
  $('#login-container').removeClass('d-none');
  $("body").addClass("no-after");

  if (typeof hideLoading != 'undefined') {
    // 隐藏等待动画
    hideLoading();
    // 关闭加载标记
    NavPageLoading = false;
  }

}

// SPA页面加载
function loadPage(htmlPath, queryString) {

  $('#login-container').addClass('d-none');
  $('#app-layout').removeClass('d-none');
  $("body").removeClass("no-after");

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

    // 隐藏等待动画
    hideLoading();
    // 关闭加载标记
    NavPageLoading = false;

    // 首次进入页面, 菜单数据没有加载完成
    var navbarMenu = document.querySelector("#navbar-menu")
    if (!navbarMenu || !navbarMenu.navbar_list) {
      $('#top-sub-navbar').hide();
      return;
    }

    var page = window.location.hash;
    if (page && page.startsWith('#/')) {
      page = page.substring(1);
    }

    // 激活菜单
    var pageMenu = getMenuId(page);
    var prevMenu = getMenuId(CurrentPageUri);

    // 记录当前页面ID
    if (page !== CurrentPageUri) {
      CurrentPageUri = page;
    }

    // 刷新子菜单
    if (pageMenu !== prevMenu) {    
      activeMenu(pageMenu);
    }

    if (status == "error") {
      $("#page_content").html(`<system-error title="${xhr.status}" text="${xhr.statusText || ''}"></system-error>`);
    } else {
      // 滚动到顶部
      $(window).scrollTop(0);
    }

    // 加载完成
    renderOther();

  });

}

// 导航菜单点击
function navmenu(page) {
 
  // 修复空格问题
  page = page.replaceAll(" ", "%20");

  // 解除滚动事件
  $(window).unbind('scroll');

  // 停止上一次加载
  if (NavPageXhr && NavPageLoading) {
    NavPageXhr.abort();
  }
  
  // 显示等待动画
  menuSwithWait();

  // 加载新页面
  NavPageLoading = true;

  // 页面切换
  navigateTo(page);

}

// 页面切换
function navigateTo(target) {

  if (target) {

    // 同页面, 只刷新内容, 不新增历史
    if (pageNotChanged(target)) {
      var current = router.current && router.current[0];
      // 直接调用 handler, 传入当前页面的数据
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

}

// 检查页面是否没有变化
function pageNotChanged(target) {

  var current = router.current && router.current[0];
  if (!current) {
    return false;
  }
  
  if (current.hashString && current.hashString.endsWith(target)) {
    return true;
  }

  if (current.queryString) {
    return current.url + '?' + current.queryString === target;
  }

  return current.url === target;

}

// 计算菜单名称
function getMenuId(input) {

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


function renderOther() {

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

  // var $page_title = $('.container-xl .page-header .row .col h2.page-title');
  // if ($page_title) {

  //   if ($('#top-sub-navbar').is(':visible') && $('#top-sub-navbar').find('.tab-text').is(':visible')) {
  //     // 检查是否有按钮
  //     const $container = $page_title.closest('.container-xl');
  //     if ($container.find('.btn-list').length == 0) {
  //       $container.hide();
  //     } else {
  //       $page_title.hide();
  //     }

  //   } else {
  //     $page_title.show();
  //   }
  // }

}

// 刷新子菜单
function activeMenu(pageMenu) {

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

  var navList = [];
  // 找到当前页面菜单配置
  var navbarMenu = document.querySelector("#navbar-menu")
  if (!navbarMenu || !navbarMenu.navbar_list) {
    $('#top-sub-navbar').hide();
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
  if (!navList || navList.length == 0) {
    // 激活主菜单
    navbarMenu.update_active(pageMenu);
    // 隐藏子菜单
    $('#top-sub-navbar').hide();
    return;
  }

  // 获取ul元素
  const ulElement = document.querySelector('#top-sub-navbar ul');
  // 清空现有的li元素
  ulElement.innerHTML = '';

  // 重新绘制子菜单
  navList.forEach(item => {

    const aElement = document.createElement('a');
    aElement.className = 'nav-link';
    aElement.href = 'javascript:void(0)';
    aElement.innerHTML = `<span class="tab-icon">${item.icon}</span><span class="tab-text">${item.name}</span>`;
    aElement.setAttribute('data-id', item.page);
    aElement.onclick = () => navmenu(item.page);

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
  const $navbar = $('#top-sub-navbar');
  if (!$navbar.is(':visible')) return;

  const menu = $navbar.find('.navbar-nav')[0]; // ul.navbar-nav
  if (!menu) return;

  const links = Array.from(menu.querySelectorAll('a.nav-link'));
  if (!links.length) return;

  // 获取父容器可用宽度
  const containerWidth = menu.parentElement.clientWidth;

  // 取 computed gap（可能为空），转换为像素数
  const cs = window.getComputedStyle(menu);
  const gapStr = cs.gap || cs.getPropertyValue('column-gap') || cs.getPropertyValue('grid-column-gap') || '0px';
  const gap = parseFloat(gapStr) || 0;

  // 创建一个测量 wrapper，每次在里面放一组 clone 链接
  const wrapper = document.createElement('div');
  wrapper.style.position = 'absolute';
  wrapper.style.left = '-9999px';
  wrapper.style.top = '0';
  wrapper.style.visibility = 'hidden';
  wrapper.style.display = 'flex';
  wrapper.style.alignItems = 'center';
  wrapper.style.gap = `${gap}px`;
  document.body.appendChild(wrapper);

  // 辅助：克隆单个 link，并设置模式（'BOTH'/'ICON'/'TEXT'）
  function cloneLinkWithMode(link, mode) {
    const c = link.cloneNode(true);
    // ensure inline-flex for spans when needed
    const text = c.querySelector('.tab-text');
    const icon = c.querySelector('.tab-icon');

    if (text) {
      text.style.display = (mode === 'ICON') ? 'none' : 'inline-flex';
    }
    if (icon) {
      icon.style.display = (mode === 'TEXT') ? 'none' : 'inline-flex';
    }

    // reset widths inside clone so offsetWidth measures content size
    c.style.display = 'inline-flex';
    c.style.alignItems = 'center';
    c.style.whiteSpace = 'nowrap';
    c.style.padding = window.getComputedStyle(link).padding;
    return c;
  }

  // 测量三种模式的总宽度（对每个 link 单独测量更稳）
  function measureTotalWidth(mode) {
    // 清空 wrapper
    wrapper.innerHTML = '';
    links.forEach(link => {
      const c = cloneLinkWithMode(link, mode);
      wrapper.appendChild(c);
    });
    // 使用 scrollWidth（包含 gap）更可靠
    return wrapper.scrollWidth;
  }

  const widths = {
    BOTH: measureTotalWidth('BOTH'),
    ICON: measureTotalWidth('ICON'),
    TEXT: measureTotalWidth('TEXT')
  };

  // 移除 wrapper
  document.body.removeChild(wrapper);

  // 选择最佳模式（优先 BOTH -> TEXT -> ICON）
  let bestMode = 'ICON';
  if (widths.BOTH <= containerWidth) {
    bestMode = 'BOTH';
  } else if (widths.TEXT <= containerWidth) {
    bestMode = 'TEXT';
  }

  // 应用到真实 DOM（安全地判断存在性）
  links.forEach(link => {
    const text = link.querySelector('.tab-text');
    const icon = link.querySelector('.tab-icon');
    if (text) text.style.display = (bestMode === 'ICON') ? 'none' : 'inline-flex';
    if (icon) icon.style.display = (bestMode === 'TEXT') ? 'none' : 'inline-flex';
  });
}

// 浏览器回退事件绑定
window.addEventListener('popstate', function (event) {

  var pageMenu = getMenuId(window.location.hash);
  if (!pageMenu) {
    pageMenu = 'index';
  }

  // 刷新子菜单
  activeMenu(pageMenu);

});

// 菜单注册
function registerRouter(user_menus) {

  user_menus.forEach(route => {
    // 有二级菜单
    if (route.nav && route.nav.length > 0) {
      route.nav.forEach(nav => {
        router.on(nav.page, (match) => {
          loadPage(nav.html, match.queryString);
        });
      });
      return;
    }
    // 一级菜单
    router.on(route.page, (match) => {
      loadPage(route.html, match.queryString);
    });

  });

  router.resolve(); 
}

window.navmenu = navmenu;
window.registerRouter = registerRouter;