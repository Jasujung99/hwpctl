"""Hancom object actions shared by public authoring commands."""
from __future__ import annotations

import re

from hwpctl.errors import HangulCommandError
from hwpctl.units import mm_to_hwpunit


def apply_position(canvas, pset, position):
    inline = position.get("mode", "inline") == "inline"
    put = lambda name, value: canvas._set_pset_item(pset, name, value)
    put("TreatAsChar", int(inline))
    put("AffectsLine", int(position.get("affect_line_spacing", False)))
    for side, value in zip(("Left", "Right", "Top", "Bottom"), position.get("outside_margin_mm", [0, 0, 0, 0])):
        put("OutsideMargin" + side, mm_to_hwpunit(value))
    if not inline:
        horizontal = {"paper": 0, "page": 1, "column": 2, "para": 3}
        vertical = {"paper": 0, "page": 1, "para": 2}
        put("HorzRelTo", horizontal[position.get("horizontal_relative_to", "para")])
        put("VertRelTo", vertical[position.get("vertical_relative_to", "para")])
        put("HorzAlign", {"left": 0, "center": 1, "right": 2}[position.get("horizontal_align", "left")])
        put("VertAlign", {"top": 0, "center": 1, "bottom": 2}[position.get("vertical_align", "top")])
        put("HorzOffset", mm_to_hwpunit(position["x_mm"]))
        put("VertOffset", mm_to_hwpunit(position["y_mm"]))
        put("TextWrap", {"square": 0, "top_and_bottom": 1, "behind_text": 2, "in_front_of_text": 3}[position["wrap"]])
        put("FlowWithText", int(position.get("flow_with_text", True)))
        put("AllowOverlap", int(position.get("allow_overlap", False)))


