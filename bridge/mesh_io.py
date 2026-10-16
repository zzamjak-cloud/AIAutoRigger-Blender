from contextlib import contextmanager

import bmesh
import bpy
from mathutils import Vector

from ..core.sampling import sample_surface

SAMPLE_COUNT = 30000


@contextmanager
def rest_shape(obj):
    """아마추어 모디파이어를 잠시 꺼 레스트 형상으로 평가하게 한다 (그 밖의 모디파이어는 그대로 적용).

    이미 다른 아마추어에 바인딩된 메시를 다시 리깅할 때, 그 아마추어의 현재 포즈(누운 자세 등)로 변형된 형상을
    분석하면 Y-up 오판이나 관절 오추정이 생긴다.
    """
    mods = [m for m in obj.modifiers if m.type == "ARMATURE" and m.show_viewport]
    for m in mods:
        m.show_viewport = False
    try:
        yield
    finally:
        for m in mods:
            m.show_viewport = True


def world_geometry(context, obj):
    """모디파이어(아마추어 제외) 적용 후 월드 좌표 정점·삼각형."""
    with rest_shape(obj):
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


def hand_graph(context, obj, wrist, hand_tip, radius_ratio=2.4, edge_ratio=0.03):
    """손목 주변 메시를 잘라 촘촘히 나눈 (정점, 간선). 로우폴리 손가락도 측지 거리 단면이 생기도록 세분한다."""
    wrist = Vector(wrist)
    hand_len = (Vector(hand_tip) - wrist).length
    bm = bmesh.new()
    try:
        with rest_shape(obj):
            bm.from_object(obj, context.evaluated_depsgraph_get())
        bm.transform(obj.matrix_world)
        far = [v for v in bm.verts if (v.co - wrist).length > radius_ratio * hand_len]
        bmesh.ops.delete(bm, geom=far, context="VERTS")
        target = edge_ratio * hand_len
        for _ in range(5):
            long_edges = [e for e in bm.edges if e.calc_length() > target]
            if not long_edges:
                break
            bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=1, use_grid_fill=True)
        bm.verts.index_update()
        verts = [tuple(v.co) for v in bm.verts]
        edges = [(e.verts[0].index, e.verts[1].index) for e in bm.edges]
    finally:
        bm.free()
    return verts, edges


def islands(obj):
    """메시 연결 성분: [(정점 인덱스 목록, 월드 중심, 반지름)]. obj.data 기준 (웨이트 지정용 인덱스와 일치)."""
    me = obj.data
    adj = [[] for _ in me.vertices]
    for e in me.edges:
        a, b = e.vertices
        adj[a].append(b)
        adj[b].append(a)
    seen = [False] * len(me.vertices)
    mw = obj.matrix_world
    out = []
    for s in range(len(me.vertices)):
        if seen[s]:
            continue
        seen[s] = True
        stack, comp = [s], []
        while stack:
            v = stack.pop()
            comp.append(v)
            for n in adj[v]:
                if not seen[n]:
                    seen[n] = True
                    stack.append(n)
        co = [mw @ me.vertices[i].co for i in comp]
        lo = Vector((min(c.x for c in co), min(c.y for c in co), min(c.z for c in co)))
        hi = Vector((max(c.x for c in co), max(c.y for c in co), max(c.z for c in co)))
        out.append((comp, tuple((lo + hi) * 0.5), 0.5 * max(hi - lo)))
    return out
