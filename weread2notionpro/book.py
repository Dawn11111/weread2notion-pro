import pendulum
from weread2notionpro.notion_helper import NotionHelper
from weread2notionpro.weread_api import WeReadApi
from weread2notionpro import utils
from weread2notionpro.config import book_properties_type_dict, tz
import logging

# 设置日志
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

TAG_ICON_URL = "https://www.notion.so/icons/tag_gray.svg"
USER_ICON_URL = "https://www.notion.so/icons/user-circle-filled_gray.svg"
BOOK_ICON_URL = "https://www.notion.so/icons/book_gray.svg"
rating = {"poor": "⭐️", "fair": "⭐️⭐️⭐️", "good": "⭐️⭐️⭐️⭐️⭐️"}

def refresh_api_session():
    """刷新微信读书API会话"""
    global weread_api
    logger.info("刷新微信读书API会话...")
    weread_api = WeReadApi()  # 重新创建API实例
    return weread_api

def handle_weread_error(e):
    """处理微信读书API错误"""
    logger.error(f"微信读书API错误: {e}")
    if "cookie" in str(e).lower() or "expired" in str(e).lower():
        logger.error("微信读书Cookie可能已过期，请检查并更新")
        return refresh_api_session()
    return None

def insert_book_to_notion(books, index, bookId):
    """插入Book到Notion"""
    try:
        book = {}
        if bookId in archive_dict:
            book["书架分类"] = archive_dict.get(bookId)
        if bookId in notion_books:
            book.update(notion_books.get(bookId))
        
        # 获取书籍信息（带错误处理）
        bookInfo = weread_api.get_bookinfo(bookId)
        if bookInfo is None:
            logger.warning(f"获取书籍信息失败: {bookId}")
            return
            
        book.update(bookInfo)
        
        # 获取阅读信息（带错误处理）
        readInfo = weread_api.get_read_info(bookId)
        if readInfo is None:
            logger.warning(f"获取阅读信息失败: {bookId}")
            readInfo = {}
        else:
            readInfo.update(readInfo.get("readDetail", {}))
            readInfo.update(readInfo.get("bookInfo", {}))
            book.update(readInfo)
        
        # 处理阅读状态
        markedStatus = book.get("markedStatus", 0)
        book["阅读进度"] = (100 if markedStatus == 4 else book.get("readingProgress", 0)) / 100
        
        status = "想读"
        if markedStatus == 4:
            status = "已读"
        elif book.get("readingTime", 0) >= 60:
            status = "在读"
        book["阅读状态"] = status
        
        # 设置书籍属性
        book["阅读时长"] = book.get("readingTime")
        book["阅读天数"] = book.get("totalReadDay")
        book["评分"] = book.get("newRating")
        
        if book.get("newRatingDetail") and book.get("newRatingDetail").get("myRating"):
            book["我的评分"] = rating.get(book.get("newRatingDetail").get("myRating"))
        elif status == "已读":
            book["我的评分"] = "未评分"
        
        book["时间"] = (
            book.get("finishedDate")
            or book.get("lastReadingDate")
            or book.get("readingBookDate")
        )
        book["开始阅读时间"] = book.get("beginReadingDate")
        book["最后阅读时间"] = book.get("lastReadingDate")
        
        # 处理封面图片
        cover = book.get("cover", "")
        if cover and cover.startswith("http"):
            cover = cover.replace("/s_", "/t7_")
        else:
            cover = BOOK_ICON_URL
        
        # 如果是新书，设置额外属性
        if bookId not in notion_books:
            book["书名"] = book.get("title")
            book["BookId"] = book.get("bookId")
            book["ISBN"] = book.get("isbn")
            book["链接"] = weread_api.get_book_url(bookId)
            book["简介"] = book.get("intro", "")
            
            # 处理作者
            author = book.get("author", "")
            if author:
                book["作者"] = [
                    notion_helper.get_relation_id(
                        x, notion_helper.author_database_id, USER_ICON_URL
                    )
                    for x in author.split(" ")
                ]
            
            # 处理分类
            if book.get("categories"):
                book["分类"] = [
                    notion_helper.get_relation_id(
                        x.get("title"), notion_helper.category_database_id, TAG_ICON_URL
                    )
                    for x in book.get("categories")
                ]
        
        # 创建属性
        properties = utils.get_properties(book, book_properties_type_dict)
        
        # 添加日期关系
        if book.get("时间"):
            notion_helper.get_date_relation(
                properties,
                pendulum.from_timestamp(book.get("时间"), tz="Asia/Shanghai"),
            )

        logger.info(
            f"正在插入《{book.get('title')}》, 进度: {index+1}/{len(books)}"
        )
        
        parent = {"database_id": notion_helper.book_database_id, "type": "database_id"}
        
        # 更新或创建页面
        if bookId in notion_books:
            result = notion_helper.update_page(
                page_id=notion_books.get(bookId).get("pageId"),
                properties=properties,
                cover=utils.get_icon(cover),
            )
        else:
            result = notion_helper.create_book_page(
                parent=parent,
                properties=properties,
                icon=utils.get_icon(cover),
            )
        
        # 插入阅读数据
        page_id = result.get("id")
        if book.get("readDetail") and book.get("readDetail").get("data"):
            data = book.get("readDetail").get("data")
            data = {item.get("readDate"): item.get("readTime") for item in data}
            insert_read_data(page_id, data)
    
    except Exception as e:
        logger.error(f"插入书籍到Notion失败: {bookId} - {e}")

