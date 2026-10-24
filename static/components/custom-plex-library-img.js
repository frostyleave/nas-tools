(function () {
  'use strict';

  const POSTER_WIDTH = 150;
  const POSTER_HEIGHT = 252;
  const MARGIN_WIDTH = 8;
  const MARGIN_HEIGHT = 4;
  const REFLECTION_HEIGHT = POSTER_HEIGHT / 2;
  const REFLECTION_SHOW_HEIGHT = 100;

  class CustomPlexLibraryImg extends HTMLElement {
    connectedCallback() {
      if (this._rendered) return;
      this._rendered = true;

      this.innerHTML = '<canvas width="640" height="360" class="w-100"></canvas>';
      this._init();
    }

    _init() {
      const canvas = this.querySelector('canvas');
      if (!canvas) return;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      // 背景色
      ctx.fillStyle = '#000000';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      const sources = (this.getAttribute('img-src-list') || '')
        .split(',')
        .map((src) => src.trim())
        .filter(Boolean);

      this._loadImages(ctx, canvas, sources);
    }

    async _loadImages(ctx, canvas, sources) {
      // 最多取 4 张
      const loopCount = Math.min(4, sources.length);

      for (let i = 0; i < loopCount; i++) {
        if (!this.isConnected) return;

        const img = new Image();

        const loaded = await new Promise((resolve) => {
          img.onload = () => resolve(true);
          img.onerror = () => resolve(false);
          img.src = sources[i];
        });

        if (!this.isConnected || !loaded) continue;
        this._drawImageWithReflection(ctx, canvas, img, i + 1);
      }
    }

    _drawImageWithReflection(ctx, canvas, img, index) {
      const x = MARGIN_WIDTH * index + POSTER_WIDTH * (index - 1);
      const y = MARGIN_HEIGHT;

      ctx.drawImage(img, x, y, POSTER_WIDTH, POSTER_HEIGHT);

      ctx.save();
      ctx.translate(0, canvas.height);
      ctx.scale(1, -1);
      ctx.drawImage(
        img,
        0,
        0,
        img.width,
        img.height,
        x,
        REFLECTION_SHOW_HEIGHT - REFLECTION_HEIGHT,
        POSTER_WIDTH,
        REFLECTION_HEIGHT
      );

      const gradient = ctx.createLinearGradient(
        0,
        REFLECTION_SHOW_HEIGHT - REFLECTION_HEIGHT,
        0,
        REFLECTION_HEIGHT
      );
      gradient.addColorStop(0, 'rgba(0, 0, 0, 1)');
      gradient.addColorStop(1, 'rgba(0, 0, 0, 0.3)');

      ctx.fillStyle = gradient;
      ctx.fillRect(x, 0, POSTER_WIDTH, REFLECTION_SHOW_HEIGHT);
      ctx.restore();
    }
  }

  if (!customElements.get('custom-plex-library-img')) {
    customElements.define('custom-plex-library-img', CustomPlexLibraryImg);
  }
})();
