import { html, nothing } from "../../utility/lit-core.min.js";
import { CustomElement, Golbal } from "../../utility/utility.js";

export class PageMediainfo extends CustomElement {
  static properties = {
    // 类型
    media_type: { attribute: "media-type" },
    // TMDBID/DB:豆瓣ID
    tmdbid: { attribute: "media-tmdbid" },
    // 是否订阅/下载
    fav: {},
    // 媒体信息
    media_info: { type: Object },
    // 类似影片
    similar_media: { type: Array },
    // 推荐影片
    recommend_media: { type: Array },
    // 季集
    seasons_data: { type: Array }
  };

  constructor() {
    super();
    this.media_info = {};
    this.similar_media = [];
    this.recommend_media = [];
    this.seasons_data = [];
    this.fav = undefined;
    this.item_url = undefined;
    this.crews = []
  }

  firstUpdated() {
    // 媒体信息、演员阵容
    Golbal.get_cache_or_ajax("media_detail", "info", { "type": this.media_type, "tmdbid": this.tmdbid},
      (ret) => {
        if (ret.code === 0) {
          this.media_info = ret.data;
          this.tmdbid = ret.data.tmdbid;
          this.fav = ret.data.fav;
          this.item_url = ret.data.item_url
          this.seasons_data = ret.data.seasons;
          
          if (this.media_info.crews && this.media_info.crews.length) {
            this.crews = this.crews.concat(this.media_info.crews)
          }

          if (this.media_info.actors && this.media_info.actors.length) {
            this.crews = this.crews.concat(this.media_info.actors)
          }

          // 类似
          Golbal.get_cache_or_ajax("get_recommend", "sim", { "type": this.media_type, "subtype": "sim", "tmdbid": ret.data.tmdbid, "page": 1},
            (ret) => {
              if (ret.code === 0) {
                this.similar_media = ret.Items;
              }
            }
          );
          // 推荐
          Golbal.get_cache_or_ajax("get_recommend", "more", { "type": this.media_type, "subtype": "more", "tmdbid": ret.data.tmdbid, "page": 1},
            (ret) => {
              if (ret.code === 0) {
                this.recommend_media = ret.Items;
              }
            }
          );
        } else {
          show_fail_modal("未查询到TMDB媒体信息！");
          window.history.go(-1);
        }
      }
    );
  }

  _render_placeholder(width, height, col, num) {
    return Array(num ?? 1).fill(html`
      <div class="placeholder ${col}"
        style="min-width:${width};min-height:${height};">
      </div>
    `);
  }

  _render_douban_a_link(douban_id) {
    var content = html``
    if (!douban_id){
        return content
    }
    var id_arr = douban_id.split(',')
    for (var id of id_arr) {
        content = html`${content}<a class="text-reset" href="https://movie.douban.com/subject/${id}" target="_blank">${id}</a>  `;
    }
    return content
  }

