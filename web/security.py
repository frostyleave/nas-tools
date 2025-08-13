import datetime
import hashlib
import secrets
import jwt

from config import Config
from app.helper.db_helper import DbHelper


def generate_access_token(username: str, algorithm: str = 'HS256', exp: float = 2):
    """
    生成access_token
    :param username: 用户名(自定义部分)
    :param algorithm: 加密算法
    :param exp: 过期时间，默认2小时
    :return:token
    """

    now = datetime.datetime.utcnow()
    exp_datetime = now + datetime.timedelta(hours=exp)
    access_payload = {
        'exp': exp_datetime,
        'iat': now,
        'username': username,
        'type': 'access'
    }
    access_token = jwt.encode(access_payload,
                              Config().get_config("security").get("api_key"),
                              algorithm=algorithm)
    return access_token


def generate_refresh_token(user_id: int, device_info: str = None, algorithm: str = 'HS256', exp_days: int = 30):
    """
    生成refresh_token
    :param user_id: 用户ID
    :param device_info: 设备信息
    :param algorithm: 加密算法
    :param exp_days: 过期时间，默认30天
    :return: refresh_token
    """
    now = datetime.datetime.utcnow()
    exp_datetime = now + datetime.timedelta(days=exp_days)

    # 生成随机字符串作为jti
    jti = secrets.token_urlsafe(32)

    refresh_payload = {
        'exp': exp_datetime,
        'iat': now,
        'user_id': user_id,
        'jti': jti,
        'type': 'refresh'
    }

    refresh_token = jwt.encode(refresh_payload,
                              Config().get_config("security").get("api_key"),
                              algorithm=algorithm)

    # 将refresh_token存储到数据库
    db_helper = DbHelper()
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

    db_helper.insert_refresh_token(
        user_id=user_id,
        token_hash=token_hash,
        device_info=device_info,
        created_at=now.strftime("%Y-%m-%d %H:%M:%S"),
        expires_at=exp_datetime.strftime("%Y-%m-%d %H:%M:%S")
    )

    return refresh_token


def __decode_auth_token(token: str, algorithms='HS256'):
    """
    解密token
    :param token:token字符串
    :return: 是否有效，playload
    """
    key = Config().get_config("security").get("api_key")
    try:
        payload = jwt.decode(token,
                             key=key,
                             algorithms=algorithms)
    except jwt.ExpiredSignatureError:
        return False, jwt.decode(token,
                                 key=key,
                                 algorithms=algorithms,
                                 options={'verify_exp': False})
    except (jwt.DecodeError, jwt.InvalidTokenError, jwt.ImmatureSignatureError):
        return False, {}
    else:
        return True, payload


def identify(auth_header: str):
    """
    用户鉴权，返回是否有效、用户名
    """
    flag = False
    if auth_header:
        flag, payload = __decode_auth_token(auth_header)
        if payload:
            return flag, payload.get("username") or ""
    return flag, ""


def verify_refresh_token(refresh_token: str):
    """
    验证refresh_token
    :param refresh_token: refresh_token字符串
    :return: (是否有效, user_id)
    """
    try:
        # 解码token
        flag, payload = __decode_auth_token(refresh_token)
        if not payload or payload.get('type') != 'refresh':
            return False, None

        user_id = payload.get('user_id')
        if not user_id:
            return False, None

        # 检查数据库中的token是否有效
        db_helper = DbHelper()
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

        # 清理过期token
        current_time = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        db_helper.cleanup_expired_refresh_tokens(current_time)

        # 查找token
        tokens = db_helper.get_refresh_tokens(token_hash=token_hash, active_only=True)
        if not tokens:
            return False, None

        # 检查用户是否存在
        from web.backend.user import UserManager
        user = UserManager().get_user_by_id(user_id)
        if not user:
            return False, None

        # 更新最后使用时间
        db_helper.update_refresh_token_last_used(token_hash, current_time)

        return flag, user_id

    except Exception as e:
        return False, None


def refresh_access_token(refresh_token: str):
    """
    使用refresh_token刷新access_token
    :param refresh_token: refresh_token字符串
    :return: (是否成功, new_access_token, username)
    """
    is_valid, user_id = verify_refresh_token(refresh_token)
    if not is_valid or not user_id:
        return False, None, None

    # 获取用户信息
    from web.backend.user import UserManager
    user = UserManager().get_user_by_id(user_id)
    if not user:
        return False, None, None

    # 生成新的access_token
    new_access_token = generate_access_token(user.username)

    return True, new_access_token, user.username


def revoke_refresh_token(refresh_token: str):
    """
    吊销refresh_token
    :param refresh_token: refresh_token字符串
    :return: 是否成功
    """
    try:
        db_helper = DbHelper()
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        db_helper.deactivate_refresh_tokens(token_hash=token_hash)
        return True
    except:
        return False


def revoke_user_refresh_tokens(user_id: int):
    """
    吊销用户的所有refresh_token（用于登出所有设备）
    :param user_id: 用户ID
    :return: 是否成功
    """
    try:
        db_helper = DbHelper()
        db_helper.deactivate_refresh_tokens(user_id=user_id)
        return True
    except:
        return False

