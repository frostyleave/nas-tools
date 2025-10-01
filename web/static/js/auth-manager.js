/**
 * 认证管理器 - 处理Token的存储、刷新和状态管理
 */
class AuthManager {

    constructor() {
        this.isRefreshing = false;
        this.failedQueue = [];
    }

    /**
     * 刷新Access Token
     */
    async refreshAccessToken() {

        try {

            const response = await fetch("/auth/refresh", {
                method: "POST",
                credentials: "include"
            });

            if (!response.ok) {
                this.logout();
                return;
            }

            localStorage.setItem("token", response.data.access_token)

            return 'ok'
        } catch (error) {
            console.log('refresh access token error: ', error);
            this.logout();
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
            console.log('request refresh access token error: ', error);
        } finally {
            this.isRefreshing = false;
        }
    }

    /**
     * 登录，获取 access_token & refresh_token
     */
    redirectToLogin() {
        localStorage.removeItem("token");
        navmenu('login')
    }
           
    /**
     * 登出
     */
    async logout() {       
        // 重定向到登录页
        this.redirectToLogin();
    }

    isLoggedIn() {
        return !!localStorage.getItem("token");
    }
}

// 创建全局实例
window.authManager = new AuthManager();
