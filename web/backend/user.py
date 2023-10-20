from flask_login import UserMixin
from werkzeug.security import check_password_hash

from app.helper import DbHelper
from config import Config


class User(UserMixin):
    """
    用户
    """
    dbhelper = None
    admin_users = []

    def __init__(self, user=None):
        self.dbhelper = DbHelper()
        self.admin_users = [{
            "id": 0,
            "name": Config().get_config('app').get('login_user'),
            "password": Config().get_config('app').get('login_password')[6:],
            "pris": "我的媒体库,资源搜索,探索,站点管理,订阅管理,下载管理,媒体整理,服务,系统设置"
        }]
        if user:
            self.id = user.get('id')
            self.username = user.get('name')
            self.password_hash = user.get('password')
            self.pris = user.get('pris')
            self.search = 1
            self.level = 99
            self.admin = 1 if '系统设置' in self.pris else 0

    # 验证密码
    def verify_password(self, password):
        if self.password_hash is None:
            return False
        return check_password_hash(self.password_hash, password)

    # 获取用户ID
    def get_id(self):
        return self.id

    # 根据用户ID获取用户实体，为 login_user 方法提供支持
    def get(self, user_id):

        if user_id is None:
            return None
        for user in self.admin_users:
            if user.get('id') == user_id:
                return User(user)
        for user in self.dbhelper.get_users():
            if not user:
                continue
            if user.ID == user_id:
                return User({"id": user.ID, "name": user.NAME, "password": user.PASSWORD, "pris": user.PRIS})
        return None

    # 根据用户名获取用户对像
    def get_user(self, user_name):
        for user in self.admin_users:
            if user.get("name") == user_name:
                return User(user)
        for user in self.dbhelper.get_users():
            if user.NAME == user_name:
                return User({"id": user.ID, "name": user.NAME, "password": user.PASSWORD, "pris": user.PRIS})
        return None

    # 查询用户列表
    def get_users(self):

        all_user = []
        for user in self.dbhelper.get_users():
            one = User({"id": user.ID, "name": user.NAME, "password": user.PASSWORD, "pris": user.PRIS})
            all_user.append(one)
        return all_user

    # 查询顶底菜单列表
    def get_topmenus(self):
        return self.pris.split(',')

    # 查询用户可用菜单
    def get_usermenus(self):
        if self.admin:
            return Config().menu
        menu = self.get_topmenus()
        return list(filter(lambda x: x.get("name") in menu, Config().menu))

    # 查询服务
    def get_services(self):
        return Config().services

    # 获取所有认证站点
    def get_authsites(self):
        return []

    # 新增用户
    def add_user(self, name, password, pris):
        try:
            self.dbhelper.insert_user(name, password, pris)
            return 1
        except Exception as e:
            print("新增用户出现严重错误！请检查：%s" % str(e))
            return 0

    # 删除用户
    def delete_user(self, name):
        try:
            self.dbhelper.delete_user(name)
            return 1
        except Exception as e:
            print("删除用户出现严重错误！请检查：%s" % str(e))
            return 0

    # 检查用户是否验证通过
    def check_user(self, site, param):
        return 1, ''