def apply_creation_geometry(pset, width, height, *, line=False, ellipse=False):
    """Absolute size references and creation points (HwpUnit) for DrawObjCreator* actions.

    An ellipse takes three points: centre, end of the horizontal axis, end of the
    vertical axis (measured on 12.0.0.4605). Rectangle-style 4 or 2 points, or 1,
    5 or 7 points, raise RPC_E_SERVERFAULT; no points at all creates a gso whose
    current/original size and axes are zero, so nothing renders.
    """
    pset.SetItem("WidthRelTo", 4)
    pset.SetItem("HeightRelTo", 2)
    layout = pset.CreateItemSet("ShapeDrawLayOut", "DrawLayOut")
    if ellipse:
        cx, cy = width // 2, height // 2
        points = (cx, cy, width, cy, cx, 0)
    elif line:
        points = (0, 0, width, height)
    else:
        points = (0, 0, width, 0, width, height, 0, height)
    array = layout.CreateItemArray("CreatePt", len(points))
    for index, value in enumerate(points):
        array.SetItem(index, value)
    layout.SetItem("CreateNumPt", len(points) // 2)


_SHAPE_COMPONENT = re.compile(r"<SHAPECOMPONENT\b([^>]*)>")


def current_size(canvas, ctrl):
    """Current (width, height) in HwpUnit of a drawing control, or ``None`` if unreadable.

    ``Properties`` Width/Height only echo the requested size; a degenerate shape
    reports them while its SHAPECOMPONENT current/original size is zero. Selecting
    the control and reading it with ``GetTextFile(..., "saveblock:true")`` writes
    nothing. HWPML omits CurWidth/CurHeight when they equal OriWidth/OriHeight.
    """
    try:
        canvas.com.SetPosBySet(ctrl.GetAnchorPos(0))
        if not canvas.com.FindCtrl():
            return None
        block = str(canvas.com.GetTextFile("HWPML2X", "saveblock:true") or "")
    except Exception:
        return None
    finally:
        canvas.run("Cancel")
    match = _SHAPE_COMPONENT.search(block)
    if match is None:
        return None
    attrs = dict(re.findall(r'(\w+)="([^"]*)"', match.group(1)))
    try:
        return (int(attrs.get("CurWidth", attrs.get("OriWidth", 0))),
                int(attrs.get("CurHeight", attrs.get("OriHeight", 0))))
    except ValueError:
        return None


def after_control(canvas, ctrl):
    """Leave a newly inserted control at the next position in the same list."""
    anchor = ctrl.GetAnchorPos(0)
    canvas.com.SetPosBySet(anchor)
    origin = canvas.get_pos()
    anchored = _anchor_tuple(anchor)
    if origin and anchored and tuple(origin[:2]) == anchored[:2] and origin[2] >= anchored[2] + 8:
        # A control character spans 8 positions. Hwp may snap the anchor to
        # the caret position right after it (e.g. at the end of the document),
        # where MoveRight has nowhere to go; that is already the boundary.
        return
    if origin and len(origin) == 3:
        next_position = (origin[0], origin[1], origin[2] + 1)
        if canvas.set_pos(next_position) and canvas.get_pos() == next_position:
            return
        canvas.set_pos(origin)
    if not origin or not canvas.run("MoveRight"):
        raise HangulCommandError("Cannot advance past inserted object")
    after = canvas.get_pos()
    if after and after[0] != origin[0]:
        if canvas.run("MoveListEnd") and canvas.run("MoveRight"):
            after = canvas.get_pos()
    if not after or after[0] != origin[0] or after[1:] <= origin[1:]:
        canvas.set_pos(origin)
        raise HangulCommandError(f"Inserted object cursor boundary could not be verified: {origin!r} -> {after!r}")


def position_control(canvas, ctrl, position):
    canvas.com.SetPosBySet(ctrl.GetAnchorPos(0))
    canvas.com.FindCtrl()
    action = canvas.com.CreateAction("ShapeObjDialog")
    pset = action.CreateSet()
    action.GetDefault(pset)
    apply_position(canvas, pset, position)
    if not action.Execute(pset):
        raise HangulCommandError("Object position action failed")
    canvas.run("Cancel")
    after_control(canvas, ctrl)


def settle_insertion_point(canvas, label="shape"):
    """Flush pending text-edit state before a drawing creator action.

    Hancom 2022 can raise RPC_E_SERVERFAULT if a drawing creator is invoked
    directly after InsertText/BreakPara. A reversible cursor movement flushes
    that edit state without changing the insertion point or object order.
    """
    origin = canvas.get_pos()
    if origin is None:
        raise HangulCommandError(f"Cannot verify {label} insertion point")
    if canvas.run("MoveLeft"):
        if not canvas.run("MoveRight") or canvas.get_pos() != origin:
            canvas.set_pos(origin)
            raise HangulCommandError(f"Cannot restore {label} insertion point")


class ChildSets:
    """Owner proxy for ShapeObjDialog child item sets.

    Automation returns a COPY of an existing child set (unlike OCX), so edits
    must be written back with ``SetItem``. Shared helpers such as
    ``_apply_shape_line`` call ``CreateItemSet`` on their owner; through this
    proxy they edit the existing copy instead of replacing it with an empty set.
    """

    def __init__(self, pset):
        self.pset = pset
        self.children = {}

    def CreateItemSet(self, name, set_id):
        if name not in self.children:
            exists = self.pset.ItemExist(name)
            self.children[name] = self.pset.Item(name) if exists else self.pset.CreateItemSet(name, set_id)
        return self.children[name]

    def write_back(self):
        for name, child in self.children.items():
            self.pset.SetItem(name, child)


def insert_text_art(canvas, *, text, width_mm, height_mm, shape, font, font_style, fill, line, shadow,
                    align, line_spacing_percent, char_spacing_percent, position):
    """Insert an editable 글맵시 (TextArt) and return the measured Undo steps (2).

    ``TextArtCreate`` ignores its parameter set and always creates Hangul's
    default object (measured on 12.0.0.850). Content, font, shape, size, fill
    and position are therefore applied by ONE ``ShapeObjDialog`` on the new
    object, so the whole command is two Undo steps.
    """
    canvas.assert_no_dialog()
    settle_insertion_point(canvas, "text art")
    create = canvas.com.CreateAction("TextArtCreate")
    if create is None:
        raise HangulCommandError("Text art creation action unavailable")
    seed = create.CreateSet()
    create.GetDefault(seed)  # Execute without GetDefault raises RPC_E_SERVERFAULT
    if not create.Execute(seed):
        raise HangulCommandError("Text art creation failed")
    ctrl = canvas.com.LastCtrl
    if ctrl is None or str(ctrl.CtrlID) != "gso" or str(getattr(ctrl, "UserDesc", "")) != "글맵시":
        raise HangulCommandError(f"New text art was not found (LastCtrl={getattr(ctrl, 'CtrlID', None)!r})")
    try:
        _apply_text_art_properties(
            canvas, ctrl, text=text, width_mm=width_mm, height_mm=height_mm, shape=shape, font=font,
            font_style=font_style, fill=fill, line=line, shadow=shadow, align=align,
            line_spacing_percent=line_spacing_percent, char_spacing_percent=char_spacing_percent,
            position=position)
    except Exception as exc:
        # The default object already exists as one Hangul Undo step. Report it
        # so the engine can keep `undo` aligned with the document.
        try:
            exc.partial_undo_steps = 1
        except Exception:
            raise HangulCommandError(f"Text art properties could not be applied: {exc}") from exc
        raise
    after_control(canvas, ctrl)
    canvas.assert_no_dialog()
    return 2


def _apply_text_art_properties(canvas, ctrl, *, text, width_mm, height_mm, shape, font, font_style, fill,
                               line, shadow, align, line_spacing_percent, char_spacing_percent, position):
    from hwpctl.textart import ALIGNS, FONT_STYLES, shape_index, text_to_com

    canvas.com.SetPosBySet(ctrl.GetAnchorPos(0))
    canvas.com.FindCtrl()
    action = canvas.com.CreateAction("ShapeObjDialog")
    pset = action.CreateSet()
    action.GetDefault(pset)
    put = canvas._set_pset_item
    children = ChildSets(pset)
    art = children.CreateItemSet("ShapeDrawTextart", "DrawTextart")
    put(art, "String", text_to_com(text))
    put(art, "NumberOfLines", text.count("\n") + 1)
    if font:
        put(art, "FontName", font)
        put(art, "FontType", 1)  # TTF; FontType=2 (HFT) is saved as TTF anyway
    put(art, "FontStyle", FONT_STYLES[font_style])
    put(art, "Shape", shape_index(shape))
    put(art, "AlignType", ALIGNS.index(align))
    put(art, "LineSpacing", line_spacing_percent)
    put(art, "CharSpacing", char_spacing_percent)
    apply_position(canvas, pset, position)
    if fill is not None:
        canvas._apply_fill(children.CreateItemSet("ShapeDrawFillAttr", "DrawFillAttr"), fill)
    if line is not None:
        canvas._apply_shape_line(children, line)
    if shadow is not None:
        canvas._apply_shape_shadow(children, shadow)
    children.write_back()
    succeeded = bool(action.Execute(pset))
    canvas.run("Cancel")
    if not succeeded:
        raise HangulCommandError("Text art property action failed")
    resize_control(ctrl, mm_to_hwpunit(width_mm), mm_to_hwpunit(height_mm))


def resize_control(ctrl, width, height):
    """Resize a drawing control in HwpUnit through its ``Properties`` set.

    ``ShapeObjDialog`` reports success but ignores Width/Height for text art
    (measured on 12.0.0.850, with every RelTo/ShapeType variant). Assigning the
    control's ShapeObject properties applies the size and adds no Undo step.
    """
    props = ctrl.Properties
    props.SetItem("Width", width)
    props.SetItem("Height", height)
    ctrl.Properties = props
    check = ctrl.Properties
    if (int(check.Item("Width")), int(check.Item("Height"))) != (width, height):
        raise HangulCommandError(
            f"Object size was not applied: requested {width}x{height} HU, "
            f"got {check.Item('Width')}x{check.Item('Height')}")


def insert_shape(canvas, *, shape_kind, width_mm, height_mm, fill, line, shadow, position):
    actions = {"rectangle": "DrawObjCreatorRectangle", "ellipse": "DrawObjCreatorEllipse", "line": "DrawObjCreatorLine"}
    canvas.assert_no_dialog()
    settle_insertion_point(canvas)
    action = canvas.com.CreateAction(actions[shape_kind])
    if action is None:
        raise HangulCommandError("Shape creation action unavailable")
    pset = action.CreateSet()
    action.GetDefault(pset)
    canvas._set_pset_item(pset, "Width", mm_to_hwpunit(width_mm))
    canvas._set_pset_item(pset, "Height", mm_to_hwpunit(height_mm))
    apply_creation_geometry(pset, mm_to_hwpunit(width_mm), mm_to_hwpunit(height_mm),
                            line=shape_kind == "line", ellipse=shape_kind == "ellipse")
    apply_position(canvas, pset, position)
    if fill is not None:
        child = pset.CreateItemSet("ShapeDrawFillAttr", "DrawFillAttr")
        canvas._apply_fill(child, fill)
    if line is not None:
        canvas._apply_shape_line(pset, line)
    if shadow is not None:
        canvas._apply_shape_shadow(pset, shadow)
    if not action.Execute(pset):
        raise HangulCommandError("Shape creation failed")
    ctrl = canvas.com.LastCtrl
    if ctrl is None or str(ctrl.CtrlID) != "gso":
        raise HangulCommandError(f"New native shape was not found (LastCtrl={getattr(ctrl, 'CtrlID', None)!r})")
    size = current_size(canvas, ctrl)
    if size is not None and (max(size) == 0 if shape_kind == "line" else min(size) == 0):
        # Width/Height in Properties still echo the request, but Hangul renders
        # nothing. Undo the creation so no invisible object is left behind.
        canvas.undo_once()
        raise HangulCommandError(
            f"New {shape_kind} has zero current size ({size[0]}x{size[1]} HU); the creation was undone")
    after_control(canvas, ctrl)
    canvas.assert_no_dialog()
    return 1


def table_properties_partial(canvas, table, *, page_break, repeat_header, cell_spacing_mm):
    saved = canvas.get_pos()
    canvas.assert_no_dialog()
    try:
        canvas.get_into_nth_table(table)
        canvas.run("CloseEx")
        canvas.com.FindCtrl()
        pset = canvas.com.HParameterSet.HShapeObject
        canvas.com.HAction.GetDefault("TablePropertyDialog", pset.HSet)
        canvas._set_pset_item(pset.HSet, "ShapeType", 3)
        canvas._set_pset_item(pset.HSet, "ShapeCellSize", 0)
        if page_break is not None:
            label, value = {"none": ("None", 0), "table": ("Table", 1), "cell": ("Cell", 2)}[page_break]
            canvas._set_pset_item(pset, "PageBreak", canvas._enum("TableBreak", label, value))
        if repeat_header is not None:
            canvas._set_pset_item(pset, "RepeatHeader", int(repeat_header))
        if cell_spacing_mm is not None:
            canvas._set_pset_item(pset, "CellSpacing", mm_to_hwpunit(cell_spacing_mm))
        if not canvas.com.HAction.Execute("TablePropertyDialog", pset.HSet):
            raise HangulCommandError("Partial table property action failed")
        return 1
    finally:
        canvas.run("Cancel")
        if saved is None or not canvas.set_pos(saved):
            raise HangulCommandError("Cannot restore cursor after table properties")


def _anchor_tuple(anchor):
    try:
        return tuple(int(anchor.Item(name)) for name in ("List", "Para", "Pos"))
    except Exception:
        return None
