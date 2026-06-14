/**
 * 认证管理器
 * 适用于将Access Token和Refresh Token存储在后端HttpOnly Cookie中的场景。
 * 管理器负责处理因Token过期（返回401状态码）而导致的请求失败，并协调Token刷新和请求重试。
 */
class AuthManager {

    constructor() {
        // 标记是否正在刷新Token，防止重复刷新
        this.isRefreshing = false;
        // 存储因Token失效而失败的请求队列
        this.failedQueue = [];
    }

    /**
     * 调用后端接口刷新Access Token。
     * 浏览器会自动携带HttpOnly Cookie（包含Refresh Token）来完成此请求。
     * 成功后，后端会在响应头中设置新的HttpOnly Cookie（包含新的Access Token）。
     * @returns {Promise<boolean>} 如果刷新成功则返回 true，否则返回 false。
     */
    async refreshAccessToken() {
        try {
            const response = await fetch("/auth/refresh", {
                method: "POST",
                credentials: "include" // 确保跨域请求时携带Cookie
            });

            if (!response.ok) {
                // 刷新失败，则跳转到登陆
                console.error('Failed to refresh token, status:', response.status);
                return false;
            }
            
            // 刷新成功，后端已设置了新的Cookie
            return true;
        } catch (error) {
            console.error('Error during access token refresh:', error);
            return false;
        }
    }

    /**
     * 处理等待队列中的请求。
     * 在Token刷新成功后，会重新执行这些请求。
     * @param {Error|null} error - 如果刷新出错，则为Error对象，否则为null。
     */
    processQueue(error) {
        this.failedQueue.forEach(({ resolve, reject }) => {
            if (error) {
                // 如果Token刷新失败，则拒绝队列中所有请求
                reject(error);
            } else {
                // 如果Token刷新成功，则解决Promise，让原请求可以重试
                resolve();
            }
        });
        
        this.failedQueue = [];
    }

    /**
     * 处理401错误。
     * 这是核心方法，当API请求返回401时被调用。
     * 它会管理Token刷新流程，并将后续的失败请求加入队列。
     * @returns {Promise<void>} 返回一个Promise，在Token刷新后解决。
     */
    async handle401Error() {
        // 如果正在刷新中，将当前请求的resolve和reject方法存入队列，并返回一个pending状态的Promise
        if (this.isRefreshing) {
            return new Promise((resolve, reject) => {
                this.failedQueue.push({ resolve, reject });
            });
        }

        this.isRefreshing = true;

        try {

            const refreshSucceeded = await this.refreshAccessToken();
            if (refreshSucceeded) {
                // Token刷新成功，处理队列中的所有等待请求
                this.processQueue(null);
            } else {
                // 向上抛出错误
                throw new Error(" refresh token failed");
            }
        } catch (error) {
            this.processQueue(error, null);
            // 出现意外错误，重定向到登录页
            this.redirectToLogin();
            // 向上抛出错误
            throw error;
        } finally {
            this.isRefreshing = false;
        }
    }

    /**
     * 重定向到登录页面。
     */
    redirectToLogin() {
        navmenu('login');
    }
           
    /**
     * 登出。
     * 首先通知后端清除会话/Cookie，然后前端重定向到登录页。
     */
    async logout() {
        try {
            // 通知后端登出，后端将清除HttpOnly Cookie
            await fetch('/auth/logout', {
                method: 'POST',
                credentials: 'include'
            });
        } catch (error) {
            console.error('Logout request failed:', error);
        } finally {
            // 无论后端请求是否成功，都将用户重定向到登录页
            this.redirectToLogin();
        }
    }
    
}

// 创建全局实例
window.authManager = new AuthManager();