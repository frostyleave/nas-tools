import base64

from app.utils import RequestUtils
from config import Config


OCR_B64_URL = "https://ocr.ddsrem.com/captcha/base64"


class OcrHelper:

    @staticmethod
    def get_captcha_text(image_url=None, image_b64=None, cookie=None, ua=None):
        """
        根据图片地址，获取验证码图片，并识别内容
        :param image_url: 图片地址
        :param image_b64: 图片base64，跳过图片地址下载
        :param cookie: 下载图片使用的cookie
        :param ua: 下载图片使用的ua
        """
        
        ocr_cfg_url = Config().get_config("app").get("ocr_url")
        if ocr_cfg_url:
            ocr_url = ocr_cfg_url
        else:
            ocr_url = OCR_B64_URL

        if image_url:
            ret = RequestUtils(ua=ua, cookies=cookie).get_res(image_url)
            if ret is not None:
                if ret.content:
                    image_b64 = base64.b64encode(ret.content).decode()

        if not image_b64:
            return ""

        json_params = {"base64_img": image_b64}
        ret = RequestUtils(content_type="application/json").post_res(url=ocr_url, json=json_params)
        
        if ret:
            return ret.json().get("result") or ""
        
        return ""
