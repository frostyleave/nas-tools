import base64
import hashlib
import json
import time

from app.models.model import UserSiteConf
from app.plugins.modules._autosignin._base import _ISiteSigninHandler
from app.utils import JsonUtils, RequestUtils, SiteUtils
from config import Config


class YemaPT(_ISiteSigninHandler):
    """
    YemaPT 签到（Altcha 工作量证明）
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "yemapt.org"

    # 接口地址
    _checkin_info_url = "https://www.yemapt.org/api/consumer/fetchCheckInPageInfo"
    _challenge_url = "https://www.yemapt.org/api/captcha/generateAltchaChallenge"
    _checkin_url = "https://www.yemapt.org/api/consumer/checkIn"

    # 人机验证所属功能
    _altcha_feature = "checkIn"
    # 人机验证支持的摘要算法
    _altcha_hashes = {
        "PBKDF2/SHA-256": "sha256",
        "PBKDF2/SHA-384": "sha384",
        "PBKDF2/SHA-512": "sha512",
    }
    # 求解上限，站点下发的 counter 通常只有几百
    _altcha_max_counter = 10000
    _altcha_timeout = 30

    @classmethod
    def match(cls, url):
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return bool(SiteUtils.url_equal(url, cls.site_url))

    def signin(self, site_info: UserSiteConf):
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.name
        if not site_info.cookie:
            return False, f'[{site}]签到失败: 未配置Cookie'

        ua = site_info.ua or Config().get_ua()
        proxy = Config().get_proxies() if site_info.proxy else None
        request = RequestUtils(
            headers={
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "User-Agent": ua
            },
            cookies=site_info.cookie,
            proxies=proxy,
            timeout=30
        )

        # 查询签到状态，已签到直接返回，避免重复请求验证
        info_res = request.get_res(url=self._checkin_info_url)
        if not info_res:
            return False, f'[{site}]签到失败: 无法连接站点'
        info = JsonUtils.loads(info_res.text, default={}) or {}
        if not info.get("success"):
            if info.get("errorCode") in (400, 401):
                return False, f'[{site}]签到失败: Cookie已失效'
            return False, f'[{site}]签到失败: {info.get("errorMessage") or "获取签到信息失败"}'
        if (info.get("data") or {}).get("checkedInToday"):
            return True, f'[{site}]今日已签到'

        # 获取并求解 Altcha 人机验证，未开启验证时提交空对象
        body = {}
        challenge = self.__post_json(request, self._challenge_url,
                                     {"feature": self._altcha_feature})
        if challenge is None:
            return False, f'[{site}]签到失败: 获取人机验证信息失败'
        if not challenge.get("success"):
            return False, f'[{site}]签到失败: {challenge.get("errorMessage") or "获取人机验证信息失败"}'
        challenge_data = challenge.get("data") or {}
        parameters = challenge_data.get("parameters")
        if parameters:
            solution = self.__solve_altcha(parameters)
            if not solution:
                return False, f'[{site}]签到失败: 人机验证求解失败'
            body["altchaPayload"] = self.__build_altcha_payload(
                parameters, challenge_data.get("signature"), solution)

        # 提交签到
        result = self.__post_json(request, self._checkin_url, body)
        if result is None:
            return False, f'[{site}]签到失败: 签到接口请求失败'
        if result.get("success"):
            bonus = result.get("data")
            if isinstance(bonus, (int, float)):
                return True, f'[{site}]签到成功，获得{int(bonus)}积分'
            return True, f'[{site}]签到成功'

        message = result.get("errorMessage") or ""
        if "已签到" in message or "已经签到" in message:
            return True, f'[{site}]今日已签到'
        return False, f'[{site}]签到失败: {message or "未知原因"}'

    @staticmethod
    def __post_json(request: RequestUtils, url: str, body: dict) -> dict | None:
        """
        发送JSON请求并解析响应，请求失败时返回None
        """
        res = request.post_res(url=url, json=body)
        if not res:
            return None
        result = JsonUtils.loads(res.text, default=None, silent=True)
        return result if isinstance(result, dict) else None

    @classmethod
    def __solve_altcha(cls, parameters: dict) -> dict | None:
        """
        求解 Altcha 工作量证明：找到使 PBKDF2(nonce+counter, salt) 以 keyPrefix 开头的 counter
        """
        digest_name = cls._altcha_hashes.get(parameters.get("algorithm"))
        if not digest_name:
            return None
        try:
            nonce = bytes.fromhex(parameters.get("nonce") or "")
            salt = bytes.fromhex(parameters.get("salt") or "")
            key_prefix = bytes.fromhex(parameters.get("keyPrefix") or "")
            cost = int(parameters.get("cost") or 10000)
            key_length = int(parameters.get("keyLength") or 32)
        except (TypeError, ValueError):
            return None

        started = time.time()
        for counter in range(cls._altcha_max_counter):
            if counter % 200 == 0 and time.time() - started > cls._altcha_timeout:
                return None
            derived_key = hashlib.pbkdf2_hmac(digest_name,
                                              nonce + counter.to_bytes(4, "big"),
                                              salt, cost, key_length)
            if derived_key.startswith(key_prefix):
                return {
                    "counter": counter,
                    "derivedKey": derived_key.hex(),
                    "time": int((time.time() - started) * 1000)
                }
        return None

    @staticmethod
    def __build_altcha_payload(parameters: dict, signature: str | None, solution: dict) -> str:
        """
        按前端格式组装提交给服务端的 altchaPayload
        """
        payload = {
            "challenge": {
                "parameters": parameters,
                "signature": signature
            },
            "solution": solution
        }
        return base64.b64encode(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).decode("utf-8")
