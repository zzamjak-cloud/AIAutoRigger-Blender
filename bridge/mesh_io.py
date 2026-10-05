import bpy

from ..core.sampling import sample_surface

SAMPLE_COUNT = 30000


def world_geometry(context, obj):
    """모디파이어 적용 후 월드 좌표 정점·삼각형."""
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    try:
        mesh.calc_loop_triangles()
        mw = obj.matrix_world
        verts = [tuple(mw @ v.co) for v in mesh.vertices]
        tris = [tuple(t.vertices) for t in mesh.loop_triangles]
    finally:
        eval_obj.to_mesh_clear()
    return verts, tris


def surface_points(context, obj, count=SAMPLE_COUNT):
    verts, tris = world_geometry(context, obj)
    if not tris:
        raise ValueError("면이 없는 메시입니다.")
    return verts, sample_surface(verts, tris, count, seed=0)
