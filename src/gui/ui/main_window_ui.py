"""Main-window UI construction.

Extracted verbatim from ``MainWindow.__init__``'s ~485-line inline widget
tree (the block between "主界面布局" and the floating-panel positioning).

The builder follows the same back-reference convention as the other GUI
helpers (``ThemeManager``, ``MarketOperations`` …): it receives the
``MainWindow`` instance and assigns every widget back onto it under the
*exact same attribute name* the rest of ``MainWindow`` already expects, and
connects signals to the window's own slots. This keeps all existing call
sites and ``self.<widget>`` references working unchanged — it is a pure
move, not a behavioural change.

Widgets are parented to ``MainWindow`` / ``central_widget`` exactly as
before; this object is a plain builder, not a Qt parent.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.gui.common import DEFAULT_REMOTE_MODELS
from src.gui.knowledge_dialog import KnowledgeDialog
from src.gui.market_dialog import MarketDialog
from src.gui.scheduler_dialog import SchedulerDialog
from src.gui.settings_dialog import SettingsDialog
from src.gui.widgets import ImageInputTextEdit, StackedPageAnimator


class MainWindowUi:
    """Builds and wires the static widget tree for ``MainWindow``."""

    def __init__(self, window):
        self.window = window

    def build(self):
        w = self.window

        # 主界面布局
        central_widget = QWidget()
        w.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 侧边栏 (Sidebar)
        w.sidebar = QWidget()
        w.sidebar.setMinimumWidth(0)
        w.sidebar.setMaximumWidth(w.sidebar_expanded_width)
        w.sidebar.setFixedWidth(w.sidebar_expanded_width)
        w.sidebar.setStyleSheet("background-color: #F8F9FA; border-right: 1px solid #E0E0E0;")
        w.sidebar_opacity = QGraphicsOpacityEffect(w.sidebar)
        w.sidebar_opacity.setOpacity(1.0)
        w.sidebar.setGraphicsEffect(w.sidebar_opacity)
        sidebar_layout = QVBoxLayout(w.sidebar)
        sidebar_layout.setContentsMargins(14, 14, 14, 20)
        sidebar_layout.setSpacing(10)

        sidebar_header = QHBoxLayout()
        sidebar_header.setContentsMargins(0, 0, 0, 2)
        w.sidebar_collapse_btn = QPushButton("☰")
        w.sidebar_collapse_btn.setFixedSize(34, 34)
        w.sidebar_collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        w.sidebar_collapse_btn.clicked.connect(w.toggle_sidebar)
        w.sidebar_title = QLabel("Workspace")
        w.sidebar_title.setObjectName("sidebarTitle")
        w.sidebar_title.setFrameShape(QFrame.Shape.NoFrame)
        w.sidebar_title.setContentsMargins(0, 0, 0, 0)
        sidebar_header.addWidget(w.sidebar_collapse_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        sidebar_header.addWidget(w.sidebar_title, alignment=Qt.AlignmentFlag.AlignVCenter)
        sidebar_header.addStretch()
        sidebar_layout.addLayout(sidebar_header)

        w.new_chat_btn = QPushButton("＋ New Chat")
        w.new_chat_btn.setStyleSheet("""
            QPushButton {
                background-color: #E8F0FE; color: #1967D2;
                border: none; border-radius: 24px;
                padding: 14px; font-weight: bold; font-size: 14px;
            }
            QPushButton:hover { background-color: #D2E3FC; }
        """)
        w.new_chat_btn.clicked.connect(w.start_new_chat)
        sidebar_layout.addWidget(w.new_chat_btn)

        w.schedule_btn = QPushButton("⏰ 定时任务")
        w.schedule_btn.setStyleSheet("text-align: center; padding: 12px; color: #444746; background: transparent; border-radius: 12px;")
        w.schedule_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        w.schedule_btn.clicked.connect(w.open_schedule)
        sidebar_layout.addWidget(w.schedule_btn)

        w.history_list = QListWidget()
        w.history_list.setSpacing(0)
        w.history_list.itemClicked.connect(w.load_selected_chat)
        sidebar_layout.addWidget(w.history_list)

        w.knowledge_btn = QPushButton("📚 Knowledge")
        w.knowledge_btn.setStyleSheet("text-align: left; padding: 12px; color: #444746; background: transparent; border-radius: 12px;")
        w.knowledge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        w.knowledge_btn.clicked.connect(w.open_knowledge)
        sidebar_layout.addWidget(w.knowledge_btn)

        w.settings_btn = QPushButton("⚙ Settings")
        w.settings_btn.setStyleSheet("text-align: left; padding: 12px; color: #444746; background: transparent; border-radius: 12px;")
        w.settings_btn.clicked.connect(w.open_settings)
        sidebar_layout.addWidget(w.settings_btn)

        main_layout.addWidget(w.sidebar)

        # 右侧内容区（页面栈）
        w.page_stack = QStackedWidget()

        w.chat_page = QWidget()
        chat_layout = QVBoxLayout(w.chat_page)
        chat_layout.setContentsMargins(18, 16, 18, 18)
        chat_layout.setSpacing(14)

        # 顶部状态栏
        w.top_bar_card = QFrame()
        w.top_bar_card.setObjectName("topBarCard")
        top_bar = QHBoxLayout(w.top_bar_card)
        top_bar.setContentsMargins(18, 14, 18, 14)
        top_bar.setSpacing(10)
        w.top_bar = top_bar
        w.status_label = QLabel("Wwise: Disconnected")
        w.status_label.setStyleSheet("color: #747775; font-size: 13px;")
        w.connect_btn = QPushButton("Connect")
        w.connect_btn.setFixedWidth(90)
        w.connect_btn.setStyleSheet("background: #F0F4F9; border-radius: 12px; font-size: 12px; padding: 5px;")
        w.connect_btn.clicked.connect(w.toggle_wwise_connection)

        # 模式选择器
        w.mode_selector = QComboBox()
        w.mode_selector.addItems(["Ask Mode", "Agent Mode"])
        w.mode_selector.setFixedWidth(120)
        w.mode_selector.setStyleSheet("""
            QComboBox {
                background: #F0F4F9; border-radius: 12px; padding: 5px 10px; font-size: 13px; border: none;
            }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { image: none; border: none; }
        """)
        w.mode_selector.setToolTip("Ask Mode: Q&A (Auto-execute read-only)\nAgent Mode: Full Control (Auto-execute with confirmation)")
        w.mode_selector.currentTextChanged.connect(w._on_mode_changed)

        w.feedback_btn = QPushButton()
        w.feedback_btn.setObjectName("feedbackButton")
        w.feedback_btn.setFixedSize(34, 28)
        w.feedback_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        w.feedback_btn.setToolTip("反馈")
        w.feedback_btn.clicked.connect(w.open_feedback)

        # w.donate_btn = QPushButton()
        # w.donate_btn.setObjectName("donateButton")
        # w.donate_btn.setFixedSize(34, 28)
        # w.donate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # w.donate_btn.setToolTip("赞赏支持")
        # w.donate_btn.clicked.connect(w.open_donate)

        w.theme_label = QLabel("Theme:")
        w.theme_selector = QComboBox()
        w.theme_selector.addItems(["Light", "Dark"])
        w.theme_selector.setFixedWidth(96)
        w.theme_selector.currentTextChanged.connect(w.on_theme_selector_changed)

        w.mode_label = QLabel("Mode:")

        top_bar.addWidget(w.status_label)
        top_bar.addWidget(w.connect_btn)
        top_bar.addStretch()
        top_bar.addWidget(w.feedback_btn)
        # top_bar.addWidget(w.donate_btn)
        top_bar.addWidget(w.mode_label)
        top_bar.addWidget(w.mode_selector)
        top_bar.addWidget(w.theme_label)
        top_bar.addWidget(w.theme_selector)
        chat_layout.addWidget(w.top_bar_card)

        # 聊天滚动区
        w.scroll_area = QScrollArea()
        w.scroll_area.setWidgetResizable(True)
        w.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        w.chat_container = QWidget()
        w.chat_container.setStyleSheet("background-color: #FFFFFF;")
        w.chat_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        w.chat_layout = QVBoxLayout(w.chat_container)
        w.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        w.chat_layout.setContentsMargins(10, 22, 10, 22)
        w.chat_layout.setSpacing(18)

        w.scroll_area.setWidget(w.chat_container)
        chat_layout.addWidget(w.scroll_area)

        # 视口外消息隐藏优化
        w._visibility_timer = QTimer(w)
        w._visibility_timer.setSingleShot(True)
        w._visibility_timer.setInterval(150)
        w._visibility_timer.timeout.connect(w._update_visible_bubbles)
        w.scroll_area.verticalScrollBar().valueChanged.connect(
            lambda: w._visibility_timer.start() if w.chat_layout.count() > 30 else None
        )

        # 底部输入框 (药丸形状)
        input_wrapper = QWidget()
        input_wrapper.setObjectName("chatInputWrapper")
        input_wrapper.setContentsMargins(36, 14, 36, 18)
        input_wrapper.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        input_wrapper_layout = QVBoxLayout(input_wrapper)
        input_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        input_wrapper_layout.setSpacing(14)
        w.input_wrapper = input_wrapper

        w.input_pill = QFrame()
        w.input_pill.setObjectName("chatInputPill")
        w.input_pill.setMaximumWidth(1500)
        w.input_pill.setMinimumHeight(128)
        w.input_pill.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        w.input_pill.setStyleSheet("""
            QFrame#chatInputPill { background-color: #FFFFFF; border: none; border-radius: 34px; }
            QFrame#chatInputPill:focus-within { background-color: #FFFFFF; border: 1px solid #A49BFF; }
        """)
        w.input_pill_shadow = QGraphicsDropShadowEffect(w.input_pill)
        w.input_pill_shadow.setBlurRadius(34)
        w.input_pill_shadow.setOffset(0, 10)
        w.input_pill.setGraphicsEffect(w.input_pill_shadow)
        pill_outer = QVBoxLayout(w.input_pill)
        pill_outer.setContentsMargins(24, 14, 20, 14)
        pill_outer.setSpacing(8)

        # 上部：输入框
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(0)

        # 输入区域容器 (包含图片预览和文本输入)
        input_area = QWidget()
        input_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        input_area_layout = QVBoxLayout(input_area)
        input_area_layout.setContentsMargins(0, 0, 0, 0)
        input_area_layout.setSpacing(8)

        # 图片预览区域
        w.image_preview_container = QScrollArea()
        w.image_preview_container.setWidgetResizable(True)
        w.image_preview_container.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        w.image_preview_container.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w.image_preview_container.setFrameShape(QFrame.Shape.NoFrame)
        w.image_preview_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        w.image_preview_container.setObjectName("attachmentPreviewScroll")
        w.image_preview_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        w.image_preview_container.viewport().setAutoFillBackground(False)
        w.image_preview_container.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        w.image_preview_container.setStyleSheet(
            "QScrollArea#attachmentPreviewScroll { background: transparent; border: none; }"
            "QScrollArea#attachmentPreviewScroll > QWidget > QWidget { background: transparent; }"
        )
        w.image_preview_content = QWidget()
        w.image_preview_content.setObjectName("attachmentPreviewContent")
        w.image_preview_content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        w.image_preview_content.setStyleSheet("QWidget#attachmentPreviewContent { background: transparent; }")
        w.image_preview_content.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        w.image_preview_layout = QHBoxLayout(w.image_preview_content)
        w.image_preview_layout.setContentsMargins(0, 4, 0, 0)
        w.image_preview_layout.setSpacing(8)
        w.image_preview_layout.addStretch()
        w.image_preview_container.setWidget(w.image_preview_content)
        w.image_preview_container.hide()
        input_area_layout.addWidget(w.image_preview_container)

        w.pending_images = w.attachment_manager.pending_images
        w.pending_files = w.attachment_manager.pending_files

        # 使用支持图片的输入框
        w.input_field = ImageInputTextEdit()
        w.input_field.setPlaceholderText("Ask AudioMate...")
        w.input_field.setStyleSheet("background: transparent; border: none; font-size: 18px; padding: 0;")
        w.input_field.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w.input_field.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        w.input_field.setMaximumHeight(78)
        w.input_field.setFixedHeight(42)
        w.input_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        w.input_field.document().contentsChanged.connect(w.adjust_input_height)
        w.input_field.image_added.connect(w.add_pending_image)
        w.input_field.paths_added.connect(w.add_pending_paths)
        w.input_field.returnPressed.connect(w.send_message)
        input_area_layout.addWidget(w.input_field)

        top_row.addWidget(input_area)
        pill_outer.addLayout(top_row)

        # 下部：模型选择器 + 知识库选择器 + 操作按钮
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(14)

        # 模型选择器
        w.model_selector = QComboBox()
        w.model_selector.addItems(DEFAULT_REMOTE_MODELS)
        if hasattr(w.llm_service, 'model') and w.llm_service.model:
             curr = w.llm_service.model
             if w.model_selector.findText(curr) == -1:
                 w.model_selector.addItem(curr)
             w.model_selector.setCurrentText(curr)
        w.model_selector.setFixedWidth(170)
        w.model_selector.setStyleSheet("""
            QComboBox {
                background: transparent;
                color: #394468; font-weight: 700; font-size: 15px;
                border: none; padding-left: 0px;
            }
            QComboBox::drop-down {
                border: none;
                width: 22px;
                subcontrol-origin: padding;
                subcontrol-position: top right;
            }
            QComboBox:hover { color: #5D64D2; }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF;
                border: 1px solid #DADCE0;
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }
            QComboBox::item {
                padding: 8px 12px;
                border-radius: 4px;
                color: #333333;
            }
            QComboBox::item:selected {
                background-color: #E8F0FE;
                color: #1967D2;
            }
        """)
        w.model_selector.setCursor(Qt.CursorShape.PointingHandCursor)
        w.model_selector.currentTextChanged.connect(w.change_model)
        bottom_row.addWidget(w.model_selector)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedSize(1, 16)
        line.setStyleSheet("background: #DADCE0; margin: 0 8px;")
        w.line = line
        w.line.hide()
        bottom_row.addWidget(line)

        # 知识库选择器
        w.kb_selector = QComboBox()
        w.kb_selector.addItem("📚 知识库")
        w.kb_selector.setFixedWidth(144)
        w.kb_selector.setStyleSheet("""
            QComboBox {
                background: transparent;
                color: #55627F; font-size: 14px; font-weight: 500;
                border: none; padding-left: 0px;
            }
            QComboBox::drop-down { border: none; width: 0px; }
            QComboBox::down-arrow { image: none; }
            QComboBox:hover { color: #5D64D2; }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF;
                border: 1px solid #DADCE0;
                border-radius: 8px;
                padding: 4px;
                outline: none;
            }
            QComboBox::item {
                padding: 8px 12px;
                border-radius: 4px;
                color: #333333;
            }
            QComboBox::item:selected {
                background-color: #E8F0FE;
                color: #1967D2;
            }
        """)
        w.kb_selector.setCursor(Qt.CursorShape.PointingHandCursor)
        bottom_row.addWidget(w.kb_selector)

        # Skill 选择器：默认自动匹配，也可固定加载某个已启用 Skill
        w.skill_selector = QComboBox()
        w.skill_selector.addItem("Auto Skill ", None)
        w.skill_selector.setFixedWidth(144)
        w.skill_selector.setStyleSheet(w.kb_selector.styleSheet())
        w.skill_selector.setCursor(Qt.CursorShape.PointingHandCursor)
        w.skill_selector.setToolTip("选择一个本轮必定加载的 Skill")
        bottom_row.addWidget(w.skill_selector)

        # 知识库分隔线 (hidden, kept for theme system)
        kb_line = QFrame()
        kb_line.setFrameShape(QFrame.Shape.VLine)
        kb_line.setFixedSize(1, 16)
        kb_line.setStyleSheet("background: #DADCE0; margin: 0 8px;")
        w.kb_line = kb_line
        kb_line.hide()

        bottom_row.addStretch()

        w.voice_btn = QPushButton("🎙")
        w.voice_btn.setFixedSize(40, 40)
        w.voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        w.voice_btn.setToolTip("语音输入（Windows Win+H）")
        w.voice_btn.clicked.connect(w._start_voice_input)
        bottom_row.addWidget(w.voice_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        w.send_btn = QPushButton("✈")
        w.send_btn.setFixedSize(52, 52)
        w.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        w.send_btn.clicked.connect(w.send_message)
        bottom_row.addWidget(w.send_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        pill_outer.addLayout(bottom_row)

        input_wrapper_layout.addWidget(w.input_pill)
        w.input_disclaimer_label = QLabel("AudioMate是一款AI工具。请核查重要信息")
        w.input_disclaimer_label.setObjectName("inputDisclaimerLabel")
        w.input_disclaimer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        w.input_disclaimer_label.setContentsMargins(0, 4, 0, 0)
        input_wrapper_layout.addWidget(w.input_disclaimer_label)

        chat_layout.addWidget(input_wrapper)

        w.page_stack.addWidget(w.chat_page)

        w.settings_page = SettingsDialog(w.auth_session, w.app_settings, w)
        w.settings_page.back_requested.connect(w.close_settings)
        w.settings_page.api_key_updated.connect(w.apply_user_api_key)
        w.settings_page.mcp_settings_updated.connect(w.apply_mcp_settings)
        w.settings_page.plugin_settings_updated.connect(w.apply_plugin_settings)
        w.settings_page.skill_settings_updated.connect(w.apply_skill_settings)
        w.settings_page.notification_settings_updated.connect(w.apply_notification_settings)
        w.settings_page.memory_settings_updated.connect(w.apply_memory_settings)
        w.settings_page.memory_record_delete_requested.connect(w.delete_memory_record)
        w.settings_page.memory_scope_clear_requested.connect(w.clear_memory_scope)
        w.settings_page.user_memory_add_requested.connect(w.add_user_memory)
        w.settings_page.pet_settings_updated.connect(w.apply_pet_settings)
        w.settings_page.pet_training_room_requested.connect(w.open_pet_training_room)
        w.settings_page.pet_chat_clicked.connect(w._on_office_chat_clicked)
        w.settings_page.pet_dispatch_requested.connect(w._on_dispatch_sub_pet)
        w.settings_page.pet_skill_map_requested.connect(w._on_skill_map_requested)
        w.settings_page.set_pet_office_chats_provider(w._pet_office_chats_provider)
        w.settings_page.set_pet_office_capabilities_provider(w._pet_office_capabilities_provider)
        w.page_stack.addWidget(w.settings_page)

        w.knowledge_page = KnowledgeDialog(w)
        w.knowledge_page.back_requested.connect(w.close_knowledge)
        w.page_stack.addWidget(w.knowledge_page)

        w.market_page = MarketDialog(w)
        w.market_page.back_requested.connect(w.close_market)
        w.market_page.import_plugin_requested.connect(w.import_plugin_from_dialog)
        w.market_page.import_bundled_plugin_requested.connect(w.import_bundled_plugin)
        w.market_page.reaper_setup_requested.connect(w.open_reaper_setup)
        w.market_page.import_skill_requested.connect(w.import_skill_from_dialog)
        w.market_page.refresh_catalog_requested.connect(w.refresh_market_catalog)
        w.page_stack.addWidget(w.market_page)

        w.schedule_page = SchedulerDialog(w)
        w.schedule_page.back_requested.connect(w.close_schedule)
        w.schedule_page.task_add_requested.connect(w._add_scheduled_task)
        w.schedule_page.task_update_requested.connect(w._update_scheduled_task)
        w.schedule_page.task_delete_requested.connect(w._delete_scheduled_task)
        w.schedule_page.task_enabled_changed.connect(w._set_scheduled_task_enabled)
        w.schedule_page.task_run_requested.connect(w._run_scheduled_task_now)
        w.page_stack.addWidget(w.schedule_page)

        w.page_stack.setCurrentWidget(w.chat_page)
        w.page_animator = StackedPageAnimator(w.page_stack, w)

        main_layout.addWidget(w.page_stack)

        w.floating_panel = QFrame(central_widget)
        w.floating_panel.setObjectName("floatingPanel")
        w.floating_panel.setFixedSize(58, 340)
        w.floating_opacity = QGraphicsOpacityEffect(w.floating_panel)
        w.floating_opacity.setOpacity(0.0)
        w.floating_panel.setGraphicsEffect(w.floating_opacity)
        w.floating_layout = QVBoxLayout(w.floating_panel)
        w.floating_layout.setContentsMargins(8, 10, 8, 10)
        w.floating_layout.setSpacing(10)

        w.float_toggle_btn = QPushButton("☰")
        w.float_toggle_btn.setFixedSize(42, 42)
        w.float_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        w.float_toggle_btn.clicked.connect(w.toggle_sidebar)
        w.floating_layout.addWidget(w.float_toggle_btn)

        w.float_new_chat_btn = QPushButton("+")
        w.float_new_chat_btn.setFixedSize(42, 42)
        w.float_new_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        w.float_new_chat_btn.clicked.connect(w.start_new_chat)
        w.floating_layout.addWidget(w.float_new_chat_btn)

        w.float_schedule_btn = QPushButton("⏰")
        w.float_schedule_btn.setFixedSize(42, 42)
        w.float_schedule_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        w.float_schedule_btn.clicked.connect(w.open_schedule)
        w.floating_layout.addWidget(w.float_schedule_btn)

        w.float_knowledge_btn = QPushButton("📚")
        w.float_knowledge_btn.setFixedSize(42, 42)
        w.float_knowledge_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        w.float_knowledge_btn.clicked.connect(w.open_knowledge)
        w.floating_layout.addWidget(w.float_knowledge_btn)

        w.float_market_btn = QPushButton("🧩")
        w.float_market_btn.setFixedSize(42, 42)
        w.float_market_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        w.float_market_btn.clicked.connect(w.open_market)
        w.floating_layout.addWidget(w.float_market_btn)

        w.float_settings_btn = QPushButton("⚙")
        w.float_settings_btn.setFixedSize(42, 42)
        w.float_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        w.float_settings_btn.clicked.connect(w.open_settings)
        w.floating_layout.addWidget(w.float_settings_btn)

        w.floating_panel.raise_()
        w.update_floating_panel_position()
