"""Offline UI translations. English fallback for specialist messages/admin workflows.

Languages are selected by the user (never guessed from their Telegram profile).
"""

LANGUAGES = {"vi": "Tiếng Việt", "en": "English"}

EN = {
    "wallet": "Wallet", "report": "Send Report", "tools": "Tool Access",
    "support": "Support", "referral": "Referral", "faq": "FAQ",
    "changes": "Changelogs", "orders": "My Orders", "back": "← Main Menu",
    "back_platforms": "← Back to Platforms", "language": "Language",
    "back_tools": "← Tool Access", "tool_menu": "<b>Tool Access</b>\n\nChoose an option:",
    "tool_buy": "Buy Tool Access", "tool_sub": "My Subscription",
    "tool_sub_title": "<b>My Subscription</b>",
    "tool_sub_none": "You have no Tool Access subscription yet.",
    "tool_sub_note": "Tool Access is activated only after Admin review and confirmation.",
    "tool_back_main": "← Back to Main Menu",
    "engagement": "Engagement Services",
    "engagement_menu": "<b>Engagement Services</b>\n\nChoose a service:",
    "member_telegram": "Member Telegram",
    "member_telegram_title": "<b>Member Telegram</b>\n\nChoose a package and contact Admin to order.",
    "member_price": "Price",
    "member_unit": "VND/member",
    "member_min": "Min",
    "member_max": "Max",
    "member_speed": "Speed",
    "member_warranty": "Warranty",
    "member_per_1000": "1,000 members",
    "member_contact": "Contact Admin to order",
    "member_note": "Prices are per member and may change. Send your channel/group link and quantity to Admin.",
    "back_engagement": "← Engagement Services",
    # Telegram Members ordering flow
    "tg_member_select": "Select a Telegram Group Members package:",
    "tg_member_enter_link": "Enter the public Telegram Group link (e.g., https://t.me/groupname or @groupname):",
    "tg_member_enter_qty": "Enter quantity of members to add (min {min_qty}, max {max_qty}):",
    "tg_member_invalid_link": "Invalid Telegram group link. Use https://t.me/... or @username format.",
    "tg_member_invalid_qty": "Invalid quantity. Must be a number between {min_qty} and {max_qty}.",
    "tg_member_confirm": "<b>Confirm Order</b>\n\n"
                          "Service: <b>{service_name}</b> (ID: <code>{service_id}</code>)\n"
                          "Group: <b>{link}</b>\n"
                          "Quantity: <b>{quantity:,}</b> members\n"
                          "Unit price: <b>{unit_price} VND</b> per 1,000 members\n"
                          "Total: <b>{total:,} VND</b>\n"
                          "Your balance: <b>{balance:,} VND</b>\n\n"
                          "Press <b>Confirm</b> to pay from wallet and place order via provider.",
    "tg_member_insufficient_balance": "Insufficient balance. Need <b>{need:,} VND</b>, you have <b>{have:,} VND</b>. Please deposit first.",
    "tg_member_placing": "Placing order via provider...",
    "tg_member_success": "Order placed successfully!\n\n"
                          "Provider Order ID: <code>{provider_order_id}</code>\n"
                          "Service: <b>{service_name}</b>\n"
                          "Quantity: <b>{quantity:,}</b> members\n"
                          "Total charged: <b>{total:,} VND</b>\n\n"
                          "Track status in <b>My Orders</b>.",
    "tg_member_failed": "Failed to place order: {error}\n\n"
                         "If money was deducted, it will be refunded automatically.",
    "tg_member_api_error": "Provider API error: {error}",
    "tg_member_timeout": "Provider request timed out. Order status unknown. Please check My Orders or contact support.",
    "tg_member_duplicate": "Duplicate order detected. Please check My Orders.",
    "tg_member_link_group_only": "This service supports Telegram Groups only. Please provide a group link.",
    "tg_member_pending_reconcile": "The provider result could not be confirmed yet. Your order <b>#{order_id}</b> is kept for reconciliation and the charge is on hold. Support will verify it shortly.",
    "tg_member_db_busy": "The system is temporarily busy. Please try again in a few seconds.",
    "tg_member_unavailable": "This service is temporarily unavailable. You have not been charged. Please try again later.",
    "confirm_pay": "Confirm & Pay",
    "cancel": "Cancel",
    "choose_language": "Verified!\n\nWelcome to our community!\nChoose your language below to get started.",
    "choose_platform": "Select the platform for your policy-compliance request.",
    "choose_service": "Select a service to open a case.",
    "choose_target": "Choose the target type:",
    "profile": "Profile", "channel": "Channel", "group": "Group",
    "post": "Post / Video", "send_target": "Send the profile/channel/post URL, @username or public ID in your next message.\n/cancel to exit.",
    "describe": "Explain the specific policy violation and why it should be reviewed (10–1,200 characters).\n/cancel to exit.",
    "evidence": "Send supporting evidence as text, a screenshot, a file or a video.\n/cancel to exit.",
    "captcha": "🔐 Verification Required\n\nSolve this math problem to continue:\n\n{a} + {b} = ?\n\nType your answer below.",
    "captcha_bad": "Incorrect answer. Attempts remaining: {remaining}.",
    "captcha_expired": "Verification expired. Here is a new question.",
    "verified": "Verified!",
    "home": "Welcome back, <b>{name}</b>!\n\nChoose a service, manage your wallet or contact support.\n\nOnly genuine policy violations with evidence can be submitted. Platform decisions are not guaranteed.",
    "invalid_target": "Enter a valid public profile URL, @username or ID (up to 500 characters).",
    "invalid_reason": "Provide a clear explanation (10–1,200 characters).",
    "invalid_evidence": "Supporting evidence is required as text, photo, file or video.",
    "submitted": "Your case <b>#{order_id}</b> has been received for manual review.",
    "no_services": "No services are available for this platform.",
    "price_quote": "Price available after review",
    "create": "Create case", "description": "Service Details", "cost": "Price",
}

