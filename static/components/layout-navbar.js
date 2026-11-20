(function () {
  'use strict';

  const FALLBACK_VERSION = 'v3.4.0';
  const UPDATE_URL = 'https://github.com/frostyleave/nas-tools';

  function fixedText(value) {
    return (!value || value === 'None' || value === 'null' || value === 'undefined')
      ? '' : value;
  }

  class LayoutNavbar extends HTMLElement {
    static get observedAttributes() {
      return ['layout-appversion'];
    }

    constructor() {
      super();
      this._navbarList = [];
      this._activeName = '';
      this._pageInitialized = false;
      // 激活项液态胶囊
      this._liquid = null;
      this._liquidObserver = null;
      this.classList.add(
        'navbar', 'navbar-vertical', 'navbar-expand-lg',
        'lit-navbar-fixed', 'lit-navbar', 'lit-navbar-hide-scrollbar'
      );
    }

    get navbar_list() {
      return this._navbarList;
    }

    set navbar_list(value) {
      this._navbarList = Array.isArray(value) ? value : [];
      if (this.isConnected) {
        this._render();
        this._initPageOnce();
      }
    }

    get layout_appversion() {
      return fixedText(this.getAttribute('layout-appversion')) || FALLBACK_VERSION;
    }

    set layout_appversion(value) {
      this.setAttribute('layout-appversion', value);
    }

    connectedCallback() {
      this._ensureVisible();
      this._render();
      this._initPageOnce();
    }

    disconnectedCallback() {
      if (this._liquidObserver) {
        this._liquidObserver.disconnect();
        this._liquidObserver = null;
      }
    }

    attributeChangedCallback(name, oldValue, newValue) {
      if (name === 'layout-appversion' && oldValue !== newValue) {
        const el = this.querySelector('.lit-navbar-version');
        if (el) el.textContent = this.layout_appversion;
      }
    }

    _initPageOnce() {
      if (this._pageInitialized || !this._navbarList.length) return;
      this._pageInitialized = true;

      setTimeout(() => this._ensureVisible(), 200);
    }

    _ensureVisible() {
      if (!this.hasAttribute('hidden')) return;
      setTimeout(() => {
        this.removeAttribute('hidden');
        const pageContent = document.querySelector('#page-content');
        const searchbar = document.querySelector('layout-searchbar');
        const logoAnimation = document.querySelector('#logo_animation');

        if (pageContent) pageContent.removeAttribute('hidden');
        if (searchbar) searchbar.removeAttribute('hidden');
        if (logoAnimation) logoAnimation.remove();
      }, 100);
    }

    update_active(page) {
      let name = page != null
        ? page
        : (window.history.state && window.history.state.page);

      if (name && name.startsWith('/')) {
        name = name.replace(/^\/+/, '');
      }

      this._setActive(name, true);
    }

    _setActive(name, animate) {
      this._activeName = name || '';

      this.querySelectorAll('a[data-lit-page]').forEach((a) => {
        const active = a.dataset.litPage === this._activeName;
        a.classList.toggle('lit-navbar-accordion-item-active', active);
        a.classList.toggle('lit-navbar-accordion-item', !active);
      });

      this.show_collapse(this._activeName);
      this._syncLiquid(animate);
    }

    // 把激活胶囊定位到当前菜单项；animate 为 true 时胶囊会滑动并拉伸回弹
    _syncLiquid(animate) {
      const liquid = this._liquid;
      if (!liquid) return;

      const active = this.querySelector('a[data-lit-page].lit-navbar-accordion-item-active');
      // 菜单隐藏或尚未布局时无法测量，先收起胶囊，等可见后由 ResizeObserver 补正
      if (!active || !active.offsetHeight) {
        liquid.style.opacity = '0';
        delete liquid.dataset.top;
        return;
      }

      const top = active.offsetTop;
      const height = active.offsetHeight;
      const prevTop = Number.parseFloat(liquid.dataset.top);
      const hasPrev = Number.isFinite(prevTop);

      // 首次定位或非动画场景：先禁用过渡，避免胶囊从旧位置滑入
      if (!animate || !hasPrev) {
        liquid.style.transition = 'none';
      }

      liquid.style.top = `${top}px`;
      liquid.style.height = `${height}px`;
      liquid.style.opacity = '1';
      liquid.dataset.top = String(top);

      if (!animate || !hasPrev) {
        void liquid.offsetHeight; // 强制回流后再恢复过渡
        liquid.style.transition = '';
        return;
      }

      if (Math.abs(top - prevTop) > 0.5) {
        this._playLiquidMove();
      }
    }

    // 滑动时叠加一次性拉伸动画，制造液态被“拽”过去的感觉
    _playLiquidMove() {
      const liquid = this._liquid;
      if (!liquid) return;
      liquid.classList.remove('is-moving');
      void liquid.offsetWidth;
      liquid.classList.add('is-moving');
    }

    _observeLiquid() {
      if (typeof ResizeObserver === 'undefined') return;
      if (!this._liquidObserver) {
        this._liquidObserver = new ResizeObserver(() => this._syncLiquid(false));
        this._liquidObserver.observe(this);
      }
      const accordion = this.querySelector('.accordion');
      if (accordion) {
        this._liquidObserver.observe(accordion);
      }
    }

    // 兼容旧 API；当前菜单是扁平结构，没有折叠容器
    show_collapse(_page) {
    }

    _render() {
      const groups = new Map();
      this._navbarList.forEach((item) => {
        const group = item.group || '';
        if (!groups.has(group)) groups.set(group, []);
        groups.get(group).push(item);
      });

      const root = document.createElement('div');
      root.className = 'container-fluid';
      root.innerHTML = `
        <div class="offcanvas offcanvas-start d-flex lit-navbar-canvas shadow" tabindex="-1" id="litLayoutNavbar">
          <div class="d-flex flex-column h-100 lit-navbar-hide-scrollbar">
            <div class="flex-shrink-0">
              <h1 class="text-center my-3">
                <img src="../static/favicon.ico"
                     style="vertical-align: bottom;border: 1px solid var(--tblr-navbar-toggler-border-color);border-radius: 5px;">
                <label style="font-size: xx-large;color: var(--tblr-body-color);">nastool</label>
              </h1>
            </div>
            <div class="flex-grow-1 overflow-auto px-2 py-2">
              <div class="accordion"></div>
            </div>
            <div class="flex-shrink-0 mt-auto">
              <div class="d-flex align-items-end">
                <span class="d-flex flex-grow-1 justify-content-center border rounded-3 m-3 p-2">
                  <a href="${UPDATE_URL}" class="text-muted" target="_blank" rel="noreferrer">
                    <strong>
                      <i class="ti ti-brand-github fs-2"></i>
                      <b class="lit-navbar-version"></b>
                    </strong>
                  </a>
                </span>
              </div>
            </div>
          </div>
        </div>`;

      root.querySelector('.lit-navbar-version').textContent = this.layout_appversion;

      const accordion = root.querySelector('.accordion');

      // 激活项液态胶囊：绝对定位在 .accordion 内，菜单项通过 z-index 浮在其上
      const liquid = document.createElement('div');
      liquid.className = 'lit-navbar-liquid';
      liquid.setAttribute('aria-hidden', 'true');
      accordion.appendChild(liquid);

      groups.forEach((items, group) => {
        if (group) {
          const title = document.createElement('div');
          title.className = 'section-title-container';

          const text = document.createElement('div');
          text.className = 'section-title';
          text.textContent = group;

          const line = document.createElement('div');
          line.className = 'divider-line';

          title.append(text, line);
          accordion.appendChild(title);
        }

        items.forEach((item) => {
          const el = this._renderItem(item);
          if (el) accordion.appendChild(el);
        });
      });

      this.replaceChildren(root);
      this._liquid = liquid;
      this._syncLiquid(false);
      this._observeLiquid();
    }

    _renderItem(item) {
      if (item.hide) return null;

      const active = this._activeName === item.page;
      const link = document.createElement('a');
      link.className = 'd-flex align-items-center p-2 my-1 nav-link '
        + (active ? 'lit-navbar-accordion-item-active' : 'lit-navbar-accordion-item')
        + ' lit-navbar-accordion-button';
      link.href = '#' + item.page;
      link.setAttribute('data-lit-page', item.page);
      link.setAttribute('data-bs-dismiss', 'offcanvas');
      link.setAttribute('aria-label', 'Close');

      const icon = document.createElement('span');
      icon.className = 'nav-item-icon';
      if (item.icon) icon.innerHTML = item.icon; // 与原 unsafeHTML 行为一致

      const title = document.createElement('span');
      title.className = 'nav-link-title';
      title.textContent = item.also != null ? item.also : item.name;

      link.append(icon, title);
      link.addEventListener('click', () => {
        // 点击即高亮，让胶囊立刻滑向目标项，不用等页面加载完成
        this._setActive(item.page, true);
        // 菜单点击视为一次全新进入，传 null 清掉该页面残留的导航参数
        navmenu(item.page, null);
      });
      return link;
    }
  }

  customElements.define('layout-navbar', LayoutNavbar);
})();
