(function () {
  'use strict';

  const NO_IMAGE = '../static/img/no-image.svg';

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

  class PosterCard extends HTMLElement {
    static get observedAttributes() {
      return [
        'card-tmdbid',
        'card-restype',
        'card-mediatype',
        'card-showsub',
        'card-title',
        'card-fav',
        'card-r18',
        'card-vote',
        'card-vote-source',
        'card-image',
        'card-overview',
        'card-year',
        'lazy'
      ];
    }

    constructor() {
      super();
      this._rendered = false;
      this._placeholder = true;
      this._bottomType = null;
      this._heartIcon = null;
      this._searchLink = null;
    }

    /**
     * 当前图片是否已成功加载
     * 懒加载尚未触发、图片加载失败（含无图兜底）时返回 false
     */
    get image_loaded() {
      const img = this._imgEl;
      if (!img) return false;
      const src = img.getAttribute('src');
      return !!src && src !== NO_IMAGE && img.complete && img.naturalWidth > 0;
    }

    connectedCallback() {
      if (!this._rendered) {
        this._build();
        this._rendered = true;
      }
      this._update();
    }

    attributeChangedCallback(name, oldValue, newValue) {
      if (oldValue === newValue || !this._rendered) return;
      this._update();
    }

    _build() {
      this.innerHTML = `
        <div class="card card-sm lit-poster-card overflow-hidden liquid-glass-panel" tabindex="0" role="link">
          <div class="poster-card-poster ratio overflow-hidden">
            <div class="placeholder-glow">
              <div class="ratio placeholder" style="--tblr-aspect-ratio:150%;"></div>
            </div>
            <div class="poster-card-content" hidden>
              <img class="card-img" alt=""
                   style="display: block; min-width: 100%; max-width: 100%; min-height: 100%; max-height: 100%; object-fit: cover;">
              <span class="poster-card-badge poster-card-left-badge" hidden></span>
              <div class="poster-card-badge poster-card-right-badge" hidden></div>
              <span class="poster-card-badge poster-card-r18-badge" hidden>R18</span>
            </div>
            <div class="poster-card-bottom-right">
              <span class="poster-card-year" hidden></span>
              <div class="poster-card-fav-ribbon" title="已入库" hidden>
                <i class="ti ti-check"></i>
              </div>
            </div>
            <div class="card-img-overlay poster-card-overlay">
              <div class="poster-card-info mb-1">
                <p class="poster-card-overview" hidden></p>
              </div>
              <div class="poster-card-bottom"></div>
            </div>
          </div>
          <div class="poster-card-title-bar" hidden>
            <span class="poster-card-title"></span>
          </div>
        </div>`;

      this._placeholderEl = this.querySelector('.placeholder-glow');
      this._contentEl = this.querySelector('.poster-card-content');
      this._imgEl = this.querySelector('img.card-img');
      this._favRibbonEl = this.querySelector('.poster-card-fav-ribbon');
      this._leftBadgeEl = this.querySelector('.poster-card-left-badge');
      this._rightBadgeEl = this.querySelector('.poster-card-right-badge');
      this._r18BadgeEl = this.querySelector('.poster-card-r18-badge');
      this._overviewLineEl = this.querySelector('.poster-card-overview');
      this._bottomEl = this.querySelector('.poster-card-bottom');
      this._titleBarEl = this.querySelector('.poster-card-title-bar');
      this._titleTextEl = this.querySelector('.poster-card-title');
      this._yearTextEl = this.querySelector('.poster-card-year');
      this._cardEl = this.querySelector('.lit-poster-card');
      this._posterEl = this.querySelector('.poster-card-poster');

      this._imgEl.addEventListener('load', () => this._onImageLoad());
      this._imgEl.addEventListener('error', () => this._onImageError());
      // 仅海报区域点击跳转详情，下方名称栏不响应
      this._posterEl.addEventListener('click', () => this._navigate());
      this._cardEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.target === this._cardEl) {
          e.preventDefault();
          this._navigate();
        }
      });
    }

    _update() {
      if (!this._rendered) return;

      const lazy = fixedText(this.getAttribute('lazy')) === '1';
      const image = fixedText(this.getAttribute('card-image'));
      const fav = fixedText(this.getAttribute('card-fav'));
      const title = fixedText(this.getAttribute('card-title'));
      const overview = fixedText(this.getAttribute('card-overview'));
      const year = fixedText(this.getAttribute('card-year'));
      const vote = fixedText(this.getAttribute('card-vote'));
      const resType = fixedText(this.getAttribute('card-restype'));
      const r18 = fixedText(this.getAttribute('card-r18'));
      const tmdbId = fixedText(this.getAttribute('card-tmdbid'));
      const mediaType = fixedText(this.getAttribute('card-mediatype'));
      const showSub = fixedText(this.getAttribute('card-showsub'));

      // Placeholder / content
      this._placeholderEl.hidden = !this._placeholder;
      this._contentEl.hidden = this._placeholder;

      // Image
      let src = '';
      if (!lazy) {
        src = image || NO_IMAGE;
      }
      src = this._toDisplaySrc(src);

      if (src) {
        if (this._imgEl.getAttribute('src') !== src) {
          this._imgEl.setAttribute('src', src);
        }
      } else {
        this._imgEl.removeAttribute('src');
      }

      // Fav ribbon
      this._favRibbonEl.hidden = fav !== '2';

      // 左上角显示媒体类型（电影 / 剧集 / 动漫）
      var typeLabel = resType;
      this._leftBadgeEl.hidden = !typeLabel;
      if (typeLabel) {
        this._leftBadgeEl.textContent = typeLabel;
        this._leftBadgeEl.className = 'poster-card-badge poster-card-left-badge';
        if (resType == '电影') {
          this._leftBadgeEl.className += ' bg-green';
        } else if (resType == '动漫') {
          this._leftBadgeEl.className += ' bg-orange';
        } else {
          this._leftBadgeEl.className += ' bg-flickr';
        }
      }

      // 右上角评分：来源图标 + 数字（豆瓣用豆瓣图标，TMDB 用青色星标，Bangumi 用黄色星标）
      // 豆瓣来源即使评分为 0 或缺失也显示图标，仅省略数字
      const isDouban = tmdbId.startsWith('DB:');
      const isBangumi = !isDouban && fixedText(this.getAttribute('card-vote-source')) === 'bangumi';
      const hasVote = !!vote && vote !== '0.0' && vote !== '0' && vote !== '10';
      if (hasVote || isDouban) {
        let sourceClass = ' poster-card-badge-tmdb';
        if (isDouban) {
          sourceClass = ' poster-card-badge-douban';
        } else if (isBangumi) {
          sourceClass = ' poster-card-badge-bangumi';
        }
        this._rightBadgeEl.className = 'poster-card-badge poster-card-right-badge' + sourceClass;
        const sourceIcon = document.createElement('i');
        sourceIcon.className = isDouban ? 'ti ti-brand-douban' : 'ti ti-star-filled';
        if (hasVote) {
          const value = document.createElement('span');
          const score = parseFloat(vote);
          // 评分固定显示 1 位小数
          value.textContent = isNaN(score) ? vote : score.toFixed(1);
          this._rightBadgeEl.replaceChildren(sourceIcon, value);
        } else {
          this._rightBadgeEl.replaceChildren(sourceIcon);
        }
        this._rightBadgeEl.hidden = false;
      } else {
        this._rightBadgeEl.hidden = true;
      }

      // R18 角标
      this._r18BadgeEl.hidden = r18 !== '1';

      // 底部名称栏：标题 + 年份
      this._titleBarEl.hidden = !title;
      if (title) {
        this._titleTextEl.textContent = title;
        this._titleBarEl.title = title;

        if (resType == '电影') {
          this._titleBarEl.className += ' border-green';
        } else if (resType == '动漫') {
          this._titleBarEl.className += ' border-orange';
        } else {
          this._titleBarEl.className += ' border-flickr';
        }
      }
      
      this._yearTextEl.hidden = !year;
      if (year) {
        this._yearTextEl.textContent = year;
      }

      // Overlay text（名称不再显示在信息层中）
      this._overviewLineEl.hidden = !overview;
      if (overview) {
        this._overviewLineEl.textContent = overview;
      }

      // Bottom actions
      if (showSub !== this._bottomType || !this._bottomEl.hasChildNodes()) {
        this._renderBottom(showSub);
      }
      this._updateSearchHref(tmdbId, title, mediaType);

      // Fav heart（必须放在 bottom 渲染之后，首次创建时才能拿到引用）
      if (this._heartIcon) {
        this._heartIcon.className = fav === '1'
          ? 'ti ti-heart-filled poster-card-action-fav'
          : 'ti ti-heart';
      }
    }

    _renderBottom(showSub) {
      this._bottomType = showSub;
      this._bottomEl.replaceChildren();
      this._searchLink = null;
      this._heartIcon = null;

      if (showSub !== '1' && showSub !== '2') {
        return;
      }

      const row = document.createElement('div');
      row.className = 'd-flex justify-content-between align-items-center';

      const searchLink = document.createElement('a');
      searchLink.className = 'poster-card-action';
      searchLink.title = '搜索资源';
      searchLink.setAttribute('aria-label', '搜索资源');
      searchLink.addEventListener('click', (e) => e.stopPropagation());

      const searchIcon = document.createElement('i');
      searchIcon.className = 'ti ti-search';
      searchLink.appendChild(searchIcon);
      row.appendChild(searchLink);
      this._searchLink = searchLink;

      const heart = document.createElement('button');
      heart.type = 'button';
      heart.className = 'poster-card-action';
      heart.title = '加入/取消订阅';
      heart.setAttribute('aria-label', '加入或取消订阅');
      heart.addEventListener('click', (e) => this._loveClick(e));

      const heartIcon = document.createElement('i');
      heartIcon.className = 'ti ti-heart';
      heart.appendChild(heartIcon);
      row.appendChild(heart);
      this._heartIcon = heartIcon;

      this._bottomEl.appendChild(row);
    }

    _updateSearchHref(tmdbId, title, mediaType) {
      if (!this._searchLink) return;

      const href = 'javascript:media_search(' +
        JSON.stringify(tmdbId) + ', ' +
        JSON.stringify(title) + ', ' +
        JSON.stringify(mediaType) + ')';

      if (this._searchLink.getAttribute('href') !== href) {
        this._searchLink.setAttribute('href', href);
      }
    }

    _toDisplaySrc(src) {
      if (!src) return '';
      return isDoubanImgUrl(src) ? '/doubanimg?url=' + src : src;
    }

    _onImageLoad() {
      this._placeholder = false;
      this._placeholderEl.hidden = true;
      this._contentEl.hidden = false;
    }

    _onImageError() {
      const lazy = fixedText(this.getAttribute('lazy')) === '1';
      if (lazy) return;

      const image = fixedText(this.getAttribute('card-image'));
      if (image !== NO_IMAGE) {
        this.setAttribute('card-image', NO_IMAGE);
      }
    }

    _loveClick(e) {
      e.stopPropagation();

      if (typeof rss_love_click !== 'function') {
        return;
      }

      rss_love_click(
        e,
        fixedText(this.getAttribute('card-title')),
        fixedText(this.getAttribute('card-year')),
        fixedText(this.getAttribute('card-mediatype')),
        fixedText(this.getAttribute('card-tmdbid')),
        fixedText(this.getAttribute('card-fav')),
        () => this._setFav('0'),
        () => this._setFav('1')
      );
    }

    _setFav(value) {
      this.setAttribute('card-fav', value);
      this.dispatchEvent(new CustomEvent('fav_change', {
        detail: { fav: value },
        bubbles: true,
        composed: true
      }));
    }

    _navigate() {
      navmenu(
        'media_detail?type=' + fixedText(this.getAttribute('card-mediatype')) +
        '&id=' + fixedText(this.getAttribute('card-tmdbid')) +
        '&title=' + fixedText(this.getAttribute('card-title')) +
        '&year=' + fixedText(this.getAttribute('card-year'))
      );
    }
  }

  if (!customElements.get('poster-card')) {
    customElements.define('poster-card', PosterCard);
  }
})();
