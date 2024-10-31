import { html, nothing } from "../../utility/lit-core.min.js";
import { CustomElement, Golbal } from "../../utility/utility.js";

export class CustomImg extends CustomElement {

  static properties = {
    img_src: { attribute: "img-src" },
    img_noimage: { attribute: "img-noimage" },
    img_class: { attribute: "img-class" },
    img_style: { attribute: "img-style" },
    img_ratio: { attribute: "img-ratio" },
    div_style: { attribute: "div-style" },
    img_placeholder: { attribute: "img-placeholder" },
    img_error: { attribute: "img-error" },
    img_vote: { attribute: "img_vote" },
    img_mark: { attribute: "img_mark" },
    img_src_list: { type: Array },
    lazy: {},
    _placeholder: { state: true },
    _timeout_update_img: { state: true },
  };

  constructor() {
    super();
    this.img_noimage = Golbal.noImage;
    this.lazy = "0";
    this.img_placeholder = "1";
    this.img_error = "1";
    this.img_src_list = [];
    this._timeout_update_img = 0;
    this._placeholder = true;
  }

  willUpdate(changedProperties) {
    if (changedProperties.has("img_src")) {
      this._placeholder = true;
    }
    if (changedProperties.has("img_src_list")) {
      this._timeout_update_img = 0;
      this._update_img();
    }
  }

  firstUpdated() {
    this._query_img = this.querySelector("img");
  }

  _update_img() {
    if (this.img_src_list) {
      if (this.img_src_list.length > 1) {
        this._query_img.classList.remove("lit-custom-img-carousel-show");
        setTimeout(() => {
          this.img_src = this.img_src_list[this._timeout_update_img];
          this._timeout_update_img ++;
          if (this._timeout_update_img >= this.img_src_list.length) {
            this._timeout_update_img = 0;
          }
        }, 1000);
      } else if (this.img_src_list.length == 1) {
        this.img_src = this.img_src_list[0];
      }
    }
  }

  render() {
    return html`
      <div class="placeholder-glow${this.img_ratio ? " ratio" : ""}"
          style=${(this.img_ratio ? "--tblr-aspect-ratio:" + this.img_ratio + ";" : "") + (this.div_style ?? "")}>
        <div ?hidden=${!this._placeholder || this.img_placeholder != "1"} class="placeholder rounded-0 ${this.img_class}" style=${this.img_style}></div>
        <img ?hidden=${this._placeholder} alt=""
          class=${this.img_class}
          style=${this.img_style}
          src=${this.lazy == "1" ? "" : this.img_src ? this.img_src : this.img_error == "1" ? this.img_noimage : ""}
          @error=${() => { if (this.lazy != "1" && this.img_error == "1") { this.img_src = this.img_noimage } }}
          @load=${() => {
            this._placeholder = false;
            // 图像渐入
            if (this.img_src_list.length > 0) {
              this._query_img.classList.add("lit-custom-img-carousel");
              setTimeout(() => {
                this._query_img.classList.add("lit-custom-img-carousel-show");
                setTimeout(() => {
                  this._update_img();
                }, 7000);
              }, 100);
            }
          }}/>
        ${
          this.img_vote ?
          html`<div class="badge badge-pill bg-purple" style="position: absolute; top: 10px; right: 10px">${this.img_vote}</div>` 
          : nothing
        }
        ${this.img_mark == "1" ? html`
            <div style="position: absolute; bottom: 0; right: 0; width: 30px; height: 30px; padding: 12px; background-color: var(--tblr-success); clip-path: polygon(100% 0, 100% 100%, 0 100%); border-radius: 0 0 8px 0;">
              <svg xmlns="http://www.w3.org/2000/svg" class="icon icon-tabler icon-tabler-check" width="15" height="15" viewBox="0 0 30 30" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round" >
                <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>
                <path d="M5 12l5 5l10 -10"></path>
              </svg>
            </div>
            ` : null
          }
      </div>
    `;
  }

}

window.customElements.define("custom-img", CustomImg);