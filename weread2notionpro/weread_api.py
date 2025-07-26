import hashlib
import json
import os
import re
import time
import logging

import requests
from requests.utils import cookiejar_from_dict
from retrying import retry
from urllib.parse import quote
from dotenv import load_dotenv

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

# API端点配置
WEREAD_URL = "https://weread.qq.com/"
WEREAD_NOTEBOOKS_URL = "https://weread.qq.com/api/user/notebook"
WEREAD_BOOKMARKLIST_URL = "https://weread.qq.com/web/book/bookmarklist"
WEREAD_CHAPTER_INFO = "https://weread.qq.com/web/book/chapterInfos"
WEREAD_READ_INFO_URL = "https://weread.qq.com/web/book/readinfo"
WEREAD_REVIEW_LIST_URL = "https://weread.qq.com/web/review/list"
WEREAD_BOOK_INFO = "https://weread.qq.com/web/book/info"
WEREAD_READDATA_DETAIL = "https://i.weread.qq.com/readdata/detail"
WEREAD_HISTORY_URL = "https://i.weread.qq.com/readdata/summary?synckey=0"


class WeReadApi:
    def __init__(self):
        self.cookie = self.get_cookie()
        self.session = requests.Session()
        self.session.cookies = self.parse_cookie_string()

    def refresh_token(self, exception=None):
        """刷新session保持有效性"""
        try:
            logging.info("刷新微信读书session...")
            self.session.get(WEREAD_URL)
        except Exception as e:
            logging.error(f"刷新token失败: {e}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def try_get_cloud_cookie(self, url, id, password):
        if url.endswith("/"):
            url = url[:-1]
        req_url = f"{url}/get/{id}"
        data = {"password": password}
        result = None
        try:
            self.session.get(WEREAD_URL)
            response = requests.post(req_url, data=data)
            if response.status_code == 200:
                data = response.json()
                cookie_data = data.get("cookie_data")
                if cookie_data and "weread.qq.com" in cookie_data:
                    cookies = cookie_data["weread.qq.com"]
                    cookie_str = "; ".join(
                        [f"{cookie['name']}={cookie['value']}" for cookie in cookies]
                    )
                    result = cookie_str
        except Exception as e:
            logging.error(f"从CookieCloud获取cookie失败: {e}")
        return result

    def get_cookie(self):
        url = os.getenv("CC_URL")
        if not url:
            url = "https://cookiecloud.malinkang.com/"
        id = os.getenv("CC_ID")
        password = os.getenv("CC_PASSWORD")
        cookie = os.getenv("WEREAD_COOKIE")
        if url and id and password:
            cookie = self.try_get_cloud_cookie(url, id, password)
        if not cookie or not cookie.strip():
            raise Exception("没有找到cookie，请按照文档填写cookie")
        return cookie

    def parse_cookie_string(self):
        cookies_dict = {}
        pattern = re.compile(r'([^=]+)=([^;]+);?\s*')
        matches = pattern.findall(self.cookie)
        
        for key, value in matches:
            cookies_dict[key] = value
        cookiejar = cookiejar_from_dict(cookies_dict)
        return cookiejar

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_bookshelf(self):
        """获取书架信息"""
        self.session.get(WEREAD_URL)
        r = self.session.get(
            "https://weread.qq.com/shelf/sync?synckey=0&teenmode=0&album=1&onlyBookid=0"
        )
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"获取书架信息失败: {r.text}")
        
    def handle_errcode(self, errcode):
        if errcode in (-2012, -2010):
            error_msg = "微信读书Cookie过期了，请参考文档重新设置。https://mp.weixin.qq.com/s/B_mqLUZv7M1rmXRsMlBf7A"
            logging.error(error_msg)
            raise Exception(error_msg)

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_notebooklist(self):
        """获取笔记本列表"""
        self.session.get(WEREAD_URL)
        r = self.session.get(WEREAD_NOTEBOOKS_URL)
        if r.ok:
            data = r.json()
            books = data.get("books", [])
            books.sort(key=lambda x: x["sort"])
            return books
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"获取笔记本列表失败: {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_bookinfo(self, bookId):
        """获取书的详情"""
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId)
        r = self.session.get(WEREAD_BOOK_INFO, params=params)
        if r.ok:
            data = r.json()
            isbn = data.get("isbn", "")
            newRating = data.get("newRating", 0) / 1000
            return (isbn, newRating)
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            logging.error(f"获取书籍信息失败: {r.text}")
            return ("", 0)

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_bookmark_list(self, bookId):
        """获取划线列表"""
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId)
        r = self.session.get(WEREAD_BOOKMARKLIST_URL, params=params)
        if r.ok:
            bookmarks = r.json().get("updated", [])
            # 修复括号缺失问题：补充闭合括号
            return sorted(
                bookmarks,
                key=lambda x: (x.get("chapterUid", 1), int(x.get("range", "0-0").split("-")[0]))
            )
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"获取划线列表失败: {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_read_info(self, bookId):
        """获取阅读信息"""
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId, readingDetail=1, readingBookIndex=1, finishedDate=1)
        r = self.session.get(WEREAD_READ_INFO_URL, params=params)
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"获取阅读信息失败: {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_review_list(self, bookId):
        """获取笔记列表"""
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId, listType=11, mine=1, syncKey=0)
        r = self.session.get(WEREAD_REVIEW_LIST_URL, params=params)
        if r.ok:
            reviews = r.json().get("reviews", [])
            summary = [x for x in reviews if x.get("review", {}).get("type") == 4]
            reviews = [x for x in reviews if x.get("review", {}).get("type") == 1]
            reviews = [x.get("review") for x in reviews]
            reviews = [{**x, "markText": x.pop("content")} for x in reviews]
            return summary, reviews
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"获取笔记列表失败: {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_api_data(self):
        """获取API数据"""
        self.session.get(WEREAD_URL)
        r = self.session.get(WEREAD_HISTORY_URL)
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"获取历史阅读数据失败: {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_chapter_info(self, bookId):
        """获取章节信息"""
        self.session.get(WEREAD_URL)
        body = {"bookIds": [bookId], "synckeys": [0], "teenmode": 0}
        r = self.session.post(WEREAD_CHAPTER_INFO, json=body)
        if r.ok and "data" in r.json() and len(r.json()["data"]) == 1:
            update = r.json()["data"][0].get("updated", [])
            return {item["chapterUid"]: item for item in update}
        else:
            raise Exception(f"获取章节信息失败: {r.text}")

    def transform_id(self, book_id):
        id_length = len(book_id)
        if re.match("^\\d*$", book_id):
            ary = []
            for i in range(0, id_length, 9):
                ary.append(format(int(book_id[i : min(i + 9, id_length)]), "x"))
            return "3", ary

        result = ""
        for i in range(id_length):
            result += format(ord(book_id[i]), "x")
        return "4", [result]

    def calculate_book_str_id(self, book_id):
        md5 = hashlib.md5()
        md5.update(book_id.encode("utf-8"))
        digest = md5.hexdigest()
        result = digest[0:3]
        code, transformed_ids = self.transform_id(book_id)
        result += code + "2" + digest[-2:]

        for i in range(len(transformed_ids)):
            hex_length_str = format(len(transformed_ids[i]), "x")
            if len(hex_length_str) == 1:
                hex_length_str = "0" + hex_length_str

            result += hex_length_str + transformed_ids[i]

            if i < len(transformed_ids) - 1:
                result += "g"

        if len(result) < 20:
            result += digest[0 : 20 - len(result)]

        md5 = hashlib.md5()
        md5.update(result.encode("utf-8"))
        result += md5.hexdigest()[0:3]
        return result

    def get_url(self, book_id):
        return f"https://weread.qq.com/web/reader/{self.calculate_book_str_id(book_id)}"
