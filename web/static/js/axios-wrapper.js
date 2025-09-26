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
 * 响应拦截器 - 处理401错误和自动刷新Token
 */
apiClient.interceptors.response.use(
    (response) => {
        return response;
    },
    async (error) => {
        const originalRequest = error.config;

        // 处理401错误
        if (error.response && error.response.status === 401 && !originalRequest._retry) {
            originalRequest._retry = true;

            try {
                // 尝试刷新Token
                const newToken = await window.authManager.handle401Error();
                
                // 重新设置Authorization头
                originalRequest.headers.Authorization = `Bearer ${newToken}`;
                
                // 重试原始请求
                return apiClient(originalRequest);
            } catch (refreshError) {
                // 刷新失败，已经在authManager中处理了重定向
                return Promise.reject(refreshError);
            }
        }

        return Promise.reject(error);
    }
);

/**
 * axios_post方法 - 替代ajax_post
 * @param {string} cmd - 命令
 * @param {object} params - 参数
 * @param {function} handler - 成功回调
 * @param {boolean} async - 是否异步，默认true
 * @param {boolean} show_progress - 是否显示进度，默认true
 */
function axios_post_do(cmd, params, handler, async = true, show_progress = true) {
    if (show_progress) {
        showLoadingWave();
    }

    const data = {
        cmd: cmd,
        data: params
    };

    const config = {
        method: 'POST',
        url: `do?random=${Math.random()}`,
        data: data,
        timeout: 0, // 与原ajax_post保持一致
    };

    // 发送请求
    const request = apiClient(config);

    request
        .then(response => {
            if (show_progress) {
                hideLoadingWave();
            }
            
            if (handler) {
                handler(response.data);
            }
        })
        .catch(error => {
            if (show_progress) {
                hideLoadingWave();
            }
            // 处理错误
            if (error.response) {
                $("#page_content").html(`<system-error title="${error.response.status}" text="${error.response.data || '请求出错'}"></system-error>`);
            } else {
                console.error('Request failed:', error);
            }
        });

    return request;
}


/**
 * axios_post方法 - 替代ajax_post
 * @param {string} req_url - 命令
 * @param {object} params - 参数
 * @param {function} handler - 成功回调
 * @param {boolean} async - 是否异步，默认true
 * @param {boolean} show_progress - 是否显示进度，默认true
 */
function axios_post(req_url, params, handler, async = true, show_progress = true) {

    if (show_progress) {
        showLoadingWave();
    }

    const config = {
        method: 'POST',
        url: req_url,
        data: params,
        timeout: 0, // 与原ajax_post保持一致
    };

    // 发送请求
    const request = apiClient(config);

    request
        .then(response => {
            if (show_progress) {
                hideLoadingWave();
            }
            
            if (handler) {
                handler(response.data);
            }
        })
        .catch(error => {
            if (show_progress) {
                hideLoadingWave();
            }
            // 处理错误
            if (error.response) {
                $("#page_content").html(`<system-error title="${error.response.status}" text="${error.response.data || '请求出错'}"></system-error>`);
            } else {
                console.error('Request failed:', error);
            }
        });

    return request;
}


/**
 * API请求方法 - 用于调用RESTful API
 * @param {string} url - API路径
 * @param {object} data - 请求数据
 * @param {string} method - HTTP方法，默认POST
 * @param {boolean} show_progress - 是否显示进度，默认true
 */
function api_request(url, data = {}, method = 'POST', show_progress = true) {
    if (show_progress) {
        showLoadingWave();
    }

    const config = {
        method: method,
        url: url,
        [method.toLowerCase() === 'get' ? 'params' : 'data']: data,
    };

    return apiClient(config)
        .then(response => {
            if (show_progress) {
                hideLoadingWave();
            }
            return response.data;
        })
        .catch(error => {
            if (show_progress) {
                hideLoadingWave();
            }
            throw error;
        });
}

// 导出方法到全局作用域
window.axios_post = axios_post;
window.api_request = api_request;
window.axios_client = apiClient;