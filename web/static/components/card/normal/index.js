import { NormalCardPlaceholder } from "./placeholder.js"; export { NormalCardPlaceholder };

import { html, nothing } from "../../utility/lit-core.min.js";
import { CustomElement, Golbal } from "../../utility/utility.js";
import { observeState } from "../../utility/lit-state.js";
import { cardState } from "./state.js";

export class NormalCard extends observeState(CustomElement) {

  static properties = {
    tmdb_id: { attribute: "card-tmdbid" },
    res_type: { attribute: "card-restype" },
    media_type: { attribute: "card-mediatype" },
    show_sub: { attribute: "card-showsub"},
    title: { attribute: "card-title" },
    fav: { attribute: "card-fav" , reflect: true},
    date: { attribute: "card-date" },
    vote: { attribute: "card-vote" },
    image: { attribute: "card-image" },
    overview: { attribute: "card-overview" },
    year: { attribute: "card-year" },
    site: { attribute: "card-site" },
    weekday: { attribute: "card-weekday" },
    lazy: {},
    _placeholder: { state: true },
    _card_id: { state: true },
    _card_image_error: { state: true },
  };

  constructor() {
    super();
    this.lazy = "0";
    this._placeholder = true;
    this._card_image_error = false;
    this._card_id = Symbol("normalCard_data_card_id");
  }

  _render_left_up() {
    if (this.weekday || this.res_type) {
      let color;
      let text;
      if (this.weekday) {
        color = "bg-orange";
        text = this.weekday;
      } else if (this.res_type) {
        color = this.res_type === "电影" ? "bg-lime" : "bg-blue";
        text = this.res_type;
      }
      return html`
        <span class="badge badge-pill ${color}" style="position: absolute; top: 10px; left: 10px; z-index: 9;">
          ${text}
        </span>`;
    } else {
      return nothing;
    }
  }

  _render_right_up() {

     var has_vote = this.vote && this.vote != "0.0" && this.vote != "0";
     var vote_html = html`
                      <div class="badge badge-pill bg-purple" style="position: absolute; top: 10px; right: 10px; z-index: 9;">
                        ${this.vote}
                      </div>`;

    if (has_vote) {
      return vote_html;
    }
    return nothing;
  }

  _render_bottom() {
    if (this.show_sub == "1") {
      return html`
        <div class="d-flex justify-content-between">
          <a class="text-muted" title="搜索资源" @click=${(e) => { e.stopPropagation() }}
             href='javascript:media_search("${this.tmdb_id}", "${this.title}", "${this.media_type}")'>
            <span class="icon-pulse text-white">
              <i class="ti ti-search fs-2"></i>
            </span>
          </a>
          <div class="ms-auto">
            <div class="text-muted" title="加入/取消订阅" style="cursor: pointer" @click=${this._loveClick}>
              <span class="icon-pulse text-white">
                ${this.fav == "1" ? html`<i class="ti ti-heart-filled fs-2 text-red"></i>` : html`<i class="ti ti-heart fs-2 text-white"></i>`}
              </span>
            </div>
          </div>
        </div>`;
    } else {
      return nothing;
    }
  }

  render() {
    return html`
      <div class="card card-sm lit-normal-card rounded-3 cursor-pointer ratio shadow-sm"
           @click=${() => { if (Golbal.is_touch_device()){ cardState.more_id = this._card_id } } }
           @mouseenter=${() => { if (!Golbal.is_touch_device()){ cardState.more_id = this._card_id } } }
           @mouseleave=${() => { if (!Golbal.is_touch_device()){ cardState.more_id = undefined } } }>
        ${this._placeholder ? NormalCardPlaceholder.render_placeholder() : nothing}
        <div ?hidden=${this._placeholder} class="rounded-3">
          <img class="card-img rounded-3" alt="" style="display: block; min-width: 100%; max-width: 100%; min-height: 100%; max-height: 100%; object-fit: cover;"
             src=${this.lazy == "1" ? "" : this.image ?? Golbal.noImage}
             @error=${() => { if (this.lazy != "1") {this.image = Golbal.noImage; this._card_image_error = true} }}
             @load=${() => { this._placeholder = false }}/>
            ${this.fav == "2" ? html`
            <div class="card-right-bottom-ribbon">
              <i class="ti ti-check"></i>
            </div> 
            ` : null}
          ${this._render_left_up()}
          ${this._render_right_up()}
        </div>
        <div class="card-img-overlay rounded-3 ms-auto" style="background-color: rgba(0, 0, 0, 0.2);"
             @click=${() => { navmenu(`media_detail?type=${this.media_type}&id=${this.tmdb_id}`) }}>
          <div style="cursor: pointer;">
            ${this.year && !this.overview.startsWith(this.year)
              ? html`<div class="text-white card-secondary-text"><strong>${this.site ? this.site : this.year}</strong></div>` 
              : nothing 
            }
            ${this.title
            ? html`
              <h3 class="lh-sm text-white card-overview-text">
                <strong>${this.title}</strong>
              </h3>`
            : nothing }
            ${this.overview
            ? html`
              <p class="lh-sm text-white card-overview-text">
                ${this.overview}
              </p>`
            : nothing }
            ${this.date
            ? html`
              <p class="lh-sm text-white card-secondary-text" style="margin-bottom: 5px;">
                <small>${this.date}</small>
              </p>`
            : nothing }
          </div>
          ${this._render_bottom()}
        </div>
      </div>
    `;
  }

  _fav_change() {
    const options = {
      detail: {
        fav: this.fav
      },
      bubbles: true,
      composed: true,
    };
    this.dispatchEvent(new CustomEvent("fav_change", options));
  }

  _loveClick(e) {
    e.stopPropagation();
    Golbal.lit_love_click(this.title, this.year, this.media_type, this.tmdb_id, this.fav,
      () => {
        this.fav = "0";
        this._fav_change();
      },
      () => {
        this.fav = "1";
        this._fav_change();
      });
  }
  
}

window.customElements.define("normal-card", NormalCard);