  render() {
    return html`
      <div class="container-xl placeholder-glow page-wrapper-top-off lit-media-info-page-bg">
        <!-- 渲染媒体信息 -->
        <div class="card rounded-0 lit-media-info-background custom-media-info-height">
          <custom-img class="custom-media-info-height"
            div-style="display:inline;"
            img-placeholder="0"
            img-error="0"
            .img_src_list=${this.media_info.background}
            img-class="card-img rounded-0"
            img-style="padding-bottom: 1px; display: block; width: 100%; height: 100%; object-fit: cover;">
          </custom-img>
          <div class="card-img-overlay rounded-0 lit-media-info-background">
            <div class="d-flex flex-row mb-4 align-items-stretch">
              <custom-img class="d-flex justify-content-center flex-shrink-0" div-style="position:relative;"
                img-class="rounded-3 object-cover lit-media-info-image"
                img-error=${Object.keys(this.media_info).length === 0 ? "0" : "1"}
                img_vote=${this.media_info.vote}
                img_mark=${this.fav == "2" ? "1" : "0"}
                img-src=${this.media_info.image}>
              </custom-img>
              <div class="d-flex flex-column justify-content-end ms-3 text-start">
                <div>
                  <h1 class="display-7 text-start text-shadow-b1">
                    <strong calss="d-inline">${this.media_info.title ?? this._render_placeholder("200px")}</strong>
                    <strong class="h3 ${!this.media_info.year ? 'd-none' : 'd-inline'} ">(${this.media_info.year})</strong>
                  </h1>
                </div>
                <div class="text-start mt-1">
                  ${this.media_info.genres ? this.media_info.genres.map((element) => (
                    html`
                    <span class="badge bg-indigo mb-1"> ${element}</span>
                    `
                  )) : nothing}
                  <span class="mb-1 ${!this.media_info.runtime ? 'd-none' : 'd-inline-flex'}"><i class="ti ti-clock fs-2"></i>&nbsp;${this.media_info.runtime}</span>
                  <span class="mb-1 ${!this.seasons_data.length ? 'd-none' : 'd-inline-flex'}"><i class="ti ti-stack-2 fs-2"></i>&nbsp;共${this.seasons_data.length}季</span>
                  <span class="mb-1 ${!this.media_info.link ? 'd-none' : 'd-inline-flex'}"><i class="ti ti-badge-tm fs-2 text-blue"></i> <a class="text-reset" href="${this.media_info.link}" target="_blank">${this.media_info.tmdbid}</a></span>
                  <span class="mb-1 ${!this.media_info.douban_id ? 'd-none' : 'd-inline-flex'}"><i class="ti ti-brand-douban fs-2 text-green"></i> ${this._render_douban_a_link(this.media_info.douban_id)}
                  ${Object.keys(this.media_info).length === 0 ? this._render_placeholder("205px") : nothing }
                </div>
                <div class="text-start mt-3">
                  ${Object.keys(this.media_info).length !== 0
                  ? html`
                    <span class="btn btn-primary mt-1"
                      @click=${(e) => {
                        e.stopPropagation();
                        media_search(this.tmdbid + "", this.media_info.title, this.media_type);
                      }}>
                      <i class="ti ti-search fs-2 text-white"></i>
                      搜索资源
                    </span>
                    ${this.fav == "1"
                    ? html`
                      <span class="btn btn-pinterest mt-1"
                        @click=${this._loveClick}>
                        <i class="ti ti-heart-filled fs-2 text-purple"></i>
                        删除订阅
                      </span>`
                    : html`
                      ${this.fav != "2"
                      ? html`
                        <span class="btn btn-purple mt-1"
                          @click=${this._loveClick}>
                          <i class="ti ti-heart fs-2 text-white"></i>
                          添加订阅
                        </span>`: nothing }`
                      }
                    ${this.item_url ? html`
                    <span class="btn btn-green mt-1" @click=${this._openItemUrl}>
                      <i class="ti ti-device-tv-old fs-2 text-white"></i>
                      在线观看
                    </span>
                    ` : nothing }`
                  : html`
                    <span class="me-1">${this._render_placeholder("100px", "30px")}</span>
                    <span class="me-1">${this._render_placeholder("100px", "30px")}</span>
                    `
                  }
                </div>
              </div>
            </div>
            <h1 class="d-flex">
              <strong>${Object.keys(this.media_info).length === 0 ? "加载中.." : "简介"}</strong>
            </h1>
          </div>
        </div>
        <div class="row">
          <div class="col-lg-9">
            <h2 class="text-muted ms-3 me-2">
              <small>${this.media_info.overview ?? this._render_placeholder("200px", "", "col-12", 7)}</small>
            </h2>
          </div>
        </div>
        <div class="d-none d-md-block position-fixed rounded" style="top: 5rem; right: 1rem; z-index: 99;width: 825px;">
          <accordion-seasons
            .seasons_data=${this.seasons_data}
            .tmdbid=${this.tmdbid}
            .title=${this.media_info.title}
            .year=${this.media_info.year}
          ></accordion-seasons>
        </div>

        <!-- 渲染演员阵容 -->
        ${this.crews && this.crews.length
        ? html`
          <custom-slide
            slide-title="演职人员"
            slide-click='javascript:navmenu("discovery_person?tmdbid=${this.tmdbid}&type=${this.media_type}&title=演职人员&subtitle=${this.media_info.title}")'
            lazy="person-card"
            .slide_card=${this.crews.map((item) => ( html`
              <person-card
                lazy=1
                person-id=${item.id}
                person-image=${item.image}
                person-name=${item.original_name}
                person-role=${item.role}
                @click=${() => {
                  navmenu("recommend?type="+this.media_type+"&subtype=person&personid="+item.id+"&title=参与作品&subtitle="+item.original_name)
                }}
              ></person-card>`))
            }
          ></custom-slide>`
        : nothing }

        <!-- 渲染类似影片 -->
        ${this.similar_media.length
        ? html`
          <custom-slide
            slide-title="类似"
            slide-click='javascript:navmenu("recommend?type=${this.media_type}&subtype=sim&tmdbid=${this.tmdbid}&title=类似&subtitle=${this.media_info.title}")'
            lazy="normal-card"
            .slide_card=${this.similar_media.map((item, index) => ( html`
              <normal-card
                @fav_change=${(e) => {
                  Golbal.update_fav_data("get_recommend", "sim", (extra) => (
                    extra.Items[index].fav = e.detail.fav, extra
                  ));
                }}
                lazy=1
                card-tmdbid=${item.id}
                card-mediatype=${item.type}
                card-showsub=1
                card-image=${item.image}
                card-fav=${item.fav}
                card-vote=${item.vote}
                card-year=${item.year}
                card-title=${item.title}
                card-overview=${item.overview}
              ></normal-card>`))
            }
          ></custom-slide>`
        : nothing }

        <!-- 渲染推荐影片 -->
        ${this.recommend_media.length
        ? html`
          <custom-slide
            slide-title="推荐"
            slide-click='javascript:navmenu("recommend?type=${this.media_type}&subtype=more&tmdbid=${this.tmdbid}&title=推荐&subtitle=${this.media_info.title}")'
            lazy="normal-card"
            .slide_card=${this.recommend_media.map((item, index) => ( html`
              <normal-card
                @fav_change=${(e) => {
                  Golbal.update_fav_data("get_recommend", "more", (extra) => (
                    extra.Items[index].fav = e.detail.fav, extra
                  ));
                }}
                lazy=1
                card-tmdbid=${item.id}
                card-mediatype=${item.type}
                card-showsub=1
                card-image=${item.image}
                card-fav=${item.fav}
                card-vote=${item.vote}
                card-year=${item.year}
                card-title=${item.title}
                card-overview=${item.overview}
              ></normal-card>`))
            }
          ></custom-slide>`
        : nothing }

      </div>
    `;
  }

  _update_fav_data() {
    Golbal.update_fav_data("media_detail", "info", (extra) => (
      extra.data.fav = this.fav, extra
    ));
  }

  _loveClick(e) {
    e.stopPropagation();
    Golbal.lit_love_click(this.media_info.title, this.media_info.year, this.media_type, this.tmdbid, this.fav,
      () => {
        this.fav = "0";
        this._update_fav_data();
      },
      () => {
        this.fav = "1";
        this._update_fav_data();
      });
  }
  _openItemUrl(){
    window.open(this.item_url, '_blank');
  }
}


window.customElements.define("page-mediainfo", PageMediainfo);