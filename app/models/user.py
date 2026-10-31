from app.helper import DbHelper
from app.utils.commons import singleton
from app.utils.password_hash import check_password_hash
from config import Config

# 用户等级：数值越大权限越高
LEVEL_SYSADMIN = 99   # 系统管理员
LEVEL_OPERATOR = 9    # 管理员
LEVEL_USER = 1        # 普通用户


class User:
    """
    用户
    """

    def __init__(self, user=None):
        self.id = None
        self.username = None
        self.password_hash = None
        self.pris = ''
        self.level = LEVEL_USER
        self.admin = False
        self.search = 1
        if user:
            self.id = user.get('id')
            self.username = user.get('name')
            self.password_hash = user.get('password')
            self.pris = user.get('pris') or ''
            level = user.get('level')
            if level is None:
                # 兼容未加 LEVEL 列的旧数据
                level = LEVEL_SYSADMIN if user.get('admin') else (
                    LEVEL_OPERATOR if '系统设置' in self.pris else LEVEL_USER)
            self.level = int(level)
            # admin 由 level 派生，不再单独存储
            self.admin = self.level >= LEVEL_SYSADMIN

    # 验证密码
    def verify_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    # 获取用户ID
    def get_id(self):
        return self.id

    # 查询顶底菜单列表
    def get_topmenus(self):
        if self.admin:
            return [menu.get('name') for menu in (Config().menu or []) if menu.get('name')]
        return [item for item in self.pris.split(',') if item]

    # 查询用户可用菜单
    def get_usermenus(self):
        if self.admin:
            return Config().menu
        menu_lst = self.get_topmenus()
        if menu_lst:
            menuGroup = list(filter(lambda x: x.get("name") in menu_lst, Config().menu))
        else:
            menuGroup = list(filter(lambda x: x.get("level", 0) <= self.level, Config().menu))

        if menuGroup:
            for groupItem in menuGroup:
                navList = groupItem.get('nav')
                if not navList:
                    continue
                navList = list(filter(lambda x: x.get("level", groupItem.get('level'), 1) <= self.level, navList))
                groupItem['nav'] = navList

        return menuGroup

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

    def __init__(self):
        self.dbhelper = DbHelper()

    @staticmethod
    def _to_user(user) -> User:
        return User({
            "id": user.ID,
            "name": user.NAME,
            "password": user.PASSWORD,
            "pris": user.PRIS,
            "level": user.LEVEL
        })

    # 查询用户列表
    def get_users(self):
        return [self._to_user(user) for user in self.dbhelper.get_users()]

    # 新增用户
    def add_user(self, name, password, pris, level=LEVEL_USER) -> int:
        try:
            if self.dbhelper.is_user_exists(name):
                print(f"新增用户失败：用户 {name} 已存在")
                return 0
            self.dbhelper.insert_user(name, password, pris, level)
            return 1
        except Exception as e:
            print(f"新增用户出现严重错误！请检查：{e!s}")
            return 0

    # 删除用户
    def delete_user(self, name) -> int:
        try:
            user = self.get_user_by_name(name)
            if not user:
                return 0
            if user.level >= LEVEL_SYSADMIN and self.get_admin_count() <= 1:
                print("删除用户失败：不能删除最后一个系统管理员")
                return 0
            self.dbhelper.delete_user(name)
            return 1
        except Exception as e:
            print(f"删除用户出现严重错误！请检查：{e!s}")
            return 0

    # 系统管理员数量
    def get_admin_count(self) -> int:
        return len(self.dbhelper.get_users_by_level(LEVEL_SYSADMIN))

    # 获取系统管理员（多管理员时返回最早创建的一个）
    def get_admin_user(self) -> User | None:
        admins = self.dbhelper.get_users_by_level(LEVEL_SYSADMIN)
        return self._to_user(admins[0]) if admins else None

    # 修改用户名
    def rename_user(self, old_name, new_name) -> int:
        if not old_name or not new_name or old_name == new_name:
            return 0
        try:
            if self.dbhelper.is_user_exists(new_name):
                print(f"修改用户名失败：用户 {new_name} 已存在")
                return 0
            if not self.dbhelper.rename_user(old_name, new_name):
                print(f"修改用户名失败：用户 {old_name} 不存在")
                return 0
            return 1
        except Exception as e:
            print(f"修改用户名出现严重错误！请检查：{e!s}")
            return 0

    # 更新用户密码
    def update_user_password(self, user_name, password_hash) -> int:
        if not user_name or not password_hash:
            return 0
        self.dbhelper.update_user_password(user_name, password_hash)
        return 1

    # 更新系统管理员密码（供配置页修改密码时同步）
    def update_admin_password(self, password_hash) -> int:
        admin = self.get_admin_user()
        if not admin:
            return 0
        return self.update_user_password(admin.username, password_hash)

    # 根据用户ID获取用户实体，为 login_user 方法提供支持
    def get_user_by_id(self, user_id) -> User | None:
        if user_id is None:
            return None
        user = self.dbhelper.get_user_by_id(user_id)
        return self._to_user(user) if user else None

    # 根据用户名获取用户对像
    def get_user_by_name(self, user_name) -> User | None:
        if not user_name:
            return None
        user = self.dbhelper.get_user_by_name(user_name)
        return self._to_user(user) if user else None
