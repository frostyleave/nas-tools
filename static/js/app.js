// 页面正在加载中的标志
let NavPageLoading = false;
// 页面切换占用的加载遮罩令牌
let PageLoadingToken = null;
// 加载中页面的字柄
let NavPageXhr;
// 是否允许打断弹窗
let GlobalModalAbort = true;

// 当前页面地址
let CurrentPageUri = "";

// 初始页面是否已由顶部 router.resolve() 加载
// 用于避免 registerRouter() 再次 resolve 同一个固定路由，导致页面片段重复加载
let InitialPageLoadStarted = false;

// 页面在菜单创建前已加载时，等待菜单就绪后再补执行菜单激活和页面后处理
let PendingPageState = false;

// 菜单切换序号：每次点击菜单自增，页面加载完成时仅最新一次切换播液态过渡
let PageLiquidSeq = 0;

// 轮询管理器：收集所有需要停止的函数
const PollingManager = {
  // key -> stopFunction
  _pollings: new Map(),

  // 启动一个轮询，如果 key 已存在，自动停止旧的再建新的
  start(key, fn, interval) {
    this.stop(key);  // 替换旧轮询

    let active = true;
    let timer = null;

    const run = () => {
      if (!active) return;
      fn().finally(() => {
        if (active) timer = setTimeout(run, interval);
      });
    };

    const stop = () => {
      active = false;
      clearTimeout(timer);
      timer = null;
    };

    // 立即启动
    run();

    // 注册停止函数
    this._pollings.set(key, stop);
  },

  // 停止指定 key 的轮询
  stop(key) {
    const stopFn = this._pollings.get(key);
    if (stopFn) {
      stopFn();
      this._pollings.delete(key);
    }
  },

  // 停止全部轮询（用于路由切换）
  stopAll() {
    for (const [key, stop] of this._pollings) {
      stop();
    }
    this._pollings.clear();
  }
};

/**
 * 页面只需调用这个函数，无需关心清理
 * @param {string}   key      - 轮询标识（同一页面多次调用且 key 相同时会自动替换）
 * @param {Function} fn       - 要执行的异步函数（需返回 Promise）
 * @param {number}   interval - 间隔毫秒
 */
function startPolling(key, fn, interval) {
  PollingManager.start(key, fn, interval);
}

// 页面级流式请求管理器：页面切换时中止未完成的 fetch 流
const PageStreamManager = {
  _controllers: new Set(),

  // 注册一个流式请求，返回 AbortController
  register() {
    const controller = new AbortController();
    this._controllers.add(controller);
    return controller;
  },

  // 请求结束（正常/异常）时释放
  release(controller) {
    this._controllers.delete(controller);
  },

  // 中止全部流式请求（用于路由切换）
  abortAll() {
    for (const controller of this._controllers) {
      controller.abort();
    }
    this._controllers.clear();
  }
};
window.PageStreamManager = PageStreamManager;

// 导航参数仓库
// 页面参数不再拼接到 hash 上，统一保存在内存和 sessionStorage 中：
// - 内存用于常规页面跳转；
// - sessionStorage 用于刷新后恢复（按页面路径分别保存，各标签页互不影响）；
// - history.state 为每个历史条目保存一份，保证前进/后退能拿到对应参数。
const NavParams = (() => {
  const STORAGE_PREFIX = "nav_params:";
  const mem = {};

  return {
    set(path, params) {
      mem[path] = params || {};
      try {
        sessionStorage.setItem(STORAGE_PREFIX + path, JSON.stringify(mem[path]));
      } catch (e) {
        // 隐私模式或存储已满时忽略，仅使用内存
      }
    },

    get(path) {
      if (mem[path]) {
        return mem[path];
      }
      let params = {};
      try {
        params = JSON.parse(sessionStorage.getItem(STORAGE_PREFIX + path) || "{}") || {};
      } catch (e) {
        params = {};
      }
      mem[path] = params;
      return params;
    }
  };
})();

// 解析查询字符串为对象（键值自动解码）
function parseQueryString(queryString) {
  const params = {};
  if (!queryString) {
    return params;
  }
  new URLSearchParams(queryString).forEach((value, key) => {
    params[key] = value;
  });
  return params;
}

// 读取当前页面参数
// loadPage 已把菜单 html 中的静态参数与导航参数合并好，页面直接使用即可
function getPageParams() {
  return $("#page-content").data("params") || {};
}
window.getPageParams = getPageParams;

