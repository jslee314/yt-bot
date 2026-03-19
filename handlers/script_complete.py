"""알림 1: yt-script 완료 관련 핸들러 등록."""

from telegram.ext import Application, CallbackQueryHandler

from handlers.hook import hook_change_callback, hook_select_callback
from handlers.thumbnail import thumb_change_callback, thumb_select_callback
from handlers.title import title_change_callback


def register(app: Application):
    """yt-script 완료 알림 관련 콜백 핸들러 등록."""
    app.add_handler(CallbackQueryHandler(hook_change_callback, pattern=r"^hook_change:"))
    app.add_handler(CallbackQueryHandler(hook_select_callback, pattern=r"^hook_select:"))
    app.add_handler(CallbackQueryHandler(thumb_change_callback, pattern=r"^thumb_change:"))
    app.add_handler(CallbackQueryHandler(thumb_select_callback, pattern=r"^thumb_select:"))
    app.add_handler(CallbackQueryHandler(title_change_callback, pattern=r"^title_change:"))
