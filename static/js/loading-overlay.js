/**
 * 全局加载遮罩（.loading-wrap）
 * 使用请求令牌（token）记录在途请求，保证并发请求场景下遮罩不会提前关闭；
 * 最后一次 hide 延迟一小段时间生效，把「页面切换」和「页面首个数据请求」合并成一段连续动画。
 */
const LoadingOverlay = (() => {
    // 隐藏延迟：两段加载的间隔小于该值时，动画保持连续不闪烁
    const HIDE_DELAY_MS = 10;

    // 在途请求的令牌集合
    const tokens = new Set();
    let seq = 0;
    let hideTimer = null;

    const apply = () => {
        const el = document.getElementById('loading-elastic');
        if (!el) {
            return;
        }
        // 只切换可见性；display 的任何变化都会让 CSS 动画从头播放。
        // 元素在 index.html 中已预挂载（visibility:hidden），不会经历 display 变化
        el.style.visibility = tokens.size > 0 ? 'visible' : 'hidden';
    };

    const render = () => {
        if (tokens.size > 0) {
            // 有新的在途请求，取消待执行的隐藏
            if (hideTimer !== null) {
                clearTimeout(hideTimer);
                hideTimer = null;
            }
            apply();
        } else if (hideTimer === null) {
            hideTimer = setTimeout(() => {
                hideTimer = null;
                apply();
            }, HIDE_DELAY_MS);
        }
    };

    return {
        // 显示遮罩，返回本次请求的令牌
        show() {
            const token = ++seq;
            tokens.add(token);
            render();
            return token;
        },
        // 隐藏遮罩，传入 show() 返回的令牌
        hide(token) {
            tokens.delete(token);
            render();
        },
    };
})();

window.LoadingOverlay = LoadingOverlay;
