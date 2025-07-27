import hashlib
import json
import os
import re
from typing import Dict, List, Optional, TypedDict, Union

import requests
from requests.utils import cookiejar_from_dict
from retrying import retry
from dotenv import load_dotenv

load_dotenv()

# 定义类型
class BookProgress(TypedDict):
    appId: str
    bookVersion: int
    reviewId: str
    chapterUid: int
    chapterOffset: int
    chapterIdx: int
    updateTime: int
    synckey: int
    summary: str
    repairOffsetTime: int
    readingTime: int
    progress: int
    isStartReading: int
    ttsTime: int
    startReadingTime: int
    installId: str
    recordReadingTime: int
    finishTime: int

class BookProgressResponse(TypedDict):
    bookId: str
    book: BookProgress
    canFreeRead: int
    timestamp: int

class ChapterInfo(TypedDict):
    chapterUid: int
    chapterIdx: int
    title: str
    level: int
    updateTime: int
    readAhead: int

class Bookmark(TypedDict):
    bookmarkId: str
    createTime: int
    chapterUid: int
    range: str
    markText: str
    style: int

class Review(TypedDict):
    reviewId: str
    abstract: str
    content: str
    type: int
    createTime: int
    chapterUid: int

class BookInfo(TypedDict):
    bookId: str
    title: str
    author: str
    cover: Union[str, Dict]  # 封面可能是字符串或字典
    intro: str
    categories: List[str]
    totalWords: int
    isbn: str

class ReadInfo(TypedDict):
    readingTime: int
    totalReadDay: Optional[int]
    continueReadDays: Optional[int]
    readingBookCount: Optional[int]
    readingBookDate: int
    finishedBookCount: Optional[int]
    finishedBookIndex: Optional[int]
    finishedDate: int
    readingProgress: float

# API端点
WEREAD_URL = "https://weread.qq.com/"
WEREAD_NOTEBOOKS_URL = "https://weread.qq.com/api/user/notebook"
WEREAD_BOOKMARKLIST_URL = "https://weread.qq.com/web/book/bookmarklist"
WEREAD_CHAPTER_INFO = "https://weread.qq.com/web/book/chapterInfos"
WEREAD_READ_INFO_URL = "https://weread.qq.com/web/book/readinfo"
WEREAD_PROGRESS_URL = "https://weread.qq.com/web/book/getProgress"
WEREAD_REVIEW_LIST_URL = "https://weread.qq.com/web/review/list"
WEREAD_BOOK_INFO = "https://i.weread.qq.com/book/info"  # 使用原始API端点
WEREAD_HISTORY_URL = "https://i.weread.qq.com/readdata/summary?synckey=0"


