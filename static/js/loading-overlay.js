/**
 * 全局加载遮罩（.loading-wrap）
 * 使用引用计数，保证并发请求场景下遮罩不会提前关闭。
 */
const LoadingOverlay = (() => {
    let count = 0;

    const render = () => {
        const el = document.getElementById('loading-scan-grid');
        if (el) {
            el.style.display = count > 0 ? 'flex' : 'none';
        }
    };

    return {
        // 显示遮罩，每调用一次计数加一
        show() {
            count++;
            render();
        },
        // 隐藏遮罩，每调用一次计数减一，计数归零时才真正隐藏
        hide() {
            count = Math.max(0, count - 1);
            render();
        },
        // 强制清空计数并隐藏遮罩
        reset() {
            count = 0;
            render();
        },
    };
})();

window.LoadingOverlay = LoadingOverlay;
