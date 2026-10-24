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

    attributeChangedCallback(name, oldValue, newValue) {
      if (name === 'layout-appversion' && oldValue !== newValue) {
        const el = this.querySelector('.lit-navbar-version');
        if (el) el.textContent = this.layout_appversion;
      }
    }

    _initPageOnce() {
      if (this._pageInitialized || !this._navbarList.length) return;
      this._pageInitialized = true;

      let page = (window.history.state && window.history.state.page) || this._getPageFromUrl();
      if (!page) {
        const first = this._navbarList[0];
        page = first.page || (first.list && first.list[0] && first.list[0].page) || 'index';
      }

      navmenu(page || 'index');
      setTimeout(() => this._ensureVisible(), 200);
    }

    _getPageFromUrl() {
      const parts = window.location.href.split('#');
      return parts.length > 1 ? parts[parts.length - 1] : undefined;
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
      this._activeName = name || '';

      this.querySelectorAll('a[data-lit-page]').forEach((a) => {
        const active = a.dataset.litPage === this._activeName;
        a.classList.toggle('lit-navbar-accordion-item-active', active);
        a.classList.toggle('lit-navbar-accordion-item', !active);
      });

      this.show_collapse(this._activeName);
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
    }

    _renderItem(item) {
      if (item.hide) return null;

      const active = this._activeName === item.page;
      const link = document.createElement('a');
      link.className = 'd-flex align-items-center p-2 nav-link '
        + (active ? 'lit-navbar-accordion-item-active' : 'lit-navbar-accordion-item')
        + ' lit-navbar-accordion-button';
      link.href = '#' + item.page;
      link.setAttribute('data-lit-page', item.page);
      link.setAttribute('data-bs-dismiss', 'offcanvas');
      link.setAttribute('aria-label', 'Close');
      link.style.fontSize = '1.1rem';

      const icon = document.createElement('span');
      icon.className = 'nav-item-icon';
      if (item.icon) icon.innerHTML = item.icon; // 与原 unsafeHTML 行为一致

      const title = document.createElement('span');
      title.className = 'nav-link-title';
      title.textContent = item.also != null ? item.also : item.name;

      link.append(icon, title);
      link.addEventListener('click', () => navmenu(item.page));
      return link;
    }
  }

  customElements.define('layout-navbar', LayoutNavbar);
})();
