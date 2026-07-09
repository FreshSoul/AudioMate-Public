"""Skill Map — visual node-graph of pets and their bound skills/plugins.

Left column: pet nodes (active main + sub-pets + default pool).
Right column: tool nodes (skills + plugins).
Edges: one line per binding (skill → owner, plugin → owner).

Hover a node to highlight its bindings; click to keep the highlight pinned
until you click elsewhere.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QFont
from PyQt6.QtWidgets import (
    QDialog,
    QGraphicsScene,
    QGraphicsView,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QGraphicsLineItem,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QLabel,
    QGraphicsItem,
)

from src.pet.store import (
    PET_KIND_MAIN,
    PET_KIND_SUB,
    list_orphan_capabilities,
)


# Visual constants.
_NODE_W = 200
_NODE_H = 44
_ROW_GAP = 18
_COL_GAP = 220
_PAD = 36

_KIND_PALETTE = {
    "main": ("#2563EB", "#DBEAFE", "#1E3A8A"),   # border, fill, text
    "sub":  ("#6B7280", "#F3F4F6", "#111827"),
    "pool": ("#8B5CF6", "#EDE9FE", "#4C1D95"),
    "skill":  ("#F97316", "#FFEDD5", "#7C2D12"),
    "plugin": ("#0D9488", "#CCFBF1", "#134E4A"),
}
_KIND_PALETTE_DARK = {
    "main": ("#60A5FA", "#1E3A8A", "#F9FAFB"),
    "sub":  ("#9CA3AF", "#1F2937", "#F3F4F6"),
    "pool": ("#A78BFA", "#4C1D95", "#F5F3FF"),
    "skill":  ("#FB923C", "#7C2D12", "#FFEDD5"),
    "plugin": ("#5EEAD4", "#134E4A", "#CCFBF1"),
}


class _NodeItem(QGraphicsRectItem):
    """A pet or tool node. Tracks its connected edges for hover highlight."""

    def __init__(self, kind: str, label: str, sub_label: str, palette):
        super().__init__(0, 0, _NODE_W, _NODE_H)
        self.kind = kind
        self.label = label
        self.edges: list[_EdgeItem] = []
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        border, fill, text_color = palette[kind]
        self._normal_pen = QPen(QColor(border), 1.5)
        self._highlight_pen = QPen(QColor(border), 3)
        self._normal_brush = QBrush(QColor(fill))
        self.setPen(self._normal_pen)
        self.setBrush(self._normal_brush)
        self.setData(0, kind)
        # Primary label.
        text = QGraphicsTextItem(label, self)
        text.setDefaultTextColor(QColor(text_color))
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        text.setFont(font)
        text.setPos(10, 4)
        # Optional secondary line (kind tag).
        if sub_label:
            sub = QGraphicsTextItem(sub_label, self)
            sub.setDefaultTextColor(QColor(text_color))
            sub_font = QFont()
            sub_font.setPointSize(8)
            sub.setFont(sub_font)
            sub.setPos(10, 22)

    def attach_edge(self, edge: "_EdgeItem") -> None:
        self.edges.append(edge)

    def hoverEnterEvent(self, event):
        self._set_highlighted(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._set_highlighted(False)
        super().hoverLeaveEvent(event)

    def _set_highlighted(self, on: bool) -> None:
        self.setPen(self._highlight_pen if on else self._normal_pen)
        for edge in self.edges:
            edge.set_highlighted(on)
            other = edge.other(self)
            if other is not None:
                other.setPen(other._highlight_pen if on else other._normal_pen)


class _EdgeItem(QGraphicsLineItem):
    """A binding line between a pet and a tool."""

    def __init__(self, pet_node: _NodeItem, tool_node: _NodeItem, palette):
        super().__init__()
        self.pet_node = pet_node
        self.tool_node = tool_node
        color = palette.get(tool_node.kind, palette["sub"])[0]
        self._normal_pen = QPen(QColor(color), 1.2)
        self._normal_pen.setStyle(Qt.PenStyle.SolidLine)
        self._highlight_pen = QPen(QColor(color), 2.6)
        self.setPen(self._normal_pen)
        self.setZValue(-1)  # behind nodes
        self._refresh_line()

    def other(self, node: _NodeItem) -> _NodeItem | None:
        if node is self.pet_node:
            return self.tool_node
        if node is self.tool_node:
            return self.pet_node
        return None

    def set_highlighted(self, on: bool) -> None:
        self.setPen(self._highlight_pen if on else self._normal_pen)

    def _refresh_line(self) -> None:
        pr = self.pet_node.sceneBoundingRect()
        tr = self.tool_node.sceneBoundingRect()
        # Pet right-mid → Tool left-mid
        self.setLine(pr.right(), pr.center().y(), tr.left(), tr.center().y())


class SkillMapDialog(QDialog):
    """Modal node-graph view of the global skill/plugin binding map."""

    def __init__(self, pet_settings: dict, skills: list, plugins: list,
                  *, theme_mode: str = "light", parent=None):
        super().__init__(parent)
        self.setWindowTitle("技能地图")
        self.setModal(True)
        self.resize(900, 640)
        self._theme = theme_mode if theme_mode in ("light", "dark") else "light"
        self._palette = _KIND_PALETTE_DARK if self._theme == "dark" else _KIND_PALETTE

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "左列：Agents（含默认池）；右列：工具。连线 = 绑定关系。"
            "悬停节点可高亮对端。",
            self,
        )
        hint.setObjectName("petHintLabel")
        layout.addWidget(hint)

        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene, self)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        layout.addWidget(self._view, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_btn = QPushButton("关闭", self)
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self._build_graph(pet_settings or {}, skills or [], plugins or [])
        self.setStyleSheet(self._stylesheet())

    def _stylesheet(self) -> str:
        if self._theme == "dark":
            return (
                "QDialog, QWidget { background: #1F2937; color: #F3F4F6; }"
                "QLabel#petHintLabel { color: #9CA3AF; font-size: 12px; }"
                "QPushButton { background: #374151; color: #F3F4F6;"
                " border: 1px solid #4B5563; border-radius: 6px; padding: 6px 14px; }"
                "QPushButton:hover { background: #4B5563; }"
                "QGraphicsView { background: #111827; border: 1px solid #374151;"
                " border-radius: 8px; }"
            )
        return (
            "QDialog, QWidget { background: #FFFFFF; color: #111827; }"
            "QLabel#petHintLabel { color: #6B7280; font-size: 12px; }"
            "QPushButton { background: #F3F4F6; color: #111827;"
            " border: 1px solid #D1D5DB; border-radius: 6px; padding: 6px 14px; }"
            "QPushButton:hover { background: #E5E7EB; }"
            "QGraphicsView { background: #FAFAFA; border: 1px solid #E5E7EB;"
            " border-radius: 8px; }"
        )

    # ------------------------------------------------------------------

    def _build_graph(self, pet_settings: dict, skills: list, plugins: list) -> None:
        items = list(pet_settings.get("items") or [])
        active_id = pet_settings.get("active_main_id") or ""
        skill_name_by_id = {s.get("id"): s.get("name") or s.get("id", "") for s in skills if s.get("id")}
        plugin_name_by_id = {p.get("id"): p.get("name") or p.get("id", "") for p in plugins if p.get("id")}
        orphans = list_orphan_capabilities(pet_settings, skills, plugins)
        orphan_skill_ids = set(orphans.get("skill_ids") or [])
        orphan_plugin_ids = set(orphans.get("plugin_ids") or [])

        # Build pet rows (left column).
        pet_nodes: dict[str, _NodeItem] = {}  # key = pet_id (or "__pool__")
        pet_order: list[tuple[str, str, str]] = []  # (key, kind, label)
        active = next((p for p in items if p.get("id") == active_id and p.get("kind") == PET_KIND_MAIN), None)
        if active is None:
            active = next((p for p in items if p.get("kind") == PET_KIND_MAIN), None)
        if active is not None:
            pet_order.append((active["id"], "main", active.get("name") or "Main"))
        for pet in items:
            if pet.get("kind") == PET_KIND_SUB:
                pet_order.append((pet["id"], "sub", pet.get("name") or "Sub"))
        pet_order.append(("__pool__", "pool", "默认池"))

        x_pet = _PAD
        x_tool = _PAD + _NODE_W + _COL_GAP
        for idx, (key, kind, label) in enumerate(pet_order):
            sub_label = {"main": "主 Agent", "sub": "副 Agent", "pool": "未绑定 → 归主宠"}[kind]
            node = _NodeItem(kind, label, sub_label, self._palette)
            node.setPos(x_pet, _PAD + idx * (_NODE_H + _ROW_GAP))
            self._scene.addItem(node)
            pet_nodes[key] = node

        # Build tool rows (right column): all skills first, then plugins.
        tool_nodes: dict[str, _NodeItem] = {}  # key = "skill:<id>" / "plugin:<id>"
        row = 0
        for sid, sname in skill_name_by_id.items():
            node = _NodeItem("skill", sname, f"Skill · {sid}", self._palette)
            node.setPos(x_tool, _PAD + row * (_NODE_H + _ROW_GAP))
            self._scene.addItem(node)
            tool_nodes[f"skill:{sid}"] = node
            row += 1
        for pid, pname in plugin_name_by_id.items():
            node = _NodeItem("plugin", pname, f"Plugin · {pid}", self._palette)
            node.setPos(x_tool, _PAD + row * (_NODE_H + _ROW_GAP))
            self._scene.addItem(node)
            tool_nodes[f"plugin:{pid}"] = node
            row += 1

        if not tool_nodes:
            empty = QGraphicsTextItem("（项目里还没有任何 Skill / Plugin）")
            empty.setDefaultTextColor(QColor("#9CA3AF"))
            empty.setPos(x_tool, _PAD)
            self._scene.addItem(empty)

        # Edges — explicit bindings, then orphan → active main (= "__pool__"
        # node, but conceptually owned by active main; we draw orphan→pool
        # so the user sees the pool's contents).
        for pet in items:
            pet_node = pet_nodes.get(pet.get("id"))
            if pet_node is None:
                continue
            caps = pet.get("capabilities") or {}
            for sid in caps.get("skill_ids") or []:
                key = f"skill:{sid}"
                if key in tool_nodes:
                    self._add_edge(pet_node, tool_nodes[key])
            for pid in caps.get("plugin_ids") or []:
                key = f"plugin:{pid}"
                if key in tool_nodes:
                    self._add_edge(pet_node, tool_nodes[key])
        pool_node = pet_nodes.get("__pool__")
        if pool_node is not None:
            for sid in orphan_skill_ids:
                key = f"skill:{sid}"
                if key in tool_nodes:
                    self._add_edge(pool_node, tool_nodes[key])
            for pid in orphan_plugin_ids:
                key = f"plugin:{pid}"
                if key in tool_nodes:
                    self._add_edge(pool_node, tool_nodes[key])

        # Fit scene rect with padding.
        rect = self._scene.itemsBoundingRect().adjusted(-_PAD, -_PAD, _PAD, _PAD)
        self._scene.setSceneRect(rect)

    def _add_edge(self, pet_node: _NodeItem, tool_node: _NodeItem) -> None:
        edge = _EdgeItem(pet_node, tool_node, self._palette)
        self._scene.addItem(edge)
        pet_node.attach_edge(edge)
        tool_node.attach_edge(edge)


__all__ = ["SkillMapDialog"]
