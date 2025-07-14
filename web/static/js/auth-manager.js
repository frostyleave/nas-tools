/**
 * 认证管理器 - 处理Token的存储、刷新和状态管理
 */
class AuthManager {
    constructor() {
        this.ACCESS_TOKEN_KEY = 'nas_access_token';
        this.REFRESH_TOKEN_KEY = 'nas_refresh_token';
        this.USER_INFO_KEY = 'nas_user_info';
        this.isRefreshing = false;
        this.failedQueue = [];
    }

    /**
     * 存储Token和用户信息
     */
    setTokens(accessToken, refreshToken, userInfo) {
        if (accessToken) {
            localStorage.setItem(this.ACCESS_TOKEN_KEY, accessToken);
        }
        if (refreshToken) {
            localStorage.setItem(this.REFRESH_TOKEN_KEY, refreshToken);
        }
        if (userInfo) {
            localStorage.setItem(this.USER_INFO_KEY, JSON.stringify(userInfo));
        }
    }

    /**
     * 获取Access Token
     */
    getAccessToken() {
        return localStorage.getItem(this.ACCESS_TOKEN_KEY);
    }

    /**
     * 获取Refresh Token
     */
    getRefreshToken() {
        return localStorage.getItem(this.REFRESH_TOKEN_KEY);
    }

    /**
     * 获取用户信息
     */
    getUserInfo() {
        const userInfo = localStorage.getItem(this.USER_INFO_KEY);
        return userInfo ? JSON.parse(userInfo) : null;
    }

    /**
     * 清除所有认证信息
     */
    clearAuth() {
        localStorage.removeItem(this.ACCESS_TOKEN_KEY);
        localStorage.removeItem(this.REFRESH_TOKEN_KEY);
        localStorage.removeItem(this.USER_INFO_KEY);
    }

    /**
     * 检查是否已登录
     */
    isAuthenticated() {
        return !!(this.getAccessToken() && this.getRefreshToken());
    }

    /**
     * 刷新Access Token
     */
    async refreshAccessToken() {
        const refreshToken = this.getRefreshToken();
        if (!refreshToken) {
            throw new Error('No refresh token available');
        }

        try {
            const response = await fetch('/api/auth/refresh', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    refresh_token: refreshToken
                })
            });

            if (!response.ok) {
                throw new Error('Failed to refresh token');
            }

            const data = await response.json();
            
            if (data.success && data.data) {
                // 更新Access Token
                this.setTokens(data.data.access_token, null, data.data.userinfo);
                return data.data.access_token;
            } else {
                throw new Error(data.message || 'Token refresh failed');
            }
        } catch (error) {
            // 刷新失败，清除认证信息
            this.clearAuth();
            throw error;
        }
    }

    /**
     * 处理Token刷新队列
     */
    processQueue(error, token = null) {
        this.failedQueue.forEach(({ resolve, reject }) => {
            if (error) {
                reject(error);
            } else {
                resolve(token);
            }
        });
        
        this.failedQueue = [];
    }

    /**
     * 获取有效的Access Token（如果过期会自动刷新）
     */
    async getValidAccessToken() {
        const accessToken = this.getAccessToken();
        
        if (!accessToken) {
            throw new Error('No access token available');
        }

        // 如果正在刷新，加入队列等待
        if (this.isRefreshing) {
            return new Promise((resolve, reject) => {
                this.failedQueue.push({ resolve, reject });
            });
        }

        return accessToken;
    }

    /**
     * 处理401错误，尝试刷新Token
     */
    async handle401Error() {
        if (this.isRefreshing) {
            return new Promise((resolve, reject) => {
                this.failedQueue.push({ resolve, reject });
            });
        }

        this.isRefreshing = true;

        try {
            const newToken = await this.refreshAccessToken();
            this.processQueue(null, newToken);
            return newToken;
        } catch (error) {
            this.processQueue(error, null);
            // 重定向到登录页
            this.redirectToLogin();
            throw error;
        } finally {
            this.isRefreshing = false;
        }
    }

    /**
     * 重定向到登录页
     */
    redirectToLogin() {
        const currentPath = window.location.pathname;
        if (currentPath !== '/' && currentPath !== '/login') {
            window.location.href = `/?next=${encodeURIComponent(currentPath)}`;
        } else {
            window.location.href = '/';
        }
    }

    /**
     * 登出
     */
    async logout() {
        const refreshToken = this.getRefreshToken();
        
        // 调用后端登出API
        if (refreshToken) {
            try {
                await fetch('/api/auth/logout', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        refresh_token: refreshToken
                    })
                });
            } catch (error) {
                console.error('Logout API call failed:', error);
            }
        }

        // 清除本地认证信息
        this.clearAuth();
        
        // 重定向到登录页
        this.redirectToLogin();
    }
}

// 创建全局实例
window.authManager = new AuthManager();
