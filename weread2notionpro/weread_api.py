import hashlib
import json
import os
import re
import requests
from requests.utils import cookiejar_from_dict
from urllib.parse import quote
from dotenv import load_dotenv
import functools

load_dotenv()
WEREAD_URL = "https://weread.qq.com/"
WEREAD_NOTEBOOKS_URL = "https://weread.qq.com/api/user/notebook"
WEREAD_BOOKMARKLIST_URL = "https://weread.qq.com/web/book/bookmarklist"
WEREAD_CHAPTER_INFO = "https://weread.qq.com/web/book/chapterInfos"
WEREAD_READ_INFO_URL = "https://weread.qq.com/web/book/readinfo"
WEREAD_REVIEW_LIST_URL = "https://weread.qq.com/web/review/list"
WEREAD_BOOK_INFO = "https://weread.qq.com/web/book/info"
WEREAD_READDATA_DETAIL = "https://weread.qq.com/readdata/detail?synckey=0"
WEREAD_BOOKSHELF_URL = "https://weread.qq.com/web/shelf/sync?synckey=0&teenmode=0&album=1&onlyBookid=0"

def handle_api_response(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            response = func(*args, **kwargs)
            
            print(f"请求 {func.__name__} 状态码: {response.status_code}")
            print(f"请求 {func.__name__} 内容: {response.text[:500]}")
            
            if response.ok:
                return response.json()
            else:
                try:
                    errcode = response.json().get("errcode", 0)
                except requests.exceptions.JSONDecodeError:
                    errcode = 0
                    print(f"警告: 响应不是有效的JSON格式")
                
                self = args[0]
                self.handle_errcode(errcode)
                raise Exception(f"API请求失败，状态码: {response.status_code}")
        except Exception as e:
            print(f"调用 {func.__name__} 时发生异常: {e}")
            raise
    return wrapper

class WeReadApi:
    def __init__(self):
        self.cookie = self.get_cookie()
        self.session = requests.Session()
        self.session.cookies = self.parse_cookie_string()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
            "Referer": "https://weread.qq.com/",
            "Origin": "https://weread.qq.com"
        })

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
            cookies_dict[key] = value.encode('unicode_escape').decode('ascii')
        cookiejar = cookiejar_from_dict(cookies_dict)
        return cookiejar

    @handle_api_response
    def get_bookshelf(self):
        self.session.get(WEREAD_URL)
        return self.session.get(WEREAD_BOOKSHELF_URL)
        
    def handle_errcode(self, errcode):
        if errcode == -2012 or errcode == -2010:
            print(f"::error::微信读书Cookie过期了，请参考文档重新设置。https://mp.weixin.qq.com/s/B_mqLUZv7M1rmXRsMlBf7A")

    # 移除 @handle_api_response 装饰器，自行处理请求和响应
    def get_notebooklist(self):
        """获取笔记本列表（过滤无效数据，确保元素为字典）"""
        self.session.get(WEREAD_URL)
        try:
            response = self.session.get(WEREAD_NOTEBOOKS_URL)
            print(f"请求 get_notebooklist 状态码: {response.status_code}")
            print(f"请求 get_notebooklist 内容: {response.text[:500]}")
            
            if not response.ok:
                try:
                    errcode = response.json().get("errcode", 0)
                    self.handle_errcode(errcode)
                except:
                    pass
                raise Exception(f"获取笔记本列表失败，状态码: {response.status_code}")
            
            data = response.json()
            books = data.get("books", [])
            valid_books = [book for book in books if isinstance(book, dict)]
            valid_books.sort(key=lambda x: x.get("sort", 0))
            return valid_books
        except Exception as e:
            print(f"解析笔记本列表失败: {e}")
            return []

    @handle_api_response
    def get_bookinfo(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId)
        return self.session.get(WEREAD_BOOK_INFO, params=params)

    @handle_api_response
    def get_bookmark_list(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId)
        return self.session.get(WEREAD_BOOKMARKLIST_URL, params=params)

    @handle_api_response
    def get_read_info(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(
            noteCount=1,
            readingDetail=1,
            finishedBookIndex=1,
            readingBookCount=1,
            readingBookIndex=1,
            finishedBookCount=1,
            bookId=bookId,
            finishedDate=1,
        )
        headers = {
            "baseapi":"32",
            "appver":"8.2.5.10163885",
            "basever":"8.2.5.10163885",
            "osver":"12",
            "User-Agent": "WeRead/8.2.5 WRBrand/xiaomi Dalvik/2.1.0 (Linux; U; Android 12; Redmi Note 7 Pro Build/SQ3A.220705.004)",
        }
        return self.session.get(WEREAD_READ_INFO_URL, headers=headers, params=params)

    @handle_api_response
    def get_review_list(self, bookId):
        self.session.get(WEREAD_URL)
        params = dict(bookId=bookId, listType=11, mine=1, syncKey=0)
        return self.session.get(WEREAD_REVIEW_LIST_URL, params=params)

    @handle_api_response
    def get_api_data(self):
        self.session.get(WEREAD_URL)
        return self.session.get(WEREAD_READDATA_DETAIL)

    @handle_api_response
    def get_chapter_info(self, bookId):
        self.session.get(WEREAD_URL)
        body = {"bookIds": [bookId], "synckeys": [0], "teenmode": 0}
        return self.session.post(WEREAD_CHAPTER_INFO, json=body)

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

    def try_get_cloud_cookie(self, url, id, password):
        if url.endswith("/"):
            url = url[:-1]
        req_url = f"{url}/get/{id}"
        data = {"password": password}
        result = None
        try:
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
            print(f"获取云Cookie失败: {e}")
        return result
