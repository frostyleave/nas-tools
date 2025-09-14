// components.js

// 定义 <nodata-found> 自定义元素
class NoDataFound extends HTMLElement {
  connectedCallback() {
    const title = this.getAttribute('title') || '无记录';
    const text = this.getAttribute('text') || '没有找到任何记录';
    
    this.innerHTML = `
      <div class="page-body">
        <div class="container-xl d-flex flex-column justify-content-center">
          <div class="empty">
            <div class="empty-img">
              <img src="./static/img/sign_in.svg" height="128" alt="No data">
            </div>
            <p class="empty-title">${title}</p>
            <p class="empty-subtitle text-muted">
              ${text}
            </p>
          </div>
        </div>
      </div>
    `;
  }
}

// 定义 <empty-content> 自定义元素
class EmptyContent extends HTMLElement {
  connectedCallback() {
    const title = this.getAttribute('title') || '内容为空';
    const text = this.getAttribute('text') || '这里暂时没有内容';
    
    this.innerHTML = `
      <div class="page-body">
        <div class="container-xl d-flex flex-column justify-content-center">
          <div class="empty">
            <div class="empty-img">
              <img src="./static/img/posting_photo.svg" height="128" alt="Empty content">
            </div>
            <p class="empty-title">${title}</p>
            <p class="empty-subtitle text-muted">
              ${text}
            </p>
          </div>
        </div>
      </div>
    `;
  }
}

// 定义 <system-error> 自定义元素
class SystemError extends HTMLElement {
  connectedCallback() {
    const title = this.getAttribute('title') || '系统错误';
    const text = this.getAttribute('text') || '发生了一个系统错误';
    
    this.innerHTML = `
      <div class="page-body">
        <div class="container-xl d-flex flex-column justify-content-center">
          <div class="empty">
            <div>
              <img src="./static/img/error.svg" class="w-25" alt="System error">
            </div>
            <p class="empty-title fs-1">${title}</p>
            <p class="empty-subtitle text-muted fs-3">
              ${text}
            </p>
          </div>
        </div>
      </div>
    `;
  }
}

// 定义 <loading-indicator> 自定义元素
class LoadingIndicator extends HTMLElement {
  connectedCallback() {
    this.innerHTML = `
      <div class="page-center justify-content-center">
        <div class="container-tight py-4">
          <div class="empty">
            <div class="mb-3">
              <img src="../static/img/quitting_time.svg" height="256" alt="Loading">
            </div>
            <p class="empty-title text-muted">
              正在加载<span class="animated-dots"></span>
            </p>
          </div>
        </div>
      </div>
    `;
  }
}

// 注册自定义元素
customElements.define('nodata-found', NoDataFound);
customElements.define('empty-content', EmptyContent);
customElements.define('system-error', SystemError);
customElements.define('loading-indicator', LoadingIndicator);

// 添加全局动画样式（只添加一次）
if (!document.getElementById('component-styles')) {
  const style = document.createElement('style');
  style.id = 'component-styles';
  style.textContent = `
    @keyframes dotAnimation {
      0%, 20% { content: '.'; }
      40% { content: '..'; }
      60%, 100% { content: '...'; }
    }
    .animated-dots::after {
      content: '...';
      animation: dotAnimation 1.5s infinite step-end;
    }
  `;
  document.head.appendChild(style);
}