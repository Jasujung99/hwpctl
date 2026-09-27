"""Hancom object actions shared by public authoring commands."""
from __future__ import annotations

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


def apply_creation_geometry(pset, width, height, *, line=False):
    """Absolute size references and creation points (HwpUnit) for DrawObjCreator* actions."""
    pset.SetItem("WidthRelTo", 4)
    pset.SetItem("HeightRelTo", 2)
    layout = pset.CreateItemSet("ShapeDrawLayOut", "DrawLayOut")
    points = (0, 0, width, height) if line else (0, 0, width, 0, width, height, 0, height)
    array = layout.CreateItemArray("CreatePt", len(points))
    for index, value in enumerate(points):
        array.SetItem(index, value)
    layout.SetItem("CreateNumPt", len(points) // 2)


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


def insert_shape(canvas, *, shape_kind, width_mm, height_mm, fill, line, shadow, position):
    actions = {"rectangle": "DrawObjCreatorRectangle", "ellipse": "DrawObjCreatorEllipse", "line": "DrawObjCreatorLine"}
    canvas.assert_no_dialog()
    # Hancom 2022 can raise RPC_E_SERVERFAULT if a drawing creator is invoked
    # directly after InsertText/BreakPara. A reversible cursor movement flushes
    # that edit state without changing the insertion point or object order.
    origin = canvas.get_pos()
    if origin is None:
        raise HangulCommandError("Cannot verify shape insertion point")
    if canvas.run("MoveLeft"):
        if not canvas.run("MoveRight") or canvas.get_pos() != origin:
            canvas.set_pos(origin)
            raise HangulCommandError("Cannot restore shape insertion point")
    action = canvas.com.CreateAction(actions[shape_kind])
    if action is None:
        raise HangulCommandError("Shape creation action unavailable")
    pset = action.CreateSet()
    action.GetDefault(pset)
    canvas._set_pset_item(pset, "Width", mm_to_hwpunit(width_mm))
    canvas._set_pset_item(pset, "Height", mm_to_hwpunit(height_mm))
    apply_creation_geometry(pset, mm_to_hwpunit(width_mm), mm_to_hwpunit(height_mm), line=shape_kind == "line")
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
