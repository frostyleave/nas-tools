(function () {
  'use strict';

  class NormalCardPlaceholder extends HTMLElement {
    connectedCallback() {
      if (this._rendered) return;
      this._rendered = true;

      this.innerHTML = `
        <div class="card card-sm rounded-3" style="border:none;">
          <div class="placeholder-glow">
            <div class="ratio placeholder rounded-3" style="--tblr-aspect-ratio:150%;"></div>
          </div>
        </div>`;
    }
  }

  if (!customElements.get('normal-card-placeholder')) {
    customElements.define('normal-card-placeholder', NormalCardPlaceholder);
  }
})();