class WeReadApi:
    def __init__(self):
        self.cookie = self.get_cookie()
        self.session = requests.Session()
        self.session.cookies = self.parse_cookie_string()
        # 设置统一的请求头
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://weread.qq.com/'
        })

    def try_get_cloud_cookie(self, url: str, id: str, password: str) -> Optional[str]:
        """尝试从CookieCloud获取cookie"""
        if url.endswith("/"):
            url = url[:-1]
        req_url = f"{url}/get/{id}"
        data = {"password": password}
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
                    return cookie_str
        except Exception as e:
            print(f"从CookieCloud获取cookie失败: {e}")
        return None

    def get_cookie(self) -> str:
        """获取cookie"""
        url = os.getenv("CC_URL", "https://cookiecloud.malinkang.com/")
        id = os.getenv("CC_ID")
        password = os.getenv("CC_PASSWORD")
        cookie = os.getenv("WEREAD_COOKIE")
        
        # 优先使用CookieCloud
        if url and id and password:
            cloud_cookie = self.try_get_cloud_cookie(url, id, password)
            if cloud_cookie:
                return cloud_cookie
        
        # 其次使用环境变量中的cookie
        if cookie and cookie.strip():
            return cookie
        
        raise Exception("没有找到有效的cookie，请按照文档填写cookie")

    def parse_cookie_string(self) -> requests.cookies.RequestsCookieJar:
        """解析cookie字符串为CookieJar"""
        cookies_dict = {}
        pattern = re.compile(r'([^=]+)=([^;]+);?\s*')
        matches = pattern.findall(self.cookie)
        
        for key, value in matches:
            cookies_dict[key] = value
        return cookiejar_from_dict(cookies_dict)

    def refresh_cookie(self):
        """刷新cookie"""
        try:
            self.session.get(WEREAD_URL)
        except Exception as e:
            print(f"刷新cookie失败: {e}")

    def get_bookshelf(self) -> dict:
        """获取书架数据"""
        self.refresh_cookie()
        r = self.session.get(
            "https://i.weread.qq.com/shelf/sync?synckey=0&teenmode=0&album=1&onlyBookid=0"
        )
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"获取书架数据失败: {r.text}")
        
    def handle_errcode(self, errcode: int):
        """处理错误码"""
        if errcode in [-2012, -2010]:
            print("::error::微信读书Cookie过期了，请参考文档重新设置。https://mp.weixin.qq.com/s/B_mqLUZv7M1rmXRsMlBf7A")
        else:
            print(f"::warning::微信读书API返回错误码: {errcode}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_notebooklist(self) -> List[dict]:
        """获取笔记本列表"""
        self.refresh_cookie()
        r = self.session.get(WEREAD_NOTEBOOKS_URL)
        if r.ok:
            data = r.json()
            books = data.get("books", [])
            books.sort(key=lambda x: x.get("sort", 0))
            return books
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"获取笔记本列表失败: {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_bookinfo(self, bookId: str) -> Optional[BookInfo]:
        """获取书籍详情信息"""
        self.refresh_cookie()
        params = {"bookId": bookId}
        r = self.session.get(WEREAD_BOOK_INFO, params=params)
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            print(f"获取书籍信息失败: {r.text}")
            return None

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_bookmark_list(self, bookId: str) -> List[Bookmark]:
        """获取书签列表"""
        self.refresh_cookie()
        params = {"bookId": bookId}
        r = self.session.get(WEREAD_BOOKMARKLIST_URL, params=params)
        if r.ok:
            return r.json().get("updated", [])
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"获取书签列表失败: {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_progress(self, bookId: str) -> Optional[BookProgressResponse]:
        """获取阅读进度信息"""
        self.refresh_cookie()
        params = {"bookId": bookId}
        r = self.session.get(WEREAD_PROGRESS_URL, params=params)
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            print(f"获取阅读进度失败: {r.text}")
            return None

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_read_info(self, bookId: str) -> Optional[ReadInfo]:
        """获取阅读信息"""
        self.refresh_cookie()
        params = {
            "bookId": bookId,
            "readingDetail": 1,
            "readingBookIndex": 1,
            "finishedDate": 1
        }
        headers = {
            "baseapi": "32",
            "appver": "8.2.5.10163885",
            "basever": "8.2.5.10163885",
            "osver": "12",
            "User-Agent": "WeRead/8.2.5 WRBrand/xiaomi Dalvik/2.1.0 (Linux; U; Android 12; Redmi Note 7 Pro Build/SQ3A.220705.004)",
        }
        r = self.session.get(WEREAD_READ_INFO_URL, headers=headers, params=params)
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            print(f"获取阅读信息失败: {r.text}")
            return None

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_review_list(self, bookId: str) -> List[Review]:
        """获取书评列表"""
        self.refresh_cookie()
        params = {"bookId": bookId, "listType": 11, "mine": 1, "synckey": 0}
        r = self.session.get(WEREAD_REVIEW_LIST_URL, params=params)
        if r.ok:
            reviews = r.json().get("reviews", [])
            processed_reviews = []
            for review in reviews:
                rev = review.get("review", {})
                if rev.get("type") == 4:  # 点评类型
                    rev["chapterUid"] = 1000000
                processed_reviews.append(rev)
            return processed_reviews
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"获取书评列表失败: {r.text}")

    def get_api_data(self) -> dict:
        """获取历史阅读数据"""
        self.refresh_cookie()
        r = self.session.get(WEREAD_HISTORY_URL)
        if r.ok:
            return r.json()
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"获取历史阅读数据失败: {r.text}")

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def get_chapter_info(self, bookId: str) -> Dict[int, ChapterInfo]:
        """获取章节信息"""
        self.refresh_cookie()
        body = {"bookIds": [bookId]}
        r = self.session.post(WEREAD_CHAPTER_INFO, json=body)
        if r.ok:
            data = r.json()
            if "data" in data and len(data["data"]) > 0:
                chapters = data["data"][0].get("updated", [])
                
                # 添加点评章节
                chapters.append({
                    "chapterUid": 1000000,
                    "chapterIdx": 1000000,
                    "title": "点评",
                    "level": 1,
                    "updateTime": int(time.time()),
                    "readAhead": 0
                })
                
                # 转换为字典格式 {chapterUid: chapterInfo}
                return {item["chapterUid"]: item for item in chapters}
            else:
                raise Exception(f"章节信息数据格式错误: {data}")
        else:
            errcode = r.json().get("errcode", 0)
            self.handle_errcode(errcode)
            raise Exception(f"获取章节信息失败: {r.text}")

    def transform_id(self, book_id: str):
        """转换书籍ID为特定格式"""
        id_length = len(book_id)
        if re.match(r"^\d+$", book_id):
            ary = []
            for i in range(0, id_length, 9):
                ary.append(format(int(book_id[i:min(i + 9, id_length)]), "x"))
            return "3", ary

        result = ""
        for char in book_id:
            result += format(ord(char), "x")
        return "4", [result]

    def calculate_book_str_id(self, book_id: str) -> str:
        """计算书籍的字符串ID"""
        md5 = hashlib.md5()
        md5.update(book_id.encode("utf-8"))
        digest = md5.hexdigest()
        result = digest[0:3]
        code, transformed_ids = self.transform_id(book_id)
        result += code + "2" + digest[-2:]

        for i, tid in enumerate(transformed_ids):
            hex_length = format(len(tid), "x")
            if len(hex_length) == 1:
                hex_length = "0" + hex_length
            result += hex_length + tid
            if i < len(transformed_ids) - 1:
                result += "g"

        if len(result) < 20:
            result += digest[:20 - len(result)]

        md5 = hashlib.md5()
        md5.update(result.encode("utf-8"))
        result += md5.hexdigest()[:3]
        return result

    def get_book_url(self, book_id: str) -> str:
        """获取书籍的URL"""
        return f"https://weread.qq.com/web/reader/{self.calculate_book_str_id(book_id)}"
