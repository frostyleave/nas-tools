"""
密码哈希兼容模块

提供与 werkzeug.security 兼容的密码哈希功能，用于替代 werkzeug 依赖
"""

import hashlib
import hmac
import re
import secrets

SALT_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
DEFAULT_PBKDF2_ITERATIONS = 1_000_000

# 本模块生成的哈希格式：method$salt$hash
_HASH_PATTERN = re.compile(r"^(scrypt:\d+:\d+:\d+|pbkdf2:\w+:\d+)\$[^$]+\$[0-9a-f]+$")


def gen_salt(length: int) -> str:
    """Generate a random string of SALT_CHARS with specified ``length``."""
    if length <= 0:
        raise ValueError("Salt length must be at least 1.")

    return "".join(secrets.choice(SALT_CHARS) for _ in range(length))


def generate_password_hash(
    password: str, method: str = "scrypt", salt_length: int = 16
) -> str:
    """
    生成密码哈希，兼容 werkzeug.security.generate_password_hash

    参数:
        password: 要哈希的密码
        method: 哈希方法，格式为 'pbkdf2:<digest>:<iterations>'
        salt_length: 盐的长度

    返回:
        格式为 'method$salt$hash' 的哈希字符串
    """
    salt = gen_salt(salt_length)

    h, actual_method = _hash_internal(method, salt, password)
    return f"{actual_method}${salt}${h}"

def _hash_internal(method: str, salt: str, password: str) -> tuple[str, str]:
    method, *args = method.split(":")
    salt_bytes = salt.encode()
    password_bytes = password.encode()

    if method == "scrypt":
        if not args:
            n = 2**15
            r = 8
            p = 1
        else:
            try:
                n, r, p = map(int, args)
            except ValueError:
                raise ValueError("'scrypt' takes 3 arguments.") from None

        maxmem = 132 * n * r * p  # ideally 128, but some extra seems needed
        return (
            hashlib.scrypt(
                password_bytes, salt=salt_bytes, n=n, r=r, p=p, maxmem=maxmem
            ).hex(),
            f"scrypt:{n}:{r}:{p}",
        )
    elif method == "pbkdf2":
        len_args = len(args)

        if len_args == 0:
            hash_name = "sha256"
            iterations = DEFAULT_PBKDF2_ITERATIONS
        elif len_args == 1:
            hash_name = args[0]
            iterations = DEFAULT_PBKDF2_ITERATIONS
        elif len_args == 2:
            hash_name = args[0]
            iterations = int(args[1])
        else:
            raise ValueError("'pbkdf2' takes 2 arguments.")

        return (
            hashlib.pbkdf2_hmac(
                hash_name, password_bytes, salt_bytes, iterations
            ).hex(),
            f"pbkdf2:{hash_name}:{iterations}",
        )
    else:
        raise ValueError(f"Invalid hash method '{method}'.")

def normalize_password_hash(value: str) -> str:
    """
    将配置中的密码值归一化为可直接存入数据库的哈希字符串。

    兼容历史格式：[hash] 前缀（可能重复多层）与明文密码。
    返回值不包含 [hash] 前缀。

    参数:
        value: 配置中的密码值

    返回:
        可直接用于 check_password_hash 的哈希字符串
    """
    if not value:
        return generate_password_hash("password")

    value = str(value)
    while value.startswith("[hash]"):
        value = value[len("[hash]"):]

    if not _HASH_PATTERN.match(value):
        value = generate_password_hash(value)

    return value


def check_password_hash(pwhash: str, password: str) -> bool:
    """Securely check that the given stored password hash, previously generated using
    :func:`generate_password_hash`, matches the given password.

    Methods may be deprecated and removed if they are no longer considered secure. To
    migrate old hashes, you may generate a new hash when checking an old hash, or you
    may contact users with a link to reset their password.

    :param pwhash: The hashed password.
    :param password: The plaintext password.

    .. versionchanged:: 2.3
        All plain hashes are deprecated and will not be supported in Werkzeug 3.0.
    """
    try:
        method, salt, hashval = pwhash.split("$", 2)
    except ValueError:
        return False

    return hmac.compare_digest(_hash_internal(method, salt, password)[0], hashval)