def insert_read_data(page_id, readTimes):
    """插入阅读数据"""
    try:
        readTimes = dict(sorted(readTimes.items()))
        filter = {"property": "书架", "relation": {"contains": page_id}}
        results = notion_helper.query_all_by_book(notion_helper.read_database_id, filter)
        
        for result in results:
            properties = result.get("properties", {})
            timestamp = properties.get("时间戳", {}).get("number")
            duration = properties.get("时长", {}).get("number")
            id = result.get("id")
            
            if timestamp in readTimes:
                value = readTimes.pop(timestamp)
                if value != duration:
                    insert_to_notion(
                        page_id=id,
                        timestamp=timestamp,
                        duration=value,
                        book_database_id=page_id,
                    )
        
        for key, value in readTimes.items():
            insert_to_notion(None, int(key), value, page_id)
    
    except Exception as e:
        logger.error(f"插入阅读数据失败: {e}")

def insert_to_notion(page_id, timestamp, duration, book_database_id):
    """插入或更新Notion页面"""
    try:
        parent = {"database_id": notion_helper.read_database_id, "type": "database_id"}
        date_str = pendulum.from_timestamp(timestamp, tz=tz).to_date_string()
        
        properties = {
            "标题": utils.get_title(date_str),
            "日期": utils.get_date(
                start=pendulum.from_timestamp(timestamp, tz=tz).format(
                    "YYYY-MM-DD HH:mm:ss"
                )
            ),
            "时长": utils.get_number(duration),
            "时间戳": utils.get_number(timestamp),
            "书架": utils.get_relation([book_database_id]),
        }
        
        if page_id:
            notion_helper.client.pages.update(page_id=page_id, properties=properties)
        else:
            notion_helper.client.pages.create(
                parent=parent,
                icon=utils.get_icon("https://www.notion.so/icons/target_red.svg"),
                properties=properties,
            )
    
    except Exception as e:
        logger.error(f"插入阅读时间失败: {timestamp} - {e}")

# 全局变量
weread_api = WeReadApi()
notion_helper = NotionHelper()
archive_dict = {}
notion_books = {}

def main():
    global notion_books
    global archive_dict
    global weread_api
    
    try:
        # 获取书架书籍
        bookshelf_books = weread_api.get_bookshelf()
        if not bookshelf_books:
            logger.error("获取书架书籍失败，请检查微信读书Cookie")
            return
        
        # 获取Notion中的书籍
        notion_books = notion_helper.get_all_book()
        
        # 处理书籍进度
        bookProgress = bookshelf_books.get("bookProgress", [])
        bookProgress_dict = {book.get("bookId"): book for book in bookProgress}
        
        # 处理书架分类
        for archive in bookshelf_books.get("archive", []):
            name = archive.get("name", "")
            bookIds = archive.get("bookIds", [])
            archive_dict.update({bookId: name for bookId in bookIds})
        
        # 确定不需要同步的书籍
        not_need_sync = []
        for key, value in notion_books.items():
            book_progress = bookProgress_dict.get(key, {})
            if (
                (
                    key not in bookProgress_dict
                    or value.get("readingTime") == book_progress.get("readingTime")
                )
                and (archive_dict.get(key) == value.get("category"))
                and (value.get("cover") is not None)
                and (
                    value.get("status") != "已读"
                    or (value.get("status") == "已读" and value.get("myRating"))
                )
            ):
                not_need_sync.append(key)
        
        # 获取笔记本和书架书籍
        notebooks = weread_api.get_notebooklist()
        notebooks = [d["bookId"] for d in notebooks if "bookId" in d]
        books = bookshelf_books.get("books", [])
        books = [d["bookId"] for d in books if "bookId" in d]
        
        # 确定需要同步的书籍
        books = list((set(notebooks) | set(books)) - set(not_need_sync))
        
        logger.info(f"需要同步的书籍数量: {len(books)}")
        
        # 同步书籍
        for index, bookId in enumerate(books):
            insert_book_to_notion(books, index, bookId)
        
        logger.info("同步完成")
    
    except Exception as e:
        logger.error(f"主程序执行失败: {e}")
        new_weread_api = handle_weread_error(e)
        if new_weread_api:
            weread_api = new_weread_api
            logger.info("尝试重新运行主程序...")
            main()

if __name__ == "__main__":
    main()
