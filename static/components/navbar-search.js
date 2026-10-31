(function () {
  'use strict';

  class NavbarSearch extends HTMLElement {
    constructor() {
      super();
      this._rendered = false;
      this._userMenuData = null;

      this._onScroll = () => {
        const scrollTop = document.body.scrollTop || window.pageYOffset || 0;
        this.classList.toggle('lit-searchbar-blur', scrollTop >= 5);
      };
    }

    /**
     * 填充用户头像下拉菜单
     * @param {Object} sysInfo /data/sysinfo 返回的数据
     */
    updateUserMenu(sysInfo) {
      this._userMenuData = sysInfo || null;
      this._renderUserMenu();
    }

    _renderUserMenu() {
      const menu = this.querySelector('#head-dropdown-menu');
      if (!menu || !this._userMenuData) return;

      const sysInfo = this._userMenuData;

      let html = `
        <a class="dropdown-item hide-theme-dark" data-id="dark" href="javascript:void(0)" onclick="theme_toggle(this)" role="button">暗黑风格</a>
        <a class="dropdown-item hide-theme-light" data-id="light" href="javascript:void(0)" onclick="theme_toggle(this)" role="button">明亮风格</a>
        <div class="dropdown-divider"></div>`;

      if (sysInfo.admin) {
        html += `
          <a class="dropdown-item" href="javascript:show_message_modal()" role="button">消息中心</a>
          <a class="dropdown-item" href="javascript:show_logging_modal()" role="button">实时日志</a>
          <div class="dropdown-divider"></div>`;

        if (sysInfo.systemFlag === 'Synology' || sysInfo.systemFlag === 'Docker') {
          html += `<a class="dropdown-item" href="javascript:restart()">重启</a>`;
        }
      }

      html += `
        <a class="dropdown-item" href="javascript:show_change_password_modal()">修改密码</a>
        <a class="dropdown-item" href="javascript:logout()"> 注销 <span class="text-muted mx-3"></span></a>
        <div class="dropdown-divider"></div>`;

      menu.innerHTML = html;

      const username = menu.querySelector('a[href="javascript:logout()"] .text-muted');
      if (username) {
        username.textContent = sysInfo.username || '';
      }
    }

    connectedCallback() {
      if (!this._rendered) {
        this._rendered = true;
        this._render();
      }

      window.addEventListener('scroll', this._onScroll, { passive: true });
      this._onScroll();
    }

    disconnectedCallback() {
      window.removeEventListener('scroll', this._onScroll);
    }

    _render() {
      this.innerHTML = `
        <div class="nav-search-bar d-flex flex-row flex-grow-1 align-items-center">
          <!-- 导航展开按钮 -->
          <button class="navbar-toggler d-lg-none py-2 me-1" type="button"
                  data-bs-toggle="offcanvas" data-bs-target="#litLayoutNavbar">
            <i class="ti ti-menu-2 fs-2"></i>
          </button>

          <div class="input-group input-group-flat">
            <!-- 搜索图标 -->
            <span class="input-group-text">
              <a href="javascript:void(0)"
                 class="link-secondary d-flex align-items-center nav-search-trigger">
                <i class="ti ti-search fs-2 text-blue"></i>
              </a>
            </span>

            <!-- 搜索入口 -->
            <a href="javascript:void(0)"
               class="form-control cursor-pointer text-decoration-none nav-search-trigger">
              <span class="text-muted">搜索电影、电视剧</span>
            </a>

            <!-- 头像下拉菜单 -->
            <span class="input-group-text border-start-0">
              <div class="nav-item dropdown">
                <a href="#" class="d-flex align-items-center" data-bs-toggle="dropdown" aria-expanded="false">
                  <i class="ti ti-user-square-rounded fs-2 text-vimeo"></i>
                </a>
                <div id="head-dropdown-menu"
                     class="dropdown-menu dropdown-menu-end dropdown-menu-arrow"></div>
              </div>
            </span>
          </div>
        </div>`;

      this.querySelectorAll('.nav-search-trigger').forEach((el) => {
        el.addEventListener('click', (event) => {
          event.preventDefault();
          if (typeof show_quick_search_modal === 'function') {
            show_quick_search_modal();
          }
        });
      });

      if (this._userMenuData) {
        this._renderUserMenu();
      }
    }
  }

  if (!customElements.get('navbar-search')) {
    customElements.define('navbar-search', NavbarSearch);
  }
})();
