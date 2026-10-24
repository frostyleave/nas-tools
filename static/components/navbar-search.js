(function () {
  'use strict';

  class NavbarSearch extends HTMLElement {
    constructor() {
      super();
      this._rendered = false;

      this._onScroll = () => {
        const scrollTop = document.body.scrollTop || window.pageYOffset || 0;
        this.classList.toggle('lit-searchbar-blur', scrollTop >= 5);
      };
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
    }
  }

  if (!customElements.get('navbar-search')) {
    customElements.define('navbar-search', NavbarSearch);
  }
})();
