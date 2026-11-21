"""什么值得买签到重定向回归测试。

全部用 mock，不联网，不用真实账号和 Cookie。

回归场景：个人页请求触发重定向循环（TooManyRedirects）时，
任务不应失败，正式签到应继续执行，个人信息字段为空。

运行方式（仓库根目录，只需装 requests）：

    python -m unittest discover -s tests -v
"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
SMZDM_MAIN = REPO_ROOT / "dailycheckin" / "smzdm" / "main.py"


def _load_smzdm():
    """优先用真实包导入；依赖不全时只按文件加载 smzdm/main.py。

    真实包导入会连带导入全部签到模块，依赖较多；按文件加载时
    用一个最小的 dailycheckin 桩模块提供 CheckIn 基类。
    两种方式测的都是同一个文件里的 SMZDM 类。
    """
    try:
        from dailycheckin.smzdm.main import SMZDM

        return SMZDM
    except Exception:
        for name in list(sys.modules):
            if name == "dailycheckin" or name.startswith("dailycheckin."):
                del sys.modules[name]
    pkg = types.ModuleType("dailycheckin")
    pkg.__path__ = []

    class CheckIn:
        name = "Base"

    pkg.CheckIn = CheckIn
    sys.modules["dailycheckin"] = pkg
    spec = importlib.util.spec_from_file_location("dailycheckin.smzdm.main", SMZDM_MAIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules["dailycheckin.smzdm.main"] = module
    spec.loader.exec_module(module)
    return module.SMZDM


SMZDM = _load_smzdm()


def _mock_post(url="", **kwargs):
    """按 URL 分流的 POST mock，返回固定成功结果。"""
    resp = MagicMock()
    if "robot/token" in url:
        resp.json.return_value = {"data": {"token": "fake-token"}}
    elif "checkin/all_reward" in url:
        resp.json.return_value = {"data": {"normal_reward": None}}
    elif "checkin" in url:
        resp.json.return_value = {"error_msg": "签到成功"}
    elif "jsonp_draw" in url:
        resp.json.return_value = {"error_msg": "抽奖成功"}
    else:
        raise AssertionError(f"未预期的 POST 地址: {url}")
    return resp


class TestSmzdmRedirect(unittest.TestCase):
    def test_info_redirect_does_not_fail_task(self):
        """个人页重定向循环时，任务继续，正式签到照常执行。"""

        def _mock_get(url="", **kwargs):
            raise requests.exceptions.TooManyRedirects("Exceeded 30 redirects.")

        with (
            patch("requests.post", side_effect=_mock_post),
            patch("requests.get", side_effect=_mock_get),
        ):
            result = SMZDM(check_item={"cookie": "fake-cookie"}).main()

        self.assertIn("抽奖成功", result)
        self.assertIn("签到成功", result)
        # 个人信息拿不到时字段为空，但任务本身成功
        self.assertIn("昵称: ", result)
        self.assertIn("等级: ", result)

    def test_info_success_still_parses(self):
        """个人页正常时，昵称、等级、金币、碎银仍能解析出来。"""
        pad = "\n" + " " * 20
        html = (
            '<a href="https://zhiyou.smzdm.com/user"> 测试昵称 </a>'
            '<img src="https://res.smzdm.com/h5/h5_user/dist/assets/level/v8.png?v=1">'
            '<div class="assets-part assets-gold">'
            + pad
            + '<span class="assets-part-element assets-num">123</span>'
            + '<div class="assets-part assets-prestige">'
            + pad
            + '<span class="assets-part-element assets-num">456</span>'
        )

        def _mock_get(url="", **kwargs):
            resp = MagicMock()
            resp.text = html
            resp.json.return_value = {}
            return resp

        with (
            patch("requests.post", side_effect=_mock_post),
            patch("requests.get", side_effect=_mock_get),
        ):
            result = SMZDM(check_item={"cookie": "fake-cookie"}).main()

        self.assertIn("昵称: 测试昵称", result)
        self.assertIn("等级: v8", result)
        self.assertIn("金币: 123", result)
        self.assertIn("碎银: 456", result)

    def test_lottery_failure_still_raises(self):
        """抽奖请求本身失败时，仍应如实抛错，不被掩盖。"""

        def _mock_post_fail(url="", **kwargs):
            if "jsonp_draw" in url:
                raise requests.exceptions.ConnectionError("网络不通")
            return _mock_post(url, **kwargs)

        with (
            patch("requests.post", side_effect=_mock_post_fail),
            patch("requests.get"),
        ):
            with self.assertRaises(requests.exceptions.ConnectionError):
                SMZDM(check_item={"cookie": "fake-cookie"}).main()


if __name__ == "__main__":
    unittest.main()
