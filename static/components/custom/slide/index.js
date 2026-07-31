import { html } from "../../utility/lit-core.min.js";
import { CustomElement } from "../../utility/utility.js";

export class CustomSlide extends CustomElement {

  static properties = {
    slide_title: { attribute: "slide-title" },
    slide_click: { attribute: "slide-click" },
    lazy: { attribute: "lazy" },
    //slide_scroll: { attribute: "slide-scroll" , reflect: true, type: Number },
    slide_card: { type: Array },
    _disabled: { state: true },
  };

  constructor() {
    super();
    this._disabled = 0;
    this.slide_title = "加载中..";
    this.slide_click = "";
    this.slide_card = Array(20).fill(html`<normal-card-placeholder class="px-2"></normal-card-placeholder>`);
  }

  render() {
    return html`
      <div class="container-fluid overflow-hidden px-0">
        <div class="page-header d-print-none">
          <div class="d-flex justify-content-between">
            <div class="d-inline-flex">
              <a class="nav-link ms-2 ${this.slide_click ? "cursor-pointer" : "cursor-default"}" href=${this.slide_click ? this.slide_click : "javascript:void(0)"}>
                <h2 class="my-1">
                  <strong>${this.slide_title}</strong>
                </h2>
                <div class="ms-2 d-flex align-items-center ${this.slide_click ? "" : "d-none"}">
                  <i class="ti ti-chevrons-right fs-1"></i>
                </div>
              </a>
            </div>
            <div ?hidden=${this._disabled ==3 } class="col-auto ms-auto d-print-none">
              <div class="d-inline-flex">
                <a class="btn btn-sm btn-icon btn-link text-muted border-0 ${this._disabled == 0 ? "disabled" : ""}"
                   @click=${ () => this._slideNext(false) }>
                  <i class="ti ti-chevron-left fs-1"></i>
                </a>
                <a class="media-slide-right btn btn-sm btn-icon btn-link border-0 text-muted ${this._disabled == 2 ? "disabled" : ""}"
                   @click=${ () => this._slideNext(true) }>
                  <i class="ti ti-chevron-right fs-1"></i>
                </a>
              </div>
            </div>
          </div>
        </div>
        <div class="media-slide-hide-scrollbar px-1 py-2"
            @scroll=${ this._countDisabled }>
          <div class="row row-cards d-flex flex-row flex-nowrap media-slide-card-number justify-content-start">
            ${this.slide_card}
          </div>
        </div>
      </div>
    `;
  }

  updated(changedProperties) {
    // slide数据刷新时触发界面状态改变
    if (changedProperties.has("slide_card")) {
      this._countDisabled();
    }
  }

  // 绑定事件
  firstUpdated() {
    this._scrollbar = this.querySelector("div.media-slide-hide-scrollbar");
    this._card_number = this.querySelector("div.media-slide-card-number");
    // 初次获取元素参数
    this._countMaxNumber();
    // 窗口大小发生改变时
    this._countMaxNumber_resize = () => { this._countMaxNumber() }; // 防止无法卸载事件
    window.addEventListener("resize", this._countMaxNumber_resize);
  }

  // 卸载事件
  disconnectedCallback() {
    window.removeEventListener("resize", this._countMaxNumber_resize);
    super.disconnectedCallback();
  }
  
  _countMaxNumber() {
    this._card_width = this._card_number.getBoundingClientRect().width;
    this._card_max = Math.trunc(this._scrollbar.clientWidth / this._card_width);
    this._card_current_load_index = 0;
    this._countDisabled();
  }

  _countDisabled() {
    this._card_current = this._scrollbar.scrollLeft == 0 ? 0 : Math.trunc((this._scrollbar.scrollLeft +  this._card_width / 2) /  this._card_width)
    if (this.slide_card.length * this._card_width <= this._scrollbar.clientWidth){
      this._disabled = 3;
    } else if (this._scrollbar.scrollLeft == 0) {
      this._disabled = 0;
    } else if (this._scrollbar.scrollLeft >= this._scrollbar.scrollWidth - this._scrollbar.clientWidth - 2){
      this._disabled = 2;
    } else {
      this._disabled = 1;
    }
    // 懒加载
    if (this.lazy) {
      if (this._card_current > this._card_current_load_index - this._card_max) {
        const card_list = this._card_number.querySelectorAll(this.lazy);
        if (card_list.length > 0) {
          const show_max = this._card_current + this._card_max + 1;
          for (let i = this._card_current; i < show_max; i++) {
            if (i >= card_list.length) {
              break;
            }
            card_list[i].removeAttribute("lazy");
          }
          this._card_current_load_index = show_max;
        }
      }
    }
  }

  _slideNext(next) {
    let run_to_left_px;
    if (next) {
      const card_index = this._card_current + this._card_max;
      run_to_left_px = card_index *  this._card_width;
      if (run_to_left_px >= this._scrollbar.scrollWidth - this._scrollbar.clientWidth) {
        run_to_left_px = this._scrollbar.scrollWidth - this._scrollbar.clientWidth;
      }
    } else {
      const card_index = this._card_current - this._card_max;
      run_to_left_px = card_index *  this._card_width;
      if (run_to_left_px <= 0) {
        run_to_left_px = 0;
      }
    }
    $(this._scrollbar).animate({
      scrollLeft: run_to_left_px
    }, 350, () => {
      this._scrollbar.scrollLeft = run_to_left_px;
    });
  }


}

window.customElements.define("custom-slide", CustomSlide);