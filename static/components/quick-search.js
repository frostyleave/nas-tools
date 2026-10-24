(function () {
  'use strict';

  const SEARCH_SOURCES = [
    { id: 'tmdb', icon: '<i class="ti ti-circle-letter-t fs-2 text-blue"></i>' },
    { id: 'douban', icon: '<i class="ti ti-circle-letter-d fs-2 text-green"></i>' },
    { id: 'person', icon: '<i class="ti ti-circle-letter-p fs-2 text-purple"></i>' }
  ];

  const MODAL_HTML = `  <!-- 搜索弹窗 -->
  <div class="modal modal-blur fade" id="quick-search-modal" tabindex="-1" aria-labelledby="quickSearchLabel" aria-hidden="true">
    <div class="modal-dialog modal-lg modal-dialog-top-offset">
      <div class="modal-content">
        <div class="modal-header align-items-end">
          <!-- 1. Tab 导航 -->
          <ul class="nav nav-tabs w-100" id="myModalTabs" role="tablist">
            <li class="nav-item" role="presentation">
              <button class="nav-link active" id="tab-media-search-tab" data-bs-toggle="tab" data-bs-target="#tab-media-search" type="button" role="tab" aria-controls="tab-media-search" aria-selected="true">搜索</button>
            </li>
            <li class="nav-item" role="presentation">
              <button class="nav-link" id="tab-source-search-tab" data-bs-toggle="tab" data-bs-target="#tab-source-search" type="button" role="tab" aria-controls="tab-source-search" aria-selected="false">快速搜索</button>
            </li>
          </ul>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
        </div>
        <div class="modal-body">
          <div class="tab-content" id="myModalTabsContent">
            <!-- 面板：常规搜索 -->
            <div class="tab-pane fade show active" id="tab-media-search" role="tabpanel" aria-labelledby="tab-media-search-tab">
              <div class="mb-2">
                <div class="input-group input-group-flat">
                  <span class="input-group-text">
                    <a href="javascript:void(0)" id="icon-source-trigger" data-id="tmdb" class="link-secondary d-flex align-items-center">
                      <i class="ti ti-circle-letter-t fs-2 text-blue"></i>
                    </a>
                  </span>
                  <input type="text" class="form-control" id="quick-search-keywords" placeholder="搜索电影、电视剧">
                </div>
              </div>
              <div class="row mb-2 align-items-center ps-2" id="search-type-choose">
                <label class="col-md-auto col-form-label w-auto">类型</label>
                <div class="col-md-9 w-auto">
                  <div>
                    <label class="form-check form-check-inline mb-0">
                      <input class="form-check-input" type="checkbox" name="search-type" value="MOV" checked>
                      <span class="form-check-label">电影</span>
                    </label>
                    <label class="form-check form-check-inline mb-0">
                      <input class="form-check-input" type="checkbox" name="search-type" value="TV" checked>
                      <span class="form-check-label">电视剧</span>
                    </label>
                  </div>
                </div>
              </div>
              <div class="modal-footer px-0">
                <button onclick="quickSearchMedia()" class="btn btn-primary">开始搜索</button>
              </div>
            </div>
            <!-- 面板：快速搜索 -->
            <div class="tab-pane fade" id="tab-source-search" role="tabpanel" aria-labelledby="tab-source-search-tab">
              <div class="row">
                <div class="col-12 col-lg-8">
                  <div class="mb-3">
                    <label class="form-label required">关键字</label>
                    <input type="text" id="advanced_search_name" class="form-control" placeholder="电影/电视剧名称">
                  </div>
                </div>
                <div class="col-12 col-lg-4">
                  <div class="mb-3">
                    <label class="form-label">站点</label>
                    <select class="form-select" id="advanced_search_site">
                      <option value="" selected>全部</option>
                    </select>
                  </div>
                </div>
              </div>
              <!-- 开关 -->
              <input type="checkbox" id="advancedSearchMoreSwitch" class="advanced-search-switch">
              <div class="more-advanced">
                <div class="row">
                  <div class="col-12 col-lg-4">
                    <div class="mb-3">
                      <label class="form-label">类型</label>
                      <select class="form-select" id="advanced_search_type">
                        <option value="" selected>全部</option>
                        <option value="电影">电影</option>
                        <option value="电视剧">电视剧</option>
                      </select>
                    </div>
                  </div>
                  <div class="col-12 col-lg-4">
                    <div class="mb-3">
                      <label class="form-label">年份</label>
                      <input type="text" id="advanced_search_year" class="form-control" placeholder="20xx">
                    </div>
                  </div>
                  <div class="col-12 col-lg-4">
                    <div class="mb-3">
                      <label class="form-label">季</label>
                      <select class="form-select" id="advanced_search_season"></select>
                    </div>
                  </div>
                </div>
                <div class="row">
                  <div class="col-12 col-lg-4">
                    <div class="mb-3">
                      <label class="form-label">分辨率</label>
                      <select class="form-select" id="advanced_search_pix"></select>
                    </div>
                  </div>
                  <div class="col-12 col-lg-4">
                    <div class="mb-3">
                      <label class="form-label">质量</label>
                      <select class="form-select" id="advanced_search_restype"></select>
                    </div>
                  </div>
                  <div class="col-12 col-lg-4">
                    <div class="mb-3">
                      <label class="form-label">促销</label>
                      <select class="form-select" id="advanced_sp_state">
                        <option value="* *" selected>全部</option>
                        <option value="1.0 1.0">普通</option>
                        <option value="1.0 0.0">免费</option>
                        <option value="2.0 1.0">2X</option>
                        <option value="2.0 0.0">2X免费</option>
                        <option value="1.0 0.5">50%</option>
                        <option value="2.0 0.5">2X 50%</option>
                        <option value="1.0 0.7">70%</option>
                        <option value="1.0 0.3">30%</option>
                      </select>
                    </div>
                  </div>
                </div>
                <div class="row">
                  <div class="col-12 col-lg-4">
                    <div class="mb-3">
                      <label class="form-label">过滤规则</label>
                      <select id="advanced_search_rule" class="form-control"></select>
                    </div>
                  </div>
                </div>
              </div>
              <!-- 切换按钮 -->
              <div class="advanced-search-toggle-wrapper d-lg-none">
                <label for="advancedSearchMoreSwitch" class="advanced-search-toggle">
                  <span class="toggle-text-open">展开更多筛选</span>
                  <span class="toggle-text-close">收起更多筛选</span>
                  <span class="toggle-icon">
                    <svg xmlns="http://www.w3.org/2000/svg"
                        width="16"
                        height="16"
                        fill="currentColor"
                        viewBox="0 0 16 16">
                      <path fill-rule="evenodd"
                            d="M1.646 5.646a.5.5 0 0 1 .708 0L8 11.293l5.646-5.647a.5.5 0 0 1 .708.708l-6 6a.5.5 0 0 1-.708 0l-6-6a.5.5 0 0 1 0-.708"/>
                    </svg>
                  </span>
                </label>
              </div>
              <div class="modal-footer px-0">
                <span class="text-muted">仅搜索站点资源, 不匹配TMDB</span><button onclick="search_media_advanced()" class="btn btn-primary">开始搜索</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
`;

  class QuickSearch extends HTMLElement {
    constructor() {
      super();
      this._rendered = false;
      this._sourceIndex = 0;
    }

    connectedCallback() {
      if (this._rendered) return;

      this._rendered = true;
      this.innerHTML = MODAL_HTML;
      this._bindEvents();
    }

    _bindEvents() {
      const trigger = this.querySelector('#icon-source-trigger');
      const input = this.querySelector('#quick-search-keywords');
      const typeChoose = this.querySelector('#search-type-choose');
      const modal = this.querySelector('#quick-search-modal');

      if (trigger) {
        trigger.addEventListener('click', (event) => {
          event.preventDefault();
          this._nextSource(trigger, input, typeChoose);
        });
      }

      if (input) {
        input.addEventListener('keydown', (event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            if (typeof quickSearchMedia === 'function') {
              quickSearchMedia();
            }
          }
        });
      }

      if (modal && input) {
        modal.addEventListener('shown.bs.modal', () => {
          input.focus();
        });
      }
    }

    _nextSource(trigger, input, typeChoose) {
      this._sourceIndex = (this._sourceIndex + 1) % SEARCH_SOURCES.length;
      const source = SEARCH_SOURCES[this._sourceIndex];

      trigger.innerHTML = source.icon;
      trigger.dataset.id = source.id;

      if (input) {
        input.placeholder = source.id === 'person'
          ? '搜索人物'
          : '搜索电影、电视剧';
      }

      if (typeChoose) {
        typeChoose.hidden = source.id === 'person';
      }
    }
  }

  if (!customElements.get('quick-search')) {
    customElements.define('quick-search', QuickSearch);
  }
})();
