"""AI 분석용 직교 뷰 렌더. 사용자 씬을 건드리지 않도록 임시 씬에서 렌더하고 정리한다."""

import os
import tempfile

import bpy
from mathutils import Vector

from ..core.triangulate import OrthoView

RESOLUTION = 768
MARGIN = 1.15


def _bounds(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def view_specs(obj, facing):
    """정면(캐릭터를 마주 봄)·측면(캐릭터 왼쪽에서 봄) 카메라 사양."""
    lo, hi = _bounds(obj)
    center = (lo + hi) * 0.5
    size = hi - lo
    s = -1.0 if facing == "-Y" else 1.0  # 정면 방향 Y 부호
    up = Vector((0.0, 0.0, 1.0))
    front_fwd = Vector((0.0, -s, 0.0))  # 카메라 → 캐릭터
    # 해부학적 왼쪽: 정면 -Y 이면 +X
    left = Vector((-s, 0.0, 0.0))
    side_fwd = -left
    specs = []
    for name, fwd, extent in (
        ("front", front_fwd, max(size.x, size.z)),
        ("side", side_fwd, max(size.y, size.z)),
    ):
        right = fwd.cross(up).normalized()
        specs.append(OrthoView(name, tuple(center), tuple(right), tuple(up), tuple(fwd), extent * MARGIN))
    return specs, max(size)


def render_views(context, obj, facing, extra_objects=(), which=None):
    """(뷰 이름→PNG 바이트, 뷰 이름→OrthoView, 크기). extra_objects 는 변형에 필요한 리그 등."""
    specs, size = view_specs(obj, facing)
    if which is not None:
        specs = [s for s in specs if s.name in which]
    scene = bpy.data.scenes.new("AIRIG_views")
    world = bpy.data.worlds.new("AIRIG_views")
    cams = []
    images = {}
    tmpdir = tempfile.mkdtemp(prefix="airig_")
    try:
        scene.world = world
        world.color = (1.0, 1.0, 1.0)
        scene.collection.objects.link(obj)
        for extra in extra_objects:
            scene.collection.objects.link(extra)
        try:
            scene.render.engine = "BLENDER_WORKBENCH"
        except TypeError:
            pass
        shading = scene.display.shading
        shading.light = "STUDIO"
        shading.color_type = "SINGLE"
        shading.single_color = (0.6, 0.6, 0.6)
        shading.show_cavity = True
        shading.show_object_outline = True
        scene.render.resolution_x = RESOLUTION
        scene.render.resolution_y = RESOLUTION
        scene.render.image_settings.file_format = "PNG"
        for spec in specs:
            cam_data = bpy.data.cameras.new(f"AIRIG_{spec.name}")
            cam_data.type = "ORTHO"
            cam_data.ortho_scale = spec.scale
            cam_data.clip_start = 0.001
            cam_data.clip_end = size * 10.0
            cam = bpy.data.objects.new(cam_data.name, cam_data)
            cams.append(cam)
            scene.collection.objects.link(cam)
            fwd = Vector(spec.forward)
            cam.location = Vector(spec.center) - fwd * size * 3.0
            cam.rotation_euler = fwd.to_track_quat("-Z", "Y").to_euler()
            scene.camera = cam
            path = os.path.join(tmpdir, f"{spec.name}.png")
            scene.render.filepath = path
            bpy.ops.render.render(write_still=True, scene=scene.name)
            with open(path, "rb") as f:
                images[spec.name] = f.read()
            os.remove(path)
    finally:
        for cam in cams:
            data = cam.data
            bpy.data.objects.remove(cam)
            bpy.data.cameras.remove(data)
        bpy.data.scenes.remove(scene)
        bpy.data.worlds.remove(world)
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
    return images, {s.name: s for s in specs}, size