// 更新当前页面参数（页面内局部刷新时使用）
// 不触达路由、不新增历史条目，只替换当前历史条目，保证刷新/前进后退能恢复最新状态
function setPageParams(params) {
  const path = getMenuId(window.location.hash);
  const next = Object.assign({}, $("#page-content").data("params") || {}, params || {});

  NavParams.set(path, next);
  $("#page-content").data("params", next);

  try {
    const state = Object.assign({}, history.state);
    if (Object.keys(next).length > 0) {
      state.navParams = next;
    } else {
      delete state.navParams;
    }
    history.replaceState(state, "");
  } catch (e) {
    // 部分环境禁止 replaceState，忽略即可
  }
}
window.setPageParams = setPageParams;

// 页面注册"局部刷新"函数：window_history_refresh() 会优先调用它，
// 避免为了刷新表格而整页重新注入（会闪烁、丢滚动位置、重新请求页面片段）
function setPageRefreshHandler(handler) {
  window.pageRefreshHandler = typeof handler === "function" ? handler : null;
}
window.setPageRefreshHandler = setPageRefreshHandler;

// 刷新后 history.state 仍会保留，先把参数同步到内存，供首次页面加载使用
(function () {
  if (history.state && history.state.navParams) {
    NavParams.set(getMenuId(window.location.hash), history.state.navParams);
  }
})();

// 前进/后退时浏览器已先更新好地址和 state，这里在 Navigo 处理之前把参数同步到内存，
// 并清掉 Navigo 缓存的当前路由：
// 同路径不同参数的历史条目在 URL 上完全相同，Navigo 会认为"路由未变化"而跳过 handler，
// 清掉缓存可强制它完整走一次路由解析，保证页面按对应参数重新加载。
// 本监听器必须先于 Navigo 注册（在其构造函数中注册），否则执行顺序不保证。
window.addEventListener("popstate", function (event) {
  if (event.state) {
    NavParams.set(getMenuId(window.location.hash), event.state.navParams || {});
  }
  router._setCurrent(null);
});

// 初始化路由
const router = new Navigo("/", { hash: true });

// 已在下方以固定路由注册过的页面
// registerRouter 按菜单再次注册同一路径时，Navigo 会保留两个 handler，
// 导致同一次路由解析触发两次 loadPage（页面片段和接口都会重复请求）
const FixedRoutePages = new Set([
  "login", 
  "index", 
  "media_detail", 
  "recommend", 
  "discovery_person",
  "rss_history", 
  "rss_parser", 
  "downloaders", 
  "download_setting",
  "download_history", 
  "open"
]);

router
  // 切换页面，停掉所有轮询
  .hooks({
    before(done) {
      PollingManager.stopAll();
      PageStreamManager.abortAll();
      done();
    }
  })
  // 登陆
  .on("/login", function (match) {
    showLogin();
  })
  // 首页
  .on("/index", function (match) {
    loadPage("/static/pages/index.html", match.queryString, match.url);
  })
  // 探索模块
  .on("/media_detail", function (match) {
    loadPage("/static/pages/media_detail.html", match.queryString, match.url);
  })
  .on("/recommend", function (match) {
    loadPage("/static/pages/recommend.html", match.queryString, match.url);
  })
  .on("/discovery_person", function (match) {
    loadPage("/static/pages/person.html", match.queryString, match.url);
  })

  // 订阅模块
  .on("/rss_history", function (match) {
    loadPage("/static/pages/rss_history.html", match.queryString, match.url);
  })
  .on("/rss_parser", function (match) {
    loadPage("/static/pages/rss_parser.html", match.queryString, match.url);
  })

  // 下载器
  .on("/downloaders", function (match) {
    loadPage("/static/pages/downloaders.html", match.queryString, match.url);
  })
  // 下载配置
  .on("/download_setting", function (match) {
    loadPage("/static/pages/download_setting.html", match.queryString, match.url);
  })
  // 下载历史
  .on("/download_history", function (match) {
    loadPage("/static/pages/download_history.html", match.queryString, match.url);
  })

  // 唤起App中转页面
  .on("/open", function (match) {
    loadPage("/static/pages/openapp.html", match.queryString, match.url);
  })

  // 404处理
  .notFound(() => {
    $("#page-content").html(`<system-error title="404" text='没有找到这个页面，请检查是不是输错地址了...'></system-error>`);
    // 未经过 loadPage 流程，需手动结束加载状态，否则提示会一直停留
    hidePageLoading();
  })
  
;

router.resolve();


function showLogin() {

  $('#app-layout').addClass('d-none');
  $('#login-container').removeClass('d-none');
  $("body").addClass("no-after");

  // 隐藏等待动画并关闭加载标记
  hidePageLoading();

}

