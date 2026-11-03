/**
 * Axios封装 - 替代ajax_post方法，包含自动Token管理和401错误处理
 */

// 检查是否已加载axios
if (typeof axios === 'undefined') {
    console.error('Axios library is required but not loaded');
}

/**
 * 创建axios实例
 */
const apiClient = axios.create({
    timeout: 30000,
    baseURL: "/",
    withCredentials: true
});

/**
 * 释放请求占用的加载动画（引用计数减一）
 * @param {object} config - 请求配置
 */
function releaseLoadingOverlay(config) {
    if (config && !config.silent && config._loadingShown) {
        config._loadingShown = false;
        LoadingOverlay.hide();
    }
}

/**
 * 请求拦截器 - 统一显示加载动画
 * config.silent 为 true 时不显示（如登录、轮询等自带进度的场景）
 */
apiClient.interceptors.request.use(
    (config) => {
        if (!config.silent && !config._loadingShown) {
            config._loadingShown = true;
            LoadingOverlay.show();
        }
        return config;
    },
    (error) => Promise.reject(error)
);

/**
 * 响应拦截器 - 统一隐藏加载动画，处理401错误和自动刷新Token
 */
apiClient.interceptors.response.use(
    (response) => {
        releaseLoadingOverlay(response.config);
        return response;
    },
    async (error) => {
        const originalRequest = error.config;

        // 处理401错误
        if (originalRequest && error.response && error.response.status === 401 && !originalRequest._retry) {
            originalRequest._retry = true;

            try {

                // 尝试刷新Token
                await window.authManager.handle401Error();

                // 重试原始请求：_loadingShown 仍为 true，不会重复显示加载动画
                return apiClient(originalRequest);
            } catch (refreshError) {
                // 刷新失败，已经在authManager中处理了重定向
                releaseLoadingOverlay(originalRequest);
                return Promise.reject(refreshError);
            }
        }

        releaseLoadingOverlay(originalRequest);
        return Promise.reject(error);
    }
);

/**
 * axios_post方法 - 替代ajax_post
 * @param {string} cmd - 命令
 * @param {object} params - 参数
 * @param {function} handler - 成功回调
 * @param {boolean} show_progress - 是否显示全局加载动画，默认true
 */
function axios_post_do(cmd, params, handler, show_progress = true) {

    const data = {
        cmd: cmd,
        data: params
    };

    const config = {
        method: 'POST',
        url: `do?random=${Math.random()}`,
        data: data,
        timeout: 0,
        silent: !show_progress
    };

    // 发送请求
    const request = apiClient(config);

    request
        .then(response => {
            if (handler) {
                handler(response.data);
            }
        })
        .catch(error => {
            // 处理错误
            if (error.response) {
                $("#page-content").html(`<system-error title="${error.response.status}" text="${error.response.data || '请求出错'}"></system-error>`);
                handler(error.response.data);
            } else {
                console.error('axios_post_do failed:', error);
            }
        });

    return request;
}


/**
 * axios_post方法 - 替代ajax_post
 * @param {string} req_url - 命令
 * @param {object} params - 参数
 * @param {function} handler - 成功回调
 * @param {boolean} show_progress - 是否显示全局加载动画，默认true
 */
function axios_post(req_url, params, handler, show_progress = true) {

    const config = {
        method: 'POST',
        url: req_url,
        data: params,
        timeout: 0, // 与原ajax_post保持一致
        silent: !show_progress
    };

    // 发送请求
    const request = apiClient(config);

    request
        .then(response => {
            if (handler) {
                handler(response.data);
            }
        })
        .catch(error => {
            // 处理错误
            if (error.response) {
                $("#page-content").html(`<system-error title="${error.response.status}" text="${error.response.data || '请求出错'}"></system-error>`);
            } else {
                console.error('Request failed:', error);
            }
        });

    return request;
}


// 导出方法到全局作用域
window.axios_post = axios_post;
window.axios_client = apiClient;
