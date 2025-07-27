import hashlib
import json
import os
import re
import time

import requests
from requests.utils import cookiejar_from_dict
from retrying import retry
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()
WEREAD_URL = "https://weread.qq.com/"
WEREAD_NOTEBOOKS_URL = "https://weread.qq.com/api/user/notebook"
WEREAD_BOOKMARKLIST_URL = "https://weread.qq.com/web/book/bookmarklist"
WEREAD_CHAPTER_INFO = "https://weread.qq.com/web/book/chapterInfos"
WEREAD_READ_INFO_URL = "https://weread.qq.com/web/book/readinfo"
WEREAD_REVIEW_LIST_URL = "https://weread.qq.com/web/review/list"
WEREAD_BOOK_INFO = "https://weread.qq.com/web/book/info"
WEREAD_READDATA_DETAIL = "https://weread.qq.com/web/readdata/detail"
WEREAD_HISTORY_URL = "https://weread.qq.com/web/readdata/summary?synckey=0"


class WeReadApi:
    def __init__(self):
        self.cookie = self.get_cookie()
        self.session = requests.Session()
        self.session.cookies = self.parse_cookie_string()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://weread.qq.com/"
        })

    def try_get_cloud_cookie(self, url, id, password):
        if url.endswith("/"):
            url = url[:-1]
        req_url = f"{url}/get/{id}"
        data = {"password": password}
        result = None
        try:
            response = requests.post(req_url, data=data, timeout=10)
            if response.status_code == 200:
                data = response.json()
                cookie_data = data.get("cookie_data")
                if cookie_data and "weread.qq.com" in cookie_data:
                    cookies = cookie_data["weread.qq.com"]
                    cookie_str = "; ".join(
                        [f"{cookie['name']}={cookie['value']}" for cookie in cookies]
                    )
                    result = cookie_str
            else:
                print(f"获取云端Cookie失败，状态码: {response.status_code}")
        except Exception as e:
            print(f"获取云端Cookie异常: {str(e)}")
        return result

    def get_cookie(self):
        url = os.getenv("CC_URL", "https://cookiecloud.malinkang.com/")
        id = os.getenv("CC_ID")
        password = os.getenv("CC_PASSWORD")
        cookie = os.getenv("WEREAD_COOKIE")
        
        if url and id and password:
            cookie = self.try_get_cloud_cookie(url, id, password)
        
        if not cookie or not cookie.strip():
            raise Exception("没有找到有效的cookie，请按照文档填写cookie")
        return cookie

    def parse_cookie_string(self):
        cookies_dict = {}
        pattern = re.compile(r'([^=]+)=([^;]+);?\s*')
        matches = pattern.findall(self.cookie)
        
        for key, value in matches:
            cookies_dict[key] = value
        
        return cookiejar_from_dict(cookies_dict)

    def refresh_token(self, exception):
        print(f"尝试刷新Token，原因: {str(exception)}")
        self.session.get(WEREAD_URL)
        return True

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_bookshelf(self):
        try:
            self.session.get(WEREAD_URL)
            r = self.session.get(
                "https://weread.qq.com/web/shelf/sync?synckey=0&teenmode=0&album=1&onlyBookid=0",
                timeout=10
            )
            
            if r.status_code != 200:
                raise Exception(f"获取书架失败，状态码: {r.status_code}，响应: {r.text[:200]}")
            
            data = r.json()
            
            if not isinstance(data, dict):
                raise ValueError(f"书架数据格式错误，预期dict，实际: {type(data)}")
            
            # 处理可能缺失或为None的字段
            data["archive"] = data.get("archive") or []
            data["bookProgress"] = data.get("bookProgress") or []
            data["books"] = data.get("books") or []
                
            return data
            
        except requests.exceptions.Timeout:
            raise Exception("获取书架超时")
        except json.JSONDecodeError:
            raise Exception(f"解析书架JSON失败，响应内容: {r.text[:200]}")
        except Exception as e:
            try:
                err_data = r.json()
                errcode = err_data.get("errcode", -1)
                self.handle_errcode(errcode)
            except:
                pass
            raise Exception(f"获取书架失败: {str(e)}")
        
    def handle_errcode(self, errcode):
        error_messages = {
            -2012: "微信读书Cookie过期了，请参考文档重新设置",
            -2010: "微信读书Cookie无效，请检查Cookie是否正确"
        }
        if errcode in error_messages:
            print(f"::error::{error_messages[errcode]}。https://mp.weixin.qq.com/s/B_mqLUZv7M1rmXRsMlBf7A")

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_notebooklist(self):
        self.session.get(WEREAD_URL)
        r = self.session.get(WEREAD_NOTEBOOKS_URL, timeout=10)
        if r.status_code != 200:
            print(f"获取笔记本列表失败，状态码: {r.status_code}，跳过处理")
            return []  # 返回空列表而不是抛出异常
        try:
            data = r.json()
            books = data.get("books", [])
            if not isinstance(books, list):
                print("警告：notebooklist返回的books不是列表，已修正为[]")
                books = []
            books.sort(key=lambda x: x.get("sort", 0))
            return books
        except Exception as e:
            print(f"获取笔记本列表异常: {str(e)}，跳过处理")
            return []

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_bookinfo(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId)
        r = self.session.get(WEREAD_BOOK_INFO, params=params, timeout=10)
        if r.status_code != 200:
            print(f"获取书籍信息失败，状态码: {r.status_code}，跳过处理")
            return None
        try:
            return r.json()
        except Exception as e:
            print(f"获取书籍信息异常: {str(e)}，跳过处理")
            return None

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_bookmark_list(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId)
        r = self.session.get(WEREAD_BOOKMARKLIST_URL, params=params, timeout=10)
        if r.status_code != 200:
            print(f"获取书签列表失败，状态码: {r.status_code}，跳过处理")
            return []
        try:
            result = r.json().get("updated", [])
            return result if isinstance(result, list) else []
        except Exception as e:
            print(f"获取书签列表异常: {str(e)}，跳过处理")
            return []

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_read_info(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId, readingDetail=1, readingBookIndex=1, finishedDate=1)
        r = self.session.get(WEREAD_READ_INFO_URL, params=params, timeout=10)
        if r.status_code != 200:
            print(f"获取阅读信息失败，状态码: {r.status_code}，跳过处理")
            return None
        try:
            return r.json()
        except Exception as e:
            print(f"获取阅读信息异常: {str(e)}，跳过处理")
            return None

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_review_list(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId, listType=11, mine=1, syncKey=0)
        r = self.session.get(WEREAD_REVIEW_LIST_URL, params=params, timeout=10)
        if r.status_code != 200:
            print(f"获取评论列表失败，状态码: {r.status_code}，跳过处理")
            return [], []  # 返回空列表而不是抛出异常
        try:
            reviews = r.json().get("reviews", [])
            reviews = reviews if isinstance(reviews, list) else []
            
            summary = list(filter(lambda x: x.get("review", {}).get("type") == 4, reviews))
            reviews = list(filter(lambda x: x.get("review", {}).get("type") == 1, reviews))
            reviews = list(map(lambda x: x.get("review"), reviews))
            reviews = list(map(lambda x: {**x, "markText": x.pop("content")} if x else x, reviews))
            return summary, reviews
        except Exception as e:
            print(f"获取评论列表异常: {str(e)}，跳过处理")
            return [], []

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_api_data(self):
        self.session.get(WEREAD_URL)
        r = self.session.get(WEREAD_HISTORY_URL, timeout=10)
        if r.status_code != 200:
            print(f"获取历史数据失败，状态码: {r.status_code}，跳过处理")
            return {}
        try:
            return r.json()
        except Exception as e:
            print(f"获取历史数据异常: {str(e)}，跳过处理")
            return {}

    @retry(stop_max_attempt_number=3, wait_fixed=5000, retry_on_exception=refresh_token)
    def get_chapter_info(self, bookId):
        self.session.get(WEREAD_URL)
        body = {"bookIds": [bookId], "synckeys": [0], "teenmode": 0}
        r = self.session.post(WEREAD_CHAPTER_INFO, json=body, timeout=10)
        if r.status_code != 200:
            print(f"获取章节信息失败，状态码: {r.status_code}，跳过处理")
            return {}
        try:
            if (
                r.ok
                and "data" in r.json()
                and len(r.json()["data"]) == 1
                and "updated" in r.json()["data"][0]
            ):
                update = r.json()["data"][0]["updated"]
                update.append(
                    {
                        "chapterUid": 1000000,
                        "chapterIdx": 1000000,
                        "updateTime": int(time.time()),
                        "readAhead": 0,
                        "title": "点评",
                        "level": 1,
                    }
                )
                return {item["chapterUid"]: item for item in update}
            else:
                print(f"获取{bookId}章节信息格式异常，跳过处理")
                return {}
        except Exception as e:
            print(f"获取章节信息异常: {str(e)}，跳过处理")
            return {}

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
