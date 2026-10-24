(function () {
  'use strict';

  const DEFAULT_NOIMAGE = '../static/img/no-image.svg';
  const EMPTY_LIST = [];

  function fixedText(value) {
    return (!value || value === 'None' || value === 'null' || value === 'undefined')
      ? ''
      : value;
  }

  function isDoubanImgUrl(url) {
    try {
      const u = new URL(url);
      return u.protocol === 'https:' && /^img\d+\.doubanio\.com$/.test(u.hostname);
    } catch (e) {
      return false;
    }
  }

  class CustomImg extends HTMLElement {
    static get observedAttributes() {
      return [
        'img-src',
        'img-noimage',
        'img-class',
        'img-style',
        'img-ratio',
        'div-style',
        'img-placeholder',
        'img-error',
        'img_vote',
        'img_mark',
        'lazy'
      ];
    }

    constructor() {
      super();
      this._placeholder = true;
      this._imgSrc = '';
      this._imgSrcList = EMPTY_LIST;
      this._carouselIndex = 0;
      this._fadeTimer = null;
      this._cycleTimer = null;
      this._expandTimer = null;
      this._rendered = false;
      this._imgClass = null;
    }

    get img_src() {
      return this._imgSrc;
    }

    set img_src(value) {
      const next = fixedText(value);
      if (next === this._imgSrc) return;

      this._imgSrc = next;
      this._placeholder = true;
      this._clearCarouselTimers();
      if (this._rendered) this._updateDom();
    }

    get img_src_list() {
      return this._imgSrcList;
    }

    set img_src_list(value) {
      let next;
      if (Array.isArray(value)) {
        next = value;
      } else if (typeof value === 'string' && value) {
        next = value.split(',').map((src) => src.trim()).filter(Boolean);
      } else {
        next = EMPTY_LIST;
      }

      // 同一个数组引用不重复启动轮播
      if (next === this._imgSrcList) return;

      this._imgSrcList = next;
      this._carouselIndex = 0;
      this._clearCarouselTimers();

      if (this._rendered) {
        this._startCarousel();
      }
    }

    connectedCallback() {
      if (!this._rendered) {
        this._build();
        this._rendered = true;
        this._imgSrc = fixedText(this.getAttribute('img-src'));
      }

      this._updateDom();

      if (this._imgSrcList.length) {
        this._startCarousel();
      }
    }

    disconnectedCallback() {
      this._clearCarouselTimers();
    }

    attributeChangedCallback(name, oldValue, newValue) {
      if (oldValue === newValue) return;

      if (name === 'img-src') {
        this._imgSrc = fixedText(newValue);
        this._placeholder = true;
        this._clearCarouselTimers();
      }

      if (this._rendered) {
        this._updateDom();
      }
    }

    _build() {
      this.innerHTML = `
        <div class="placeholder-glow">
          <div class="placeholder rounded-0"></div>
          <img alt="">
          <div class="badge badge-pill bg-purple" style="position: absolute; top: 10px; right: 10px" hidden></div>
          <div class="card-right-bottom-ribbon" hidden><i class="ti ti-check"></i></div>
        </div>`;

      this._wrapper = this.querySelector('.placeholder-glow');
      this._placeholderEl = this._wrapper.querySelector('.placeholder');
      this._imgEl = this._wrapper.querySelector('img');
      this._voteEl = this._wrapper.querySelector('.badge');
      this._markEl = this._wrapper.querySelector('.card-right-bottom-ribbon');

      this._imgEl.addEventListener('load', () => this._onLoad());
      this._imgEl.addEventListener('error', () => this._onError());
    }

    _updateDom() {
      if (!this._wrapper) return;

      const ratio = fixedText(this.getAttribute('img-ratio'));
      const divStyle = fixedText(this.getAttribute('div-style'));
      const imgClass = fixedText(this.getAttribute('img-class'));
      const imgStyle = fixedText(this.getAttribute('img-style'));
      const placeholderEnabled = fixedText(this.getAttribute('img-placeholder')) !== '0';
      const errorEnabled = fixedText(this.getAttribute('img-error')) !== '0';
      const lazy = fixedText(this.getAttribute('lazy')) === '1';
      const noImage = fixedText(this.getAttribute('img-noimage')) || DEFAULT_NOIMAGE;

      this._wrapper.className = 'placeholder-glow' + (ratio ? ' ratio' : '');
      this._wrapper.style.cssText =
        (ratio ? '--tblr-aspect-ratio:' + ratio + ';' : '') + divStyle;

      this._placeholderEl.className = 'placeholder rounded-0 ' + imgClass;
      this._placeholderEl.style.cssText = imgStyle;
      this._placeholderEl.hidden = !(this._placeholder && placeholderEnabled);

      // 不要覆盖轮播过程中动态添加的 class
      if (this._imgClass !== imgClass) {
        this._imgEl.className = imgClass;
        this._imgClass = imgClass;
      }
      this._imgEl.style.cssText = imgStyle;
      this._imgEl.hidden = this._placeholder;

      let src = '';
      if (!lazy) {
        src = this._imgSrc || (errorEnabled ? noImage : '');
      }
      src = this._toDisplaySrc(src);

      if (src) {
        if (this._imgEl.getAttribute('src') !== src) {
          this._imgEl.setAttribute('src', src);
        }
      } else {
        this._imgEl.removeAttribute('src');
      }

      const vote = fixedText(this.getAttribute('img_vote'));
      this._voteEl.hidden = !vote;
      this._voteEl.textContent = vote;

      this._markEl.hidden = fixedText(this.getAttribute('img_mark')) !== '1';
    }

    _toDisplaySrc(src) {
      if (!src) return '';
      return isDoubanImgUrl(src) ? '/doubanimg?url=' + src : src;
    }

    _startCarousel() {
      this._clearCarouselTimers();

      if (!this._rendered || !this._imgSrcList.length) return;

      if (this._imgSrcList.length === 1) {
        this.img_src = this._imgSrcList[0];
        return;
      }

      this._carouselIndex = 0;
      this._imgEl.classList.remove('lit-custom-img-carousel-show');

      this._expandTimer = setTimeout(() => {
        this.img_src = this._imgSrcList[0];
        this._carouselIndex = 1 % this._imgSrcList.length;
      }, 1000);
    }

    _updateFromList() {
      if (!this._imgSrcList.length) return;

      if (this._imgSrcList.length === 1) {
        this.img_src = this._imgSrcList[0];
        return;
      }

      this._imgEl.classList.remove('lit-custom-img-carousel-show');

      this._expandTimer = setTimeout(() => {
        const next = this._imgSrcList[this._carouselIndex];
        this._carouselIndex = (this._carouselIndex + 1) % this._imgSrcList.length;
        this.img_src = next;
      }, 1000);
    }

    _onLoad() {
      this._placeholder = false;
      this._updateDom();
      // 不要清掉 _expandTimer：初次加载 fallback 图片时，
      // 1 秒后切换到轮播第一张图的定时器仍需要执行
      this._clearCycleTimers();

      if (this._imgSrcList.length > 0) {
        this._imgEl.classList.add('lit-custom-img-carousel');

        this._fadeTimer = setTimeout(() => {
          this._imgEl.classList.add('lit-custom-img-carousel-show');

          this._cycleTimer = setTimeout(() => {
            this._updateFromList();
          }, 7000);
        }, 100);
      }
    }

    _onError() {
      const lazy = fixedText(this.getAttribute('lazy')) === '1';
      const errorEnabled = fixedText(this.getAttribute('img-error')) !== '0';
      if (lazy || !errorEnabled) return;

      const noImage = fixedText(this.getAttribute('img-noimage')) || DEFAULT_NOIMAGE;
      if (this._imgSrc === noImage) return;

      this.img_src = noImage;
    }

    _clearCycleTimers() {
      if (this._fadeTimer) {
        clearTimeout(this._fadeTimer);
        this._fadeTimer = null;
      }
      if (this._cycleTimer) {
        clearTimeout(this._cycleTimer);
        this._cycleTimer = null;
      }
    }

    _clearCarouselTimers() {
      this._clearCycleTimers();
      if (this._expandTimer) {
        clearTimeout(this._expandTimer);
        this._expandTimer = null;
      }
    }
  }

  if (!customElements.get('custom-img')) {
    customElements.define('custom-img', CustomImg);
  }
})();