VI = {
    "wallet": "Ví tiền", "report": "Gửi báo cáo", "tools": "Tool Access",
    "support": "Hỗ trợ", "referral": "Giới thiệu", "faq": "FAQ",
    "changes": "Cập nhật", "orders": "Đơn của tôi", "back": "← Menu chính",
    "back_platforms": "← Nền tảng", "language": "Ngôn ngữ",
    "back_tools": "← Tool Access", "tool_menu": "<b>Tool Access</b>\n\nChọn một mục:",
    "tool_buy": "Mua Tool Access", "tool_sub": "Gói của tôi",
    "tool_sub_title": "<b>Gói của tôi</b>",
    "tool_sub_none": "Bạn chưa có gói Tool Access nào.",
    "tool_sub_note": "Tool Access chỉ được kích hoạt sau khi Admin xét duyệt và xác nhận.",
    "tool_back_main": "← Menu chính",
    "engagement": "Engagement Services",
    "engagement_menu": "<b>Engagement Services</b>\n\nChọn dịch vụ:",
    "member_telegram": "Member Telegram",
    "member_telegram_title": "<b>Member Telegram</b>\n\nChọn gói và liên hệ Admin để đặt.",
    "member_price": "Giá",
    "member_unit": "đ/member",
    "member_min": "Tối thiểu",
    "member_max": "Tối đa",
    "member_speed": "Tốc độ",
    "member_warranty": "Bảo hành",
    "member_per_1000": "1.000 member",
    "member_contact": "Liên hệ Admin để đặt",
    "member_note": "Giá tính theo member và có thể thay đổi. Gửi link kênh/nhóm và số lượng cho Admin.",
    "back_engagement": "← Engagement Services",
    # Telegram Members ordering flow
    "tg_member_select": "Chọn gói thành viên Telegram Group:",
    "tg_member_enter_link": "Nhập link Telegram Group công khai (vd: https://t.me/tennhom hoặc @tennhom):",
    "tg_member_enter_qty": "Nhập số lượng member cần thêm (tối thiểu {min_qty}, tối đa {max_qty}):",
    "tg_member_invalid_link": "Link nhóm Telegram không hợp lệ. Dùng dạng https://t.me/... hoặc @username.",
    "tg_member_invalid_qty": "Số lượng không hợp lệ. Phải là số từ {min_qty} đến {max_qty}.",
    "tg_member_confirm": "<b>Xác nhận đặt hàng</b>\n\n"
                          "Dịch vụ: <b>{service_name}</b> (ID: <code>{service_id}</code>)\n"
                          "Nhóm: <b>{link}</b>\n"
                          "Số lượng: <b>{quantity:,}</b> member\n"
                          "Đơn giá: <b>{unit_price} VND</b> / 1.000 member\n"
                          "Tổng cộng: <b>{total:,} VND</b>\n"
                          "Số dư hiện tại: <b>{balance:,} VND</b>\n\n"
                          "Nhấn <b>Xác nhận</b> để thanh toán từ ví và đặt hàng qua nhà cung cấp.",
    "tg_member_insufficient_balance": "Số dư không đủ. Cần <b>{need:,} VND</b>, bạn có <b>{have:,} VND</b>. Hãy nạp tiền trước.",
    "tg_member_placing": "Đang đặt hàng qua nhà cung cấp...",
    "tg_member_success": "Đặt hàng thành công!\n\n"
                          "Provider Order ID: <code>{provider_order_id}</code>\n"
                          "Dịch vụ: <b>{service_name}</b>\n"
                          "Số lượng: <b>{quantity:,}</b> member\n"
                          "Đã trừ: <b>{total:,} VND</b>\n\n"
                          "Theo dõi trạng thái ở <b>Đơn của tôi</b>.",
    "tg_member_failed": "Đặt hàng thất bại: {error}\n\n"
                         "Nếu đã trừ tiền, hệ thống sẽ hoàn trả tự động.",
    "tg_member_api_error": "Lỗi API nhà cung cấp: {error}",
    "tg_member_timeout": "Yêu cầu tới nhà cung cấp hết thời gian. Trạng thái đơn chưa rõ. Kiểm tra <b>Đơn của tôi</b> hoặc liên hệ hỗ trợ.",
    "tg_member_duplicate": "Phát hiện đơn trùng lặp. Vui lòng kiểm tra <b>Đơn của tôi</b>.",
    "tg_member_link_group_only": "Dịch vụ này chỉ hỗ trợ Telegram Group. Vui lòng cung cấp link nhóm.",
    "tg_member_pending_reconcile": "Chưa xác nhận được kết quả từ nhà cung cấp. Đơn <b>#{order_id}</b> đã được giữ để đối soát và khoản trừ đang tạm giữ. Bộ phận hỗ trợ sẽ kiểm tra ngay.",
    "tg_member_db_busy": "Hệ thống đang bận tạm thời. Vui lòng thử lại sau vài giây.",
    "tg_member_unavailable": "Dịch vụ tạm thời không khả dụng. Bạn chưa bị trừ tiền. Vui lòng thử lại sau.",
    "confirm_pay": "Xác nhận & Thanh toán",
    "cancel": "Hủy",
    "choose_language": "Đã xác minh!\n\nChào mừng đến cộng đồng.\nChọn ngôn ngữ để bắt đầu.",
    "choose_platform": "Chọn nền tảng có nội dung cần rà soát vi phạm.",
    "choose_service": "Chọn dịch vụ để tạo hồ sơ.",
    "choose_target": "Chọn loại đối tượng:",
    "profile": "Trang cá nhân", "channel": "Kênh", "group": "Nhóm",
    "post": "Bài đăng / Video", "send_target": "Gửi URL công khai, @username hoặc ID cần rà soát ở tin nhắn tiếp theo.\n/cancel để hủy.",
    "describe": "Mô tả vi phạm cụ thể và căn cứ chính sách (10–1.200 ký tự).\n/cancel để hủy.",
    "evidence": "Gửi bằng chứng dạng văn bản, ảnh chụp, tệp hoặc video.\n/cancel để hủy.",
    "captcha": "🔐 Yêu cầu xác minh\n\nGiải phép tính để tiếp tục:\n\n{a} + {b} = ?\n\nNhập câu trả lời bên dưới.",
    "captcha_bad": "Chưa đúng. Còn {remaining} lần thử.",
    "captcha_expired": "Mã xác minh hết hạn. Đây là câu hỏi mới.",
    "verified": "Xác minh thành công!",
    "home": "Chào mừng trở lại, <b>{name}</b>!\n\nChọn dịch vụ, quản lý ví tiền hoặc liên hệ hỗ trợ.\n\nChỉ tiếp nhận báo cáo vi phạm có thật và có bằng chứng. Không cam kết quyết định của nền tảng.",
    "invalid_target": "Nhập URL công khai, @username hoặc ID hợp lệ (tối đa 500 ký tự).",
    "invalid_reason": "Hãy mô tả rõ vi phạm (10–1.200 ký tự).",
    "invalid_evidence": "Cần gửi bằng chứng dưới dạng chữ, ảnh, tệp hoặc video.",
    "submitted": "Đã nhận hồ sơ <b>#{order_id}</b> để quản trị viên xét duyệt.",
    "no_services": "Nền tảng này chưa có dịch vụ.",
    "price_quote": "Báo giá sau khi thẩm định",
    "create": "Tạo hồ sơ", "description": "Chi tiết dịch vụ", "cost": "Chi phí",
}



def translate(language: str, key: str, **params) -> str:
    template = VI.get(key, EN.get(key, key)) if language == "vi" else EN.get(key, key)
    return template.format(**params)
