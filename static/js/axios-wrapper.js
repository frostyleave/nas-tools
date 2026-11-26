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
    // silent 请求不会分配令牌，判断令牌即可
    if (config && config._loadingToken !== undefined) {
        LoadingOverlay.hide(config._loadingToken);
        config._loadingToken = undefined;
    }
}

// 属性转义，用于把错误信息拼进 <system-error> 的属性
function escape_error_attr(value) {
    return String(value === undefined || value === null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// 提取错误提示文本
function request_error_text(error) {
    const data = error && error.response ? error.response.data : null;
    if (typeof data === 'string' && data.trim()) {
        return data;
    }
    if (data && typeof data === 'object') {
        if (data.msg) {
            return data.msg;
        }
        if (typeof data.detail === 'string' && data.detail) {
            return data.detail;
        }
    }
    return error && error.response ? `请求失败（${error.response.status}）` : '网络请求失败，请稍后重试';
}

/**
 * 统一错误处理
 * 仅页面级数据请求（/data、非静默、服务端错误）替换整页错误页，
 * 其余请求交给调用方回调或弹出提示，避免轮询/自动保存的瞬时错误清空当前页面。
 */
function handle_request_error(config, error, handler, errorHandler) {
    if (!error || !error.response) {
        console.error('Request failed:', error);
        if (errorHandler) errorHandler(error);
        return;
    }

    const data = error.response.data;
    // 业务错误（/do 返回的结构体）仍交给 handler 处理，保持页面内的失败提示
    if (handler && data && typeof data === 'object' && typeof data.code !== 'undefined') {
        handler(data);
        return;
    }

    if (errorHandler) {
        errorHandler(error);
        return;
    }

    if (config && !config.silent && error.response.status >= 500
        && String(config.url || '').startsWith('/data/')) {
        $("#page-content").html(
            `<system-error title="${escape_error_attr(error.response.status)}" text="${escape_error_attr(request_error_text(error))}"></system-error>`
        );
        return;
    }

    // 静默请求（轮询等）只记录，不打扰用户
    if (config && config.silent) {
        console.error('Request failed:', error);
        return;
    }
    show_fail_modal(request_error_text(error));
}

/**
 * 请求拦截器 - 统一显示加载动画
 * config.silent 为 true 时不显示（如登录、轮询等自带进度的场景）
 */
apiClient.interceptors.request.use(
    (config) => {
        if (!config.silent && config._loadingToken === undefined) {
            config._loadingToken = LoadingOverlay.show();
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

                // 重试原始请求：_loadingToken 仍存在，不会重复显示加载动画
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
 * @param {function} [errorHandler] - 请求失败回调（不传时由统一错误处理提示）
 */
function axios_post_do(cmd, params, handler, show_progress = true, errorHandler) {

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
            handle_request_error(config, error, handler, errorHandler);
        });

    return request;
}


/**
 * axios_post方法 - 替代ajax_post
 * @param {string} req_url - 命令
 * @param {object} params - 参数
 * @param {function} handler - 成功回调
 * @param {boolean} show_progress - 是否显示全局加载动画，默认true
 * @param {function} [errorHandler] - 请求失败回调（不传时由统一错误处理提示）
 */
function axios_post(req_url, params, handler, show_progress = true, errorHandler) {

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
            handle_request_error(config, error, handler, errorHandler);
        });

    return request;
}


/**
 * axios_post_do_async方法 - /do 的异步命令入口
 * @param {string} cmd - 命令
 * @param {object} params - 参数
 * @param {function} handler - 成功回调
 * @param {boolean} show_progress - 是否显示全局加载动画，默认true
 * @param {function} [errorHandler] - 请求失败回调（不传时由统一错误处理提示）
 */
function axios_post_do_async(cmd, params, handler, show_progress = true, errorHandler) {

    return axios_post("/do_async", {
        cmd: cmd,
        data: params
    }, handler, show_progress, errorHandler);
}


// 导出方法到全局作用域
window.axios_post = axios_post;
window.axios_client = apiClient;
