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

  class NormalCard extends HTMLElement {
    static get observedAttributes() {
      return [
        'card-tmdbid',
        'card-restype',
        'card-mediatype',
        'card-showsub',
        'card-title',
        'card-fav',
        'card-date',
        'card-vote',
        'card-image',
        'card-overview',
        'card-year',
        'card-site',
        'card-weekday',
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
        <div class="card card-sm lit-normal-card rounded-3 cursor-pointer ratio shadow-sm">
          <div class="placeholder-glow">
            <div class="ratio placeholder rounded-3" style="--tblr-aspect-ratio:150%;"></div>
          </div>
          <div class="rounded-3 normal-card-content" hidden>
            <img class="card-img rounded-3" alt=""
                 style="display: block; min-width: 100%; max-width: 100%; min-height: 100%; max-height: 100%; object-fit: cover;">
            <div class="card-right-bottom-ribbon normal-card-fav-ribbon" hidden>
              <i class="ti ti-check"></i>
            </div>
            <span class="badge badge-pill normal-card-left-badge"
                  style="position: absolute; top: 10px; left: 10px; z-index: 9;" hidden></span>
            <div class="badge badge-pill normal-card-right-badge"
                 style="position: absolute; top: 10px; right: 10px; z-index: 9;" hidden></div>
          </div>
          <div class="card-img-overlay rounded-3 ms-auto" style="background-color: rgba(0, 0, 0, 0.2);">
            <div style="cursor: pointer;">
              <div class="text-white card-secondary-text normal-card-year" hidden><strong></strong></div>
              <h3 class="lh-sm text-white card-overview-text normal-card-title" hidden><strong></strong></h3>
              <p class="lh-sm text-white card-overview-text normal-card-overview" hidden></p>
              <p class="lh-sm text-white card-secondary-text normal-card-date" style="margin-bottom: 5px;" hidden><small></small></p>
            </div>
            <div class="normal-card-bottom"></div>
          </div>
        </div>`;

      this._placeholderEl = this.querySelector('.placeholder-glow');
      this._contentEl = this.querySelector('.normal-card-content');
      this._imgEl = this.querySelector('img.card-img');
      this._favRibbonEl = this.querySelector('.normal-card-fav-ribbon');
      this._leftBadgeEl = this.querySelector('.normal-card-left-badge');
      this._rightBadgeEl = this.querySelector('.normal-card-right-badge');
      this._yearLineEl = this.querySelector('.normal-card-year');
      this._yearTextEl = this._yearLineEl.querySelector('strong');
      this._titleLineEl = this.querySelector('.normal-card-title');
      this._titleTextEl = this._titleLineEl.querySelector('strong');
      this._overviewLineEl = this.querySelector('.normal-card-overview');
      this._dateLineEl = this.querySelector('.normal-card-date');
      this._dateTextEl = this._dateLineEl.querySelector('small');
      this._bottomEl = this.querySelector('.normal-card-bottom');
      this._overlayEl = this.querySelector('.card-img-overlay');

      this._imgEl.addEventListener('load', () => this._onImageLoad());
      this._imgEl.addEventListener('error', () => this._onImageError());
      this._overlayEl.addEventListener('click', () => this._navigate());
    }

    _update() {
      if (!this._rendered) return;

      const lazy = fixedText(this.getAttribute('lazy')) === '1';
      const image = fixedText(this.getAttribute('card-image'));
      const fav = fixedText(this.getAttribute('card-fav'));
      const title = fixedText(this.getAttribute('card-title'));
      const overview = fixedText(this.getAttribute('card-overview'));
      const year = fixedText(this.getAttribute('card-year'));
      const site = fixedText(this.getAttribute('card-site'));
      const date = fixedText(this.getAttribute('card-date'));
      const vote = fixedText(this.getAttribute('card-vote'));
      const weekday = fixedText(this.getAttribute('card-weekday'));
      const resType = fixedText(this.getAttribute('card-restype'));
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

      // Left top badge
      if (weekday) {
        this._leftBadgeEl.className = 'badge badge-pill bg-orange normal-card-left-badge';
        this._leftBadgeEl.textContent = weekday;
        this._leftBadgeEl.hidden = false;
      } else if (resType) {
        this._leftBadgeEl.className = 'badge badge-pill ' +
          (resType === '电影' ? 'bg-lime' : 'bg-blue') +
          ' normal-card-left-badge';
        this._leftBadgeEl.textContent = resType;
        this._leftBadgeEl.hidden = false;
      } else {
        this._leftBadgeEl.hidden = true;
      }

      // Right top vote badge
      const hasVote = !!vote && vote !== '0.0' && vote !== '0';
      if (hasVote) {
        this._rightBadgeEl.className = 'badge badge-pill ' +
          (tmdbId.startsWith('DB:') ? 'bg-green' : 'bg-purple') +
          ' normal-card-right-badge';
        this._rightBadgeEl.textContent = vote;
        this._rightBadgeEl.hidden = false;
      } else {
        this._rightBadgeEl.hidden = true;
      }

      // Overlay text
      const showYear = !!year && !(overview || '').startsWith(year);
      this._yearLineEl.hidden = !showYear;
      if (showYear) {
        this._yearTextEl.textContent = site || year;
      }

      this._titleLineEl.hidden = !title;
      if (title) {
        this._titleTextEl.textContent = title;
      }

      this._overviewLineEl.hidden = !overview;
      if (overview) {
        this._overviewLineEl.textContent = overview;
      }

      this._dateLineEl.hidden = !date;
      if (date) {
        this._dateTextEl.textContent = date;
      }

      // Bottom actions
      if (showSub !== this._bottomType || !this._bottomEl.hasChildNodes()) {
        this._renderBottom(showSub);
      }
      this._updateSearchHref(tmdbId, title, mediaType);

      // Fav heart（必须放在 bottom 渲染之后，首次创建时才能拿到引用）
      if (this._heartIcon) {
        this._heartIcon.className = fav === '1'
          ? 'ti ti-heart-filled fs-2 text-red'
          : 'ti ti-heart fs-2 text-white';
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
      row.className = 'd-flex justify-content-between';

      const searchLink = document.createElement('a');
      searchLink.className = 'text-muted';
      searchLink.title = '搜索资源';
      searchLink.addEventListener('click', (e) => e.stopPropagation());

      const searchSpan = document.createElement('span');
      searchSpan.className = 'icon-pulse text-white';
      const searchIcon = document.createElement('i');
      searchIcon.className = 'ti ti-search fs-2';
      searchSpan.appendChild(searchIcon);
      searchLink.appendChild(searchSpan);
      row.appendChild(searchLink);
      this._searchLink = searchLink;

      const heartWrap = document.createElement('div');
      heartWrap.className = 'ms-auto';

      const heart = document.createElement('div');
      heart.className = 'text-muted';
      heart.title = '加入/取消订阅';
      heart.style.cursor = 'pointer';
      heart.addEventListener('click', (e) => this._loveClick(e));

      const heartSpan = document.createElement('span');
      heartSpan.className = 'icon-pulse text-white';
      const heartIcon = document.createElement('i');
      heartIcon.className = 'ti ti-heart fs-2 text-white';
      heartSpan.appendChild(heartIcon);
      heart.appendChild(heartSpan);
      heartWrap.appendChild(heart);
      row.appendChild(heartWrap);
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

  if (!customElements.get('normal-card')) {
    customElements.define('normal-card', NormalCard);
  }
})();