// SPA页面加载
// navPath: 目标页面路径（来自路由 match.url）。Navigo 是先执行 handler 再更新 URL，
//          因此跳转过程中不能直接读 window.location.hash，必须由调用方传入。
function loadPage(htmlPath, queryString, navPath) {

  InitialPageLoadStarted = true;

  // 上一页注册的局部刷新函数已失效，进入新页面时清掉
  window.pageRefreshHandler = null;

  $('#login-container').addClass('d-none');
  $('#app-layout').removeClass('d-none');
  $("body").removeClass("no-after");

  // 覆盖直接打开/刷新页面的场景；经 navmenu 进入时令牌已存在，不会重复显示
  showPageLoading();

  // 记录本次加载所属的菜单切换序号（0 表示首次加载/刷新等非菜单切换）
  const liquidSeq = PageLiquidSeq;

  // 1. 页面片段自带的静态参数（来自菜单配置的 html，如 rss.html?t=TV）
  let params = {};
  const [path, paramString] = htmlPath.split("?");
  if (paramString) {
    params = parseQueryString(paramString);
  }

  // 目标页面路径：优先使用路由解析结果；没有时（直接调用）退回当前地址
  const currentHashPath = getMenuId(window.location.hash);
  const pagePath = getMenuId(navPath || currentHashPath);
  // 地址栏是否已经指向本次要加载的页面（初始化/popstate/同页刷新为 true，跳转中为 false）
  const hashIsCurrent = pagePath === currentHashPath;

  // 2. 兼容旧版直接拼在 hash 上的地址，如 #/media_detail?type=movie&id=1
  let legacyParams = {};
  const hashQueryIndex = window.location.hash.indexOf("?");
  if (hashIsCurrent && hashQueryIndex !== -1) {
    legacyParams = parseQueryString(window.location.hash.substring(hashQueryIndex + 1));
  }

  // 3. 导航参数：navmenu 会写入内存，popstate/初始化时会从 history.state 同步，
  //    旧地址自带的参数优先级更高（避免打开旧链接时被缓存参数覆盖）
  const navParams = Object.assign({}, NavParams.get(pagePath), legacyParams);

  // 合并后挂到页面容器上，页面通过 getPageParams() 读取
  Object.assign(params, navParams);
  $("#page-content").data("params", params);
  $("#page-content").data("queryString", paramString);

  // 参数同步到仓库，供刷新后恢复
  NavParams.set(pagePath, navParams);

  // 地址栏已指向当前页面时，把参数写入当前历史条目（跳转中的 URL 由 Navigo 更新）
  if (hashIsCurrent) {
    try {
      const state = Object.assign({}, history.state);
      if (Object.keys(navParams).length > 0) {
        state.navParams = navParams;
      } else {
        delete state.navParams;
      }
      if (hashQueryIndex !== -1) {
        // 旧地址：替换为干净路径，参数只保留在 state 中
        history.replaceState(state, "", "#/" + pagePath);
      } else {
        history.replaceState(state, "");
      }
    } catch (e) {
      // 部分环境禁止 replaceState，忽略即可
    }
  }

  // 直接加载HTML文件
  $("#page-content").load(htmlPath, function(_, status, xhr) {

    // 隐藏等待动画并关闭加载标记（菜单切换时顺带播放液态展开）
    hidePageLoading(liquidSeq);

    if (status == "error") {
      $("#page-content").html(`<system-error title="${xhr.status}" text="${xhr.statusText || ''}"></system-error>`);
    } else {
      // 滚动到顶部
      $(window).scrollTop(0);
    }

    // 激活菜单、刷新子菜单并执行页面后处理
    applyPageState();

  });

}

