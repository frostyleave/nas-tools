from typing import Optional

from app.helper import DbHelper
from app.utils.commons import singleton
from app.utils.password_hash import check_password_hash

from config import Config

class User:
    """
    用户
    """

    def __init__(self, user=None):
        if user:
            self.id = user.get('id')
            self.username = user.get('name')
            self.password_hash = user.get('password')
            self.pris = user.get('pris')
            self.admin = user.get('admin', 0)
            self.search = 1
            self.level = 99 if self.admin else (2 if '系统设置' in self.pris else 1)

    # 验证密码
    def verify_password(self, password):
        if self.password_hash is None:
            return False
        return check_password_hash(self.password_hash, password)

    # 获取用户ID
    def get_id(self):
        return self.id

    # 查询顶底菜单列表
    def get_topmenus(self):
        return self.pris.split(',')

    # 查询用户可用菜单
    def get_usermenus(self):
        if self.admin:
            return Config().menu
        menu_lst = self.get_topmenus()
        return list(filter(lambda x: x.get("name") in menu_lst, Config().menu))

    # 查询服务
    def get_services(self):
        return Config().services

    # 为FastAPI添加的方法
    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

@singleton
class UserManager:

    dbhelper = None
    admin_user = {}

    def __init__(self):
        self.dbhelper = DbHelper()
        app_config = Config().get_config('app')
        self.admin_user = {
            "id": 0,
            "name": app_config.get('login_user'),
            "password": app_config.get('login_password')[6:],
            "pris": "我的媒体库,探索,资源搜索,订阅管理,下载管理,服务,媒体整理,站点管理,插件,系统设置",
            "admin": 1
        }


    # 查询用户列表
    def get_users(self):
        all_user = []
        for user in self.dbhelper.get_users():
            one = User({"id": user.ID, "name": user.NAME, "password": user.PASSWORD, "pris": user.PRIS})
            all_user.append(one)
        return all_user

    # 新增用户
    def add_user(self, name, password, pris) -> int:
        try:
            self.dbhelper.insert_user(name, password, pris)
            return 1
        except Exception as e:
            print("新增用户出现严重错误！请检查：%s" % str(e))
            return 0

    # 删除用户
    def delete_user(self, name) -> int:
        try:
            self.dbhelper.delete_user(name)
            return 1
        except Exception as e:
            print("删除用户出现严重错误！请检查：%s" % str(e))
            return 0

    def get_admin_user(self) -> User:
        return User(self.admin_user)
    
    # 根据用户ID获取用户实体，为 login_user 方法提供支持
    def get_user_by_id(self, user_id) -> Optional[User]:
        if user_id is None:
            return None
        if self.admin_user == user_id:
            return User(self.admin_user)
        for user in self.dbhelper.get_users():
            if not user:
                continue
            if user.ID == user_id:
                return User({"id": user.ID, "name": user.NAME, "password": user.PASSWORD, "pris": user.PRIS})
        return None

    # 根据用户名获取用户对像
    def get_user_by_name(self, user_name) -> Optional[User]:
        if not user_name:
            return None
        if self.admin_user.get("name") == user_name:
            return User(self.admin_user)
        for user in self.dbhelper.get_users():
            if user.NAME == user_name:
                return User({"id": user.ID, "name": user.NAME, "password": user.PASSWORD, "pris": user.PRIS})
        return None
    