(function () {
  'use strict';

  const DEFAULT_NOIMAGE = '../static/img/person.png';

  function fixedText(value) {
    return (!value || value === 'None' || value === 'null' || value === 'undefined')
      ? ''
      : value;
  }

  class PersonCard extends HTMLElement {
    static get observedAttributes() {
      return ['person-id', 'person-image', 'person-name', 'person-role', 'lazy'];
    }

    constructor() {
      super();
      this._rendered = false;
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
        <div class="card card-sm lit-person-card rounded-3 overflow-hidden cursor-pointer ratio">
          <div class="text-center p-4 pt-3 placeholder-glow">
            <div class="avatar-rounded overflow-hidden" style="position:relative;z-index:1;"></div>
            <h3 class="lh-sm text-white card-overview-text mt-3"><strong></strong></h3>
            <div class="lh-sm text-white card-overview-text mt-2"></div>
          </div>
        </div>`;

      this._avatarEl = this.querySelector('.avatar-rounded');
      this._nameEl = this.querySelector('h3');
      this._nameTextEl = this._nameEl.querySelector('strong');
      this._roleEl = this.querySelector('h3 + div');

      this._imgEl = document.createElement('custom-img');
      this._imgEl.setAttribute('img-noimage', DEFAULT_NOIMAGE);
      this._imgEl.setAttribute('img-ratio', '100%');
      this._imgEl.setAttribute('img-style', 'object-fit:cover;');

      // 先设置动态属性再插入，避免先加载一次默认图片
      this._updateImageAttrs();
      this._avatarEl.appendChild(this._imgEl);
    }

    _updateImageAttrs() {
      if (!this._imgEl) return;

      const lazy = fixedText(this.getAttribute('lazy')) === '1';
      const image = fixedText(this.getAttribute('person-image'));

      this._imgEl.setAttribute('lazy', lazy ? '1' : '0');

      if (image) {
        this._imgEl.setAttribute('img-src', image);
      } else {
        this._imgEl.removeAttribute('img-src');
      }
    }

    _update() {
      if (!this._rendered) return;

      const name = fixedText(this.getAttribute('person-name'));
      const role = fixedText(this.getAttribute('person-role'));
      const lazy = fixedText(this.getAttribute('lazy')) === '1';

      this._nameTextEl.textContent = name;
      this._roleEl.textContent = role;

      this._nameEl.classList.toggle('placeholder', lazy);
      this._roleEl.classList.toggle('placeholder', lazy);

      this._updateImageAttrs();
    }
  }

  if (!customElements.get('person-card')) {
    customElements.define('person-card', PersonCard);
  }
})();
