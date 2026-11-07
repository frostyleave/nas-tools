(function () {
  'use strict';

  const PLACEHOLDER_COUNT = 20;

  function nextFrame(fn) {
    const raf = window.requestAnimationFrame || ((cb) => setTimeout(cb, 0));
    raf(fn);
  }

  function nextMicrotask(fn) {
    if (typeof queueMicrotask === 'function') {
      queueMicrotask(fn);
    } else {
      setTimeout(fn, 0);
    }
  }

  class CustomSlide extends HTMLElement {
    static get observedAttributes() {
      return ['slide-title', 'slide-click', 'lazy'];
    }

    constructor() {
      super();
      this._slideCard = null;       // null: 显示占位符；[]: 明确为空
      this._disabled = 0;
      this._cardWidth = 0;
      this._cardMax = 1;
      this._cardCurrent = 0;
      this._cardCurrentLoadIndex = 0;
      this._rendered = false;
      this._renderPending = false;
      this._resizeObserver = null;
      this._measureRetryTimer = null;
      this._scrollRaf = null;       // 翻页动画句柄，null 表示未在动画中
      this._scrollTarget = 0;       // 动画目标位置（动画中有效）
      this._onResize = () => this._countMaxNumber();
      this._onScroll = () => this._countDisabled();
    }

    get slide_title() { return this.getAttribute('slide-title') || '加载中..'; }
    set slide_title(value) { this.setAttribute('slide-title', value); }

    get slide_click() { return this.getAttribute('slide-click') || ''; }
    set slide_click(value) { this.setAttribute('slide-click', value); }

    get lazy() { return this.getAttribute('lazy') || ''; }
    set lazy(value) { this.setAttribute('lazy', value); }

    get slide_card() { return this._slideCard || []; }
    set slide_card(value) {
      const next = Array.isArray(value)
        ? value
        : (value == null ? [] : [value]);

      // 同一个数组引用不重复渲染（Lit 页面重新 render 时会复用缓存数组）
      if (next === this._slideCard) return;

      this._slideCard = next;

      if (this._rendered) {
        this._scheduleRenderCards();
      }
    }

    connectedCallback() {
      if (!this._rendered) {
        this._render();
        this._rendered = true;
        this._renderCards();
      } else if (this._cardNumber && this._cardNumber.childElementCount === 0) {
        // 重新连接时如果卡片还在，不要重复 replaceChildren，
        // 否则会触发子自定义元素的 disconnect/connect
        this._renderCards();
      }
      window.addEventListener('resize', this._onResize);
    }

    disconnectedCallback() {
      window.removeEventListener('resize', this._onResize);

      this._cancelScrollAnimation();

      if (this._resizeObserver) {
        this._resizeObserver.disconnect();
        this._resizeObserver = null;
      }
      if (this._measureRetryTimer) {
        clearTimeout(this._measureRetryTimer);
        this._measureRetryTimer = null;
      }
    }

    attributeChangedCallback(name, oldValue, newValue) {
      if (!this._rendered || oldValue === newValue) return;
      if (name === 'slide-title' || name === 'slide-click') {
        this._updateHeader();
      }
    }

    _render() {
      this.innerHTML = `
        <div class="container-fluid overflow-hidden px-0">
          <div class="page-header d-print-none">
            <div class="d-flex justify-content-between">
              <div class="d-inline-flex">
                <a class="nav-link ms-2 cursor-default" href="javascript:void(0)">
                  <h2 class="my-1"><strong></strong></h2>
                  <div class="ms-2 d-flex align-items-center d-none">
                    <i class="ti ti-chevrons-right fs-1"></i>
                  </div>
                </a>
              </div>
              <div class="col-auto ms-auto d-print-none">
                <div class="d-inline-flex">
                  <a class="btn btn-sm btn-icon btn-link text-muted border-0 disabled">
                    <i class="ti ti-chevron-left fs-1"></i>
                  </a>
                  <a class="media-slide-right btn btn-sm btn-icon btn-link border-0 text-muted">
                    <i class="ti ti-chevron-right fs-1"></i>
                  </a>
                </div>
              </div>
            </div>
          </div>
          <div class="media-slide-hide-scrollbar px-1 py-2">
            <div class="row row-cards d-flex flex-row flex-nowrap media-slide-card-number justify-content-start"></div>
          </div>
        </div>`;

      this._headerLink = this.querySelector('.page-header a.nav-link');
      this._titleEl = this._headerLink.querySelector('h2 strong');
      this._moreIcon = this._headerLink.querySelector('.ms-2');
      this._controls = this.querySelector('.col-auto');
      this._prevBtn = this.querySelector('.btn:not(.media-slide-right)');
      this._nextBtn = this.querySelector('.media-slide-right');
      this._scrollbar = this.querySelector('.media-slide-hide-scrollbar');
      this._cardNumber = this.querySelector('.media-slide-card-number');

      this._prevBtn.addEventListener('click', () => this._slideNext(false));
      this._nextBtn.addEventListener('click', () => this._slideNext(true));
      this._scrollbar.addEventListener('scroll', this._onScroll, { passive: true });

      // 页面刷新时 #page-content 可能仍是 hidden，首次测量宽度为 0；
      // 等容器真正可见后重新测量，触发懒加载移除 lazy
      if (typeof ResizeObserver === 'function') {
        this._resizeObserver = new ResizeObserver(() => {
          if (!this.isConnected || !this._cardNumber) return;

          const width = this._cardNumber.getBoundingClientRect().width;
          if (width && width !== this._cardWidth) {
            this._countMaxNumber();
          }
        });
        this._resizeObserver.observe(this._cardNumber);
      }

      this._updateHeader();
    }

    _updateHeader() {
      const click = this.slide_click;
      this._titleEl.textContent = this.slide_title;
      this._headerLink.classList.toggle('cursor-pointer', !!click);
      this._headerLink.classList.toggle('cursor-default', !click);
      this._headerLink.setAttribute('href', click || 'javascript:void(0)');
      this._moreIcon.classList.toggle('d-none', !click);
    }

    _scheduleRenderCards() {
      if (this._renderPending) return;
      this._renderPending = true;
      nextMicrotask(() => {
        this._renderPending = false;
        this._renderCards();
      });
    }

    _renderCards() {
      if (!this._cardNumber) return;

      this._cancelScrollAnimation();
      this._cardNumber.replaceChildren();

      if (this._slideCard === null) {
        for (let i = 0; i < PLACEHOLDER_COUNT; i++) {
          const placeholder = document.createElement('normal-card-placeholder');
          placeholder.className = 'px-2';
          this._cardNumber.appendChild(placeholder);
        }
      } else {
        for (const card of this._slideCard) {
          if (card && card.nodeType) {
            this._cardNumber.appendChild(card);
          } else if (card != null) {
            this._cardNumber.appendChild(document.createTextNode(String(card)));
          }
        }
      }

      this._cardCurrent = 0;
      this._cardCurrentLoadIndex = 0;

      // 首次需要测量卡片宽度；后续只需更新箭头状态，避免重复强制布局
      if (!this._cardWidth) {
        nextFrame(() => this._countMaxNumber());
        this._scheduleMeasureRetry();
      } else {
        nextFrame(() => this._countDisabled());
      }
    }

    _scheduleMeasureRetry() {
      if (this._measureRetryTimer) return;

      let attempts = 0;
      const tick = () => {
        this._measureRetryTimer = null;

        if (!this.isConnected || this._cardWidth) return;

        this._countMaxNumber();

        if (!this._cardWidth && attempts++ < 60) {
          this._measureRetryTimer = setTimeout(tick, 16);
        }
      };

      this._measureRetryTimer = setTimeout(tick, 16);
    }

    _countMaxNumber() {
      if (!this._cardNumber || !this._scrollbar) return;

      const width = this._cardNumber.getBoundingClientRect().width;
      if (!width) return;

      this._cardWidth = width;
      this._cardMax = Math.max(1, Math.trunc(this._scrollbar.clientWidth / width));
      this._cardCurrentLoadIndex = 0;
      this._countDisabled();
    }

    _countDisabled() {
      if (!this._cardNumber || !this._scrollbar || !this._cardWidth) return;

      const scroll = this._scrollbar;
      const width = this._cardWidth;
      const count = this._cardNumber.children.length;
      const maxScroll = Math.max(0, scroll.scrollWidth - scroll.clientWidth);

      // 动画过程中按目标位置计算当前页，滚动事件才触发时不会因为中间位置
      // 让箭头状态与懒加载来回跳变
      const position = this._scrollRaf ? this._scrollTarget : scroll.scrollLeft;

      this._cardCurrent = position <= 0
        ? 0
        : Math.trunc((position + width / 2) / width);

      if (count * width <= scroll.clientWidth || maxScroll <= 0) {
        this._setDisabled(3);
      } else if (position <= 0) {
        this._setDisabled(0);
      } else if (position >= maxScroll - 2) {
        this._setDisabled(2);
      } else {
        this._setDisabled(1);
      }

      if (this.lazy) {
        if (this._cardCurrent > this._cardCurrentLoadIndex - this._cardMax) {
          const children = this._cardNumber.children;
          const showMax = Math.min(
            this._cardCurrent + this._cardMax + 1,
            children.length
          );

          // 按完整子节点索引处理，避免 querySelectorAll 在移除 lazy 后
          // 列表收缩导致索引错位
          for (let i = this._cardCurrent; i < showMax; i++) {
            const card = children[i];
            if (!card || !card.hasAttribute('lazy')) continue;

            try {
              if (card.matches(this.lazy)) {
                card.removeAttribute('lazy');
              }
            } catch (e) {
              break;
            }
          }

          if (showMax > this._cardCurrentLoadIndex) {
            this._cardCurrentLoadIndex = showMax;
          }
        }
      }
    }

    _setDisabled(value) {
      this._disabled = value;
      if (!this._controls) return;
      this._controls.hidden = value === 3;
      this._prevBtn.classList.toggle('disabled', value === 0);
      this._nextBtn.classList.toggle('disabled', value === 2);
    }

    _slideNext(next) {
      if (!this._scrollbar || !this._cardWidth) return;

      const scroll = this._scrollbar;
      const width = this._cardWidth;

      // 动画进行中以目标位置为基准，连续点击才能顺滑接着翻页，
      // 否则会从半路的位置重新计算，产生一顿一顿的感觉
      const baseLeft = this._scrollRaf ? this._scrollTarget : scroll.scrollLeft;
      const baseIndex = baseLeft <= 0
        ? 0
        : Math.trunc((baseLeft + width / 2) / width);

      const cardIndex = next
        ? baseIndex + this._cardMax
        : baseIndex - this._cardMax;

      const maxScroll = Math.max(0, scroll.scrollWidth - scroll.clientWidth);
      const left = Math.max(0, Math.min(cardIndex * width, maxScroll));

      this._animateScroll(left);
    }

    _cancelScrollAnimation() {
      if (this._scrollRaf) {
        (window.cancelAnimationFrame || clearTimeout)(this._scrollRaf);
        this._scrollRaf = null;
      }
    }

    _animateScroll(target) {
      const scroll = this._scrollbar;
      if (!scroll) return;

      this._cancelScrollAnimation();

      const start = scroll.scrollLeft;
      const distance = target - start;

      // 目标位置与当前位置几乎一致时不启动动画，避免无意义的抖动
      if (Math.abs(distance) < 1) {
        scroll.scrollLeft = target;
        return;
      }

      const raf = window.requestAnimationFrame || ((cb) => setTimeout(() => cb(Date.now()), 16));

      // 距离越长时长略增加，但控制在 320~520ms，保证快慢一致的手感
      const duration = Math.min(520, 320 + Math.abs(distance) * 0.06);
      const startTime = (window.performance && performance.now) ? performance.now() : Date.now();

      this._scrollTarget = target;

      const step = (now) => {
        const progress = Math.min(1, (now - startTime) / duration);
        // easeInOutCubic：起步和收尾都柔和
        const eased = progress < 0.5
          ? 4 * progress * progress * progress
          : 1 - Math.pow(-2 * progress + 2, 3) / 2;

        scroll.scrollLeft = start + distance * eased;

        if (progress < 1) {
          this._scrollRaf = raf(step);
        } else {
          this._scrollRaf = null;
          scroll.scrollLeft = target;
        }
      };

      this._scrollRaf = raf(step);
    }
  }

  if (!customElements.get('custom-slide')) {
    customElements.define('custom-slide', CustomSlide);
  }
})();
