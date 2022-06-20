"""
Bake image from material
- Set parameter for bake.
- Make image.
- Bake.
- Replace to baked image.

Prerequisite
- Named "Principled BSDF" node must exist.
- UV Map must not stick out.
"""
import os
import tempfile
from dataclasses import dataclass
from typing import Iterator

import bpy

bl_info = {
    "name": "Bake Image",  # プラグイン名
    "author": "tsutomu",  # 制作者名
    "version": (1, 0),  # バージョン
    "blender": (3, 1, 0),  # 動作可能なBlenderバージョン
    "support": "TESTING",  # サポートレベル
    "category": "Object",  # カテゴリ名
    "description": "Bake image",  # 説明文
    "location": "View3D > Sidebar > Edit Tab",  # 場所
    "warning": "",  # 注意点やバグ情報
    "doc_url": "https://github.com/SaitoTsutomu/Bake-Image",  # ドキュメントURL
}


@dataclass
class NodeData:
    """get_node_data返り値用"""

    material: bpy.types.Material
    bsdf: bpy.types.ShaderNodeBsdfPrincipled
    image_node: bpy.types.ShaderNodeTexImage

    @property
    def node_tree(self) -> bpy.types.ShaderNodeTree:
        return self.material.node_tree

    @property
    def nodes(self) -> bpy.types.bpy_prop_collection:
        return self.material.node_tree.nodes


def get_node_data(obj: bpy.types.Object, input_name: str) -> Iterator[NodeData]:
    """input_nameがベイク処理対象となるNodeDataのリストを求める

    :param obj: メッシュオブジェクト
    :param input_name: 入力項目名
    :return: NodeDataのリスト
    """
    for slot in obj.material_slots:
        mat = slot.material
        if mat and mat.use_nodes:
            if bsdf := mat.node_tree.nodes.get("Principled BSDF"):
                if links := bsdf.inputs[input_name].links:
                    if links[0].from_node.type != "TEX_IMAGE":
                        if links[0].from_node.type == "NORMAL_MAP":
                            if links := links[0].from_node.inputs["Color"].links:
                                if links[0].from_node.type == "TEX_IMAGE":
                                    continue
                        yield NodeData(mat, bsdf, None)


def bake_target(context, target: str, lst: list[NodeData]) -> bpy.types.Image:
    """ベイク

    :param context: コンテキスト
    :param target: 画像種類
    :param lst: NodeDataのリスト
    :return: 作成した画像
    """
    # 新規画像作成
    name = f"{lst[0].material.name}_{target.split()[-1].lower()}"
    img = bpy.data.images.new(name, context.scene.width, context.scene.height)
    for nd in lst:
        # 画像テクスチャノード作成
        nd.image_node = nd.node_tree.nodes.new(type="ShaderNodeTexImage")
        nd.image_node.image = img
        nd.node_tree.nodes.active = nd.image_node
    # ベイク
    bake_type = "DIFFUSE" if target == "Base Color" else target.upper()
    bpy.ops.object.bake(type=bake_type)
    # 一度JPEGファイルで保存して開き直し、パックしてJPEGファイルを削除
    img.file_format = "JPEG"
    img.filepath_raw = f"{tempfile.gettempdir()}/{img.name}.jpg"
    img.save()
    bpy.ops.image.open(filepath=img.filepath_raw)
    img.pack()
    os.remove(img.filepath_from_user())
    for nd in lst:
        nd.node_tree.nodes.remove(nd.image_node)
    return img


class CBI_OT_bake(bpy.types.Operator):
    bl_idname = "object.bake_operator"
    bl_label = "Bake"

    use_selected_to_active: bpy.props.BoolProperty()
    cage_extrusion: bpy.props.FloatProperty()

    def execute(self, context):
        # ベイクの設定
        render = context.scene.render
        render.engine = "CYCLES"
        render.bake.use_pass_direct = False
        render.bake.use_pass_indirect = False
        render.bake.use_pass_color = True
        render.bake.use_selected_to_active = self.use_selected_to_active
        render.bake.cage_extrusion = self.cage_extrusion
        obj = context.active_object
        tt = ["Base Color", "Roughness", "Normal"]
        dct = {t: [lst, None] for t in tt if (lst := list(get_node_data(obj, t)))}
        if not dct and self.use_selected_to_active:
            if obj.material_slots:
                mat = obj.material_slots[0].material
                if mat and mat.use_nodes:
                    if bsdf := mat.node_tree.nodes.get("Principled BSDF"):
                        dct = {tt[0]: [[NodeData(mat, bsdf, None)], None]}

        for target, lsts in dct.items():
            lsts[1] = bake_target(context, target, lsts[0])
        for target, lsts in dct.items():
            for nd in lsts[0]:
                nodes = nd.node_tree.nodes
                # 画像テクスチャノード作成
                image_node = nodes.new(type="ShaderNodeTexImage")
                image_node.image = lsts[1]
                # ベイク画像に変更
                if target == "Normal":
                    image_node.image.colorspace_settings.name = "Non-Color"
                    nmlmp_node = nodes.get("Normal Map") or nodes.new(type="ShaderNodeNormalMap")
                    nd.node_tree.links.new(image_node.outputs["Color"], nmlmp_node.inputs["Color"])
                    nd.node_tree.links.new(nmlmp_node.outputs[target], nd.bsdf.inputs[target])
                else:
                    nd.node_tree.links.new(image_node.outputs["Color"], nd.bsdf.inputs[target])
        self.report({"INFO"}, "Done" if dct else "Nothing")
        return {"FINISHED"}


class CBI_PT_bake(bpy.types.Panel):
    bl_label = "Bake Image"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Edit"
    bl_context = "objectmode"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == "MESH" and obj.select_get() and obj.active_material

    def draw(self, context):
        self.layout.prop(context.scene, "width")
        self.layout.prop(context.scene, "height")
        self.layout.prop(context.scene, "use_selected_to_active")
        self.layout.prop(context.scene, "cage_extrusion")
        prop = self.layout.operator(CBI_OT_bake.bl_idname, text=CBI_OT_bake.bl_label)
        prop.use_selected_to_active = context.scene.use_selected_to_active
        prop.cage_extrusion = context.scene.cage_extrusion


ui_classes = (
    CBI_OT_bake,
    CBI_PT_bake,
)


def register():
    for ui_class in ui_classes:
        bpy.utils.register_class(ui_class)
    bpy.types.Scene.width = bpy.props.IntProperty(default=1024)
    bpy.types.Scene.height = bpy.props.IntProperty(default=1024)
    bpy.types.Scene.use_selected_to_active = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.cage_extrusion = bpy.props.FloatProperty(default=0.01)


def unregister():
    for ui_class in ui_classes:
        bpy.utils.unregister_class(ui_class)
    del bpy.types.Scene.width
    del bpy.types.Scene.height
    del bpy.types.Scene.use_selected_to_active
    del bpy.types.Scene.cage_extrusion


if __name__ == "__main__":
    register()
