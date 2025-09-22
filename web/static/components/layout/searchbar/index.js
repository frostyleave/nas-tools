import { html, nothing } from "../../utility/lit-core.min.js";
import { CustomElement } from "../../utility/utility.js";

const search_source_icon = {
  tmdb: html`<i class="ti ti-circle-letter-t fs-2 text-blue"></i>`,
  douban: html`<i class="ti ti-circle-letter-d fs-2 text-green"></i>`,
  person: html`<i class="ti ti-circle-letter-p fs-2 text-purple"></i>`
}

export class LayoutSearchbar extends CustomElement {
  static properties = {
    layout_systemflag: { attribute: "layout-systemflag" },
    layout_username: { attribute: "layout-username" },
    layout_search: { attribute: "layout-search"},
    layout_useradmin: { attribute: "layout-useradmin" },
    layout_search_source: { attribute: "layout-search-source" },
    _search_source: { state: true },
  };

  constructor() {
    super();
    this.layout_systemflag = "Docker";
    this.layout_username = "admin";
    this.layout_search_source = "tmdb";
    this._search_source = "tmdb";
    this.classList.add("navbar", "fixed-top", "lit-searchbar");
  }

  firstUpdated() {
    this._search_source = localStorage.getItem("SearchSource") ?? this.layout_search_source;
    // 当前状态：是否模糊
    let blur = false;
    window.addEventListener("scroll", () => {
      const scroll_length = document.body.scrollTop || window.pageYOffset;
      // 滚动发生时改变模糊状态
      if (!blur && scroll_length >= 5) {
        // 模糊状态
        blur = true;
        this.classList.add("lit-searchbar-blur");
      } else if (blur && scroll_length < 5) {
        // 非模糊状态
       blur = false
       this.classList.remove("lit-searchbar-blur");
      }
    });
  }

  // 卸载事件
  disconnectedCallback() {
    super.disconnectedCallback();
  }

  get input() {
    return this.querySelector(".home_search_bar") ?? null;
  }

  render() {
  return html`
    <div class="container-fluid nav-search-bar">
      <div class="d-flex flex-row flex-grow-1 align-items-center py-1">
        <!-- 导航展开按钮 -->
        <button class="navbar-toggler d-lg-none ms-2" type="button" data-bs-toggle="offcanvas" data-bs-target="#litLayoutNavbar">
          <span class="navbar-toggler-icon"></span>
        </button>

        <!-- 搜索栏 -->
        <div class="input-group input-group-flat ms-2">
          <span class="input-group-text">
            <a href="javascript:void(0)" class="link-secondary d-flex align-items-center"
              @click=${() => {
                let source_dict = { tmdb: "douban", douban: "person", person: "tmdb" };
                this._search_source = source_dict[this._search_source];
                localStorage.setItem("SearchSource", this._search_source);
              }}>
              ${search_source_icon[this._search_source]}
            </a>
          </span>

          <input type="text" class="home_search_bar form-control form-control-rounded"
            placeholder=${this._search_source === "person" ? "搜索人物" : "搜索电影、电视剧"}
            autocomplete="new-password" 
            @keypress=${(e) => {
              if (e.which === 13 && this.input.value) {
                if (this._search_source === "person") {
                  navmenu("discovery_person?&type=ALL&title=演员搜索&subtitle=" + this.input.value + "&keyword=" + this.input.value);
                } else {
                  navmenu("recommend?type=SEARCH&title=搜索结果&subtitle=" + this.input.value + "&keyword=" + this.input.value + "&source=" + this._search_source);
                }
                this.input.value = "";
              }
            }}>
          
          <span class="input-group-text">
            <a href="${this.layout_search > 0 ? "javascript:show_search_advanced_modal()" : "javascript:void(0)"}"
              class="link-secondary d-flex align-items-center">
              <i class="ti ti-adjustments fs-2"></i>
            </a>
          </span>

          <!-- 头像 dropdown -->
          <span class="input-group-text border-start-0">
            <div class="nav-item dropdown">
              <a href="#" class="d-flex align-items-center" data-bs-toggle="dropdown">
                <i class="ti ti-user-square-rounded fs-2 text-vimeo"></i>
              </a>
              <div class="dropdown-menu dropdown-menu-end dropdown-menu-arrow">
                <a class="dropdown-item hide-theme-dark" data-id="dark" href="javascript:void(0)" onclick="theme_toggle(this)" role="button">暗黑风格</a>
                <a class="dropdown-item hide-theme-light" data-id="light" href="javascript:void(0)" onclick="theme_toggle(this)" role="button">明亮风格</a>
                <div class="dropdown-divider"></div>
                ${this.layout_useradmin === "1"
                  ? html`
                      <a class="dropdown-item" href="javascript:show_message_modal()" role="button">消息中心</a>
                      <a class="dropdown-item" href="javascript:show_logging_modal()" role="button">实时日志</a>
                      <div class="dropdown-divider"></div>
                      ${["Docker", "Synology"].includes(this.layout_systemflag)
                        ? html`<a href="javascript:restart()" class="dropdown-item">重启</a>` : nothing }
                    `
                  : nothing }
                <a href="javascript:logout()" class="dropdown-item">
                  注销 <span class="text-muted mx-3">${this.layout_username}</span>
                </a>
                <div class="dropdown-divider"></div>
              </div>
            </div>
          </span>
        </div>
      </div>
    </div>
  `;
}

}


window.customElements.define("layout-searchbar", LayoutSearchbar);