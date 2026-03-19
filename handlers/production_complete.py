"""알림 2: yt-production 완료 관련 핸들러 등록."""

from telegram.ext import Application, CallbackQueryHandler

from handlers.thumbnail import thumb_change_prod_callback, thumb_full_regen_callback
from handlers.upload import (
    schedule_cancel_callback,
    schedule_confirm_callback,
    upload_now_callback,
    upload_schedule_callback,
)


def register(app: Application):
    """yt-production 완료 알림 관련 콜백 핸들러 등록."""
    app.add_handler(CallbackQueryHandler(upload_now_callback, pattern=r"^upload_now:"))
    app.add_handler(CallbackQueryHandler(upload_schedule_callback, pattern=r"^upload_schedule:"))
    app.add_handler(CallbackQueryHandler(schedule_confirm_callback, pattern=r"^schedule_confirm:"))
    app.add_handler(CallbackQueryHandler(schedule_cancel_callback, pattern=r"^schedule_cancel:"))
    app.add_handler(CallbackQueryHandler(thumb_change_prod_callback, pattern=r"^thumb_change_prod:"))
    app.add_handler(CallbackQueryHandler(thumb_full_regen_callback, pattern=r"^thumb_full_regen:"))