// 页面加载后的菜单状态处理
// 如果菜单尚未创建，先记录 pending，等 initSysInfo 创建菜单后再补执行
function applyPageState() {
  var navbarMenu = document.querySelector("#navbar-menu");
  if (!navbarMenu || !navbarMenu.navbar_list) {
    $('#top-sub-navbar').hide();
    PendingPageState = true;
    return;
  }

  PendingPageState = false;

  var page = window.location.hash;
  if (page) {
    page = page.replace(/^[#/]+/, "");
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

  // 页面后处理
  renderOther();
}

// 菜单创建完成后，补执行之前挂起的页面状态处理
function initPendingPageState() {
  if (PendingPageState) {
    applyPageState();
  }
}

window.initPendingPageState = initPendingPageState;

// 导航菜单点击
// page: 页面名，如 "media_detail"
// params: 页面参数对象，如 {type: "MOV", id: 123}；不再拼接到 URL 上
// 向后兼容旧写法 navmenu("media_detail?type=MOV&id=123")，参数会被提取并隐藏
function navmenu(page, params) {

  if (typeof page === "string") {
    const queryIndex = page.indexOf("?");
    if (queryIndex !== -1) {
      if (params === undefined) {
        params = parseQueryString(page.substring(queryIndex + 1));
      }
      page = page.substring(0, queryIndex);
    }
  }

  // 修复空格问题
  page = page.replaceAll(" ", "%20");

  // 参数存入仓库，loadPage 时再读取
  if (params !== undefined) {
    NavParams.set(getMenuId(page), params);
  }

  // 标记本次为菜单切换，加载完成后播放页面液态展开
  PageLiquidSeq++;

  // 解除滚动事件
  $(window).unbind('scroll');

  // 停止上一次加载
  if (NavPageXhr && NavPageLoading) {
    NavPageXhr.abort();
  }
  
  // 显示等待动画并标记加载中
  showPageLoading();

  // 页面切换
  navigateTo(page, params);

}

// 页面切换：显示加载动画，隐藏页面内容
function showPageLoading() {
  $("#page-content").hide();
  NavPageLoading = true;
  if (PageLoadingToken === null) {
    PageLoadingToken = LoadingOverlay.show();
  }
}

// 页面切换完成：显示页面内容并释放页面加载动画
// liquidSeq 为触发本次加载的菜单切换序号，仅最新一次菜单切换才播放液态展开
function hidePageLoading(liquidSeq) {
  // 清理页面内自行使用的加载提示（如 ranking 页）
  $("#loading-tips").hide();
  $("#page-content").show();

  if (liquidSeq && liquidSeq === PageLiquidSeq) {
    playPageLiquidReveal(document.getElementById("page-content"));
  }

  NavPageLoading = false;
  if (PageLoadingToken !== null) {
    LoadingOverlay.hide(PageLoadingToken);
    PageLoadingToken = null;
  }
}

// 页面液态展开：重挂 class 触发 CSS 动画，支持连续切换时反复播放
function playPageLiquidReveal(el) {
  if (!el) return;
  el.classList.remove("page-liquid-reveal");
  void el.offsetWidth; // 强制回流，保证动画重新开始
  el.classList.add("page-liquid-reveal");

  // 用定时器（略长于动画时长）清理，连续切换时重置，不依赖 animationend
  if (el._liquidRevealTimer) clearTimeout(el._liquidRevealTimer);
  el._liquidRevealTimer = setTimeout(() => {
    el.classList.remove("page-liquid-reveal");
    el._liquidRevealTimer = null;
  }, 700);
}


// 页面切换
function navigateTo(target, params) {

  if (target) {

    // 同页面：只刷新内容
    if (pageNotChanged(target)) {
      // 同页面但参数不同（如推荐页切换过滤条件）时新增一条历史记录，
      // 保证浏览器前进/后退能回到对应的参数状态；传 null 表示重置参数，不新增历史
      if (params !== undefined && params !== null) {
        try {
          history.pushState({ navParams: params }, "", "#/" + getMenuId(target));
        } catch (e) {
          // 忽略：部分环境禁止 pushState
        }
      } else if (params === null) {
        // 重置参数：清掉当前历史条目里保存的参数，页面重新按默认状态加载
        try {
          const state = Object.assign({}, history.state);
          delete state.navParams;
          history.replaceState(state, "");
        } catch (e) {
          // 忽略
        }
      }

      var current = router.current && router.current[0];
      // 直接调用 handler, 传入当前页面的数据
      current.route.handler({
        url: getMenuId(target),
        data: current.data,
        params: current.route.params || {},
        queryString: "",
        hashString: window.location.hash
      });
      return;
    }

    // 正常跳转：把参数写进新历史条目的 state，URL 中不出现参数
    router.navigate(target, params != null ? { stateObj: { navParams: params } } : undefined);
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
    // 菜单点击视为一次全新进入，传 null 清掉该页面残留的导航参数
    aElement.onclick = () => navmenu(item.page, null);

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
  updateTabDisplay();

}

// 更新子菜单图标、名称显示
function updateTabDisplay() {
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
        // 固定路由已注册的页面不再重复注册
        if (FixedRoutePages.has(nav.page)) {
          return;
        }
        router.on(nav.page, (match) => {
          loadPage(nav.html, match.queryString, match.url);
        });
      });
      return;
    }
    // 一级菜单
    if (FixedRoutePages.has(route.page)) {
      return;
    }
    router.on(route.page, (match) => {
      loadPage(route.html, match.queryString, match.url);
    });

  });

  // 如果初始 URL 已经由顶部 router.resolve() 命中固定路由并加载，
  // 不能再 resolve 一次，否则会重复 loadPage，页面内联脚本会执行两次
  if (!InitialPageLoadStarted) {
    router.resolve();
  }
}

window.navmenu = navmenu;
window.registerRouter = registerRouter;