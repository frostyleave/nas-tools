import { html, nothing, unsafeHTML, repeat } from "../../utility/lit-core.min.js";
import { CustomElement, Golbal } from "../../utility/utility.js";

export class LayoutNavbar extends CustomElement {

  static properties = {
    navbar_list: { type: Array },
    layout_appversion: { attribute: "layout-appversion"},
    layout_useradmin: { attribute: "layout-useradmin"},
    _active_name: { state: true},
    _update_appversion: { state: true },
    _update_url: { state: true },
    _is_update: { state: true },
  };

  constructor() {
    super();
    this.navbar_list = [];
    this.layout_appversion = "v3.4.0";
    this._active_name = "";
    this._update_appversion = "";
    this._update_url = "https://github.com/frostyleave/nas-tools";
    this._is_update = false;

    this.classList.add("navbar","navbar-vertical","navbar-expand-lg","lit-navbar-fixed","lit-navbar","lit-navbar-hide-scrollbar");
    // 加载菜单
    Golbal.get_cache_or_ajax("get_user_menus", "usermenus", {},
      (ret) => {
        if (ret.code === 0) {
          this.navbar_list = ret.menus;
        }
      },false
    );
  }

  firstUpdated() {
    // 如果菜单已经加载，直接初始化页面
    if (this.navbar_list && this.navbar_list.length > 0 && !this._pageInitialized) {
      this._pageInitialized = true;
      this._init_page();
    }
  }

  connectedCallback() {
    super.connectedCallback();
    // 确保组件在重新连接时能够正确显示
    this._ensureVisible();
    // 如果菜单为空，重新加载菜单数据
    if (!this.navbar_list?.length) {
      this._loadMenus();
    }
  }

  _loadMenus() {

    axios_post_do("get_user_menus", {}, (ret) => {
      if (ret.code === 0) {
        this.navbar_list = ret.menus;
        // lit 会在 navbar_list 变动时自动触发渲染
        // this.requestUpdate();
        this._init_page();
      } else {
        console.error('Failed to load menus:', ret);
      }
    }, false, false);
    
  }

  _ensureVisible() {
    // 如果组件是隐藏的，延迟显示
    if (this.hasAttribute('hidden')) {
      setTimeout(() => {
        this.removeAttribute("hidden");
        const pageContent = document.querySelector("#page_content");
        const searchbar = document.querySelector("layout-searchbar");
        const logoAnimation = document.querySelector("#logo_animation");

        if (pageContent) pageContent.removeAttribute("hidden");
        if (searchbar) searchbar.removeAttribute("hidden");
        if (logoAnimation) logoAnimation.remove();
      }, 100);
    }
  }

  _init_page() {

    if (this._pageInitialized) 
      return;

    this._pageInitialized = true;

    let page = window.history.state?.page || this._get_page_from_url();
    if (!page && this.navbar_list?.length) {
      page = this.navbar_list[0].page || this.navbar_list[0].list?.[0]?.page || "index";
    }

    navmenu(page || "index");

    // 删除logo动画 加点延迟切换体验好
    setTimeout(() => {
      this._ensureVisible();
    }, 200);

  }

  _get_page_from_url() {
    const pages = window.location.href.split('#');
    if (pages.length > 1) {
      return pages[pages.length - 1]
    }
  }

  update_active(page) {
    this._active_name = page ?? window.history.state?.page;
    if (this._active_name && this._active_name.startsWith('/')) {
      this._active_name = this._active_name.replace(/^\/+/, "");
    }
    this.show_collapse(this._active_name);
  }

  show_collapse(page) {
    for (const item of this.querySelectorAll("div[id^='lit-navbar-collapse-']")) {
      for (const a of item.querySelectorAll("a")) {
        if (page === a.getAttribute("data-lit-page")) {
          item.classList.add("show");
          return;
        }
      }
    }
  }


  render() {

    const menuGroup = this.navbar_list.reduce((acc, item) => {
      const group = item.group || "";
      // 初始化分组数组
      acc[group] = acc[group] || [];
      // 添加元素到分组
      acc[group].push(item);
      return acc;
    }, {});

    const content = [];

    Object.keys(menuGroup).map(group => {
      const groupTitle = group !== ""
      ? html`<div class="section-title-container">
           <div class="section-title">${group}</div>
           <div class="divider-line"></div>
         </div>`
      : html``;

      // 遍历分组内的 items，调用 _render_page_item 生成每个 item 的 HTML
      const itemsContent = html`
        ${repeat(
          menuGroup[group],
          item => item.page,  // 唯一键
          item => this._render_page_item(item)
        )}
      `;

      // 添加到 content 列表
      content.push(html`${groupTitle}${itemsContent}`);

    })

    return html`
      <div class="container-fluid">
        <div class="offcanvas offcanvas-start d-flex lit-navbar-canvas shadow" tabindex="-1" id="litLayoutNavbar">
          <div class="d-flex flex-row flex-grow-1 lit-navbar-hide-scrollbar">
            <div class="d-flex flex-column flex-grow-1">
              <h1 style="text-align:center;margin: 1.5rem 0">
                <img src="../static/favicon.ico" style="vertical-align: bottom;border: 1px solid var(--tblr-navbar-toggler-border-color);border-radius: 5px;">
                <label style="font-size: xx-large;color: var(--tblr-body-color);">nastool</label>
              </h1>
              <div class="accordion px-2 py-2 flex-grow-1">
              ${content}
              </div>
              <div class="d-flex align-items-end">
                <span class="d-flex flex-grow-1 justify-content-center border rounded-3 m-3 p-2">
                  <a href=${this._update_url} class="text-muted" target="_blank" rel="noreferrer">
                    <strong>
                      <i class="ti ti-brand-github fs-2 me-1"></i>
                      <b id="version-txt"></b>
                    </strong>
                  </a>
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _render_page_item(item, child) {
    return html`
    <a class="nav-link lit-navbar-accordion-item${this._active_name === item.page ? "-active" : ""} my-1 p-2 ${child ? "ps-3" : "lit-navbar-accordion-button"}"
      href="#${item.page}" data-bs-dismiss="offcanvas" aria-label="Close"
      style="${child ? "font-size:1rem" : "font-size:1.1rem;"}"
      data-lit-page=${item.page}
      @click=${ () => {
        navmenu(item.page);
      }}>
      <span class="nav-link-icon" style="color:var(--tblr-body-color);">
        ${item.icon ? unsafeHTML(item.icon) : nothing}
      </span>
      <span class="nav-link-title">
        ${item.also ?? item.name}
      </span>
    </a>`
  }

}


window.customElements.define("layout-navbar", LayoutNavbar);